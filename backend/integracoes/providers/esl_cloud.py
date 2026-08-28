import requests
import json
import logging
import time
import pytz
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from integracoes.base import BaseTMSAdapter
from usuarios.models import Motorista, Filial
from manifesto.models import Manifesto, NotaFiscal, ManifestoBuscaLog, BaixaNF, Veiculo, Frete
from manifesto.services import enviar_painel
from configuracao.utils import notificar_falha_tms

logger = logging.getLogger(__name__)


def limpar_codigo_ocorrencia(codigo):
    """Remove zeros à esquerda do código de ocorrência para a ESL (ex: 098 -> 98, 050 -> 50).
    Nunca retorna 0 pois a ESL não aceita - usa 1 (entrega) como padrão.
    Retorna um inteiro para compatibilidade com o TMS."""
    if not codigo:
        return 1
    codigo_str = str(codigo).strip()
    try:
        resultado = int(codigo_str)
        # ESL não aceita código 0, usa padrão de entrega
        return resultado if resultado != 0 else 1
    except ValueError:
        limpo = codigo_str.lstrip('0')
        try:
            return int(limpo)
        except ValueError:
            return 1


# Códigos que FECHAM notas na ESL (Entrega/Coleta com sucesso)
CODIGOS_ENTREGA_FINAL = [1, 2]

def obter_codigo_ocorrencia_seguro(codigo_tms_val, tipo_operacao=None, nota_fiscal=None):
    """
    Retorna o código de ocorrência correto baseado no tipo de operação e contexto da nota/manifesto/frete.
    Para DESPACHO: NUNCA retorna 1 ou 2 (que fecham a nota). Default é 50.
    Para outros tipos: Comportamento normal com default 1.
    
    Retorna: tuple (codigo_int, trace_list) onde trace_list é a lista de decisões tomadas.
    """
    trace = []  # Acumula cada decisão para debug
    
    nf_num = getattr(nota_fiscal, 'numero_nota', 'N/A') if nota_fiscal else 'N/A'
    trace.append(f"[INICIO] codigo_tms_val='{codigo_tms_val}', tipo_operacao_param='{tipo_operacao}', NF='{nf_num}'")
    
    tipo_op = str(tipo_operacao or '').strip().upper()
    if not tipo_op and nota_fiscal:
        tipo_op = str(nota_fiscal.tipo_operacao or '').strip().upper()
        trace.append(f"[TIPO_OP] Sem tipo_operacao no param, usando da NF: '{tipo_op}'")
    else:
        trace.append(f"[TIPO_OP] tipo_operacao do param: '{tipo_op}'")
    
    is_despacho = 'DESPACHO' in tipo_op
    despacho_origem = 'tipo_operacao' if is_despacho else None
    trace.append(f"[CHECK_1] is_despacho por tipo_operacao='{tipo_op}': {is_despacho}")

    # IMPORTANTE: A verificação de despacho DEVE se basear APENAS no tipo_operacao explícito da nota,
    # e NUNCA no modal do frete (ex: 'air') ou no manifesto. Cargas aéreas/fretes podem ter entregas normais!
    trace.append(f"[CHECK_CONTEXT] Respeitando tipo_operacao='{tipo_op}'. Nenhuma inferência externa por modal/manifesto.")

    if codigo_tms_val:
        codigo = limpar_codigo_ocorrencia(codigo_tms_val)
        trace.append(f"[CODIGO] limpar_codigo_ocorrencia('{codigo_tms_val}') = {codigo}")
    else:
        # Default baseado no tipo de operação
        codigo = 50 if is_despacho else 1
        trace.append(f"[CODIGO] Sem codigo_tms_val, usando default: {codigo} (is_despacho={is_despacho})")
    
    codigo_original = codigo
    
    # PROTEÇÃO CRÍTICA: Nunca permite código de entrega final para DESPACHO
    if is_despacho and codigo in CODIGOS_ENTREGA_FINAL:
        trace.append(f"[OVERRIDE] 🚨 CÓDIGO ALTERADO! is_despacho=True (origem: {despacho_origem}), código {codigo} está em CODIGOS_ENTREGA_FINAL={CODIGOS_ENTREGA_FINAL} → FORÇANDO para 50")
        logger.error(
            f"🚨 BLOQUEADO: Tentativa de enviar código {codigo} (Entrega Final) "
            f"para nota em contexto de DESPACHO (NF: {nf_num}). "
            f"Código original do TMS: '{codigo_tms_val}'. Despacho detectado por: {despacho_origem}. "
            f"Usando 50 (Carga Despachada) como proteção."
        )
        codigo = 50
    else:
        trace.append(f"[RESULTADO] Código final: {codigo} (sem alteração, is_despacho={is_despacho})")
    
    # Log completo do trace
    trace_str = " | ".join(trace)
    logger.info(f"🔍 [TRACE OCORRENCIA] NF={nf_num} | {trace_str}")
    
    return codigo, trace



