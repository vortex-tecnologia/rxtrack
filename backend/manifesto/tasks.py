# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
from celery import shared_task
import requests
import json
import logging
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from usuarios.models import Motorista
from manifesto.models import Manifesto, NotaFiscal, ManifestoBuscaLog , BaixaNF
from operacional.tasks import enviar_email_erro_tms_task

import time # Necessário para respeitar os 2 segundos


logger = logging.getLogger(__name__)
# Configurações centralizadas
MAPA_JSON = {
    'CPF_MOTORISTA_TMS': 'mft_mft_driver_document_number',
    # Adicione outros mapeamentos conforme necessário
}

def validar_motorista_request(numero_manifesto):
    """Retorna o CPF do motorista vinculado ao manifesto no Endpoint 1"""
    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_analytics
    URL = f"https://{config.dominio_esl}/api/analytics/reports/{config.report_validacao}/data"
    payload = {
        "search": {
            "manifests": {
                "sequence_code": int(numero_manifesto),
                "service_date": "2024-01-01 - 2050-12-31"
            }
        },
        "page": "1", "per": "50"
    }
    response = requests.get(URL, headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, data=json.dumps(payload), timeout=20)
    response.raise_for_status()
    dados = response.json()
    if dados and len(dados) > 0:
        # Pega o documento do primeiro item da lista
        return str(dados[0].get('mft_mdr_iil_document', '')).strip()
    return None

def capturar_notas_unicas(manifesto_id):
    """Percorre a paginação da ESL e filtra as chaves únicas de NF-e"""
    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_invoices
    url = f"https://{config.dominio_esl}/api/invoice_occurrences"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    notas_unicas = {}
    next_id = None

    while True:
        params = {"manifest_id": manifesto_id, "per": 50}
        if next_id:
            params["after_id"] = next_id

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data_json = response.json()
            
            records = data_json.get('data', [])
            if not records:
                break

            for item in records:
                invoice = item.get('invoice', {})
                chave = invoice.get('key')
                if chave:
                    # Armazena apenas uma entrada por chave de acesso
                    notas_unicas[chave] = {
                        'numero': invoice.get('number'),
                        'chave': chave
                    }

            # Lógica de Paginação baseada no seu JSON
            paging = data_json.get('paging', {})
            next_id = paging.get('next_id')
            
            if not next_id or next_id >= paging.get('last_id', 0):
                # Se não houver next_id ou se já chegamos no last_id, encerra o loop
                break
                
            time.sleep(2) # Respeita o limite da API da transportadora

        except Exception as e:
            logger.error(f"Erro ao paginar notas: {e}")
            break

    return list(notas_unicas.values())

