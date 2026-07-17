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
from manifesto.models import Manifesto, NotaFiscal, ManifestoBuscaLog, BaixaNF
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
            
            log.status = 'ENRIQUECENDO'
            log.save()

            token_notas = self.config.token_invoices
            url_notas = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
            
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

            log.quantidade_notas = len(notas_unicas_dict)
            log.save()
            
            total_processadas = 0
            ids_processadas = []
            for id_doc, dados_base in notas_unicas_dict.items():
                try:
                    chave = dados_base['chave']
                    numero = dados_base['numero']
                    tipo_operacao = dados_base['tipo']
                    freight_id = dados_base['freight_id']

                    destinatario = "DADOS NÃO REPASSADOS PELA ESL"
                    endereco = "CONSULTE O DOCUMENTO FÍSICO"

                    if chave:
                        time.sleep(2.1)
                        detalhes = self.buscar_detalhes_esl_interno(chave, numero, token_geral)
                        if detalhes:
                            nome_det = detalhes.get('ioe_rpt_name')
                            if nome_det: 
                                destinatario = str(nome_det).upper()

                            rua = detalhes.get('ioe_rpt_mds_line_1', '')
                            num = detalhes.get('ioe_rpt_mds_number', '')
                            if rua:
                                endereco = f"{rua} {num}".strip().upper()

                        nota_no_manifesto = NotaFiscal.objects.filter(
                            manifesto=manifesto_obj, 
                            numero_nota=str(numero),
                            chave_acesso=chave
                        ).first()

                        status_final = nota_no_manifesto.status if nota_no_manifesto else 'PENDENTE'

                        nota_obj, _ = NotaFiscal.objects.update_or_create(
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
                        ids_processadas.append(nota_obj.id)
                    else:
                        nota_no_manifesto = NotaFiscal.objects.filter(
                            manifesto=manifesto_obj,
                            numero_nota=str(numero),
                            chave_acesso__isnull=True
                        ).first()
                        
                        status_final = nota_no_manifesto.status if nota_no_manifesto else 'PENDENTE'

                        nota_obj, _ = NotaFiscal.objects.update_or_create(
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
                        ids_processadas.append(nota_obj.id)

                    total_processadas += 1

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
            codigo_ocorrencia = limpar_codigo_ocorrencia(codigo_tms_val) if codigo_tms_val else 1

            tms_manifest_id = manifesto.numero_manifesto 
            
            fuso_brasilia = pytz.timezone('America/Sao_Paulo')
            data_br = baixa.data_baixa.astimezone(fuso_brasilia)
            data_ocorrencia_str = data_br.strftime('%Y-%m-%dT%H:%M:%S.000-03:00')

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

            baixa.payload_enviado = payload

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
            return f"Baixa {baixa_id} integrada com sucesso."

        except BaixaNF.DoesNotExist:
            return f"Baixa {baixa_id} não encontrada"

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
            detalhe_erro = exc.response.text if hasattr(exc, 'response') and exc.response is not None else str(exc)
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
            freight_id = nf.freight_id_tms
            manifesto = nf.manifesto
            
            codigo_tms_val = (baixa.ocorrencia.codigo_tms or baixa.ocorrencia.codigo_referencia) if baixa.ocorrencia else None
            codigo_ocorrencia = limpar_codigo_ocorrencia(codigo_tms_val) if codigo_tms_val else 1
            
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
                else:
                    logger.warning(f"Minuta {nf.numero_nota}: freight_id não encontrado na ESL.")

            if not freight_id:
                raise Exception(
                    f"Minuta {nf.numero_nota} sem freight_id. "
                    f"Não é possível enviar baixa sem freight_id (endpoint geral exige chave NF-e)."
                )

            # Envia via endpoint V1 de freight (único que funciona para minutas)
            URL_ESL_FRETE = f"https://{self.config.dominio_esl}/api/v1/freights/{freight_id}/invoice_occurrences"
            
            motorista = manifesto.motorista.nome_completo if (manifesto and manifesto.motorista) else "Motorista não identificado"
            url_foto = baixa.comprovante_foto_url or ""
            
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
            
            # Adiciona foto
            if url_foto:
                payload["invoice_occurrence"]["delivery_receipt_url"] = url_foto
            
            baixa.payload_enviado = payload
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}"
            }
            
            logger.info(f"Enviando Minuta {nf.numero_nota} via Freight V1 (ID: {freight_id})")
            logger.info(f"Payload: {json.dumps(payload)}")
            response = requests.post(URL_ESL_FRETE, json=payload, headers=headers, timeout=30)
            
            # Se falhar com 422 (Unprocessable Entity), verifica se o erro é de ocorrência inválida/em branco
            # e tenta novamente com o código padrão 1 (sucesso de entrega)
            if response.status_code == 422 and codigo_ocorrencia != 1:
                try:
                    error_data = response.json()
                    errors = error_data.get("errors", {})
                    is_occurrence_error = False
                    
                    if isinstance(errors, dict):
                        for key, val in errors.items():
                            val_str = str(val).lower()
                            if "ocorrência" in val_str or "occurrence" in val_str or "branco" in val_str or "blank" in val_str:
                                is_occurrence_error = True
                                break
                    elif isinstance(errors, str):
                        errors_lower = errors.lower()
                        if "ocorrência" in errors_lower or "occurrence" in errors_lower or "branco" in errors_lower or "blank" in errors_lower:
                            is_occurrence_error = True
                            
                    if is_occurrence_error:
                        logger.warning(
                            f"Ocorrência {codigo_ocorrencia} rejeitada pela ESL para a Minuta {nf.numero_nota}. "
                            "Tentando novamente com o código padrão 1 (sucesso)."
                        )
                        payload["invoice_occurrence"]["occurrence"]["code"] = 1
                        logger.info(f"Payload de Fallback: {json.dumps(payload)}")
                        response = requests.post(URL_ESL_FRETE, json=payload, headers=headers, timeout=30)
                except Exception as ex_fallback:
                    logger.error(f"Erro ao processar fallback de ocorrência na Minuta {nf.numero_nota}: {ex_fallback}")
            
            response.raise_for_status()

            baixa.processado_tms = True
            baixa.integrado_tms = True
            baixa.data_integracao = timezone.now()
            baixa.log_erro_tms = f"Sucesso: Baixa de Minuta integrada via Freight ID {freight_id}"
            baixa.save()
            
            return f"Baixa de Minuta {nf.numero_nota} enviada com sucesso (Freight: {freight_id})."

        except Exception as e:
            payload_str = f" | Payload: {json.dumps(payload)}" if payload else ""
            msg_falha = f"Erro na integração da Minuta: {str(e)}{payload_str}"
            if hasattr(e, 'response') and e.response is not None:
                msg_falha = f"Erro na integração da Minuta ({e.response.status_code}): {e.response.text}{payload_str}"
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