class ESLCloudAdapter(BaseTMSAdapter):
    """Implementação para o TMS ESL Cloud."""

    # =====================================================
    # HELPER METHODS (MIGRATED FROM tasks.py)
    # =====================================================
    def validar_motorista_request(self, numero_manifesto):
        """Retorna o CPF do motorista vinculado ao manifesto no Endpoint 1"""
        TOKEN = self.config.token_analytics
        URL = f"https://{self.config.dominio_esl}/api/analytics/reports/{self.config.report_validacao}/data"
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
            return str(dados[0].get('mft_mdr_iil_document', '')).strip()
        return None

    def capturar_notas_unicas(self, manifesto_id):
        """Percorre a paginação da ESL e filtra as chaves únicas de NF-e"""
        TOKEN = self.config.token_invoices
        url = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
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
                        notas_unicas[chave] = {
                            'numero': invoice.get('number'),
                            'chave': chave
                        }

                paging = data_json.get('paging', {})
                next_id = paging.get('next_id')
                
                if not next_id or next_id >= paging.get('last_id', 0):
                    break
                    
                time.sleep(2)

            except Exception as e:
                logger.error(f"Erro ao paginar notas: {e}")
                break

        return list(notas_unicas.values())

    def enriquecer_dados_api(self, chave_nfe, numero_nfe):
        """Busca detalhes (Nome, Endereço) de uma nota específica"""
        TOKEN = self.config.token_analytics
        URL = f"https://{self.config.dominio_esl}/api/analytics/reports/{self.config.report_busca_nfe}/data"
        
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

    def buscar_detalhes_esl_interno(self, chave, numero, token):
        """Auxiliar para buscar endereço no Endpoint 3"""
        url = f"https://{self.config.dominio_esl}/api/analytics/reports/9873/data"
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

    def buscar_dados_frete_report_7693(self, chave, numero, token):
        """Busca os dados de frete (CT-e, valores, pagador) no relatório 7693"""
        from datetime import datetime, timedelta
        data_fim_dt = datetime.now()
        data_inicio_dt = data_fim_dt - timedelta(days=365)
        
        data_inicio_service = data_inicio_dt.strftime("%Y-%m-%d")
        data_fim = data_fim_dt.strftime("%Y-%m-%d")
        
        url = f"https://{self.config.dominio_esl}/api/analytics/reports/7693/data"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        def fazer_busca(payload):
            try:
                r = requests.get(url, headers=headers, json=payload, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    if data and len(data) > 0:
                        if chave:
                            for registro in data:
                                if registro.get("fit_fis_ioe_key") == chave:
                                    return registro
                        return data[0]
            except Exception as e:
                logger.error(f"Erro no report 7693: {e}")
            return None

        # Tentativa 1: Por chave_nfe (se existir)
        if chave:
            payload_chave = {
                "search": {
                    "freights": {"service_at": f"{data_inicio_service} - {data_fim}"},
                    "scopes": {"by_invoice_key": chave}
                },
                "page": 1, "per": 50
            }
            resultado = fazer_busca(payload_chave)
            if resultado:
                return resultado
                
        # Tentativa 2: Por numero_nfe (fallback ou para minutas sem chave)
        if numero:
            payload_numero = {
                "search": {
                    "freights": {"service_at": f"{data_inicio_service} - {data_fim}"},
                    "scopes": {"from_invoice_number": str(numero)}
                },
                "page": 1, "per": 50
            }
            resultado = fazer_busca(payload_numero)
            if resultado:
                return resultado
                
        return None

    def buscar_coletas_esl(self, numero_manifesto, token, dominio, report_coletas):
        """Busca coletas no Data Export usando o sequence_code do manifesto."""
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
                raise Exception(f"Rate limit ESL (429): API pediu para aguardar. Manifesto {numero_manifesto}")
            else:
                logger.error(f"Erro ao buscar coletas para manifesto {numero_manifesto}: {r.status_code} - {r.text}")
        except Exception as e:
            logger.error(f"Exceção ao buscar coletas: {e}")
            raise
        return []

    # =====================================================
    # INTERFACE IMPLEMENTATION
    # =====================================================
    def iniciar_transporte(self, numero_manifesto, task=None):
        TOKEN = self.config.token_invoices
        URL = f"https://{self.config.dominio_esl}/graphql"
        HEADERS = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}"
        }

        try:
            manifesto = Manifesto.objects.select_related("motorista").get(
                numero_manifesto=numero_manifesto
            )

            if not manifesto.motorista:
                raise Exception("Manifesto sem motorista vinculado")

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
                  "id": manifesto.numero_manifesto,
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
            if task:
                raise task.retry(exc=exc)
            raise

    def resolver_numero_visual_manifesto(self, id_tms):
        """
        Busca o número visual (sequence_code) na ESL a partir do ID interno do manifesto (id).
        Usado pelo Webhook quando recebe um manifesto novo pelo ID interno para descobrir o número visual.
        """
        try:
            if not self.config or not self.config.token_analytics or not self.config.report_validacao:
                return None

            token_geral = self.config.token_analytics
            headers_geral = {"Content-Type": "application/json", "Authorization": f"Bearer {token_geral}"}
            url_valida = f"https://{self.config.dominio_esl}/api/analytics/reports/{self.config.report_validacao}/data"
            
            id_busca = int(id_tms) if str(id_tms).isdigit() else id_tms
            payload_busca = {
                "search": {
                    "manifests": {
                        "id": id_busca,
                        "service_date": "2024-01-01 - 2050-12-31"
                    }
                },
                "page": "1", "per": "5"
            }

            res = requests.get(url_valida, headers=headers_geral, data=json.dumps(payload_busca), timeout=15)
            if res.status_code == 200:
                dados = res.json()
                if dados and len(dados) > 0:
                    info = dados[0]
                    seq = info.get('mft_sequence_code') or info.get('sequence_code')
                    if seq:
                        id_op = str(info.get('mft_uer_crn_id')).strip() if info.get('mft_uer_crn_id') else None
                        nome_op = str(info.get('mft_uer_name', '')).strip().upper() if info.get('mft_uer_name') else None
                        placa = str(info.get('mft_vie_license_plate', '')).strip().upper().replace(' ', '').replace('-', '') if info.get('mft_vie_license_plate') else None

                        logger.info(f"🔍 [RESOLVER_VISUAL] ID {id_tms} resolvido: Visual #{seq}, Base Op: {nome_op or 'N/A'}")
                        return {
                            'sequence_code': str(seq).strip(),
                            'id_filial_operacao': id_op,
                            'nome_filial_operacao': nome_op,
                            'placa': placa
                        }
        except Exception as e:
            logger.warning(f"⚠️ [RESOLVER_VISUAL] Erro ao consultar ESL para ID {id_tms}: {e}")
        return None

    def buscar_manifesto_completo(self, log_id, task=None):
        try:
            log = ManifestoBuscaLog.objects.select_related('motorista').get(id=log_id)
            numero_visual = log.numero_manifesto
            motorista = log.motorista
            token_geral = self.config.token_analytics
            headers_geral = {"Content-Type": "application/json", "Authorization": f"Bearer {token_geral}"}

            url_valida = f"https://{self.config.dominio_esl}/api/analytics/reports/{self.config.report_validacao}/data"
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

            cpf_tms = str(info_tms.get('mft_mdr_iil_document', '')).strip().replace('.','').replace('-','')
            cpf_motorista = str(motorista.cpf).strip().replace('.','').replace('-','')
            
            if cpf_tms != cpf_motorista:
                log.status = 'ERRO'
                log.mensagem_erro = "O CPF vinculado a este manifesto no TMS não coincide com o CPF do motorista selecionado."
                log.save()
                return

            # === VALIDAÇÃO DO STATUS DO MANIFESTO NO TMS ===
            status_tms = str(info_tms.get('status', '')).strip().lower()
            logger.info(f"[STATUS_TMS] Manifesto {numero_visual}: status no TMS = '{status_tms}'")

            if status_tms == 'closed':
                mft_existente = Manifesto.objects.filter(numero_manifesto=numero_visual).first()
                if mft_existente:
                    mft_existente.status = 'FINALIZADO'
                    mft_existente.status_tms = 'closed'
                    mft_existente.finalizado = True
                    if not mft_existente.data_finalizacao:
                        mft_existente.data_finalizacao = timezone.now()
                    mft_existente.save(update_fields=['status', 'status_tms', 'finalizado', 'data_finalizacao'])
                    log.status = 'PROCESSADO'
                    log.mensagem_erro = "Manifesto já finalizado no TMS. Atualizado localmente para finalizado."
                    log.save(update_fields=['status', 'mensagem_erro'])
                    logger.info(f"✅ Manifesto {numero_visual} sincronizado como finalizado (status 'closed' no TMS).")
                    return
                else:
                    log.status = 'ERRO'
                    log.mensagem_erro = "Este manifesto já foi finalizado no TMS. Não é possível carregar um manifesto ativo."
                    log.save()
                    logger.warning(f"🚫 Manifesto {numero_visual} BLOQUEADO: status 'closed' no TMS.")
                    return

            # === VEÍCULO (PLACA) ===
            veiculo_obj = None
            placa_tms = info_tms.get('mft_vie_license_plate')
            if placa_tms:
                placa_limpa = str(placa_tms).strip().upper().replace(' ', '').replace('-', '')
                if placa_limpa:
                    veiculo_obj, _ = Veiculo.objects.get_or_create(
                        placa=placa_limpa,
                        defaults={'tipo': 'CAVALO'}
                    )
                    logger.info(f"🚛 Veículo {placa_limpa} vinculado ao manifesto {numero_visual}")

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

            # --- FILIAL DE OPERAÇÃO (base física de onde o caminhão sai) ---
            # Determinada pelo mft_uer_crn_id (filial do emissor do manifesto na ESL)
            filial_operacao_obj = None
            id_filial_operacao_tms = info_tms.get('mft_uer_crn_id')
            if id_filial_operacao_tms:
                filial_operacao_obj = Filial.objects.filter(
                    id_filial_tms=str(id_filial_operacao_tms)
                ).first()
                if not filial_operacao_obj:
                    # Cria filial com nome do operador como referência temporária
                    nome_emissor = info_tms.get('mft_uer_name', '').strip().upper()
                    filial_operacao_obj, _ = Filial.objects.get_or_create(
                        id_filial_tms=str(id_filial_operacao_tms),
                        defaults={'nome': nome_emissor or f'BASE {id_filial_operacao_tms}'}
                    )
                    logger.info(f"🏢 Nova filial de operação criada: {filial_operacao_obj.nome} (TMS ID: {id_filial_operacao_tms})")

            manifesto_obj, _ = Manifesto.objects.update_or_create(
                numero_manifesto=numero_visual,
                defaults={
                    'motorista': motorista, 
                    'filial': filial_obj,
                    'filial_operacao': filial_operacao_obj,
                    'status': 'EM_TRANSPORTE',
                    'status_tms': status_tms if status_tms in ('pending', 'in_transit') else 'in_transit',
                    'manifesto_id_tms': info_tms.get('id'), 
                    'veiculo': veiculo_obj,
                    'qtd_transferencia': int(info_tms.get('transfer_manifest_items_count', 0)),
                    'qtd_entrega': int(info_tms.get('dispatch_draft_manifest_items_count', 0)),
                    'qtd_retirada': int(info_tms.get('pick_manifest_items_count', 0)),
                }
            )
            
            log.status = 'ENRIQUECENDO'
            log.save()

            token_notas = self.config.token_invoices
            url_notas = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
            
            params_notas = {"manifest_id": str(numero_visual), "per": 20}
            start_cursor = None
            notas_unicas_dict = {} 
            
            GATILHOS = {
                '122': 'TRANSFERENCIA', 
                '117': 'TRANSFERENCIA',
                '119': 'DESPACHO', 
                '114': 'DESPACHO', 
                '50': 'DESPACHO', 
                '050': 'DESPACHO', 
                '55': 'DESPACHO', 
                '055': 'DESPACHO', 
                '120': 'ENTREGA', 
                '107': 'ENTREGA',
                '101': 'ENTREGA',
                '121': 'RETIRADA'
            }

            while True:
                time.sleep(2.0)
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
                    data_oc = str(item.get("occurrence_at") or item.get("created_at") or "")
                    
                    id_unico = chave if chave else f"MINUTA_{numero_doc}"

                    if id_unico not in notas_unicas_dict:
                        notas_unicas_dict[id_unico] = {
                            'chave': chave,
                            'numero': numero_doc,
                            'freight_id': freight_id,
                            'tipo': GATILHOS.get(codigo_oc, None),  # None se não for um gatilho
                            'data_oc_tipo': data_oc if codigo_oc in GATILHOS else ''  # data do gatilho que definiu o tipo
                        }
                    else:
                        # Atualiza freight_id se veio nesta ocorrência e estava vazio
                        if freight_id and not notas_unicas_dict[id_unico].get('freight_id'):
                            notas_unicas_dict[id_unico]['freight_id'] = freight_id
                        
                        # Só usa ocorrências do GATILHOS para definir tipo_operacao
                        # Sempre pega a ocorrência GATILHO mais recente por data
                        if codigo_oc in GATILHOS:
                            data_tipo_anterior = notas_unicas_dict[id_unico].get('data_oc_tipo', '')
                            if not data_tipo_anterior or data_oc >= data_tipo_anterior:
                                notas_unicas_dict[id_unico]['tipo'] = GATILHOS[codigo_oc]
                                notas_unicas_dict[id_unico]['data_oc_tipo'] = data_oc

                if data_n.get("paging", {}).get("next_id") is None: break
                start_cursor = data_n["paging"]["next_id"]
                time.sleep(2.0)

            log.quantidade_notas = len(notas_unicas_dict)
            log.save()
            
            total_processadas = 0
            ids_processadas = []
            for id_doc, dados_base in notas_unicas_dict.items():
                try:
                    chave = dados_base['chave']
                    numero = dados_base['numero']
                    tipo_operacao = dados_base['tipo'] or 'ENTREGA'  # Default ENTREGA se nenhum gatilho definiu
                    freight_id = dados_base['freight_id']

                    # 1. VERIFICA SE A NOTA JÁ EXISTE NO MANIFESTO
                    if chave:
                        nota_no_manifesto = NotaFiscal.objects.filter(
                            manifesto=manifesto_obj, 
                            numero_nota=str(numero),
                            chave_acesso=chave
                        ).first()
                    else:
                        nota_no_manifesto = NotaFiscal.objects.filter(
                            manifesto=manifesto_obj,
                            numero_nota=str(numero),
                            chave_acesso__isnull=True
                        ).first()

                    if nota_no_manifesto:
                        # NOTA JÁ EXISTE: Não faz requisições extras de endereço/frete na ESL!
                        update_fields = []
                        if nota_no_manifesto.tipo_operacao != tipo_operacao:
                            nota_no_manifesto.tipo_operacao = tipo_operacao
                            update_fields.append('tipo_operacao')
                        if freight_id and nota_no_manifesto.freight_id_tms != str(freight_id):
                            nota_no_manifesto.freight_id_tms = str(freight_id)
                            update_fields.append('freight_id_tms')
                        if update_fields:
                            nota_no_manifesto.save(update_fields=update_fields)
                            
                        ids_processadas.append(nota_no_manifesto.id)
                        total_processadas += 1
                        continue

                    # 2. NOTA NOVA: Apenas para notas novas busca detalhes de endereço e frete na ESL
                    destinatario = "DADOS NÃO REPASSADOS PELA ESL"
                    endereco = "CONSULTE O DOCUMENTO FÍSICO"
                    cep_nota = None

                    if chave:
                        time.sleep(2.0)
                        detalhes = self.buscar_detalhes_esl_interno(chave, numero, token_geral)
                        if detalhes:
                            nome_det = detalhes.get('ioe_rpt_name')
                            if nome_det: 
                                destinatario = str(nome_det).upper()

                            rua = detalhes.get('ioe_rpt_mds_line_1', '')
                            num = detalhes.get('ioe_rpt_mds_number', '')
                            if rua:
                                endereco = f"{rua} {num}".strip().upper()

                            cep_val = (
                                detalhes.get('ioe_rpt_mds_postal_code') or 
                                detalhes.get('ioe_rpt_zip_code') or 
                                detalhes.get('ioe_rpt_mds_zip_code') or 
                                detalhes.get('zip_code') or 
                                detalhes.get('cep')
                            )
                            if cep_val:
                                cep_nota = str(cep_val).strip()[:10]

                    time.sleep(2.0)
                    dados_frete = self.buscar_dados_frete_report_7693(chave, numero, token_geral)
                    frete_obj = None
                    if dados_frete:
                        seq_code_frete = dados_frete.get('sequence_code')
                        if seq_code_frete:
                            def extrair_decimal(valor):
                                try: return float(valor) if valor else None
                                except: return None
                            
                            frete_obj, _ = Frete.objects.get_or_create(
                                freight_id_tms=str(seq_code_frete),
                                defaults={
                                    'numero_cte': str(dados_frete.get('fit_fhe_cte_number', '')) if dados_frete.get('fit_fhe_cte_number') else None,
                                    'chave_cte': dados_frete.get('fit_fhe_cte_key'),
                                    'modal': dados_frete.get('modal'),
                                    'valor_frete': extrair_decimal(dados_frete.get('total')),
                                    'peso_taxado': extrair_decimal(dados_frete.get('taxed_weight')),
                                    'volumes': int(dados_frete.get('invoices_volumes', 0)) if dados_frete.get('invoices_volumes') else None,
                                    'remetente': dados_frete.get('fit_sdr_nickname'),
                                    'pagador_nome': dados_frete.get('fit_pyr_nickname'),
                                    'pagador_documento': dados_frete.get('fit_pyr_document'),
                                    'natureza_carga': dados_frete.get('fit_psn_name')
                                }
                            )

                    nota_obj = NotaFiscal.objects.create(
                        manifesto=manifesto_obj,
                        chave_acesso=chave if chave else None,
                        numero_nota=str(numero),
                        destinatario=destinatario,
                        endereco_entrega=endereco,
                        cep=cep_nota,
                        tipo_operacao=tipo_operacao,
                        status='PENDENTE',
                        freight_id_tms=str(freight_id) if freight_id else None,
                        frete=frete_obj
                    )
                    ids_processadas.append(nota_obj.id)
                    total_processadas += 1

                    # 📍 Dispara enriquecimento de geolocalização automática se não tiver coordenadas
                    if nota_obj and (nota_obj.latitude is None or nota_obj.longitude is None):
                        try:
                            from manifesto.tasks import enriquecer_geolocalizacao_nota_task
                            enriquecer_geolocalizacao_nota_task.delay(nota_obj.id)
                        except Exception as geo_err:
                            logger.warning(f"Erro ao agendar geolocalização para nota #{nota_obj.numero_nota}: {geo_err}")

                except Exception as e:
                    logger.warning(f"⚠️ Erro no documento {id_doc}: {e}")
                    continue
            
            log.status = 'PROCESSADO'
            log.save()

            time.sleep(2.1)
            total_coletas = 0
            try:
                report_coletas = getattr(self.config, 'report_coletas', '11324')
                coletas = self.buscar_coletas_esl(numero_visual, token_geral, self.config.dominio_esl, report_coletas)
                
                if coletas:
                    for coleta in coletas:
                        seq_code = coleta.get('sequence_code')
                        if not seq_code:
                            continue
                        
                        solicitante = coleta.get('pck_pln_name', '')
                        if not solicitante:
                            solicitante = coleta.get('requester', 'SOLICITANTE NÃO INFORMADO')
                        destinatario = str(solicitante).upper()
                        
                        rua = coleta.get('pck_pln_mds_line_1', '')
                        num = coleta.get('pck_pln_mds_number', '')
                        bairro = coleta.get('pck_pln_mds_neighborhood', '')
                        cidade = coleta.get('pck_pln_mds_cty_name', '')
                        
                        partes_endereco = [rua, num, bairro, cidade]
                        endereco = ", ".join([p.strip() for p in partes_endereco if p and str(p).strip()])
                        if not endereco:
                            endereco = "ENDEREÇO NÃO INFORMADO"
                        endereco = endereco.upper()
                        
                        coleta_obj, _ = NotaFiscal.objects.update_or_create(
                            manifesto=manifesto_obj,
                            numero_nota=str(seq_code),
                            tipo_operacao='COLETA',
                            defaults={
                                'destinatario': destinatario,
                                'endereco_entrega': endereco,
                                'numero_coleta': str(seq_code),
                            }
                        )
                        ids_processadas.append(coleta_obj.id)
                        total_coletas += 1
                    
                    if total_coletas > 0:
                        qtd_coletas = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='COLETA').count()
                        manifesto_obj.qtd_retirada = qtd_coletas
                        manifesto_obj.save(update_fields=['qtd_retirada'])
                        
                logger.info(f"Coletas para {numero_visual}: {total_coletas} encontradas e salvas.")
            except Exception as e:
                logger.warning(f"⚠️ Erro ao processar coletas para o manifesto {numero_visual}: {e}. Disparando retry em background.")
                from manifesto.tasks import buscar_coletas_manifesto_task
                buscar_coletas_manifesto_task.apply_async(
                    args=[manifesto_obj.id, numero_visual],
                    countdown=30
                )

            # === REMOÇÃO DE NOTAS ÓRFÃS ===
            try:
                if ids_processadas:
                    notas_removidas = NotaFiscal.objects.filter(
                        manifesto=manifesto_obj,
                        status__in=['PENDENTE', 'AGUARDANDO']
                    ).exclude(id__in=ids_processadas)
                    
                    qtd_removidas = notas_removidas.count()
                    if qtd_removidas > 0:
                        logger.info(f"🗑️ Removendo {qtd_removidas} notas órfãs do manifesto {numero_visual} que foram excluídas no TMS.")
                        notas_removidas.delete()
            except Exception as e:
                logger.error(f"Erro ao tentar remover notas órfãs: {e}")

            logger.info(f"✅ Manifesto {numero_visual} processado. Entregas/Transferências: {total_processadas}. Coletas: {total_coletas}")

            transaction.on_commit(lambda: enviar_painel(manifesto_obj))

            return f"Manifesto {numero_visual} processado: {total_processadas} notas/minutas + {total_coletas} coletas."

        except Exception as e:
            logger.error(f"🔴 Erro crítico: {str(e)}")
            log.status, log.mensagem_erro = 'ERRO', str(e)
            log.save()
            if task:
                raise task.retry(exc=e, countdown=60)
            raise

    def buscar_coletas_manifesto(self, manifesto_id, numero_visual, task=None):
        logger.info(f"Iniciando busca de coletas em background para manifesto {numero_visual}")

        try:
            manifesto_obj = Manifesto.objects.get(id=manifesto_id)
            token_geral = self.config.token_analytics
            dominio = self.config.dominio_esl
            report_coletas = getattr(self.config, 'report_coletas', '11324')
            
            coletas = self.buscar_coletas_esl(numero_visual, token_geral, dominio, report_coletas)
            
            if coletas:
                total_adicionadas = 0
                for coleta in coletas:
                    seq_code = coleta.get('sequence_code')
                    if not seq_code:
                        continue
                    
                    solicitante = coleta.get('pck_pln_name', '')
                    if not solicitante:
                        solicitante = coleta.get('requester', 'SOLICITANTE NÃO INFORMADO')
                        
                    destinatario = str(solicitante).upper()
                    
                    rua = coleta.get('pck_pln_mds_line_1', '')
                    num = coleta.get('pck_pln_mds_number', '')
                    bairro = coleta.get('pck_pln_mds_neighborhood', '')
                    cidade = coleta.get('pck_pln_mds_cty_name', '')
                    
                    partes_endereco = [rua, num, bairro, cidade]
                    endereco = ", ".join([p.strip() for p in partes_endereco if p and str(p).strip()])
                    if not endereco:
                        endereco = "ENDEREÇO NÃO INFORMADO"
                    endereco = endereco.upper()
                    
                    NotaFiscal.objects.update_or_create(
                        manifesto=manifesto_obj,
                        numero_nota=str(seq_code),
                        tipo_operacao='COLETA',
                        defaults={
                            'destinatario': destinatario,
                            'endereco_entrega': endereco,
                            'numero_coleta': str(seq_code),
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
            if task:
                raise task.retry(exc=e, countdown=60)
            raise

    def enviar_baixa(self, baixa_id, task=None):
        TOKEN = self.config.token_invoices
        URL_ESL = f"https://{self.config.dominio_esl}/api/invoice_occurrences"

        try:
            baixa = BaixaNF.objects.select_related(
                'nota_fiscal',
                'ocorrencia',
                'nota_fiscal__manifesto',
                'nota_fiscal__manifesto__motorista'
            ).get(id=baixa_id)

            nf = baixa.nota_fiscal
            
            # --- PROTEÇÃO DE IDEMPOTÊNCIA: Se já foi integrada com sucesso, não envia de novo ---
            if baixa.integrado_tms:
                logger.info(f"⏭️ Baixa #{baixa_id} (NF {nf.numero_nota}) já integrada ao TMS com sucesso. Pulando reenvio.")
                return f"Baixa {baixa_id} já integrada previamente."
            
            # --- DESPACHO SEM CHAVE: Usa endpoint de Frete (Minuta) ---
            # REGRA: Se tem chave_acesso, SEMPRE usa o endpoint de NF-e (normal).
            # O endpoint de Frete/Minuta só é usado quando NÃO há chave de acesso.
            tipo_op = str(nf.tipo_operacao or '').strip().upper()
            if ('DESPACHO' in tipo_op or tipo_op == 'DESPACHO') and not nf.chave_acesso:
                logger.info(f"🚀 NF {nf.numero_nota} é DESPACHO sem chave. Redirecionando para enviar_baixa_minuta (Frete ESL V1)")
                return self.enviar_baixa_minuta(baixa_id, task=task)
            
            # NOTA: O endpoint de Frete/Minuta só é usado quando a NF NÃO possui chave de acesso.





            if not nf.chave_acesso:
                # Coletas usam endpoint próprio (/api/v1/picks/) e não precisam de freight_id
                if nf.numero_coleta or nf.tipo_operacao == 'COLETA':
                    logger.info(f"Redirecionando baixa {baixa_id} (coleta) para enviar_coleta")
                    return self.enviar_coleta(baixa_id, task=task)
                logger.info(f"Redirecionando baixa {baixa_id} (minuta) para enviar_baixa_minuta")
                return self.enviar_baixa_minuta(baixa_id, task=task)

            manifesto = nf.manifesto
            motorista = manifesto.motorista.nome_completo if manifesto.motorista else "Motorista não identificado"
            url_foto = baixa.comprovante_foto_url or ""
            
            codigo_tms_val = (baixa.ocorrencia.codigo_tms or baixa.ocorrencia.codigo_referencia) if baixa.ocorrencia else None
            codigo_ocorrencia, trace_ocorrencia = obter_codigo_ocorrencia_seguro(codigo_tms_val, tipo_operacao=nf.tipo_operacao, nota_fiscal=nf)

            tms_manifest_id = manifesto.numero_manifesto 
            
            fuso_brasilia = pytz.timezone('America/Sao_Paulo')
            data_br = baixa.data_baixa.astimezone(fuso_brasilia)
            data_ocorrencia_str = data_br.strftime('%Y-%m-%dT%H:%M:%S.000-03:00')

            # =====================================================
            # OCORRÊNCIA 125 (RECUSA TOTAL) - ENVIO INTELIGENTE POR FRETE
            # Quando é recusa (125), envia direto para o endpoint de FRETE
            # ao invés de enviar nota por nota. Isso evita o bloqueio 422 da ESL.
            # =====================================================
            CODIGOS_RECUSA_TOTAL = [125]
            
            if codigo_ocorrencia in CODIGOS_RECUSA_TOTAL and nf.frete and nf.frete.freight_id_tms:
                frete = nf.frete
                
                # Verifica se outra nota do mesmo frete JÁ foi integrada com sucesso (recusa já enviada pro frete)
                ja_integrado_no_frete = BaixaNF.objects.filter(
                    nota_fiscal__frete=frete,
                    integrado_tms=True,
                    ocorrencia=baixa.ocorrencia  # mesma ocorrência (125)
                ).exclude(id=baixa_id).exists()
                
                if ja_integrado_no_frete:
                    # BYPASS: O frete já recebeu a recusa pela primeira nota. Não precisa enviar de novo.
                    logger.info(f"Bypass inteligente: Frete {frete.freight_id_tms} já recebeu recusa. NF {nf.numero_nota} marcada localmente.")
                    baixa.log_erro_tms = f"Sucesso (Bypass): Recusa já registrada no Frete {frete.freight_id_tms}. Ocorrência aceita localmente."
                    baixa.processado_tms = True
                    baixa.integrado_tms = True
                    baixa.data_integracao = timezone.now()
                    baixa.payload_enviado = {"bypass": True, "motivo": "Frete já possui recusa integrada"}
                    baixa.save()
                    
                    if nf.status != 'OCORRENCIA':
                        nf.status = 'OCORRENCIA'
                        nf.save(update_fields=['status'])
                    
                    try:
                        from operacional.services import resolver_erros_automaticamente
                        resolver_erros_automaticamente(manifesto.numero_manifesto, nf.numero_nota, manifesto.filial)
                    except Exception as e:
                        logger.error(f"Erro auto-resolucao bypass: {e}")
                    
                    return f"Baixa {baixa_id} integrada (Bypass - Frete já recusado)."
                
                # PRIMEIRA NOTA DO FRETE COM RECUSA: Envia para o endpoint de FRETE
                id_interno_frete = nf.freight_id_tms or frete.freight_id_tms
                logger.info(f"Ocorrência 125 detectada. Enviando recusa para FRETE ID {id_interno_frete} ao invés de nota individual.")
                
                comentario_final = f"Recusa total via App - Motorista: {motorista}. NF: {nf.numero_nota}. Obs: {baixa.observacao or ''}"
                
                url_frete_endpoint = f"https://{self.config.dominio_esl}/api/v1/freights/{id_interno_frete}/invoice_occurrences"
                payload_frete = {
                    "invoice_occurrence": {
                        "receiver": baixa.recebedor or "Nao identificado",
                        "document_number": baixa.documento_recebedor or "",
                        "comments": comentario_final,
                        "occurrence_at": data_ocorrencia_str,
                        "occurrence": {
                            "code": codigo_ocorrencia
                        }
                    }
                }
                
                # ESL Cloud não aceita 'delivery_receipt_url' no endpoint de Frete.
                # Removemos a lógica de enviar foto nesse endpoint.
                
                baixa.payload_enviado = payload_frete
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {TOKEN}"
                }
                
                print(f"Enviando recusa (125) para FRETE {frete.freight_id_tms} - CT-e: {frete.numero_cte}")
                
                response = requests.post(
                    url_frete_endpoint,
                    json=payload_frete,
                    headers=headers,
                    timeout=30
                )
                
                response.raise_for_status()
                
                # Sucesso! Marca a baixa como integrada
                baixa.processado_tms = True
                baixa.integrado_tms = True
                baixa.data_integracao = timezone.now()
                baixa.log_erro_tms = f"Sucesso: Recusa integrada via Frete {frete.freight_id_tms} (CT-e {frete.numero_cte})"
                baixa.save()
                
                # Marca TODAS as notas deste frete no mesmo manifesto como OCORRENCIA
                notas_do_frete = NotaFiscal.objects.filter(frete=frete, manifesto=manifesto)
                notas_atualizadas = notas_do_frete.exclude(status='OCORRENCIA').update(status='OCORRENCIA')
                logger.info(f"Marcadas {notas_atualizadas} notas do Frete {frete.freight_id_tms} como OCORRENCIA.")
                
                try:
                    from operacional.services import resolver_erros_automaticamente
                    resolver_erros_automaticamente(manifesto.numero_manifesto, nf.numero_nota, manifesto.filial)
                except Exception as e:
                    logger.error(f"Erro auto-resolucao: {e}")
                
                return f"Baixa {baixa_id} integrada via Frete {frete.freight_id_tms}."
            
            # =====================================================
            # FLUXO NORMAL (entregas, ocorrências parciais, etc.)
            # =====================================================

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
                    "delivery_receipt_url": url_foto,
                    "occurrence": {
                        "code": codigo_ocorrencia
                    }
                } if url_foto else {}

            prefixo_retida = "[NOTA RETIDA] " if not url_foto and codigo_ocorrencia in [1, 2] else ""
            comentario_final = f"{prefixo_retida}Baixa via App - Motorista: {motorista}. Obs: {baixa.observacao or ''}"

            payload = {
                "invoice_occurrence": {
                    "receiver": baixa.recebedor or "Nao identificado",
                    "document_number": baixa.documento_recebedor or "",
                    "comments": comentario_final,
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

            if freight_data:
                payload["invoice_occurrence"]["freight"] = freight_data

            baixa.payload_enviado = {
                **payload,
                "_debug_trace": {
                    "codigo_tms_val_original": codigo_tms_val,
                    "codigo_final_enviado": codigo_ocorrencia,
                    "nf_tipo_operacao": nf.tipo_operacao,
                    "ocorrencia_db_id": getattr(baixa.ocorrencia, 'id', None),
                    "ocorrencia_db_tms": getattr(baixa.ocorrencia, 'codigo_tms', None),
                    "ocorrencia_db_ref": getattr(baixa.ocorrencia, 'codigo_referencia', None),
                    "trace": trace_ocorrencia
                }
            }

            logger.info(f"🚀 [ESL TRANSMISSÃO NF-e] NF: {nf.numero_nota} | Chave: {nf.chave_acesso}")
            logger.info(f"   -> NF.tipo_operacao: '{nf.tipo_operacao}'")
            logger.info(f"   -> Baixa Ocorrência DB: ID={getattr(baixa.ocorrencia, 'id', 'None')}, TMS='{getattr(baixa.ocorrencia, 'codigo_tms', 'None')}', Ref='{getattr(baixa.ocorrencia, 'codigo_referencia', 'None')}', Desc='{getattr(baixa.ocorrencia, 'descricao', 'None')}'")
            logger.info(f"   -> Código Final Enviado: {codigo_ocorrencia}")
            logger.info(f"   -> PAYLOAD INTEGRAL ENVIADO PARA ESL:\n{json.dumps(payload, indent=2)}")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}"
            }

            print(f"Enviando baixa da NF {nf.chave_acesso} para o Manifesto TMS ID: {tms_manifest_id}")

            response = requests.post(
                URL_ESL,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()

            baixa.processado_tms = True
            baixa.integrado_tms = True
            baixa.data_integracao = timezone.now()
            baixa.log_erro_tms = "Sucesso: Integrado com ESL vinculando ao Manifesto"
            baixa.save()
            
            try:
                from operacional.services import resolver_erros_automaticamente
                resolver_erros_automaticamente(manifesto.numero_manifesto, nf.numero_nota, manifesto.filial)
            except Exception as e:
                logger.error(f"Erro auto-resolucao: {e}")

            return f"Baixa {baixa_id} integrada com sucesso."

        except BaixaNF.DoesNotExist:
            return f"Baixa {baixa_id} não encontrada"

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
            detalhe_erro = exc.response.text if hasattr(exc, 'response') and exc.response is not None else str(exc)
            
            # --- AUTO-BYPASS PARA TRATATIVAS DE CT-E MÚLTIPLAS NOTAS ---
            # Se der 422 dizendo que o CT-e não permite alteração e a ocorrência que estamos mandando é uma ocorrência (não entrega)
            detalhe_lower = detalhe_erro.lower()

            # 1. IDEMPOTÊNCIA: Se a ocorrência já existe na ESL (já foi cadastrada com sucesso antes)
            eh_ja_existe = (
                status == 422 and (
                    "já existe" in detalhe_lower or
                    "ja existe" in detalhe_lower or
                    "já cadastrada" in detalhe_lower or
                    "ja cadastrada" in detalhe_lower or
                    "já se encontra" in detalhe_lower or
                    "ja se encontra" in detalhe_lower or
                    "já finalizad" in detalhe_lower or
                    "ja finalizad" in detalhe_lower
                )
            )
            if eh_ja_existe:
                logger.info(f"✅ NF {nf.numero_nota}: Ocorrência já registrada previamente no TMS (ESL Cloud). Marcando como sucesso (Idempotência).")
                baixa.log_erro_tms = "Sucesso: Ocorrência já registrada previamente no TMS (ESL Cloud)."
                baixa.processado_tms = True
                baixa.integrado_tms = True
                baixa.data_integracao = timezone.now()
                baixa.save()
                
                # Auto-resolução na Torre de Erros
                try:
                    from operacional.services import resolver_erros_automaticamente
                    resolver_erros_automaticamente(manifesto.numero_manifesto, nf.numero_nota, manifesto.filial)
                except Exception as e:
                    logger.error(f"Erro auto-resolucao ja_existe: {e}")
                
                return f"Baixa {baixa_id} integrada (Já existia no TMS)."

            # 2. TRATATIVA DE CT-E MULTI-NOTAS
            eh_tratativa_cte = (
                status == 422 and (
                    "não permite alteração de status" in detalhe_erro or
                    "nao permite alteracao de status" in detalhe_lower or
                    "n\u00e3o permite altera\u00e7\u00e3o" in detalhe_lower
                )
            )
            if eh_tratativa_cte and codigo_ocorrencia not in [1, 2]:
                logger.info(f"Bypass de erro 422 para NF {nf.numero_nota}: CT-e {nf.frete.numero_cte if nf.frete else 'N/A'} já está em tratativa na ESL.")
                baixa.log_erro_tms = "Sucesso (Bypass): CT-e já se encontra em tratativa no TMS. Ocorrência aceita localmente."
                baixa.processado_tms = True
                baixa.integrado_tms = True
                baixa.data_integracao = timezone.now()
                baixa.save()
                
                # Atualiza status da NF para OCORRENCIA, já que o CT-e inteiro foi recusado
                if nf.status != 'OCORRENCIA':
                    nf.status = 'OCORRENCIA'
                    nf.save(update_fields=['status'])
                
                # Limpa erros anteriores desta nota na Torre de Erros
                try:
                    from operacional.services import resolver_erros_automaticamente
                    resolver_erros_automaticamente(manifesto.numero_manifesto, nf.numero_nota, manifesto.filial)
                except Exception as e:
                    logger.error(f"Erro auto-resolucao bypass: {e}")
                
                return f"Baixa {baixa_id} integrada (Bypass Tratativa)."

            msg_erro = f"Erro {status}: {detalhe_erro}"

            baixa.log_erro_tms = msg_erro[:500]
            baixa.integrado_tms = False
            baixa.save()

            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=manifesto.filial,
                    categoria='INTEGRACAO_BAIXA',
                    severidade_padrao='CRITICO',
                    titulo=f"Falha integração NF {nf.numero_nota}",
                    descricao=f"Manifesto #{manifesto.numero_manifesto} - {msg_erro[:300]}",
                    erro_raw=msg_erro,
                    manifesto_numero=manifesto.numero_manifesto,
                    nota_fiscal_numero=nf.numero_nota,
                    motorista_nome=motorista,
                )
            except Exception as tr_exc:
                logger.error(f"Erro ao registrar torre de controle: {tr_exc}")

            if status and 400 <= status < 500:
                notificar_falha_tms(baixa_id, msg_erro, "enviar_baixa_esl_task")
                return f"Erro de validação ESL: {msg_erro}"

            if task and task.request.retries < task.max_retries:
                raise task.retry(exc=exc, countdown=60)

            return f"Falha definitiva ESL: {msg_erro}"

        except Exception as e:
            msg = f"Erro inesperado: {str(e)}"
            baixa.log_erro_tms = msg[:500]
            baixa.save()
            
            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=manifesto.filial,
                    categoria='INTEGRACAO_BAIXA',
                    severidade_padrao='CRITICO',
                    titulo=f"Erro inesperado NF {nf.numero_nota}",
                    descricao=f"Manifesto #{manifesto.numero_manifesto} - {msg[:300]}",
                    erro_raw=msg,
                    manifesto_numero=manifesto.numero_manifesto,
                    nota_fiscal_numero=nf.numero_nota,
                    motorista_nome=motorista,
                )
            except Exception as tr_exc:
                logger.error(f"Erro ao registrar torre de controle: {tr_exc}")
            if task:
                raise task.retry(exc=e, countdown=60)
            raise

    def _buscar_freight_id_por_numero(self, numero_nota, manifesto_id_tms, token):
        """
        Busca o freight_id na ESL pesquisando invoice_occurrences do manifesto
        e encontrando o item cujo invoice.number bate com numero_nota.
        """
        url = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"manifest_id": str(manifesto_id_tms), "per": 50}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code != 200:
                return None
            
            data = response.json()
            for item in data.get("data", []):
                invoice = item.get("invoice", {})
                # Compara numero removendo zeros à esquerda de ambos
                numero_esl = str(invoice.get("number", "")).strip()
                numero_local = str(numero_nota).strip()
                
                # Comparação direta e sem zeros à esquerda
                if numero_esl == numero_local or numero_esl.lstrip('0') == numero_local.lstrip('0'):
                    freight = item.get("freight")
                    if freight and freight.get("id"):
                        return str(freight["id"])
        except Exception as e:
            logger.warning(f"Erro ao buscar freight_id por número {numero_nota}: {e}")
        
        return None

    def enviar_baixa_minuta(self, baixa_id, task=None):
        """
        Envia baixa de minuta (sem chave NF-e) para a ESL.
        Minutas DEVEM usar o endpoint V1 de freight (/api/v1/freights/{id}/invoice_occurrences)
        porque o endpoint geral (/api/invoice_occurrences) exige 'key' que minutas não possuem.
        """
        TOKEN = self.config.token_invoices
        payload = None
        try:
            baixa = BaixaNF.objects.select_related(
                'nota_fiscal',
                'ocorrencia',
                'nota_fiscal__manifesto',
                'nota_fiscal__manifesto__motorista'
            ).get(id=baixa_id)
            nf = baixa.nota_fiscal
            
            # --- PROTEÇÃO DE IDEMPOTÊNCIA: Se já foi integrada com sucesso, não envia de novo ---
            if baixa.integrado_tms:
                logger.info(f"⏭️ Baixa de Minuta #{baixa_id} (NF {nf.numero_nota}) já integrada ao TMS. Pulando reenvio.")
                return f"Baixa de Minuta {baixa_id} já integrada previamente."

            freight_id = nf.freight_id_tms
            manifesto = nf.manifesto
            
            codigo_tms_val = (baixa.ocorrencia.codigo_tms or baixa.ocorrencia.codigo_referencia) if baixa.ocorrencia else None
            tipo_op_nf = str(nf.tipo_operacao or '').strip().upper()
            codigo_ocorrencia, trace_ocorrencia = obter_codigo_ocorrencia_seguro(codigo_tms_val, tipo_operacao=nf.tipo_operacao, nota_fiscal=nf)
            
            logger.info(f"Minuta {nf.numero_nota}: tipo_operacao='{tipo_op_nf}', codigo_tms_val='{codigo_tms_val}', codigo_final={codigo_ocorrencia}")
            
            fuso_br = pytz.timezone('America/Sao_Paulo')
            data_ocorrencia_str = baixa.data_baixa.astimezone(fuso_br).strftime('%Y-%m-%dT%H:%M:%S.000-03:00')
            
            # Se não temos freight_id salvo, busca na ESL pelo número da nota no manifesto
            if not freight_id and manifesto and manifesto.manifesto_id_tms:
                logger.info(f"Minuta {nf.numero_nota}: freight_id não salvo. Buscando na ESL...")
                freight_id = self._buscar_freight_id_por_numero(
                    nf.numero_nota, 
                    manifesto.numero_manifesto, 
                    TOKEN
                )
                # Salva o freight_id encontrado para futuras tentativas
                if freight_id:
                    nf.freight_id_tms = freight_id
                    nf.save(update_fields=['freight_id_tms'])
                    logger.info(f"Minuta {nf.numero_nota}: freight_id encontrado = {freight_id}")
            
            if not freight_id:
                raise Exception(
                    f"Minuta {nf.numero_nota} sem freight_id. "
                    f"Não é possível enviar baixa sem freight_id (endpoint geral exige chave NF-e)."
                )



            # Envia via endpoint V1 de freight (único que funciona para minutas)
            URL_ESL_FRETE = f"https://{self.config.dominio_esl}/api/v1/freights/{freight_id}/invoice_occurrences"
            
            motorista = manifesto.motorista.nome_completo if (manifesto and manifesto.motorista) else "Motorista não identificado"
            
            payload = {
                "invoice_occurrence": {
                    "receiver": baixa.recebedor or "Nao identificado",
                    "document_number": baixa.documento_recebedor or "",
                    "comments": f"Baixa Minuta via App - Motorista: {motorista}. Obs: {baixa.observacao or ''}",
                    "occurrence_at": data_ocorrencia_str,
                    "latitude": float(baixa.latitude) if baixa.latitude else None,
                    "longitude": float(baixa.longitude) if baixa.longitude else None,
                    "occurrence": {
                        "code": codigo_ocorrencia
                    }
                }
            }
            
            # ESL Cloud não aceita 'delivery_receipt_url' no endpoint de Frete.
            # Lógica de enviar foto comentada/removida para evitar Erro 400.
            
            baixa.payload_enviado = {
                **payload,
                "_debug_trace": {
                    "codigo_tms_val_original": codigo_tms_val,
                    "codigo_final_enviado": codigo_ocorrencia,
                    "nf_tipo_operacao": nf.tipo_operacao,
                    "ocorrencia_db_id": getattr(baixa.ocorrencia, 'id', None),
                    "ocorrencia_db_tms": getattr(baixa.ocorrencia, 'codigo_tms', None),
                    "ocorrencia_db_ref": getattr(baixa.ocorrencia, 'codigo_referencia', None),
                    "trace": trace_ocorrencia
                }
            }

            logger.info(f"🚀 [ESL TRANSMISSÃO MINUTA/FRETE V1] Minuta NF: {nf.numero_nota} | Freight ID: {freight_id}")
            logger.info(f"   -> NF.tipo_operacao: '{nf.tipo_operacao}'")
            logger.info(f"   -> Baixa Ocorrência DB: ID={getattr(baixa.ocorrencia, 'id', 'None')}, TMS='{getattr(baixa.ocorrencia, 'codigo_tms', 'None')}', Ref='{getattr(baixa.ocorrencia, 'codigo_referencia', 'None')}', Desc='{getattr(baixa.ocorrencia, 'descricao', 'None')}'")
            logger.info(f"   -> Código Final Enviado: {codigo_ocorrencia}")
            logger.info(f"   -> PAYLOAD INTEGRAL ENVIADO PARA ESL:\n{json.dumps(payload, indent=2)}")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}"
            }
            
            logger.info(f"Enviando Minuta {nf.numero_nota} via Freight V1 (ID: {freight_id})")
            logger.info(f"Payload: {json.dumps(payload)}")
            response = requests.post(URL_ESL_FRETE, json=payload, headers=headers, timeout=30)
            
            response.raise_for_status()

            baixa.processado_tms = True
            baixa.integrado_tms = True
            baixa.data_integracao = timezone.now()
            baixa.log_erro_tms = f"Sucesso: Baixa de Minuta integrada via Freight ID {freight_id}"
            baixa.save()
            
            try:
                from operacional.services import resolver_erros_automaticamente
                resolver_erros_automaticamente(nf.manifesto.numero_manifesto, nf.numero_nota, nf.manifesto.filial)
            except Exception as auto_e:
                logger.error(f"Erro auto-resolucao minuta: {auto_e}")
            
            return f"Baixa de Minuta {nf.numero_nota} enviada com sucesso (Freight: {freight_id})."

        except Exception as e:
            payload_str = f" | Payload: {json.dumps(payload)}" if payload else ""
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)
            response_text = getattr(getattr(e, 'response', None), 'text', '')
            detalhe_lower = (response_text or str(e)).lower()

            eh_ja_existe = (
                status_code == 422 and (
                    "já existe" in detalhe_lower or
                    "ja existe" in detalhe_lower or
                    "já cadastrada" in detalhe_lower or
                    "ja cadastrada" in detalhe_lower or
                    "já se encontra" in detalhe_lower or
                    "ja se encontra" in detalhe_lower or
                    "não permite alteração" in detalhe_lower or
                    "nao permite alteracao" in detalhe_lower
                )
            )
            if eh_ja_existe:
                logger.info(f"✅ Minuta {nf.numero_nota}: Ocorrência já registrada previamente no TMS (ESL). Marcando como sucesso (Idempotência).")
                baixa.processado_tms = True
                baixa.integrado_tms = True
                baixa.data_integracao = timezone.now()
                baixa.log_erro_tms = "Sucesso: Baixa de Minuta já registrada previamente no TMS (ESL Cloud)."
                baixa.save()
                
                try:
                    from operacional.services import resolver_erros_automaticamente
                    resolver_erros_automaticamente(nf.manifesto.numero_manifesto, nf.numero_nota, nf.manifesto.filial)
                except Exception as auto_e:
                    logger.error(f"Erro auto-resolucao minuta ja_existe: {auto_e}")
                
                return f"Baixa de Minuta {nf.numero_nota} integrada (Já existia no TMS)."

            msg_falha = f"Erro na integração da Minuta: {str(e)}{payload_str}"
            if status_code:
                msg_falha = f"Erro na integração da Minuta ({status_code}): {response_text}{payload_str}"
            baixa.log_erro_tms = msg_falha[:500]
            baixa.integrado_tms = False
            baixa.save()
            
            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=nf.manifesto.filial,
                    categoria='INTEGRACAO_MINUTA',
                    severidade_padrao='CRITICO',
                    titulo=f"Falha na Minuta {nf.numero_nota}",
                    descricao=f"Manifesto #{nf.manifesto.numero_manifesto} - {msg_falha[:300]}",
                    erro_raw=msg_falha,
                    manifesto_numero=nf.manifesto.numero_manifesto,
                    nota_fiscal_numero=nf.numero_nota,
                    motorista_nome=nf.manifesto.motorista.nome_completo if nf.manifesto.motorista else "Desconhecido",
                )
            except Exception as tr_exc:
                logger.error(f"Erro ao registrar torre de controle: {tr_exc}")
            
            notificar_falha_tms(baixa_id, msg_falha, "enviar_baixa_minuta_task")
            
            if task:
                raise task.retry(exc=e, countdown=60)
            raise

    def enviar_coleta(self, baixa_id, task=None):
        TOKEN = self.config.token_invoices
        
        try:
            baixa = BaixaNF.objects.select_related('nota_fiscal', 'ocorrencia', 'nota_fiscal__manifesto').get(id=baixa_id)
            nf = baixa.nota_fiscal
            manifesto = nf.manifesto
            
            # --- PROTEÇÃO DE IDEMPOTÊNCIA: Se já foi integrada com sucesso, não envia de novo ---
            if baixa.integrado_tms:
                logger.info(f"⏭️ Coleta #{baixa_id} (NF/Coleta {nf.numero_nota}) já integrada ao TMS. Pulando reenvio.")
                return f"Coleta {baixa_id} já integrada previamente."
            
            identificador = (nf.numero_coleta or nf.freight_id_tms or nf.numero_nota or "").strip()
            
            if not identificador:
                msg = "Erro: Nenhum identificador de coleta encontrado (numero_coleta/freight_id_tms)."
                baixa.integrado_tms = False
                baixa.log_erro_tms = msg
                baixa.save()
                return msg

            fuso_br = pytz.timezone('America/Sao_Paulo')
            data_iso_v2 = baixa.data_baixa.astimezone(fuso_br).strftime('%Y-%m-%dT%H:%M:%S.000-03:00')

            is_numeric = identificador.isdigit()
            
            codigo_tms_val = (baixa.ocorrencia.codigo_tms or baixa.ocorrencia.codigo_referencia) if baixa.ocorrencia else None
            codigo_ocorrencia = limpar_codigo_ocorrencia(codigo_tms_val) if codigo_tms_val else 1

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}"
            }

            if is_numeric:
                url = f"https://{self.config.dominio_esl}/api/v1/picks/{identificador}/pick_occurrences"
                payload = {
                    "pick_occurrence": {
                        "receiver": baixa.recebedor or "Nao identificado",
                        "document_number": baixa.documento_recebedor or "",
                        "comments": f"Coleta via App - Obs: {baixa.observacao or ''}",
                        "occurrence_at": data_iso_v2,
                        "latitude": float(baixa.latitude) if baixa.latitude else 0.0,
                        "longitude": float(baixa.longitude) if baixa.longitude else 0.0,
                        "occurrence": {
                            "code": codigo_ocorrencia
                        }
                    }
                }
                logger.info(f"Enviando Coleta V1 (Picks): {url}")
            else:
                url = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
                payload = {
                    "invoice_occurrence": {
                        "occurrence_at": data_iso_v2,
                        "occurrence": {
                            "code": codigo_ocorrencia
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
                
                try:
                    from operacional.services import resolver_erros_automaticamente
                    resolver_erros_automaticamente(manifesto.numero_manifesto, identificador, manifesto.filial)
                except Exception as auto_e:
                    logger.error(f"Erro auto-resolucao coleta: {auto_e}")
                    
                return f"Coleta {identificador} enviada com sucesso ao ESL ({'V1' if is_numeric else 'V2'})."
            else:
                msg_erro = f"Status: {response.status_code} - {response.text}"
                baixa.processado_tms = True
                baixa.integrado_tms = False
                baixa.log_erro_tms = msg_erro[:500]
                baixa.payload_enviado = payload
                baixa.save()
                
                try:
                    from operacional.services import registrar_erro_torre
                    registrar_erro_torre(
                        filial=manifesto.filial,
                        categoria='INTEGRACAO_COLETA',
                        severidade_padrao='CRITICO',
                        titulo=f"Falha na Coleta {identificador}",
                        descricao=f"Manifesto #{manifesto.numero_manifesto} - {msg_erro[:300]}",
                        erro_raw=msg_erro,
                        manifesto_numero=manifesto.numero_manifesto,
                        nota_fiscal_numero=identificador,
                        motorista_nome=manifesto.motorista.nome_completo if manifesto.motorista else "Desconhecido",
                    )
                except Exception as tr_exc:
                    logger.error(f"Erro ao registrar torre de controle: {tr_exc}")
                
                notificar_falha_tms(baixa_id, msg_erro, "enviar_coleta_esl_task")
                
                if response.status_code == 404 and is_numeric:
                     logger.warning(f"ID numérico {identificador} deu 404 na V1. Tentando V2 em breve via retry.")
                
                raise Exception(f"Erro no ESL (Coleta): {msg_erro}")

        except Exception as e:
            logger.error(f"Erro enviar_coleta_esl_task ({baixa_id}): {str(e)}")
            
            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=manifesto.filial,
                    categoria='INTEGRACAO_COLETA',
                    severidade_padrao='CRITICO',
                    titulo=f"Erro inesperado na Coleta {baixa_id}",
                    descricao=str(e)[:300],
                    erro_raw=str(e),
                    manifesto_numero=manifesto.numero_manifesto,
                )
            except Exception as tr_exc:
                logger.error(f"Erro ao registrar torre de controle: {tr_exc}")
            if task:
                raise task.retry(exc=e, countdown=60)
            raise

    def finalizar_manifesto(self, manifesto_id, task=None):
        try:
            manifesto = Manifesto.objects.get(id=manifesto_id)
            
            if not manifesto.manifesto_id_tms:
                return f"Erro: Manifesto {manifesto.numero_manifesto} sem ID interno do TMS."

            # Garante que 100% das baixas/ocorrências deste manifesto estejam registradas na ESL antes de fechar
            from manifesto.models import BaixaNF
            baixas_pendentes_tms = BaixaNF.objects.filter(nota_fiscal__manifesto=manifesto, integrado_tms=False)
            for b in baixas_pendentes_tms:
                try:
                    if b.qualidade_canhoto == 'PENDENTE_ANALISE':
                        b.qualidade_canhoto = 'APROVADO'
                        b.solicitar_nova_foto = False
                        b.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])

                    if b.nota_fiscal and b.nota_fiscal.tipo_operacao == 'COLETA':
                        self.enviar_coleta(b.id)
                    elif b.nota_fiscal and b.nota_fiscal.chave_acesso:
                        self.enviar_baixa_nfe(b.id)
                    else:
                        self.enviar_baixa_minuta(b.id)
                except Exception as b_err:
                    print(f"⚠️ Aviso ao enviar baixa pendente #{b.id} antes do fechamento do manifesto: {b_err}")

            fuso_br = pytz.timezone('America/Sao_Paulo')
            data_fim = manifesto.data_finalizacao or timezone.now()
            data_iso = data_fim.astimezone(fuso_br).strftime('%Y-%m-%dT%H:%M:%S-03:00')

            url_graphql = f"https://{self.config.dominio_esl}/graphql"
            token = self.config.token_analytics

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

            response = requests.post(url_graphql, json={"query": mutation, "variables": variables}, headers=headers, timeout=30)
            
            if not response.text:
                 raise Exception(f"Resposta vazia da ESL. HTTP Status: {response.status_code}")

            res_data = response.json()
            result = res_data.get('data', {}).get('manifestClose', {})

            if result.get('success'):
                manifesto.status = 'FINALIZADO'
                manifesto.save()
                
                try:
                    from operacional.services import resolver_erros_automaticamente
                    resolver_erros_automaticamente(manifesto.numero_manifesto, None, manifesto.filial)
                except Exception as e:
                    pass
                
                # Notifica grupos: TMS OK
                try:
                    from whatsbot.tasks import notificar_finalizacao_manifesto_grupos
                    notificar_finalizacao_manifesto_grupos(manifesto_id, tms_sucesso=True)
                except Exception as notif_err:
                    logger.error(f"Erro ao notificar grupos (sucesso TMS): {notif_err}")
                
                return f"Manifesto {manifesto.numero_manifesto} finalizado com sucesso no TMS."
            else:
                erros = result.get('errors', 'Erro desconhecido')
                
                if "already closed" in str(erros).lower():
                    manifesto.status = 'FINALIZADO'
                    manifesto.save()
                    
                    try:
                        from operacional.services import resolver_erros_automaticamente
                        resolver_erros_automaticamente(manifesto.numero_manifesto, None, manifesto.filial)
                    except Exception as e:
                        pass
                    
                    # Notifica grupos: TMS já estava fechado (consideramos sucesso)
                    try:
                        from whatsbot.tasks import notificar_finalizacao_manifesto_grupos
                        notificar_finalizacao_manifesto_grupos(manifesto_id, tms_sucesso=True)
                    except Exception as notif_err:
                        logger.error(f"Erro ao notificar grupos (already closed): {notif_err}")
                    
                    return f"Manifesto {manifesto.numero_manifesto} já constava como fechado."
                raise Exception(f"TMS recusou fechamento: {erros}")

        except Exception as exc:
            # Verifica se é a última tentativa para não spammar o grupo de WhatsApp
            is_last_attempt = not task or (hasattr(task, 'request') and getattr(task.request, 'retries', 0) >= getattr(task, 'max_retries', 3))
            
            if is_last_attempt:
                try:
                    from whatsbot.tasks import notificar_finalizacao_manifesto_grupos
                    notificar_finalizacao_manifesto_grupos(manifesto_id, tms_sucesso=False, tms_erro_msg=str(exc))
                except Exception as notif_err:
                    logger.error(f"Erro ao notificar grupos (erro TMS/Rede): {notif_err}")
                    
            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=manifesto.filial,
                    categoria='FINALIZACAO_MANIFESTO',
                    severidade_padrao='CRITICO',
                    titulo=f"Falha finalização Manifesto #{manifesto.numero_manifesto}",
                    descricao=str(exc)[:300],
                    erro_raw=str(exc),
                    manifesto_numero=manifesto.numero_manifesto,
                    motorista_nome=manifesto.motorista.nome_completo if manifesto.motorista else "Desconhecido",
                )
            except Exception as tr_exc:
                logger.error(f"Erro ao registrar torre de controle: {tr_exc}")

            if task:
                raise task.retry(exc=exc, countdown=300)
            raise

    def enviar_comprovante_entrega(self, baixa_id, task=None):
        """
        Cadastra/Atualiza o comprovante de entrega (foto/canhoto) no TMS ESL Cloud.
        Endpoints ESL Cloud:
        1. NF-e (chave_acesso): POST /api/freight_invoice_delivery_receipts
        2. Frete / CT-e (chave_cte): POST /api/freight_delivery_receipts
        """
        TOKEN = self.config.token_invoices
        try:
            baixa = BaixaNF.objects.select_related(
                'nota_fiscal',
                'nota_fiscal__manifesto',
                'nota_fiscal__frete'
            ).get(id=baixa_id)

            nf = baixa.nota_fiscal
            url_foto = baixa.comprovante_foto_url
            if not url_foto:
                msg = f"Nenhuma URL de foto cadastrada na baixa #{baixa_id}."
                logger.warning(msg)
                return msg

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}"
            }

            # Define se a operação é por Frete (CT-e/Minuta/Despacho) ou por Invoice (NF-e)
            tipo_op = str(nf.tipo_operacao or '').strip().upper()
            is_operacao_frete = tipo_op in ['DESPACHO', 'TRANSFERENCIA', 'FRETE'] or (not nf.chave_acesso)

            chave_cte = nf.chave_cte or (nf.frete.chave_cte if (hasattr(nf, 'frete') and nf.frete) else None) or nf.numero_cte

            if is_operacao_frete and chave_cte:
                # 📍 Endpoint 1: Cadastrar Comprovante de Entrega por Frete (CT-e)
                url_esl = f"https://{self.config.dominio_esl}/api/freight_delivery_receipts"
                payload = {
                    "freight_delivery_receipt": {
                        "freight": {
                            "cte_key": str(chave_cte).strip(),
                            "delivery_receipt_url": str(url_foto).strip()
                        }
                    }
                }
                logger.info(f"📸 [ESL COMPROVANTE FRETE/CT-E] Enviando comprovante da Nota #{nf.numero_nota} (Chave CT-e: {chave_cte})")
            elif nf.chave_acesso:
                # 📍 Endpoint 2: Cadastrar Comprovante de Entrega por NF-e (Invoice)
                url_esl = f"https://{self.config.dominio_esl}/api/freight_invoice_delivery_receipts"
                payload = {
                    "freight_invoice_delivery_receipt": {
                        "invoice": {
                            "key": str(nf.chave_acesso).strip(),
                            "delivery_receipt_url": str(url_foto).strip()
                        }
                    }
                }
                logger.info(f"📸 [ESL COMPROVANTE INVOICE/NF-E] Enviando comprovante da Nota #{nf.numero_nota} (Chave NF-e: {nf.chave_acesso})")
            elif chave_cte:
                # Fallback: Se tem chave_cte envia por Frete
                url_esl = f"https://{self.config.dominio_esl}/api/freight_delivery_receipts"
                payload = {
                    "freight_delivery_receipt": {
                        "freight": {
                            "cte_key": str(chave_cte).strip(),
                            "delivery_receipt_url": str(url_foto).strip()
                        }
                    }
                }
                logger.info(f"📸 [ESL COMPROVANTE FRETE] Enviando comprovante da Nota #{nf.numero_nota} (Chave CT-e: {chave_cte})")
            else:
                msg = f"Nota #{nf.numero_nota} sem chave_acesso nem chave_cte para envio do comprovante ao TMS."
                logger.warning(msg)
                baixa.log_erro_tms = msg
                baixa.save(update_fields=['log_erro_tms'])
                return msg

            response = requests.post(url_esl, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 429:
                import time
                logger.warning("Rate limit 429 atingido ao enviar comprovante. Aguardando 2.5s...")
                time.sleep(2.5)
                response = requests.post(url_esl, json=payload, headers=headers, timeout=30)

            response.raise_for_status()

            baixa.processado_tms = True
            baixa.integrado_tms = True
            baixa.log_erro_tms = f"Sucesso: Comprovante de entrega atualizado no TMS ESL Cloud em {timezone.now().strftime('%d/%m/%Y %H:%M')}"
            baixa.data_integracao = timezone.now()
            baixa.save(update_fields=['processado_tms', 'integrado_tms', 'log_erro_tms', 'data_integracao'])

            logger.info(f"✅ Comprovante da nota #{nf.numero_nota} atualizado no TMS com sucesso!")
            return f"Comprovante da nota #{nf.numero_nota} atualizado com sucesso."

        except Exception as e:
            payload_str = f" | Payload: {json.dumps(payload)}" if ('payload' in locals() and payload) else ""
            msg_falha = f"Erro ao cadastrar comprovante no TMS: {str(e)}{payload_str}"
            if hasattr(e, 'response') and e.response is not None:
                msg_falha = f"Erro ao cadastrar comprovante no TMS ({e.response.status_code}): {e.response.text}{payload_str}"
            
            logger.error(msg_falha)
            baixa.log_erro_tms = msg_falha[:500]
            baixa.integrado_tms = False
            baixa.save(update_fields=['log_erro_tms', 'integrado_tms'])

            try:
                from operacional.services import registrar_erro_torre
                registrar_erro_torre(
                    filial=nf.manifesto.filial if (nf and nf.manifesto) else None,
                    categoria='INTEGRACAO_COMPROVANTE',
                    severidade_padrao='CRITICO',
                    titulo=f"Falha envio comprovante NF {nf.numero_nota if nf else baixa_id}",
                    descricao=msg_falha[:300],
                    erro_raw=msg_falha,
                    manifesto_numero=nf.manifesto.numero_manifesto if (nf and nf.manifesto) else None,
                    nota_fiscal_numero=nf.numero_nota if nf else None,
                    motorista_nome=nf.manifesto.motorista.nome_completo if (nf and nf.manifesto and nf.manifesto.motorista) else "Operacional",
                )
            except Exception as tr_exc:
                logger.error(f"Erro ao registrar torre de controle: {tr_exc}")

            if task:
                raise task.retry(exc=e, countdown=60)
            raise