def enriquecer_dados_api(chave_nfe, numero_nfe):
    """Busca detalhes (Nome, Endereço) de uma nota específica"""
    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_analytics
    URL = f"https://{config.dominio_esl}/api/analytics/reports/{config.report_busca_nfe}/data"
    
    payload = {
        "search": {
            "invoices": {
                "number": int(numero_nfe),
                "issue_date": "2024-01-01 - 2050-12-31" 
            }
        },
        "page": "1", "per": "100"
    }
    
    try:
        response = requests.get(URL, headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
        if response.status_code == 200:
            dados = response.json()
            for nf in dados:
                if nf.get('key') == chave_nfe:
                    return nf
    except Exception as e:
        logger.error(f"Erro na API de enriquecimento para nota {numero_nfe}: {e}")
    return None

# =====================================================
# TASK MUDA STATUS MANIFESTO PARA EM TRANSPORTE NO TMS
# =====================================================
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def iniciar_transporte_manifesto_tms_task(self, numero_manifesto):
    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_invoices
    URL = f"https://{config.dominio_esl}/graphql"

    HEADERS = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }

    """
    - Busca manifesto no banco local
    - Calcula km inicial pelo último manifesto finalizado
    - Inicia transporte no TMS
    - Atualiza manifesto local
    """

    try:
        # -----------------------------------
        # 1️⃣ Buscar manifesto local
        # -----------------------------------
        manifesto = Manifesto.objects.select_related("motorista").get(
            numero_manifesto=numero_manifesto
        )

        if not manifesto.motorista:
            raise Exception("Manifesto sem motorista vinculado")

        # -----------------------------------
        # 2️⃣ Buscar último manifesto FINALIZADO
        # -----------------------------------
        ultimo_manifesto = (
            Manifesto.objects
            .filter(
                motorista=manifesto.motorista,
                status="FINALIZADO",
                km_final__isnull=False
            )
            .order_by("-data_finalizacao")
            .first()
        )

        if not ultimo_manifesto:
            raise Exception("Motorista não possui manifesto finalizado anterior")

        km_inicial = ultimo_manifesto.km_final

        # -----------------------------------
        # 3️⃣ Chamar TMS
        # -----------------------------------
        payload = {
            "query": """
            mutation ($id: ID!, $params: ManifestStartTransportInput!) {
              manifestStartTransport(id: $id, params: $params) {
                success
                errors
              }
            }
            """,
            "variables": {
                "id": manifesto.numero_manifesto,  # ID do TMS
                "params": {
                    "km": float(km_inicial)
                }
            }
        }

        response = requests.post(URL, headers=HEADERS, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()["data"]["manifestStartTransport"]

        if not result["success"]:
            raise Exception(result["errors"])

        # -----------------------------------
        # 4️⃣ Atualizar manifesto local
        # -----------------------------------
        with transaction.atomic():
            manifesto.km_inicial = km_inicial
            manifesto.status = "EM_TRANSPORTE"
            manifesto.save(update_fields=["km_inicial", "status"])

        return {
            "success": True,
            "numero_manifesto": manifesto.numero_manifesto,
            "km_inicial": km_inicial
        }

    except Exception as exc:
        raise self.retry(exc=exc)

# =====================================================
# TASK PRINCIPAL DO CELERY
# =====================================================

@shared_task(bind=True, max_retries=3)
def buscar_manifesto_completo_task(self, log_id):
    from manifesto.models import Manifesto, NotaFiscal, ManifestoBuscaLog    
    from manifesto.services import enviar_painel
    from django.db import transaction
    from usuarios.models import Filial
    from django.db import transaction
    import requests
    import json
    import time
    import logging

    logger = logging.getLogger(__name__)

    try:
        log = ManifestoBuscaLog.objects.select_related('motorista').get(id=log_id)
        numero_visual = log.numero_manifesto
        motorista = log.motorista
        from configuracao.utils import get_config
        config = get_config()
        token_geral = config.token_analytics
        headers_geral = {"Content-Type": "application/json", "Authorization": f"Bearer {token_geral}"}

        # --- ETAPA 1: VALIDAR MOTORISTA E PEGAR ID INTERNO ---
        url_valida = f"https://{config.dominio_esl}/api/analytics/reports/{config.report_validacao}/data"
        payload_busca = {
            "search": {
                "manifests": {
                    "sequence_code": int(numero_visual),
                    "service_date": "2024-01-01 - 2050-12-31"
                }
            },
            "page": "1", "per": "10"
        }
        
        res_valida = requests.get(url_valida, headers=headers_geral, data=json.dumps(payload_busca), timeout=30)
        
        try:
            dados_mft = res_valida.json()
        except json.JSONDecodeError:
            log.status, log.mensagem_erro = 'ERRO', f"Erro de comunicação com o TMS (API retornou {res_valida.status_code})"
            log.save()
            return
            
        if not dados_mft:
            log.status, log.mensagem_erro = 'ERRO', "Manifesto não encontrado no TMS."
            log.save()
            return

        info_tms = dados_mft[0]

        # Validação de CPF
        cpf_tms = str(info_tms.get('mft_mdr_iil_document', '')).strip().replace('.','').replace('-','')
        cpf_motorista = str(motorista.cpf).strip().replace('.','').replace('-','')
        
        if cpf_tms != cpf_motorista:
            log.status = 'ERRO'
            log.mensagem_erro = "O CPF vinculado a este manifesto no TMS não coincide com o CPF do motorista selecionado."
            log.save()
            return

        # Lógica de Filial
        nome_filial_tms = info_tms.get('mft_crn_psn_nickname')
        if not nome_filial_tms:
            nome_filial_tms = 'MATRIZ'
        else:
            nome_filial_tms = nome_filial_tms.strip().upper()
            
        id_filial_tms = info_tms.get('mft_crn_id')
        
        filial_obj, created = Filial.objects.get_or_create(nome=nome_filial_tms)
        
        if id_filial_tms and (created or not filial_obj.id_filial_tms):
            filial_obj.id_filial_tms = str(id_filial_tms)
            filial_obj.save(update_fields=['id_filial_tms'])

        # Criar/Recuperar Manifesto Local
        manifesto_obj, _ = Manifesto.objects.update_or_create(
            numero_manifesto=numero_visual,
            defaults={
                'motorista': motorista, 
                'filial': filial_obj,
                'status': 'EM_TRANSPORTE',
                'manifesto_id_tms': info_tms.get('id'), 
                'qtd_transferencia': int(info_tms.get('transfer_manifest_items_count', 0)),
                'qtd_entrega': int(info_tms.get('dispatch_draft_manifest_items_count', 0)),
                'qtd_retirada': int(info_tms.get('pick_manifest_items_count', 0)),
            }
        )
        
        id_interno_esl = info_tms.get('id') or numero_visual
        log.status = 'ENRIQUECENDO'
        log.save()

        # --- ETAPA 2: CAPTURAR LISTA E CLASSIFICAR TIPO (COM SUPORTE A FREIGHT_ID) ---
        token_notas = config.token_invoices
        url_notas = f"https://{config.dominio_esl}/api/invoice_occurrences"
        
        params_notas = {"manifest_id": str(numero_visual), "per": 20}
        start_cursor = None
        notas_unicas_dict = {} 
        
        GATILHOS = {'122': 'TRANSFERENCIA', '119': 'DESPACHO', '120': 'ENTREGA', '121': 'RETIRADA'}

        while True:
            if start_cursor: params_notas["start"] = start_cursor
            res_n = requests.get(url_notas, headers={"Authorization": f"Bearer {token_notas}"}, params=params_notas, timeout=30)
            if res_n.status_code != 200: break

            data_n = res_n.json()
            registros = data_n.get("data", [])
            for item in registros:
                invoice_data = item.get("invoice", {})
                chave = invoice_data.get("key")
                numero_doc = invoice_data.get("number")
                freight_id = item.get("freight", {}).get("id") if item.get("freight") else None
                codigo_oc = str(item.get("occurrence", {}).get("code"))
                
                # Identificador Híbrido: Se não tem chave, usa o número para compor o ID único
                id_unico = chave if chave else f"MINUTA_{numero_doc}"

                if id_unico not in notas_unicas_dict:
                    notas_unicas_dict[id_unico] = {
                        'chave': chave,
                        'numero': numero_doc,
                        'freight_id': freight_id,
                        'tipo': GATILHOS.get(codigo_oc, 'ENTREGA')
                    }
                elif codigo_oc in GATILHOS:
                    notas_unicas_dict[id_unico]['tipo'] = GATILHOS.get(codigo_oc)

            if data_n.get("paging", {}).get("next_id") is None: break
            start_cursor = data_n["paging"]["next_id"]
            time.sleep(1.5)

        # --- ETAPA 3: ENRIQUECIMENTO OU CADASTRO PADRÃO (MINUTAS) ---
        log.quantidade_notas = len(notas_unicas_dict)
        log.save()
        
        total_processadas = 0
        for id_doc, dados_base in notas_unicas_dict.items():
            try:
                chave = dados_base['chave']  # Pode ser None
                numero = dados_base['numero']
                tipo_operacao = dados_base['tipo']
                freight_id = dados_base['freight_id']

                destinatario = "DADOS NÃO REPASSADOS PELA ESL"
                endereco = "CONSULTE O DOCUMENTO FÍSICO"

                # --- NF-e (tem chave) ---
                if chave:
                    time.sleep(2.1)
                    detalhes = buscar_detalhes_esl_interno(chave, numero, token_geral)
                    if detalhes:
                        nome_det = detalhes.get('ioe_rpt_name')
                        if nome_det: 
                            destinatario = str(nome_det).upper()

                        rua = detalhes.get('ioe_rpt_mds_line_1', '')
                        num = detalhes.get('ioe_rpt_mds_number', '')
                        if rua:
                            endereco = f"{rua} {num}".strip().upper()

                    # Busca mantendo compatibilidade com as duas chaves
                    nota_no_manifesto = NotaFiscal.objects.filter(
                        manifesto=manifesto_obj, 
                        numero_nota=str(numero),
                        chave_acesso=chave
                    ).first()

                    status_final = nota_no_manifesto.status if nota_no_manifesto else 'PENDENTE'

                    NotaFiscal.objects.update_or_create(
                        manifesto=manifesto_obj,
                        chave_acesso=chave,
                        numero_nota=str(numero),
                        defaults={
                            'destinatario': destinatario,
                            'endereco_entrega': endereco,
                            'tipo_operacao': tipo_operacao,
                            'status': status_final,
                            'freight_id_tms': str(freight_id) if freight_id else None
                        }
                    )
                
                # --- MINUTAS / ORDENS SEM CHAVE ---
                else:
                    # Mantendo mesma lógica de última ocorrência pelo dicionário
                    nota_no_manifesto = NotaFiscal.objects.filter(
                        manifesto=manifesto_obj,
                        numero_nota=str(numero),
                        chave_acesso__isnull=True
                    ).first()
                    
                    status_final = nota_no_manifesto.status if nota_no_manifesto else 'PENDENTE'

                    NotaFiscal.objects.update_or_create(
                        manifesto=manifesto_obj,
                        numero_nota=str(numero),
                        chave_acesso=None,
                        defaults={
                            'destinatario': destinatario,
                            'endereco_entrega': endereco,
                            'tipo_operacao': tipo_operacao,
                            'status': status_final,
                            'freight_id_tms': str(freight_id) if freight_id else None
                        }
                    )

                total_processadas += 1

            except Exception as e:
                logger.warning(f"⚠️ Erro no documento {id_doc}: {e}")
                continue
        log.status = 'PROCESSADO'
        log.save()
        # 🔔 Atualiza o painel somente depois que tudo foi salvo
        transaction.on_commit(lambda: enviar_painel(manifesto_obj))

        # Dispara busca de coletas em background após finalizar o processo principal
        # Aguarda 30s antes de disparar para respeitar o rate limit da API ESL
        buscar_coletas_manifesto_task.apply_async(
            args=[manifesto_obj.id, numero_visual],
            countdown=30
        )

        return f"Manifesto {numero_visual} processado: {total_processadas} itens entre notas e minutas."

    except Exception as e:
        logger.error(f"🔴 Erro crítico: {str(e)}")
        log.status, log.mensagem_erro = 'ERRO', str(e)
        log.save()
        raise self.retry(exc=e, countdown=60)
    
def buscar_detalhes_esl_interno(chave, numero, token):
    """Auxiliar para buscar endereço no Endpoint 3"""
    url = "https://quickdelivery.eslcloud.com.br/api/analytics/reports/9873/data"
    payload = {
        "search": {
            "invoices": {
                "issue_date": "2024-01-01 - 2050-12-31",
                "number": int(numero)
            }
        }
    }
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
        if r.status_code == 200:
            for nf in r.json():
                if nf.get('key') == chave: return nf
    except: pass
    return None

def buscar_coletas_esl(numero_manifesto, token, dominio, report_coletas):
    """Busca coletas no Data Export usando o sequence_code do manifesto."""
    import requests
    import json
    
    url = f"https://{dominio}/api/analytics/reports/{report_coletas}/data"
    payload = {
        "search": {
            "picks": {
                "request_date": "2024-01-01 - 2050-12-31"
            },
            "scopes": {
                "from_manifest_sequence_code": str(numero_manifesto)
            }
        },
        "page": "1",
        "per": "100"
    }
    
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        r = requests.get(
            url, 
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, 
            data=json.dumps(payload), 
            timeout=30
        )
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            # Rate limit da ESL - propaga o erro para o Celery fazer retry
            raise Exception(f"Rate limit ESL (429): API pediu para aguardar. Manifesto {numero_manifesto}")
        else:
            logger.error(f"Erro ao buscar coletas para manifesto {numero_manifesto}: {r.status_code} - {r.text}")
    except Exception as e:
        logger.error(f"Exceção ao buscar coletas: {e}")
        raise  # Re-lança para o Celery fazer retry
    return []

@shared_task(bind=True, max_retries=3)
def buscar_coletas_manifesto_task(self, manifesto_id, numero_visual):
    from manifesto.models import Manifesto, NotaFiscal
    from manifesto.services import enviar_painel
    from configuracao.utils import get_config
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"Iniciando busca de coletas em background para manifesto {numero_visual}")

    try:
        manifesto_obj = Manifesto.objects.get(id=manifesto_id)
        config = get_config()
        token_geral = config.token_analytics
        dominio = config.dominio_esl
        report_coletas = getattr(config, 'report_coletas', '11324')
        
        coletas = buscar_coletas_esl(numero_visual, token_geral, dominio, report_coletas)
        
        if coletas:
            total_adicionadas = 0
            for coleta in coletas:
                seq_code = coleta.get('sequence_code')
                if not seq_code:
                    continue
                
                # Campos de Destinatário / Endereço
                solicitante = coleta.get('pck_pln_name', '')
                if not solicitante:
                    solicitante = coleta.get('requester', 'SOLICITANTE NÃO INFORMADO')
                    
                destinatario = str(solicitante).upper()
                
                rua = coleta.get('pck_pln_mds_line_1', '')
                num = coleta.get('pck_pln_mds_number', '')
                bairro = coleta.get('pck_pln_mds_neighborhood', '')
                cidade = coleta.get('pck_pln_mds_cty_name', '')
                
                # Montando endereço
                partes_endereco = [rua, num, bairro, cidade]
                endereco = ", ".join([p.strip() for p in partes_endereco if p and str(p).strip()])
                if not endereco:
                    endereco = "ENDEREÇO NÃO INFORMADO"
                endereco = endereco.upper()
                
                # Atualiza ou cria a coleta
                NotaFiscal.objects.update_or_create(
                    manifesto=manifesto_obj,
                    numero_nota=str(seq_code), # Salva como nota
                    tipo_operacao='COLETA',
                    defaults={
                        'destinatario': destinatario,
                        'endereco_entrega': endereco,
                        'numero_coleta': str(seq_code), # E salva como coleta tbm
                    }
                )
                total_adicionadas += 1
            
            if total_adicionadas > 0:
                qtd_coletas = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='COLETA').count()
                manifesto_obj.qtd_retirada = qtd_coletas
                manifesto_obj.save(update_fields=['qtd_retirada'])
                
            enviar_painel(manifesto_obj)
            return f"Adicionadas {total_adicionadas} coletas ao manifesto {numero_visual}"
            
        return "Nenhuma coleta encontrada."
        
    except Exception as e:
        logger.error(f"Erro na task de buscar coletas para {numero_visual}: {e}")
        raise self.retry(exc=e, countdown=60)
