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



def _is_chave_nfe_valida(chave):
    """Verifica se a chave de acesso é uma chave NF-e/NFC-e válida (44 dígitos numéricos, modelo 55 ou 65).
    Chaves com modelo 99 são Minutas / Documentos Não Fiscais / Outros.
    Chaves com modelo 57 são CT-e (Conhecimento de Transporte).
    Valores curtos são números de nota ou IDs internos.
    """
    if not chave:
        return False
    chave_str = str(chave).strip()
    if len(chave_str) != 44 or not chave_str.isdigit():
        return False
    
    # Posições 20 a 22 (0-indexed: [20:22]) contêm o modelo fiscal na chave SEFAZ de 44 dígitos:
    # 55 = NF-e (Nota Fiscal Eletrônica de mercadorias)
    # 65 = NFC-e (Nota Fiscal ao Consumidor Eletrônica)
    # 99 = Minuta / Declaração / Não Fiscal (deve ser tratada como Minuta/Frete na ESL)
    # 57 = CT-e (Conhecimento de Transporte Eletrônico)
    modelo = chave_str[20:22]
    return modelo in ('55', '65')


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
            dados = res.json() if res.status_code == 200 else []

            # Fallback: Se não encontrou por ID interno, tenta buscar por sequence_code (número visual)
            if not dados and str(id_tms).isdigit():
                payload_seq = {
                    "search": {
                        "manifests": {
                            "sequence_code": int(id_tms),
                            "service_date": "2024-01-01 - 2050-12-31"
                        }
                    },
                    "page": "1", "per": "5"
                }
                res_seq = requests.get(url_valida, headers=headers_geral, data=json.dumps(payload_seq), timeout=15)
                if res_seq.status_code == 200:
                    dados = res_seq.json()

            if dados and len(dados) > 0:
                info = dados[0]
                seq = info.get('mft_sequence_code') or info.get('sequence_code')
                id_interno_retornado = str(info.get('id') or id_tms).strip()
                if seq:
                    id_op = str(info.get('mft_uer_crn_id')).strip() if info.get('mft_uer_crn_id') else None
                    
                    # Mapeamento oficial dos IDs das bases/filiais no TMS ESL
                    MAPA_FILIAIS_TMS = {
                        '237988': 'RD EXPRESSO',
                        '237973': 'QUICK BRASILIA',
                        '237978': 'QUICK SAO PAULO',
                        '237974': 'QUICK GOIANIA',
                    }
                    nome_op = MAPA_FILIAIS_TMS.get(id_op)
                    if not nome_op and id_op and id_op == str(info.get('mft_crn_id')):
                        nome_op = str(info.get('mft_crn_psn_nickname') or '').strip().upper()
                    if not nome_op and id_op:
                        nome_op = f"BASE {id_op}"

                    placa = str(info.get('mft_vie_license_plate', '')).strip().upper().replace(' ', '').replace('-', '') if info.get('mft_vie_license_plate') else None

                    # Extrai contagens de operações de carga do relatório TMS
                    qtd_ent = int(float(info.get('delivery_subtotal') or 0))
                    qtd_transf = int(info.get('transfer_manifest_items_count') or 0)
                    qtd_col = int(info.get('pick_manifest_items_count') or 0)
                    qtd_desp = int(info.get('dispatch_draft_manifest_items_count') or 0)
                    qtd_ret = 0

                    logger.info(f"🔍 [RESOLVER_VISUAL] ID {id_tms} resolvido: Visual #{seq}, ID TMS: {id_interno_retornado}, Base Op: {nome_op or 'N/A'} (ID: {id_op}), Placa: {placa or 'N/A'}")
                    return {
                        'sequence_code': str(seq).strip(),
                        'id_tms': id_interno_retornado,
                        'id_filial_operacao': id_op,
                        'nome_filial_operacao': nome_op,
                        'id_filial_fiscal': str(info.get('mft_crn_id', '')).strip() or None,
                        'nome_filial_fiscal': str(info.get('mft_crn_psn_nickname', '')).strip().upper() or None,
                        'placa': placa,
                        'qtd_entrega': qtd_ent,
                        'qtd_transferencia': qtd_transf,
                        'qtd_coleta': qtd_col,
                        'qtd_despacho': qtd_desp,
                        'qtd_retirada': qtd_ret,
                        'status_tms': str(info.get('status', '')).strip().lower() or None,
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
                    log.status = 'ERRO'
                    log.mensagem_erro = f"O Manifesto #{numero_visual} já se encontra FINALIZADO no TMS (status 'closed')."
                    log.save(update_fields=['status', 'mensagem_erro'])
                    logger.info(f"🚫 Manifesto {numero_visual} já finalizado no TMS ('closed'). Log marcado como ERRO para informar o motorista.")
                    return
                else:
                    log.status = 'ERRO'
                    log.mensagem_erro = f"O Manifesto #{numero_visual} já se encontra FINALIZADO no TMS. Não é possível iniciar uma rota já encerrada."
                    log.save(update_fields=['status', 'mensagem_erro'])
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
            from manifesto.tasks import _buscar_ou_criar_filial_unificada, _resolver_filial_operacao_tms
            filial_obj = _buscar_ou_criar_filial_unificada(id_filial_tms, nome_filial_tms)

            # --- FILIAL DE OPERAÇÃO (base física de onde o caminhão sai) ---
            # Determinada pelo mft_uer_crn_id (filial do emissor do manifesto na ESL)
            filial_operacao_obj = None
            id_filial_operacao_tms = info_tms.get('mft_uer_crn_id')
            if id_filial_operacao_tms:
                filial_operacao_obj = _resolver_filial_operacao_tms(id_filial_operacao_tms)

            mft_existente = Manifesto.objects.filter(numero_manifesto=numero_visual).first()
            tem_notas_confirmadas_wh = False
            if mft_existente:
                tem_notas_confirmadas_wh = mft_existente.notas_fiscais.filter(tipo_operacao_confirmado_webhook=True).exists()

            defaults_manifesto = {
                'motorista': motorista, 
                'filial': filial_obj,
                'filial_operacao': filial_operacao_obj,
                'status': 'EM_TRANSPORTE',
                'status_tms': status_tms if status_tms in ('pending', 'in_transit') else 'in_transit',
                'manifesto_id_tms': info_tms.get('id'), 
                'veiculo': veiculo_obj,
            }
            # Se já existem notas confirmadas via Webhook, NÃO sobrescreve as contagens com números analíticos da ESL
            if not tem_notas_confirmadas_wh:
                defaults_manifesto['qtd_transferencia'] = int(info_tms.get('transfer_manifest_items_count', 0))
                defaults_manifesto['qtd_entrega'] = int(info_tms.get('dispatch_draft_manifest_items_count', 0))
                defaults_manifesto['qtd_retirada'] = int(info_tms.get('pick_manifest_items_count', 0))

            manifesto_obj, _ = Manifesto.objects.update_or_create(
                numero_manifesto=numero_visual,
                defaults=defaults_manifesto
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
                        # ✅ NOTA JÁ EXISTE: VERIFICAÇÃO COMPLETA CAMPO A CAMPO
                        # PROTEÇÃO: Notas BAIXADA/OCORRENCIA NÃO são alteradas (já finalizadas)
                        update_fields = []
                        cep_mudou = False

                        if nota_no_manifesto.status not in ['BAIXADA', 'OCORRENCIA']:
                            # 📋 Nota PENDENTE — verificação COMPLETA
                            # 🛡️ TRAVA: tipo_operacao confirmado via Webhook NÃO pode ser alterado pela busca manual
                            if nota_no_manifesto.tipo_operacao != tipo_operacao:
                                if nota_no_manifesto.tipo_operacao_confirmado_webhook:
                                    logger.info(f"🛡️ [BUSCA MANUAL] NF #{numero}: tipo_operacao '{nota_no_manifesto.tipo_operacao}' PROTEGIDO (confirmado via Webhook). Busca manual tentou '{tipo_operacao}' — IGNORADO.")
                                else:
                                    logger.info(f"🔄 [BUSCA MANUAL CORREÇÃO] NF #{numero}: tipo_operacao '{nota_no_manifesto.tipo_operacao}' → '{tipo_operacao}'")
                                    nota_no_manifesto.tipo_operacao = tipo_operacao
                                    update_fields.append('tipo_operacao')
                            if freight_id and nota_no_manifesto.freight_id_tms != str(freight_id):
                                nota_no_manifesto.freight_id_tms = str(freight_id)
                                update_fields.append('freight_id_tms')
                            if chave and nota_no_manifesto.chave_acesso != chave:
                                nota_no_manifesto.chave_acesso = chave
                                update_fields.append('chave_acesso')

                            # Busca endereço/destinatário atualizado na ESL se dados parecem incompletos
                            dados_incompletos = (
                                not nota_no_manifesto.endereco_entrega or
                                'CONSULTE' in (nota_no_manifesto.endereco_entrega or '') or
                                'DADOS NÃO REPASSADOS' in (nota_no_manifesto.endereco_entrega or '') or
                                'NÃO INFORMADO' in (nota_no_manifesto.destinatario or '') or
                                'DADOS NÃO REPASSADOS' in (nota_no_manifesto.destinatario or '') or
                                not nota_no_manifesto.cep
                            )
                            if dados_incompletos and chave:
                                try:
                                    time.sleep(2.0)
                                    detalhes = self.buscar_detalhes_esl_interno(chave, numero, token_geral)
                                    if detalhes:
                                        nome_det = detalhes.get('ioe_rpt_name')
                                        if nome_det:
                                            nome_limpo = str(nome_det).upper().strip()
                                            if nome_limpo and nota_no_manifesto.destinatario != nome_limpo:
                                                nota_no_manifesto.destinatario = nome_limpo
                                                update_fields.append('destinatario')

                                        rua = detalhes.get('ioe_rpt_mds_line_1', '')
                                        num_end = detalhes.get('ioe_rpt_mds_number', '')
                                        if rua:
                                            endereco_novo = f"{rua} {num_end}".strip().upper()
                                            if nota_no_manifesto.endereco_entrega != endereco_novo:
                                                nota_no_manifesto.endereco_entrega = endereco_novo
                                                update_fields.append('endereco_entrega')
                                                cep_mudou = True

                                        cep_val = (
                                            detalhes.get('ioe_rpt_mds_postal_code') or
                                            detalhes.get('ioe_rpt_zip_code') or
                                            detalhes.get('ioe_rpt_mds_zip_code') or
                                            detalhes.get('zip_code') or
                                            detalhes.get('cep')
                                        )
                                        if cep_val:
                                            cep_limpo = str(cep_val).strip()[:10]
                                            if cep_limpo and nota_no_manifesto.cep != cep_limpo:
                                                nota_no_manifesto.cep = cep_limpo
                                                update_fields.append('cep')
                                                cep_mudou = True
                                except Exception as det_err:
                                    logger.warning(f"⚠️ Erro ao buscar detalhes ESL para NF #{numero}: {det_err}")
                        else:
                            # 🔒 Nota BAIXADA/OCORRENCIA — apenas atualiza freight_id se faltava
                            if freight_id and nota_no_manifesto.freight_id_tms != str(freight_id):
                                nota_no_manifesto.freight_id_tms = str(freight_id)
                                update_fields.append('freight_id_tms')

                        if update_fields:
                            logger.info(f"📝 [BUSCA MANUAL SYNC] NF #{numero} - Campos atualizados: {update_fields}")
                            nota_no_manifesto.save(update_fields=update_fields)

                        # 🌍 Re-geocodificação: se CEP ou endereço mudou, atualiza lat/lng
                        if cep_mudou and nota_no_manifesto.cep:
                            try:
                                nota_no_manifesto.latitude = None
                                nota_no_manifesto.longitude = None
                                nota_no_manifesto.save(update_fields=['latitude', 'longitude'])
                                from manifesto.tasks import enriquecer_geolocalizacao_nota_task
                                enriquecer_geolocalizacao_nota_task.delay(nota_no_manifesto.id)
                                logger.info(f"🌍 [BUSCA MANUAL GEO] Re-geocodificação disparada para NF #{numero} (CEP/endereço alterado)")
                            except Exception as geo_err:
                                logger.warning(f"⚠️ Erro ao re-geocodificar NF #{numero}: {geo_err}")

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

            # === VERIFICAÇÃO DE PENDÊNCIAS E AUTO-REABERTURA ===
            notas_pendentes_count = NotaFiscal.objects.filter(manifesto=manifesto_obj, status='PENDENTE').count()
            if notas_pendentes_count > 0 and status_tms != 'closed':
                if manifesto_obj.finalizado or manifesto_obj.status == 'FINALIZADO':
                    from datetime import timedelta
                    data_ref_fim = manifesto_obj.data_finalizacao or manifesto_obj.data_criacao
                    recente_24h = bool(data_ref_fim and (timezone.now() - data_ref_fim <= timedelta(hours=24)))
                    outro_ativo = False
                    if motorista:
                        outro_ativo = Manifesto.objects.filter(
                            motorista=motorista,
                            status='EM_TRANSPORTE',
                            finalizado=False
                        ).exclude(id=manifesto_obj.id).exists()

                    if recente_24h and not outro_ativo:
                        manifesto_obj.status = 'EM_TRANSPORTE'
                        manifesto_obj.finalizado = False
                        manifesto_obj.data_finalizacao = None
                        manifesto_obj.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
                        logger.info(f"🔄 [AUTO-REABERTURA BUSCA TMS] Manifesto #{numero_visual} REABERTO (<24h e sem outro ativo)! {notas_pendentes_count} nota(s) pendente(s).")

                        try:
                            if motorista and motorista.fcm_token:
                                from common.tasks_notificacoes import notificar_atribuicao_manifesto
                                notificar_atribuicao_manifesto(motorista, numero_visual, total_processadas + total_coletas)
                        except Exception as push_err:
                            logger.error(f"⚠️ Erro ao disparar Push FCM de reabertura busca TMS #{numero_visual}: {push_err}")
                    else:
                        manifesto_obj.status = 'FINALIZADO'
                        manifesto_obj.finalizado = True
                        manifesto_obj.save(update_fields=['status', 'finalizado'])
            elif notas_pendentes_count == 0 and (status_tms == 'closed' or manifesto_obj.finalizado):
                manifesto_obj.status = 'FINALIZADO'
                manifesto_obj.finalizado = True
                manifesto_obj.save(update_fields=['status', 'finalizado'])

            # 📦 Recalcula contagens oficiais de carga diretamente das notas salvas no banco
            tot_ent = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='ENTREGA').count()
            tot_tra = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='TRANSFERENCIA').count()
            tot_col = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='COLETA').count()
            tot_des = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='DESPACHO').count()
            tot_ret = NotaFiscal.objects.filter(manifesto=manifesto_obj, tipo_operacao='RETIRADA').count()

            manifesto_obj.qtd_entrega = tot_ent
            manifesto_obj.qtd_transferencia = tot_tra
            manifesto_obj.qtd_coleta = tot_col
            manifesto_obj.qtd_despacho = tot_des
            manifesto_obj.qtd_retirada = tot_ret
            manifesto_obj.save(update_fields=['qtd_entrega', 'qtd_transferencia', 'qtd_coleta', 'qtd_despacho', 'qtd_retirada'])

            if manifesto_obj.finalizado or manifesto_obj.status == 'FINALIZADO':
                log.status = 'ERRO'
                log.mensagem_erro = f"O Manifesto #{numero_visual} já se encontra FINALIZADO (todas as notas concluídas)."
                log.save(update_fields=['status', 'mensagem_erro'])
                logger.info(f"🚫 Manifesto {numero_visual} finalizado. Log de busca marcado como ERRO para alertar no app.")
            else:
                log.status = 'PROCESSADO'
                log.mensagem_erro = None
                log.save(update_fields=['status', 'mensagem_erro'])
                logger.info(f"✅ Manifesto {numero_visual} processado e ativo com sucesso.")

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

        # Trava de concorrência por baixa (Ajuste 1: Prevenção contra workers simultâneos ou retries de Celery)
        from django.core.cache import cache
        lock_key = f"lock_celery_esl_baixa_{baixa_id}"
        lock_adquirido = False
        try:
            lock_adquirido = cache.add(lock_key, "running", timeout=180)
            if not lock_adquirido:
                logger.warning(f"⚠️ Task Celery ignorada para Baixa #{baixa_id}: envio já em andamento por outro worker.")
                return f"Baixa {baixa_id} já em processamento concorrente."
        except Exception:
            pass

        try:
            baixa = BaixaNF.objects.select_related(
                'nota_fiscal',
                'ocorrencia',
                'nota_fiscal__manifesto',
                'nota_fiscal__manifesto__motorista'
            ).get(id=baixa_id)

            nf = baixa.nota_fiscal
            
            # --- PROTEÇÃO DE IDEMPOTÊNCIA: Se já foi integrada com sucesso, não envia de novo ---
            ja_foi_bypass = bool(
                (baixa.payload_enviado and isinstance(baixa.payload_enviado, dict) and baixa.payload_enviado.get('bypass')) or
                ('Bypass' in str(baixa.log_erro_tms or ''))
            )
            if baixa.integrado_tms and not ja_foi_bypass:
                logger.info(f"⏭️ Baixa #{baixa_id} (NF {nf.numero_nota}) já integrada ao TMS com sucesso. Pulando reenvio.")
                return f"Baixa {baixa_id} já integrada previamente."
            
            # --- MINUTAS SEM CHAVE VÁLIDA: Usa endpoint de Frete (/api/v1/freights/{id}/invoice_occurrences) ---
            # REGRA: O endpoint geral (/api/invoice_occurrences) exige uma chave NF-e válida (44 dígitos).
            # Minutas podem ter um valor curto no campo chave_acesso (ex: número da nota),
            # que NÃO é aceito pelo endpoint geral e causa erro 404.
            # Apenas chaves com 44 dígitos numéricos são consideradas válidas para o endpoint de NF-e.
            tem_chave_valida = _is_chave_nfe_valida(nf.chave_acesso)
            tipo_op = str(nf.tipo_operacao or '').strip().upper()
            
            if not tem_chave_valida:
                # Coletas usam endpoint próprio (/api/v1/picks/) e não precisam de freight_id
                if nf.numero_coleta or nf.tipo_operacao == 'COLETA':
                    logger.info(f"Redirecionando baixa {baixa_id} (coleta sem chave válida) para enviar_coleta")
                    return self.enviar_coleta(baixa_id, task=task)
                logger.info(
                    f"🚀 NF {nf.numero_nota} sem chave NF-e válida (chave_acesso='{nf.chave_acesso}'). "
                    f"Redirecionando para enviar_baixa_minuta (Frete ESL V1)"
                )
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
            # TRANSMISSÃO NF-e (COM CHAVE DE 44 DÍGITOS)
            # Se tem chave NF-e, envia DIRETAMENTE para o endpoint de notas
            # (/api/invoice_occurrences) vinculado à chave de acesso nacional (key).
            # Nada de frete ou bypass local!
            # =====================================================

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
                    "invoice": {
                        "key": nf.chave_acesso,
                        "delivery_receipt_url": url_foto or ""
                    }
                }
            }

            if manifesto and manifesto.manifesto_id_tms and str(manifesto.manifesto_id_tms).isdigit():
                payload["invoice_occurrence"]["manifest"] = {
                    "id": int(manifesto.manifesto_id_tms)
                }

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

            # --- AUTO-RECUPERAÇÃO DE ERRO 404 NA TRANSMISSÃO DE NF-e ---
            if response.status_code == 404:
                logger.warning(f"⚠️ [ESL 404] NF #{nf.numero_nota} retornou 404 na ESL. Iniciando auto-recuperação...")
                
                # Tentativa 1: Reenviar sem o bloco 'manifest'
                # Se manifesto_id_tms for o sequence_code visual e não o ID interno, a ESL rejeita com 404 Not Found
                if "manifest" in payload.get("invoice_occurrence", {}):
                    logger.info(f"🔄 Tentativa 1: Reenviando NF #{nf.numero_nota} sem o campo manifest...")
                    import copy
                    payload_sem_m = copy.deepcopy(payload)
                    payload_sem_m["invoice_occurrence"].pop("manifest", None)
                    res_sem_m = requests.post(URL_ESL, json=payload_sem_m, headers=headers, timeout=30)
                    if res_sem_m.status_code in [200, 201]:
                        response = res_sem_m
                        logger.info(f"✅ NF #{nf.numero_nota} integrada com sucesso sem vincular manifest!")
                
                # Tentativa 2: Reenviar por número da nota (caso a ESL não encontre pela chave enviada)
                if response.status_code == 404 and nf.numero_nota:
                    logger.info(f"🔄 Tentativa 2: Reenviando por número da nota ({nf.numero_nota})...")
                    import copy
                    payload_num = copy.deepcopy(payload)
                    payload_num["invoice_occurrence"]["invoice"] = {
                        "number": str(nf.numero_nota),
                        "delivery_receipt_url": url_foto or ""
                    }
                    payload_num["invoice_occurrence"].pop("manifest", None)
                    res_num = requests.post(URL_ESL, json=payload_num, headers=headers, timeout=30)
                    if res_num.status_code in [200, 201]:
                        response = res_num
                        logger.info(f"✅ NF #{nf.numero_nota} integrada com sucesso por número da nota!")

                # Tentativa 3: Se ainda for 404, redireciona para a rota de Minutas/Fretes
                # (O documento pode estar cadastrado na ESL como Frete/Minuta e não como Invoice tradicional)
                if response.status_code == 404:
                    logger.warning(f"🔄 Tentativa 3: NF #{nf.numero_nota} não encontrada no endpoint geral. Redirecionando para enviar_baixa_minuta...")
                    return self.enviar_baixa_minuta(baixa_id, task=task)
            
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
                    "ja finalizad" in detalhe_lower or
                    "não permite data e hora menor ou igual" in detalhe_lower or
                    "nao permite data e hora menor ou igual" in detalhe_lower or
                    "menor ou igual" in detalhe_lower
                )
            )
            if eh_ja_existe:
                logger.info(f"✅ NF {nf.numero_nota}: Ocorrência já registrada previamente no TMS (ESL Cloud). Marcando como sucesso (Idempotência).")
                baixa.log_erro_tms = "Sucesso: Ocorrência já registrada previamente no TMS (ESL Cloud)."
                baixa.processado_tms = True
                baixa.integrado_tms = True
                baixa.data_integracao = timezone.now()
                if isinstance(baixa.payload_enviado, dict) and 'bypass' in baixa.payload_enviado:
                    baixa.payload_enviado.pop('bypass', None)
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

            is_4xx_fatal = bool(status and 400 <= status < 500)
            is_ultima_tentativa = (not task) or (task.request.retries >= task.max_retries) or is_4xx_fatal

            if is_ultima_tentativa:
                try:
                    from operacional.services import registrar_erro_torre
                    registrar_erro_torre(
                        filial=(manifesto.filial_operacao or manifesto.filial),
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

            if is_4xx_fatal:
                notificar_falha_tms(baixa_id, msg_erro, "enviar_baixa_esl_task")
                return f"Erro de validação ESL: {msg_erro}"

            if task and task.request.retries < task.max_retries:
                logger.info(f"⏳ [RETRY] Baixa NF {nf.numero_nota}: Tentativa {task.request.retries + 1}/{task.max_retries + 1} falhou. Retentando sem alertar o painel...")
                raise task.retry(exc=exc, countdown=60)

            notificar_falha_tms(baixa_id, msg_erro, "enviar_baixa_esl_task")
            return f"Falha definitiva ESL: {msg_erro}"

        except Exception as e:
            msg = f"Erro inesperado: {str(e)}"
            baixa.log_erro_tms = msg[:500]
            baixa.save()
            
            is_ultima_tentativa = (not task) or (task.request.retries >= task.max_retries)
            if is_ultima_tentativa:
                try:
                    from operacional.services import registrar_erro_torre
                    registrar_erro_torre(
                        filial=(manifesto.filial_operacao or manifesto.filial),
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
                notificar_falha_tms(baixa_id, msg, "enviar_baixa_esl_task")
            else:
                logger.info(f"⏳ [RETRY] Baixa NF {nf.numero_nota}: Tentativa {task.request.retries + 1}/{task.max_retries + 1} falhou. Retentando sem alertar o painel...")

            if task:
                raise task.retry(exc=e, countdown=60)
            raise
        finally:
            if lock_adquirido:
                try:
                    cache.delete(lock_key)
                except Exception:
                    pass

    def _buscar_freight_id_minuta(self, nf, ignorar_ids=None):
        """
        Busca o freight_id correto de uma Minuta na ESL Cloud usando múltiplos fallbacks:
        1. Busca direta em /api/invoice_occurrences por invoice_number ou invoice_key
        2. Busca em /api/invoice_occurrences pelo manifesto (com paginação 'start')
        3. Relatório de Fretes (Report 7693) buscando pelo número da nota/minuta
        """
        ignorar = set(str(x).strip() for x in (ignorar_ids or []) if x)
        TOKEN = self.config.token_invoices
        manifesto = nf.manifesto
        numero_local = str(nf.numero_nota or '').strip()
        numero_local_limpo = numero_local.lstrip('0')
        chave_local = str(nf.chave_acesso or '').strip()

        url_oc = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
        headers = {"Authorization": f"Bearer {TOKEN}"}

        def _item_bate(item):
            invoice = item.get("invoice") or {}
            freight = item.get("freight") or {}
            
            num_inv = str(invoice.get("number") or "").strip()
            key_inv = str(invoice.get("key") or "").strip()
            seq_freight = str(freight.get("sequence_code") or "").strip()
            cte_freight = str(freight.get("cte_number") or "").strip()

            return (
                (num_inv and (num_inv == numero_local or num_inv.lstrip('0') == numero_local_limpo)) or
                (key_inv and (key_inv == numero_local or key_inv == chave_local or key_inv.lstrip('0') == numero_local_limpo)) or
                (seq_freight and (seq_freight == numero_local or seq_freight.lstrip('0') == numero_local_limpo)) or
                (cte_freight and (cte_freight == numero_local or cte_freight.lstrip('0') == numero_local_limpo))
            )

        # 1. Busca direta por invoice_number ou invoice_key na ESL (mais rápido e assertivo)
        buscas_diretas = []
        if numero_local:
            buscas_diretas.append({"invoice_number": numero_local, "per": 50})
            if numero_local_limpo and numero_local_limpo != numero_local:
                buscas_diretas.append({"invoice_number": numero_local_limpo, "per": 50})
        if chave_local and chave_local != numero_local:
            buscas_diretas.append({"invoice_key": chave_local, "per": 50})

        for p_dir in buscas_diretas:
            try:
                resp = requests.get(url_oc, headers=headers, params=p_dir, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("data", []):
                        if _item_bate(item):
                            freight = item.get("freight") or {}
                            fid = freight.get("id")
                            if fid and str(fid) not in ignorar:
                                logger.info(f"🎯 [ESL MINUTA] Freight ID interno {fid} encontrado via busca direta ({p_dir}) para Minuta #{nf.numero_nota}")
                                return str(fid)
            except Exception as e_dir:
                logger.warning(f"Aviso na busca direta de minuta ({p_dir}): {e_dir}")

        # 2. Busca no endpoint de invoice_occurrences do manifesto com paginação correta ('start')
        ids_manifesto_para_tentar = []
        if manifesto:
            if manifesto.numero_manifesto:
                ids_manifesto_para_tentar.append(str(manifesto.numero_manifesto).strip())
            if manifesto.manifesto_id_tms and str(manifesto.manifesto_id_tms).strip() not in ids_manifesto_para_tentar:
                ids_manifesto_para_tentar.append(str(manifesto.manifesto_id_tms).strip())

        for m_id in ids_manifesto_para_tentar:
            try:
                start_id = None
                for _ in range(5):  # até 5 páginas
                    params = {"manifest_id": str(m_id), "per": 50}
                    if start_id:
                        params["start"] = start_id

                    resp = requests.get(url_oc, headers=headers, params=params, timeout=25)
                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    itens = data.get("data", [])
                    if not itens:
                        break

                    for item in itens:
                        if _item_bate(item):
                            freight = item.get("freight") or {}
                            fid = freight.get("id")
                            if fid and str(fid) not in ignorar:
                                logger.info(f"🎯 [ESL MINUTA] Freight ID interno {fid} encontrado via manifesto {m_id} para Minuta #{nf.numero_nota}")
                                return str(fid)

                    paging = data.get("paging") or {}
                    start_id = paging.get("next_id")
                    if not start_id or start_id >= paging.get("last_id", 0):
                        break
            except Exception as e_oc:
                logger.warning(f"Erro ao buscar invoice_occurrences para manifesto {m_id}: {e_oc}")

        # 3. Fallback: Busca no Relatório de Fretes (Report 7693)
        try:
            token_geral = self.config.token_analytics or TOKEN
            dados_frete = self.buscar_dados_frete_report_7693(
                chave=chave_local or None, 
                numero=numero_local, 
                token=token_geral
            )
            if dados_frete:
                # Procura explicitamente pelo ID interno da ESL (fit_fhe_id ou id)
                fid = dados_frete.get("fit_fhe_id") or dados_frete.get("id") or dados_frete.get("freight_id")
                if fid and str(fid) not in ignorar:
                    logger.info(f"🎯 [ESL MINUTA] Freight ID interno encontrado via Report 7693: {fid} para Minuta #{nf.numero_nota}")
                    return str(fid)
                
                # Se o relatório só tem cte_number, tenta buscar o ID interno via cte_number em invoice_occurrences
                cte_num = dados_frete.get("fit_fhe_cte_number")
                if cte_num:
                    try:
                        r_cte = requests.get(url_oc, headers=headers, params={"cte_number": str(cte_num)}, timeout=20)
                        if r_cte.status_code == 200:
                            for it in r_cte.json().get("data", []):
                                f_id = (it.get("freight") or {}).get("id")
                                if f_id and str(f_id) not in ignorar:
                                    logger.info(f"🎯 [ESL MINUTA] Freight ID interno {f_id} obtido via CT-e {cte_num}")
                                    return str(f_id)
                    except Exception:
                        pass
        except Exception as e_rep:
            logger.warning(f"Erro ao buscar minuta no Report 7693: {e_rep}")

        return None

    def _buscar_freight_id_por_numero(self, numero_nota, manifesto_id_tms, token):
        """Wrapper de retrocompatibilidade"""
        url = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"manifest_id": str(manifesto_id_tms), "per": 50}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                numero_local = str(numero_nota).strip()
                numero_local_limpo = numero_local.lstrip('0')
                for item in data.get("data", []):
                    invoice = item.get("invoice", {})
                    numero_esl = str(invoice.get("number", "")).strip()
                    if numero_esl == numero_local or numero_esl.lstrip('0') == numero_local_limpo:
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
        baixa = None
        nf = None
        is_ultima_tentativa = (not task) or (task.request.retries >= task.max_retries)

        # Trava de concorrência por baixa de minuta
        from django.core.cache import cache
        lock_key = f"lock_celery_esl_baixa_minuta_{baixa_id}"
        lock_adquirido = False
        try:
            lock_adquirido = cache.add(lock_key, "running", timeout=180)
            if not lock_adquirido:
                logger.warning(f"⚠️ Task Celery ignorada para Baixa Minuta #{baixa_id}: envio já em andamento por outro worker.")
                return f"Baixa de Minuta {baixa_id} já em processamento concorrente."
        except Exception:
            pass

        try:
            baixa = BaixaNF.objects.select_related(
                'nota_fiscal',
                'ocorrencia',
                'nota_fiscal__manifesto',
                'nota_fiscal__manifesto__motorista',
                'nota_fiscal__manifesto__filial',
                'nota_fiscal__frete'
            ).get(id=baixa_id)
            nf = baixa.nota_fiscal
            manifesto = nf.manifesto
            
            # --- PROTEÇÃO DE IDEMPOTÊNCIA: Se já foi integrada com sucesso, não envia de novo ---
            if baixa.integrado_tms:
                logger.info(f"⏭️ Baixa de Minuta #{baixa_id} (NF {nf.numero_nota}) já integrada ao TMS. Pulando reenvio.")
                return f"Baixa de Minuta {baixa_id} já integrada previamente."

            codigo_tms_val = (baixa.ocorrencia.codigo_tms or baixa.ocorrencia.codigo_referencia) if baixa.ocorrencia else None
            tipo_op_nf = str(nf.tipo_operacao or '').strip().upper()
            codigo_ocorrencia, trace_ocorrencia = obter_codigo_ocorrencia_seguro(codigo_tms_val, tipo_operacao=nf.tipo_operacao, nota_fiscal=nf)
            
            logger.info(f"Minuta {nf.numero_nota}: tipo_operacao='{tipo_op_nf}', codigo_tms_val='{codigo_tms_val}', codigo_final={codigo_ocorrencia}")
            
            fuso_br = pytz.timezone('America/Sao_Paulo')
            data_ocorrencia_str = baixa.data_baixa.astimezone(fuso_br).strftime('%Y-%m-%dT%H:%M:%S.000-03:00')
            motorista = manifesto.motorista.nome_completo if (manifesto and manifesto.motorista) else "Motorista não identificado"

            # 📦 MONTA O PAYLOAD BASE (comprovante incluído se existir)
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
            if baixa.comprovante_foto_url:
                payload["invoice_occurrence"]["delivery_receipt_url"] = baixa.comprovante_foto_url

            baixa.payload_enviado = {
                **payload,
                "_debug_trace": {
                    "codigo_tms_val_original": codigo_tms_val,
                    "codigo_final_enviado": codigo_ocorrencia,
                    "nf_tipo_operacao": nf.tipo_operacao,
                    "ocorrencia_db_id": getattr(baixa.ocorrencia, 'id', None),
                    "ocorrencia_db_tms": getattr(baixa.ocorrencia, 'codigo_tms', None),
                    "ocorrencia_db_ref": getattr(baixa.ocorrencia, 'codigo_referencia', None),
                    "trace": trace_ocorrencia,
                    "freight_id_tms_salvo": nf.freight_id_tms,
                }
            }
            baixa.save(update_fields=['payload_enviado'])

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN}"
            }

            response = None
            sucesso = False
            integrado_via_frete = False
            msg_sucesso = ""
            url_tentada = ""

            # --- ESTRATÉGIA 1: TENTATIVA VIA ENDPOINT DE FRETE V1 (/api/v1/freights/{id}/invoice_occurrences) ---
            freight_id = nf.freight_id_tms or (nf.frete.freight_id_tms if (hasattr(nf, 'frete') and nf.frete) else None)
            # Identifica ID ausente ou suspeito (menor que 100, ou igual ao número da própria nota/chave)
            id_suspeito = (
                not freight_id or 
                (str(freight_id).isdigit() and int(freight_id) < 100) or
                (str(freight_id).strip() == str(nf.numero_nota).strip()) or
                (nf.chave_acesso and str(freight_id).strip() == str(nf.chave_acesso).strip())
            )
            if id_suspeito:
                logger.info(f"Minuta {nf.numero_nota}: freight_id '{freight_id}' ausente/suspeito. Buscando ID interno real na ESL...")
                novo_fid = self._buscar_freight_id_minuta(nf, ignorar_ids=[freight_id] if freight_id else [])
                if novo_fid:
                    freight_id = novo_fid
                    nf.freight_id_tms = novo_fid
                    nf.save(update_fields=['freight_id_tms'])
                    logger.info(f"Minuta {nf.numero_nota}: freight_id real encontrado = {freight_id}")

            if freight_id:
                URL_ESL_FRETE = f"https://{self.config.dominio_esl}/api/v1/freights/{freight_id}/invoice_occurrences"
                url_tentada = URL_ESL_FRETE
                logger.info(f"🚀 [ESL TRANSMISSÃO MINUTA V1] Minuta NF: {nf.numero_nota} | Freight ID: {freight_id} -> {URL_ESL_FRETE}")
                
                # Payload limpo para rota de ocorrência por Frete (sem delivery_receipt_url, não aceito por este endpoint)
                payload_frete = {
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

                try:
                    res_frete = requests.post(URL_ESL_FRETE, json=payload_frete, headers=headers, timeout=30)
                    if res_frete.status_code in [200, 201]:
                        response = res_frete
                        sucesso = True
                        integrado_via_frete = True
                        msg_sucesso = f"Sucesso: Baixa de Minuta integrada via Freight ID {freight_id}"
                    elif res_frete.status_code == 404:
                        logger.warning(f"⚠️ Freight ID {freight_id} retornou 404 na ESL para Minuta {nf.numero_nota}. Buscando ID alternativo...")
                        novo_fid = self._buscar_freight_id_minuta(nf, ignorar_ids=[freight_id])
                        if novo_fid and novo_fid != freight_id:
                            freight_id = novo_fid
                            nf.freight_id_tms = novo_fid
                            nf.save(update_fields=['freight_id_tms'])
                            URL_ESL_FRETE_NOVO = f"https://{self.config.dominio_esl}/api/v1/freights/{freight_id}/invoice_occurrences"
                            url_tentada = URL_ESL_FRETE_NOVO
                            res_frete_novo = requests.post(URL_ESL_FRETE_NOVO, json=payload_frete, headers=headers, timeout=30)
                            if res_frete_novo.status_code in [200, 201]:
                                response = res_frete_novo
                                sucesso = True
                                integrado_via_frete = True
                                msg_sucesso = f"Sucesso: Baixa de Minuta integrada via Freight ID {freight_id}"
                            else:
                                response = res_frete_novo
                        else:
                            response = res_frete
                    else:
                        response = res_frete
                except Exception as e_post_frete:
                    logger.warning(f"Exceção no envio via Freight ID {freight_id}: {e_post_frete}")

            # --- ESTRATÉGIA 2: FALLBACK PARA ENDPOINT GERAL (/api/invoice_occurrences) ---
            # Se a tentativa de frete não deu sucesso (404 ou sem freight_id), tenta o endpoint geral de notas
            if not sucesso:
                URL_ESL_NOTAS = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
                logger.info(f"🔄 [FALLBACK MINUTA] Tentando endpoint geral {URL_ESL_NOTAS} para Minuta #{nf.numero_nota}...")
                
                # Tentativa 2.1: Enviar com a chave cadastrada (mesmo curta, como '2373')
                if nf.chave_acesso:
                    payload_chave = {
                        "invoice_occurrence": {
                            **payload["invoice_occurrence"],
                            "invoice": {
                                "key": str(nf.chave_acesso),
                                "delivery_receipt_url": baixa.comprovante_foto_url or ""
                            }
                        }
                    }
                    if manifesto and manifesto.manifesto_id_tms and str(manifesto.manifesto_id_tms).isdigit():
                        payload_chave["invoice_occurrence"]["manifest"] = {"id": int(manifesto.manifesto_id_tms)}

                    url_tentada = URL_ESL_NOTAS
                    try:
                        res_chave = requests.post(URL_ESL_NOTAS, json=payload_chave, headers=headers, timeout=30)
                        if res_chave.status_code in [200, 201]:
                            response = res_chave
                            sucesso = True
                            msg_sucesso = f"Sucesso: Baixa de Minuta integrada via /api/invoice_occurrences (chave: {nf.chave_acesso})"
                        elif res_chave.status_code == 422:
                            response = res_chave
                    except Exception as e_chave:
                        logger.warning(f"Aviso no envio por chave em invoice_occurrences: {e_chave}")

                # Tentativa 2.2: Enviar com o número do documento
                if not sucesso:
                    payload_num = {
                        "invoice_occurrence": {
                            **payload["invoice_occurrence"],
                            "invoice": {
                                "number": str(nf.numero_nota),
                                "delivery_receipt_url": baixa.comprovante_foto_url or ""
                            }
                        }
                    }
                    if manifesto and manifesto.manifesto_id_tms and str(manifesto.manifesto_id_tms).isdigit():
                        payload_num["invoice_occurrence"]["manifest"] = {"id": int(manifesto.manifesto_id_tms)}

                    url_tentada = URL_ESL_NOTAS
                    try:
                        res_num = requests.post(URL_ESL_NOTAS, json=payload_num, headers=headers, timeout=30)
                        if res_num.status_code in [200, 201]:
                            response = res_num
                            sucesso = True
                            msg_sucesso = f"Sucesso: Baixa de Minuta integrada via /api/invoice_occurrences (número: {nf.numero_nota})"
                        elif res_num.status_code == 422 or not response:
                            response = res_num
                    except Exception as e_num:
                        logger.warning(f"Aviso no envio por número em invoice_occurrences: {e_num}")

            if not response:
                raise Exception(
                    f"Minuta #{nf.numero_nota} sem freight_id válido e nenhuma rota de integração foi concluída (Manifesto #{manifesto.numero_manifesto if manifesto else 'N/A'})."
                )

            response.raise_for_status()

            baixa.processado_tms = True
            baixa.integrado_tms = True
            baixa.data_integracao = timezone.now()
            baixa.log_erro_tms = msg_sucesso or f"Sucesso: Baixa de Minuta integrada (Freight: {freight_id})"
            baixa.save()

            # 📸 SE A BAIXA FOI FEITA VIA FRETE E TEM FOTO, ENVIA O ANEXO PARA POST /api/freight_attachments
            if integrado_via_frete and baixa.comprovante_foto_url:
                ok_anexo, msg_anexo = self.enviar_anexo_frete(baixa=baixa, nf=nf, freight_id=freight_id)
                if ok_anexo:
                    baixa.log_erro_tms = f"{baixa.log_erro_tms} | {msg_anexo}"
                    baixa.save(update_fields=['log_erro_tms'])
            
            try:
                from operacional.services import resolver_erros_automaticamente
                if manifesto:
                    resolver_erros_automaticamente(manifesto.numero_manifesto, nf.numero_nota, manifesto.filial)
            except Exception as auto_e:
                logger.error(f"Erro auto-resolucao minuta: {auto_e}")
            
            return f"Baixa de Minuta {nf.numero_nota} enviada com sucesso ({msg_sucesso})."

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
                    "nao permite alteracao" in detalhe_lower or
                    "não permite data e hora menor ou igual" in detalhe_lower or
                    "nao permite data e hora menor ou igual" in detalhe_lower or
                    "menor ou igual" in detalhe_lower
                )
            )
            if eh_ja_existe:
                logger.info(f"✅ Minuta {nf.numero_nota if nf else baixa_id}: Ocorrência já registrada previamente no TMS (ESL). Marcando como sucesso (Idempotência).")
                if baixa:
                    baixa.processado_tms = True
                    baixa.integrado_tms = True
                    baixa.data_integracao = timezone.now()
                    baixa.log_erro_tms = "Sucesso: Baixa de Minuta já registrada previamente no TMS (ESL Cloud)."
                    baixa.save()

                    # 📸 Mesmo se a ocorrência já existia, se tiver foto de comprovante, envia o anexo de frete
                    if baixa.comprovante_foto_url and (integrado_via_frete or freight_id):
                        ok_anexo, msg_anexo = self.enviar_anexo_frete(baixa=baixa, nf=nf, freight_id=freight_id)
                        if ok_anexo:
                            baixa.log_erro_tms = f"{baixa.log_erro_tms} | {msg_anexo}"
                            baixa.save(update_fields=['log_erro_tms'])
                    
                    if nf and nf.manifesto:
                        try:
                            from operacional.services import resolver_erros_automaticamente
                            resolver_erros_automaticamente(nf.manifesto.numero_manifesto, nf.numero_nota, nf.manifesto.filial)
                        except Exception as auto_e:
                            logger.error(f"Erro auto-resolucao minuta ja_existe: {auto_e}")
                
                return f"Baixa de Minuta {nf.numero_nota if nf else baixa_id} integrada (Já existia no TMS)."

            info_url = f" [URL: {url_tentada}]" if url_tentada else ""
            msg_falha = f"Erro na integração da Minuta{info_url}: {str(e)}{payload_str}"
            if status_code:
                msg_falha = f"Erro na integração da Minuta ({status_code}){info_url}: {response_text}{payload_str}"
            
            if baixa:
                baixa.log_erro_tms = msg_falha[:500]
                baixa.integrado_tms = False
                baixa.save()
            
            # 🚨 ALERTA NA TORRE E NOTIFICAÇÃO: SOMENTE NA ÚLTIMA TENTATIVA!
            if is_ultima_tentativa:
                logger.info(f"🚨 [ÚLTIMA TENTATIVA ESGOTADA] Disparando alerta na Torre e notificação para Baixa Minuta #{baixa_id}")
                if nf and nf.manifesto:
                    try:
                        from operacional.services import registrar_erro_torre
                        registrar_erro_torre(
                            filial=(nf.manifesto.filial_operacao or nf.manifesto.filial),
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
            else:
                logger.info(f"⏳ [RETRY] Minuta NF {nf.numero_nota if nf else baixa_id}: Tentativa {task.request.retries + 1}/{task.max_retries + 1} falhou. Retentando em 60s sem alertar o painel...")
            
            if task:
                raise task.retry(exc=e, countdown=60)
            raise
        finally:
            if lock_adquirido:
                try:
                    cache.delete(lock_key)
                except Exception:
                    pass

    def enviar_coleta(self, baixa_id, task=None):
        TOKEN = self.config.token_invoices
        
        # Trava de concorrência por coleta
        from django.core.cache import cache
        lock_key = f"lock_celery_esl_coleta_{baixa_id}"
        lock_adquirido = False
        try:
            lock_adquirido = cache.add(lock_key, "running", timeout=180)
            if not lock_adquirido:
                logger.warning(f"⚠️ Task Celery ignorada para Coleta #{baixa_id}: envio já em andamento por outro worker.")
                return f"Coleta {baixa_id} já em processamento concorrente."
        except Exception:
            pass

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
                
                is_ultima_tentativa = (not task) or (task.request.retries >= task.max_retries)

                if is_ultima_tentativa:
                    try:
                        from operacional.services import registrar_erro_torre
                        registrar_erro_torre(
                            filial=(manifesto.filial_operacao or manifesto.filial),
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
                else:
                    logger.info(f"⏳ [RETRY] Coleta {identificador}: Tentativa {task.request.retries + 1}/{task.max_retries + 1} falhou. Retentando sem alertar o painel...")
                
                if response.status_code == 404 and is_numeric:
                     logger.warning(f"ID numérico {identificador} deu 404 na V1. Tentando V2 em breve via retry.")
                
                raise Exception(f"Erro no ESL (Coleta): {msg_erro}")

        except Exception as e:
            logger.error(f"Erro enviar_coleta_esl_task ({baixa_id}): {str(e)}")
            
            is_ultima_tentativa = (not task) or (task.request.retries >= task.max_retries)
            if is_ultima_tentativa:
                try:
                    from operacional.services import registrar_erro_torre
                    registrar_erro_torre(
                        filial=(manifesto.filial_operacao or manifesto.filial),
                        categoria='INTEGRACAO_COLETA',
                        severidade_padrao='CRITICO',
                        titulo=f"Erro inesperado na Coleta {baixa_id}",
                        descricao=str(e)[:300],
                        erro_raw=str(e),
                        manifesto_numero=manifesto.numero_manifesto,
                    )
                except Exception as tr_exc:
                    logger.error(f"Erro ao registrar torre de controle: {tr_exc}")
            else:
                logger.info(f"⏳ [RETRY] Coleta {baixa_id}: Tentativa {task.request.retries + 1}/{task.max_retries + 1} falhou. Retentando sem alertar o painel...")

            if task:
                raise task.retry(exc=e, countdown=60)
            raise
        finally:
            if lock_adquirido:
                try:
                    cache.delete(lock_key)
                except Exception:
                    pass

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
                        self.enviar_baixa(b.id)
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
                    filial=(manifesto.filial_operacao or manifesto.filial),
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

    def _resolver_chave_cte_para_frete(self, nf, fid=None):
        """Busca chave de CT-e (44 dígitos) no objeto local ou consulta ESL."""
        if not nf:
            return None

        # 1. Chave gravada diretamente na nota
        if nf.chave_cte and len(str(nf.chave_cte).strip()) == 44:
            return str(nf.chave_cte).strip()

        # 2. Chave gravada no Frete relacionado
        if hasattr(nf, 'frete') and nf.frete and nf.frete.chave_cte and len(str(nf.frete.chave_cte).strip()) == 44:
            k = str(nf.frete.chave_cte).strip()
            if not nf.chave_cte:
                try:
                    nf.chave_cte = k
                    nf.save(update_fields=['chave_cte'])
                except Exception:
                    pass
            return k

        # 3. Chave de acesso da nota com 44 dígitos (se modelo 57 ou minuta com chave)
        if nf.chave_acesso and len(str(nf.chave_acesso).strip()) == 44 and str(nf.chave_acesso).strip().isdigit():
            return str(nf.chave_acesso).strip()

        # 4. Consulta rápida em /api/invoice_occurrences por invoice_number ou freight_id para obter cte_key
        try:
            num = str(nf.numero_nota or '').strip()
            url_oc = f"https://{self.config.dominio_esl}/api/invoice_occurrences"
            headers = {"Authorization": f"Bearer {self.config.token_invoices}"}
            params = {}
            if num:
                params["invoice_number"] = num
            elif fid:
                params["freight_id"] = str(fid).strip()

            if params:
                r = requests.get(url_oc, headers=headers, params=params, timeout=15)
                if r.status_code == 200:
                    for it in r.json().get("data", []):
                        f_info = it.get("freight") or {}
                        k = f_info.get("cte_key")
                        if k and len(str(k).strip()) == 44:
                            cte_k = str(k).strip()
                            try:
                                nf.chave_cte = cte_k
                                nf.save(update_fields=['chave_cte'])
                                if hasattr(nf, 'frete') and nf.frete and not nf.frete.chave_cte:
                                    nf.frete.chave_cte = cte_k
                                    nf.frete.save(update_fields=['chave_cte'])
                            except Exception:
                                pass
                            return cte_k
        except Exception as e_busca_cte:
            logger.warning(f"Aviso ao consultar cte_key na ESL: {e_busca_cte}")

        return None

    def enviar_anexo_frete(self, baixa, nf=None, freight_id=None):
        """
        Envia a foto de comprovante para fretes/minutas na ESL Cloud com roteamento inteligente:
        1. Se houver chave do CT-e (cte_key), envia via POST /api/freight_delivery_receipts (Comprovante Oficial).
        2. Se não houver chave do CT-e (ou se delivery_receipts falhar), envia via POST /api/freight_attachments
           usando o ID interno do frete e o número da minuta (draft_number).
        """
        if not baixa:
            return False, "Baixa inexistente"

        url_foto = getattr(baixa, 'comprovante_foto_url', None) or getattr(baixa, 'url_foto_recortada', None) or getattr(baixa, 'url_foto_original', None)
        if not url_foto:
            logger.info(f"ℹ️ Baixa #{getattr(baixa, 'id', 'N/A')} sem foto de comprovante. Pulando envio.")
            return True, "Sem foto para enviar"

        # Se for uma URL do proxy interno do painel, extrai a URL real da imagem
        url_foto_final = str(url_foto).strip()
        if 'proxy-imagem' in url_foto_final and 'url=' in url_foto_final:
            try:
                from urllib.parse import parse_qs, urlparse, unquote
                parsed_qs = parse_qs(urlparse(url_foto_final).query)
                if 'url' in parsed_qs:
                    url_foto_final = unquote(parsed_qs['url'][0])
            except Exception:
                pass

        if not nf and hasattr(baixa, 'nota_fiscal'):
            nf = baixa.nota_fiscal

        # Resolve freight_id (ID interno da ESL)
        fid = freight_id or getattr(nf, 'freight_id_tms', None) or (getattr(nf.frete, 'freight_id_tms', None) if (nf and hasattr(nf, 'frete') and nf.frete) else None)
        
        # Resolve número da minuta / nota (draft_number)
        draft_num = getattr(nf, 'numero_nota', None) or getattr(baixa, 'numero_nota', None)

        # 1. Tenta resolver a chave do CT-e (cte_key de 44 dígitos)
        cte_key = self._resolver_chave_cte_para_frete(nf, fid=fid)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.token_invoices}"
        }

        # =========================================================================
        # ROTA 1: Se tem chave CT-e de 44 dígitos -> POST /api/freight_delivery_receipts
        # (Cadastrar Comprovante de Entrega por Frete - Canhoto Oficial)
        # =========================================================================
        if cte_key and len(str(cte_key).strip()) == 44:
            url_receipt = f"https://{self.config.dominio_esl}/api/freight_delivery_receipts"
            payload_receipt = {
                "freight_delivery_receipt": {
                    "freight": {
                        "cte_key": str(cte_key).strip(),
                        "delivery_receipt_url": url_foto_final
                    }
                }
            }
            logger.info(f"📸 [ESL COMPROVANTE FRETE] Enviando via CT-e {cte_key} -> {url_receipt}")
            try:
                resp_rec = requests.post(url_receipt, json=payload_receipt, headers=headers, timeout=30)
                if resp_rec.status_code == 429:
                    import time
                    time.sleep(2.5)
                    resp_rec = requests.post(url_receipt, json=payload_receipt, headers=headers, timeout=30)

                if resp_rec.status_code in [200, 201]:
                    logger.info(f"✅ [ESL COMPROVANTE FRETE] Comprovante oficial cadastrado com sucesso via CT-e {cte_key}!")
                    return True, f"Comprovante cadastrado via CT-e ({cte_key[:6]}...)"
                else:
                    logger.warning(f"⚠️ [ESL COMPROVANTE FRETE] Status {resp_rec.status_code} em delivery_receipts ({resp_rec.text[:200]}). Tentando freight_attachments como fallback...")
            except Exception as e_rec:
                logger.warning(f"⚠️ [ESL COMPROVANTE FRETE] Exceção em delivery_receipts: {e_rec}. Tentando freight_attachments...")

        # =========================================================================
        # ROTA 2: Sem chave CT-e (ou fallback) -> POST /api/freight_attachments
        # (Cadastrar Anexo por Frete usando ID interno e draft_number)
        # =========================================================================
        freight_data = {
            "attachment_url": url_foto_final
        }
        if fid:
            freight_data["id"] = str(fid).strip()
        if draft_num:
            freight_data["draft_number"] = str(draft_num).strip()
        if cte_key:
            freight_data["cte_key"] = str(cte_key).strip()

        # Se não temos nem ID nem draft_number nem cte_key, tenta buscar ID interno na ESL
        if not (fid or draft_num or cte_key):
            if nf:
                fid = self._buscar_freight_id_minuta(nf)
                if fid:
                    freight_data["id"] = str(fid).strip()
            if not (freight_data.get("id") or freight_data.get("draft_number")):
                msg_falha = f"Impossível enviar foto: nenhum identificador de frete encontrado (id, draft_number, cte_key) para nota #{draft_num or 'N/A'}"
                logger.warning(f"⚠️ {msg_falha}")
                return False, msg_falha

        url_esl = f"https://{self.config.dominio_esl}/api/freight_attachments"
        payload = {
            "freight_attachment": {
                "freight": freight_data
            }
        }

        logger.info(f"📸 [ESL ANEXO FRETE] Enviando via Anexo de Frete (ID: {fid}, Draft: {draft_num}, CT-e: {cte_key}) -> {url_esl}")

        try:
            resp = requests.post(url_esl, json=payload, headers=headers, timeout=30)
            if resp.status_code == 429:
                import time
                logger.warning("Rate limit 429 atingido ao enviar anexo de frete. Aguardando 2.5s...")
                time.sleep(2.5)
                resp = requests.post(url_esl, json=payload, headers=headers, timeout=30)

            if resp.status_code in [200, 201]:
                logger.info(f"✅ [ESL ANEXO FRETE] Comprovante anexado ao frete com sucesso! (ID: {fid}, Draft: {draft_num})")
                return True, f"Anexo de frete integrado com sucesso (ESL Status {resp.status_code})"
            else:
                detalhe = resp.text
                logger.warning(f"⚠️ [ESL ANEXO FRETE] Resposta inesperada ({resp.status_code}): {detalhe}")
                return False, f"Erro status {resp.status_code}: {detalhe[:200]}"
        except Exception as e:
            logger.error(f"❌ [ESL ANEXO FRETE] Erro de conexão ao enviar anexo de frete: {e}")
            return False, str(e)

    def enviar_comprovante_entrega(self, baixa_id, task=None):
        """
        Cadastra/Atualiza o comprovante de entrega (foto/canhoto) no TMS ESL Cloud.
        Endpoints ESL Cloud:
        1. NF-e (chave_acesso): POST /api/freight_invoice_delivery_receipts
        2. Frete / CT-e / Minuta: POST /api/freight_attachments
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
            tem_chave_nfe = _is_chave_nfe_valida(nf.chave_acesso)
            is_operacao_frete = tipo_op in ['DESPACHO', 'TRANSFERENCIA', 'FRETE'] or (not tem_chave_nfe)

            if is_operacao_frete:
                # 📍 Operação de Frete/Minuta: Envia anexo via POST /api/freight_attachments
                ok_anexo, msg_anexo = self.enviar_anexo_frete(baixa=baixa, nf=nf)
                if ok_anexo:
                    baixa.processado_tms = True
                    baixa.integrado_tms = True
                    baixa.log_erro_tms = f"Sucesso: Comprovante anexado ao frete no TMS ({msg_anexo}) em {timezone.localtime().strftime('%d/%m/%Y %H:%M')}"
                    baixa.data_integracao = timezone.now()
                    baixa.save(update_fields=['processado_tms', 'integrado_tms', 'log_erro_tms', 'data_integracao'])
                    logger.info(f"✅ {baixa.log_erro_tms}")
                    return f"Comprovante de frete da nota #{nf.numero_nota} atualizado com sucesso."
                else:
                    raise Exception(msg_anexo)

            elif tem_chave_nfe:
                # 📍 Cadastrar Comprovante de Entrega por NF-e (Invoice modelo 55/65)
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
            else:
                msg = f"Nota #{nf.numero_nota} sem chave NF-e nem dados de frete para envio de comprovante."
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
            baixa.log_erro_tms = f"Sucesso: Comprovante de entrega atualizado no TMS ESL Cloud em {timezone.localtime().strftime('%d/%m/%Y %H:%M')}"
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

            is_ultima_tentativa = (not task) or (task.request.retries >= task.max_retries)
            if is_ultima_tentativa:
                try:
                    from operacional.services import registrar_erro_torre
                    registrar_erro_torre(
                        filial=(nf.manifesto.filial_operacao or nf.manifesto.filial) if (nf and nf.manifesto) else None,
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
            else:
                logger.info(f"⏳ [RETRY] Comprovante NF {nf.numero_nota if nf else baixa_id}: Tentativa {task.request.retries + 1}/{task.max_retries + 1} falhou. Retentando sem alertar o painel...")

            if task:
                raise task.retry(exc=e, countdown=60)
            raise