from celery import shared_task

@shared_task(bind=True, max_retries=2)
def enviar_baixa_esl_task(self, baixa_id):
    from .models import BaixaNF
    from django.utils import timezone
    from datetime import timezone as dt_timezone
    import requests
    import json
    import pytz

    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_invoices
    URL_ESL = f"https://{config.dominio_esl}/api/invoice_occurrences"

    try:
        # Adicionado select_related para o manifesto para pegar o ID interno
        baixa = BaixaNF.objects.select_related(
            'nota_fiscal',
            'ocorrencia',
            'nota_fiscal__manifesto',
            'nota_fiscal__manifesto__motorista'
        ).get(id=baixa_id)

        nf = baixa.nota_fiscal
        manifesto = nf.manifesto
        motorista = manifesto.motorista.nome_completo if manifesto.motorista else "Motorista não identificado"
        url_foto = baixa.comprovante_foto_url or ""
        codigo_ocorrencia = int(baixa.ocorrencia.codigo_tms) if baixa.ocorrencia else 1

        # ID Interno do TMS que você salvou na busca
        tms_manifest_id = manifesto.numero_manifesto 
        
        # 1. Pega a timezone de Brasília
        fuso_brasilia = pytz.timezone('America/Sao_Paulo')
        
        # 2. Converte a data da baixa (que está no banco) para Brasília
        data_br = baixa.data_baixa.astimezone(fuso_brasilia)
        
        # 3. Formata exatamente como a ESL pede (YYYY-MM-DDTHH:MM:SS.000-03:00)
        data_ocorrencia_str = data_br.strftime('%Y-%m-%dT%H:%M:%S.000-03:00')

        # --- LÓGICA DE FOTOS (Invoice vs Freight) - MANTIDA ORIGINAL ---
        if codigo_ocorrencia in [1, 2]:
            invoice_data = {
                "key": nf.chave_acesso,
                "delivery_receipt_url": url_foto
            }
            freight_data = {}
        else:
            invoice_data = {
                "key": nf.chave_acesso,
                "delivery_receipt_url": ""
            }
            freight_data = {
                "delivery_receipt_url": url_foto
            } if url_foto else {}

        # --- NOVA INFORMAÇÃO: COMENTÁRIO COM OBSERVAÇÃO ---
        # Verificamos se é nota retida (sem foto em entrega) para avisar no comentário
        prefixo_retida = "[NOTA RETIDA] " if not url_foto and codigo_ocorrencia in [1, 2] else ""
        comentario_final = f"{prefixo_retida}Baixa via App - Motorista: {motorista}. Obs: {baixa.observacao or ''}"

        # Montagem do Payload conforme a documentação enviada
        payload = {
            "invoice_occurrence": {
                "receiver": baixa.recebedor or "Nao identificado",
                "document_number": baixa.documento_recebedor or "",
                "comments": comentario_final, # 👈 Atualizado com a nova lógica
                "occurrence_at": data_ocorrencia_str,
                "occurrence": {
                    "code": codigo_ocorrencia
                },
                "invoice": invoice_data,
                "manifest": {
                    "id": int(manifesto.manifesto_id_tms) if manifesto.manifesto_id_tms else None
                }
            }
        }

        # Se houver dados de frete/cte, insere no payload (MANTIDO ORIGINAL)
        if freight_data:
            payload["invoice_occurrence"]["freight"] = freight_data

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}"
        }

        # Log para debug interno antes de enviar (opcional)
        print(f"Enviando baixa da NF {nf.chave_acesso} para o Manifesto TMS ID: {tms_manifest_id}")

        response = requests.post(
            URL_ESL,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        # Se retornar 422 ou 400, o raise_for_status vai para o except HTTPError
        response.raise_for_status()

        # ✅ SUCESSO
        baixa.processado_tms = True
        baixa.integrado_tms = True
        baixa.data_integracao = timezone.now()
        baixa.log_erro_tms = "Sucesso: Integrado com ESL vinculando ao Manifesto"
        baixa.save()

    except BaixaNF.DoesNotExist:
        return f"Baixa {baixa_id} não encontrada"

    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
        detalhe_erro = exc.response.text if hasattr(exc, 'response') and exc.response is not None else str(exc)
        msg_erro = f"Erro {status}: {detalhe_erro}"

        baixa.log_erro_tms = msg_erro[:500]
        baixa.integrado_tms = False
        baixa.save()

        # Se for erro de validação (como ID de manifesto inexistente ou chave inválida)
        if status and 400 <= status < 500:
            from configuracao.utils import notificar_falha_tms
            notificar_falha_tms(baixa_id, msg_erro, "enviar_baixa_esl_task")
            return f"Erro de validação ESL: {msg_erro}"

        # Retry para erros de servidor (5xx)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60)

        return f"Falha definitiva ESL: {msg_erro}"

    except Exception as e:
        msg = f"Erro inesperado: {str(e)}"
        baixa.log_erro_tms = msg[:500]
        baixa.save()
        raise self.retry(exc=e, countdown=60)

@shared_task(bind=True, max_retries=5)
def finalizar_manifesto_tms_task(self, manifesto_id):
    from manifesto.models import Manifesto
    import requests
    from django.utils import timezone
    import pytz

    try:
        manifesto = Manifesto.objects.get(id=manifesto_id)
        
        if not manifesto.manifesto_id_tms:
            return f"Erro: Manifesto {manifesto.numero_manifesto} sem ID interno do TMS."

        # 1. Define a data de fechamento (Usa a do banco ou a de agora)
        # Formato ISO com fuso horário de Brasília (-03:00)
        fuso_br = pytz.timezone('America/Sao_Paulo')
        data_fim = manifesto.data_finalizacao or timezone.now()
        data_iso = data_fim.astimezone(fuso_br).strftime('%Y-%m-%dT%H:%M:%S-03:00')

        from configuracao.utils import get_config
        config = get_config()
        url_graphql = f"https://{config.dominio_esl}/graphql"
        token = config.token_analytics  # O manual da ESL usa o token de analytics para essa ação

        # 2. Mutation completa conforme documentação da ESL
        mutation = """
        mutation manifestClose($id: ID, $sequenceCode: String, $params: ManifestCloseInput!) {
          manifestClose(id: $id, sequenceCode: $sequenceCode, params: $params) {
            errors
            resource {
              id
              closedAt
            }
            success
          }
        }
        """

        # 3. Variáveis com Data de Fechamento (obrigatório)
        variables = {
            "id": str(manifesto.manifesto_id_tms),
            "params": {
                "closedAt": data_iso
            }
        }

        headers = {
            'Content-Type': 'application/json', 
            'Authorization': f'Bearer {token}'
        }

        # 4. Chamada para a ESL
        response = requests.post(url_graphql, json={"query": mutation, "variables": variables}, headers=headers, timeout=30)
        
        if not response.text:
             raise Exception(f"Resposta vazia da ESL. HTTP Status: {response.status_code}")

        res_data = response.json()
        result = res_data.get('data', {}).get('manifestClose', {})

        # 5. Validação de Sucesso
        if result.get('success'):
            manifesto.status = 'FINALIZADO'
            manifesto.save()
            return f"Manifesto {manifesto.numero_manifesto} finalizado com sucesso no TMS."
        else:
            erros = result.get('errors', 'Erro desconhecido')
            
            # Se já estiver fechado, consideramos sucesso para não travar a fila
            if "already closed" in str(erros).lower():
                manifesto.status = 'FINALIZADO'
                manifesto.save()
                return f"Manifesto {manifesto.numero_manifesto} já constava como fechado."
            
            raise Exception(f"TMS recusou fechamento: {erros}")

    except Exception as exc:
        # Tenta novamente se houver erro de rede ou instabilidade
        raise self.retry(exc=exc, countdown=300)
    
@shared_task(bind=True, max_retries=2)
def enviar_baixa_minuta_task(self, baixa_id):
    from .models import BaixaNF
    import requests
    import json
    import pytz
    from django.utils import timezone

    # Configurações de API
    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_invoices
    
    try:
        # Busca a baixa e a nota relacionada
        baixa = BaixaNF.objects.select_related('nota_fiscal').get(id=baixa_id)
        nf = baixa.nota_fiscal
        
        # Recupera o ID do Frete que salvamos na busca do manifesto
        freight_id = nf.freight_id_tms
        
        if not freight_id:
            msg_erro = f"Erro: Documento {nf.numero_nota} não possui ID de Frete vinculado para integração."
            baixa.log_erro_tms = msg_erro
            baixa.save()
            return msg_erro

        # URL específica para ocorrência por Frete (V1)
        URL_ESL_FRETE = f"https://quickdelivery.eslcloud.com.br/api/v1/freights/{freight_id}/invoice_occurrences"

        # 1. Ajuste de Horário (Brasília GMT-3)
        fuso_br = pytz.timezone('America/Sao_Paulo')
        data_ocorrencia_str = baixa.data_baixa.astimezone(fuso_br).strftime('%Y-%m-%dT%H:%M:%S.000-03:00')

        # 2. Montagem do Payload conforme a documentação de Fretes
        payload = {
            "invoice_occurrence": {
                "receiver": baixa.recebedor or "Nao identificado",
                "document_number": baixa.documento_recebedor or "",
                "comments": f"Baixa Minuta via App - Obs: {baixa.observacao or ''}",
                "occurrence_at": data_ocorrencia_str,
                "latitude": float(baixa.latitude) if baixa.latitude else None,
                "longitude": float(baixa.longitude) if baixa.longitude else None,
                "occurrence": {
                    "code": int(baixa.ocorrencia.codigo_tms) if baixa.ocorrencia else 1
                }
            }
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}"
        }

        # 3. Envio da Requisição
        response = requests.post(
            URL_ESL_FRETE,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        # Se retornar erro (4xx ou 5xx), levanta exceção para o log
        response.raise_for_status()

        # ✅ SUCESSO: Atualiza os campos de controle no banco
        baixa.processado_tms = True
        baixa.integrado_tms = True
        baixa.data_integracao = timezone.now()
        baixa.log_erro_tms = "Sucesso: Baixa de Minuta integrada via Freight ID"
        baixa.save()
        
        return f"Baixa de Minuta {nf.numero_nota} enviada com sucesso."

    except Exception as e:
        # Registra a falha no log da baixa para conferência na Torre de Controle
        msg_falha = f"Erro na integração da Minuta: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            msg_falha = f"Erro na integração da Minuta ({e.response.status_code}): {e.response.text}"
        baixa.log_erro_tms = msg_falha[:500]
        baixa.integrado_tms = False
        baixa.save()
        
        from configuracao.utils import notificar_falha_tms
        notificar_falha_tms(baixa_id, msg_falha, "enviar_baixa_minuta_task")
        
        # Tenta novamente em caso de erro de servidor (5xx)
        raise self.retry(exc=e, countdown=60)

        
@shared_task(bind=True, max_retries=3)
def processar_webhook_manifesto_task(self, event_id):
    """
    Processa o payload de um WebhookEventoManifestoESL.
    - Cria/Busca Filial e Motorista.
    - Cria/Atualiza Manifesto com status 'AGUARDANDO'.
    - Cria/Atualiza Notas Fiscais vinculadas.
    """
    from manifesto.models import WebhookEventoManifestoESL, Manifesto, NotaFiscal, ManifestoBuscaLog
    from usuarios.models import Motorista, Filial
    from django.contrib.auth.models import User
    from django.db import transaction
    from django.utils import timezone
    import logging

    logger = logging.getLogger(__name__)

    try:
        with transaction.atomic():
            event = WebhookEventoManifestoESL.objects.get(id=event_id)
            payload = event.payload
            
            # 1. Filial (Vínculo comercial)
            f_data = payload.get('filial', {})
            id_f_tms = f_data.get('id_tms')
            filial_nome = f_data.get('nome', 'FILIAL WEBHOOK').upper()
            
            if id_f_tms:
                filial_obj, _ = Filial.objects.get_or_create(
                    id_filial_tms=str(id_f_tms),
                    defaults={'nome': filial_nome}
                )
            else:
                filial_obj, _ = Filial.objects.get_or_create(nome=filial_nome)

            # 2. Motorista (Cadastro Automático de Perfil)
            m_data = payload.get('motorista', {})
            cpf = str(m_data.get('cpf', '')).strip().replace('.', '').replace('-', '')
            nome_mot = m_data.get('nome', 'MOTORISTA WEBHOOK').upper()

            if not cpf:
                raise Exception("CPF do motorista não informado no payload.")

            # Apenas cria ou recupera o perfil do Motorista pelo CPF
            # O 'user' fica nulo até o motorista fazer o primeiro acesso/cadastro no PWA
            motorista_obj, created_mot = Motorista.objects.get_or_create(
                cpf=cpf,
                defaults={
                    'nome_completo': nome_mot,
                    'filial': filial_obj
                }
            )
            
            # Atualiza dados se o motorista já existia
            if not created_mot:
                motorista_obj.nome_completo = nome_mot
                if not motorista_obj.filial:
                    motorista_obj.filial = filial_obj
                motorista_obj.save()

            # 3. Manifesto (Status 'AGUARDANDO' para controle operacional)
            mani_data = payload.get('manifesto', {})
            num_mani = str(mani_data.get('numero'))
            
            if not num_mani:
                raise Exception("Número do manifesto não informado no payload.")

            # Busca o manifesto existente
            manifesto_obj = Manifesto.objects.filter(numero_manifesto=num_mani).first()
            
            # Se não existe, cria como AGUARDANDO. Se existe, preserva o status EM_TRANSPORTE
            status_novo = 'AGUARDANDO'
            if manifesto_obj and manifesto_obj.status == 'EM_TRANSPORTE':
                status_novo = 'EM_TRANSPORTE'

            manifesto_obj, _ = Manifesto.objects.update_or_create(
                numero_manifesto=num_mani,
                defaults={
                    'motorista': motorista_obj,
                    'filial': filial_obj,
                    'status': status_novo,
                    'manifesto_id_tms': mani_data.get('id_tms'),
                }
            )

            # 4. Itens (Notas Fiscais, Coletas, Minutas)
            itens = payload.get('itens', [])
            count_notas = 0
            for item in itens:
                dest = item.get('destinatario', {})
                endereco = f"{dest.get('logradouro', '')}, {dest.get('numero', '')} - {dest.get('bairro', '')} ({dest.get('cidade', '')}/{dest.get('uf', '')})".upper()

                # Inteligência para Itens sem Chave (Coletas / Webhook TMS)
                tipo_item = item.get('tipo', 'ENTREGA')
                numero_item = str(item.get('numero_item', ''))
                id_tms = item.get('id_tms')
                
                # Normalização de chaves (Transforma '' ou 'null' em None)
                def normalizar_valor(val):
                    if val is None: return None
                    v = str(val).strip()
                    return None if v.lower() in ['', 'null', 'none'] else v

                chave_nfe = normalizar_valor(item.get('chave_item'))
                chave_cte = normalizar_valor(item.get('chave_cte'))
                num_coleta = normalizar_valor(item.get('numero_coleta'))

                # Se for COLETA, numero_item com letras (ex: ITEM007) geralmente é ruído do JSON.
                # Vamos priorizar numero_coleta real ou id_tms.
                if tipo_item == 'COLETA' and not num_coleta:
                    if numero_item.isdigit():
                        num_coleta = numero_item
                    else:
                        # Se numero_item tem letras, usamos o id_tms como fallback de número
                        num_coleta = str(id_tms) if id_tms else None

                # Busca o registro existente de forma segura (Prioriza ID do TMS se disponível)
                # Isso evita criar duplicatas quando o item não tem chave (Chave=None)
                filtros_busca = {'manifesto': manifesto_obj}
                if id_tms:
                    filtros_busca['freight_id_tms'] = str(id_tms)
                elif chave_nfe:
                    filtros_busca['chave_acesso'] = chave_nfe
                else:
                    # Fallback para número e tipo (Único no manifesto)
                    filtros_busca['numero_nota'] = numero_item
                    filtros_busca['tipo_operacao'] = tipo_item

                NotaFiscal.objects.update_or_create(
                    **filtros_busca,
                    defaults={
                        'destinatario': str(dest.get('nome', 'NÃO INFORMADO')).upper(),
                        'endereco_entrega': endereco,
                        'tipo_operacao': tipo_item,
                        'freight_id_tms': str(id_tms) if id_tms else None,
                        'numero_nota': numero_item,
                        'chave_acesso': chave_nfe,
                        'numero_coleta': num_coleta,
                        'numero_cte': normalizar_valor(item.get('numero_cte')),
                        'chave_cte': chave_cte
                    }
                )
                count_notas += 1

            # 5. Criar Log de Auditoria/Visibilidade no Dashboard
            ManifestoBuscaLog.objects.update_or_create(
                numero_manifesto=num_mani,
                motorista=motorista_obj,
                defaults={
                    'status': 'PROCESSADO',
                    'mensagem_erro': None,
                    'quantidade_notas': count_notas
                }
            )

            # Marca evento como processado
            event.status = 'PROCESSADO'
            event.processed_at = timezone.now()
            event.save()

            return f"Manifesto {num_mani} (Motorista: {nome_mot}) processado com sucesso. {count_notas} notas."

    except Exception as e:
        logger.error(f"Erro ao processar Webhook {event_id}: {str(e)}")
        try:
            from manifesto.models import WebhookEventoManifestoESL, ManifestoBuscaLog
            evt = WebhookEventoManifestoESL.objects.get(id=event_id)
            evt.status = 'ERRO'
            evt.erro = str(e)
            evt.save()
            
            # Tenta criar log de erro para visibilidade
            mani_data = evt.payload.get('manifesto', {})
            num_mani = mani_data.get('numero', 'WEBHOOK_FAILURE')
            m_data = evt.payload.get('motorista', {})
            cpf = str(m_data.get('cpf', '')).strip().replace('.', '').replace('-', '')
            
            from usuarios.models import Motorista
            motorista = Motorista.objects.filter(cpf=cpf).first()
            
            ManifestoBuscaLog.objects.create(
                numero_manifesto=num_mani,
                motorista=motorista,
                status='ERRO',
                mensagem_erro=f"Webhook Error: {str(e)}"
            )
        except Exception as logger_err:
            logger.error(f"Falha ao registrar log de erro do webhook: {logger_err}")
            
        raise self.retry(exc=e, countdown=60)

@shared_task(bind=True, max_retries=3)
def enviar_coleta_esl_task(self, baixa_id):
    """
    Envia o registro de coleta para o TMS da ESL.
    Suporta Roteamento Inteligente:
    - Se ID numérico: usa API V1 Picks (/api/v1/picks)
    - Se ID alfanumérico: usa API V2 (/api/invoice_occurrences)
    """
    from manifesto.models import BaixaNF
    import requests
    import pytz
    import json
    from django.conf import settings
    from django.utils import timezone

    from configuracao.utils import get_config
    config = get_config()
    TOKEN = config.token_invoices
    
    try:
        baixa = BaixaNF.objects.select_related('nota_fiscal', 'ocorrencia', 'nota_fiscal__manifesto').get(id=baixa_id)
        nf = baixa.nota_fiscal
        manifesto = nf.manifesto
        
        # Identificador: Prioriza numero_coleta (confirmado pelo usuário)
        identificador = (nf.numero_coleta or nf.freight_id_tms or nf.numero_nota or "").strip()
        
        if not identificador:
            msg = "Erro: Nenhum identificador de coleta encontrado (numero_coleta/freight_id_tms)."
            baixa.integrado_tms = False
            baixa.log_erro_tms = msg
            baixa.save()
            return msg

        # 1. Ajuste de Horário (Brasília GMT-3)
        fuso_br = pytz.timezone('America/Sao_Paulo')
        data_ocorrencia_str = baixa.data_baixa.astimezone(fuso_br).strftime('%Y-%m-%d %H:%M:%S')
        data_iso_v2 = baixa.data_baixa.astimezone(fuso_br).strftime('%Y-%m-%dT%H:%M:%S.000-03:00')

        # 2. LÓGICA DE ROTEAMENTO (V1 vs V2)
        is_numeric = identificador.isdigit()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}"
        }

        if is_numeric:
            # --- FLUXO V1 (PICKS) ---
            url = f"https://quickdelivery.eslcloud.com.br/api/v1/picks/{identificador}/pick_occurrences"
            payload = {
                "pick_occurrence": {
                    "receiver": baixa.recebedor or "Nao identificado",
                    "document_number": baixa.documento_recebedor or "",
                    "comments": f"Coleta via App - Obs: {baixa.observacao or ''}",
                    "occurrence_at": data_iso_v2,
                    "latitude": float(baixa.latitude) if baixa.latitude else 0.0,
                    "longitude": float(baixa.longitude) if baixa.longitude else 0.0,
                    "occurrence": {
                        "code": int(baixa.ocorrencia.codigo_tms) if baixa.ocorrencia else 1
                    }
                }
            }
            logger.info(f"Enviando Coleta V1 (Picks): {url}")
        else:
            # --- FLUXO V2 (INVOICE OCCURRENCES - Mais flexível para alfanuméricos) ---
            url = "https://quickdelivery.eslcloud.com.br/api/invoice_occurrences"
            payload = {
                "invoice_occurrence": {
                    "occurrence_at": data_iso_v2,
                    "occurrence": {
                        "code": int(baixa.ocorrencia.codigo_tms)
                    },
                    "invoice": {
                        "number": identificador
                    },
                    "manifest": {
                        "id": int(manifesto.manifesto_id_tms) if manifesto.manifesto_id_tms else None
                    },
                    "comments": f"Coleta via App (Alfanumérico: {identificador})"
                }
            }
            logger.info(f"Enviando Coleta V2 (Invoice Occurrences) para ID Alfanumérico: {identificador}")

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            baixa.processado_tms = True
            baixa.integrado_tms = True
            baixa.data_integracao = timezone.now()
            baixa.log_erro_tms = f"Sucesso: Coleta registrada ({'V1' if is_numeric else 'V2'}: {identificador})"
            baixa.payload_enviado = payload
            baixa.save()
            return f"Coleta {identificador} enviada com sucesso ao ESL ({'V1' if is_numeric else 'V2'})."
        else:
            msg_erro = f"Status: {response.status_code} - {response.text}"
            baixa.processado_tms = True
            baixa.integrado_tms = False
            baixa.log_erro_tms = msg_erro[:500]
            baixa.payload_enviado = payload
            baixa.save()
            
            from configuracao.utils import notificar_falha_tms
            notificar_falha_tms(baixa_id, msg_erro, "enviar_coleta_esl_task")
            
            # Se for 404 e tentou V1, pode ser que o número precise de V2 mesmo sendo numérico
            if response.status_code == 404 and is_numeric:
                 logger.warning(f"ID numérico {identificador} deu 404 na V1. Tentando V2 em breve via retry.")
            
            raise Exception(f"Erro no ESL (Coleta): {msg_erro}")

    except Exception as e:
        logger.error(f"Erro enviar_coleta_esl_task ({baixa_id}): {str(e)}")
        raise self.retry(exc=e, countdown=60)
