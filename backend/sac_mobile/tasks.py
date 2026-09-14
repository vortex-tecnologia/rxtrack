# sac_mobile/tasks.py
# Task isolada do SAC para enviar baixas ou comprovantes ao TMS

from celery import shared_task
import requests
import logging

logger = logging.getLogger(__name__)


def limpar_codigo_ocorrencia(codigo):
    """Remove zeros à esquerda do código de ocorrência para a ESL (ex: 098 -> 98, 050 -> 50).
    Nunca retorna '0' pois a ESL não aceita - usa '1' (entrega) como padrão."""
    if not codigo:
        return "1"
    codigo_str = str(codigo).strip()
    try:
        resultado = str(int(codigo_str))
        return resultado if resultado != "0" else "1"
    except ValueError:
        limpo = codigo_str.lstrip('0')
        return limpo if limpo else "1"


def enviar_comprovante_frete_sac(config, headers, freight_id=None, numero_doc=None, cte_k=None, url_foto=None):
    """
    Envia foto de comprovante para frete/minuta na ESL Cloud com roteamento inteligente:
    1. Se houver chave CT-e de 44 dígitos (ou resolver na ESL), envia via POST /api/freight_delivery_receipts.
    2. Se não houver chave CT-e (ou se delivery_receipts falhar), envia via POST /api/freight_attachments
       usando ID interno do frete e o draft_number (número da minuta).
    """
    if not url_foto:
        return False, "Sem URL de foto"

    url_foto_final = str(url_foto).strip()
    if 'proxy-imagem' in url_foto_final and 'url=' in url_foto_final:
        try:
            from urllib.parse import parse_qs, urlparse, unquote
            parsed_qs = parse_qs(urlparse(url_foto_final).query)
            if 'url' in parsed_qs:
                url_foto_final = unquote(parsed_qs['url'][0])
        except Exception:
            pass

    # 1. Tenta resolver a chave de CT-e de 44 dígitos se não informada
    if not cte_k or len(str(cte_k).strip()) != 44:
        # Busca local no banco
        try:
            from manifesto.models import NotaFiscal
            nf_item = None
            if numero_doc:
                nf_item = NotaFiscal.objects.filter(numero_nota=str(numero_doc).strip()).select_related('frete').first()
            if not nf_item and freight_id:
                nf_item = NotaFiscal.objects.filter(freight_id_tms=str(freight_id).strip()).select_related('frete').first()
            if nf_item:
                if nf_item.chave_cte and len(str(nf_item.chave_cte).strip()) == 44:
                    cte_k = str(nf_item.chave_cte).strip()
                elif hasattr(nf_item, 'frete') and nf_item.frete and nf_item.frete.chave_cte and len(str(nf_item.frete.chave_cte).strip()) == 44:
                    cte_k = str(nf_item.frete.chave_cte).strip()
        except Exception:
            pass

        # Se ainda não temos a chave, consulta ESL /api/invoice_occurrences por invoice_number ou freight_id
        if not cte_k or len(str(cte_k).strip()) != 44:
            try:
                url_oc = f"https://{config.dominio_esl}/api/invoice_occurrences"
                params = {}
                if numero_doc:
                    params["invoice_number"] = str(numero_doc).strip()
                elif freight_id:
                    params["freight_id"] = str(freight_id).strip()

                if params:
                    r_oc = requests.get(url_oc, headers=headers, params=params, timeout=15)
                    if r_oc.status_code == 200:
                        for it in r_oc.json().get("data", []):
                            k = (it.get("freight") or {}).get("cte_key")
                            if k and len(str(k).strip()) == 44:
                                cte_k = str(k).strip()
                                break
            except Exception as e_oc:
                logger.warning(f"Aviso ao consultar cte_key na ESL (SAC): {e_oc}")

    # =========================================================================
    # ROTA 1: Se tem chave CT-e de 44 dígitos -> POST /api/freight_delivery_receipts
    # =========================================================================
    if cte_k and len(str(cte_k).strip()) == 44:
        url_receipt = f"https://{config.dominio_esl}/api/freight_delivery_receipts"
        payload_rec = {
            "freight_delivery_receipt": {
                "freight": {
                    "cte_key": str(cte_k).strip(),
                    "delivery_receipt_url": url_foto_final
                }
            }
        }
        logger.info(f"📸 [SAC COMPROVANTE FRETE] Enviando via CT-e {cte_k} -> {url_receipt}")
        try:
            r_rec = requests.post(url_receipt, json=payload_rec, headers=headers, timeout=30)
            if r_rec.status_code in [200, 201]:
                logger.info(f"✅ [SAC COMPROVANTE FRETE] Comprovante oficial cadastrado via CT-e {cte_k}")
                return True, f"Comprovante cadastrado via CT-e ({cte_k[:6]}...)"
            else:
                logger.warning(f"⚠️ [SAC COMPROVANTE FRETE] Status {r_rec.status_code} em delivery_receipts ({r_rec.text[:200]}). Tentando freight_attachments como fallback...")
        except Exception as e_rec:
            logger.warning(f"⚠️ [SAC COMPROVANTE FRETE] Exceção em delivery_receipts: {e_rec}. Tentando freight_attachments...")

    # =========================================================================
    # ROTA 2: Fallback ou sem chave CT-e -> POST /api/freight_attachments
    # =========================================================================
    f_data = {
        "attachment_url": url_foto_final
    }
    if freight_id:
        f_data["id"] = str(freight_id).strip()
    if numero_doc:
        f_data["draft_number"] = str(numero_doc).strip()
    if cte_k:
        f_data["cte_key"] = str(cte_k).strip()

    if not (f_data.get("id") or f_data.get("draft_number") or f_data.get("cte_key")):
        return False, "Nenhum identificador de frete encontrado (id, draft_number ou cte_key)"

    url_anexo = f"https://{config.dominio_esl}/api/freight_attachments"
    payload_anexo = {
        "freight_attachment": {
            "freight": f_data
        }
    }
    logger.info(f"📸 [SAC ANEXO FRETE] Enviando via freight_attachments (ID: {freight_id}, Draft: {numero_doc}) -> {url_anexo}")
    try:
        r_anexo = requests.post(url_anexo, json=payload_anexo, headers=headers, timeout=30)
        if r_anexo.status_code in [200, 201]:
            logger.info(f"✅ [SAC ANEXO FRETE] Comprovante anexado com sucesso ao frete (ID: {freight_id})")
            return True, f"Anexo de frete integrado (Status {r_anexo.status_code})"
        else:
            logger.warning(f"⚠️ [SAC ANEXO FRETE] Status {r_anexo.status_code}: {r_anexo.text[:200]}")
            return False, f"Erro {r_anexo.status_code}: {r_anexo.text[:200]}"
    except Exception as e_anexo:
        logger.error(f"❌ [SAC ANEXO FRETE] Erro ao enviar anexo de frete: {e_anexo}")
        return False, str(e_anexo)


@shared_task(bind=True, max_retries=2)
def processar_envio_sac_tms_task(self, dados_baixa):
    """
    Processa o envio de ocorrência ou apenas comprovante para a ESL.
    Recebe um dicionário com os dados necessários em vez de acessar o banco local.
    """
    from configuracao.utils import get_config
    from .models import HistoricoBaixaSAC

    config = get_config()
    TOKEN = config.token_invoices
    
    historico_id = dados_baixa.get('historico_id')
    chave_acesso = dados_baixa.get('chave_acesso')
    freight_id = dados_baixa.get('freight_id')
    url_foto = dados_baixa.get('url_foto', '')
    if url_foto and 'proxy-imagem' in str(url_foto) and 'url=' in str(url_foto):
        try:
            from urllib.parse import parse_qs, urlparse, unquote
            parsed_qs = parse_qs(urlparse(str(url_foto)).query)
            if 'url' in parsed_qs:
                url_foto = unquote(parsed_qs['url'][0])
        except Exception:
            pass
    somente_comprovante = dados_baixa.get('somente_comprovante', False)
    
    # Função auxiliar para atualizar o log
    def atualizar_historico(status, msg_erro=None):
        if historico_id:
            try:
                hist = HistoricoBaixaSAC.objects.get(id=historico_id)
                hist.status_tms = status
                if msg_erro:
                    hist.log_erro_tms = msg_erro[:2000]
                hist.save(update_fields=['status_tms', 'log_erro_tms'])
            except Exception as e:
                logger.error(f"[SAC] Falha ao atualizar histórico {historico_id}: {e}")
    
    if not chave_acesso and not freight_id:
        atualizar_historico('ERRO', 'Nem chave de acesso nem ID do frete informados.')
        return "Erro: Nem chave de acesso nem ID do frete foram informados."

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }

    try:
        codigo_ocorrencia = None
        if somente_comprovante:
            # -------------------------------------------------------------
            # ENVIO APENAS DE COMPROVANTE (SEM OCORRÊNCIA)
            # -------------------------------------------------------------
            if not chave_acesso and (freight_id or dados_baixa.get('numero_nota')):
                numero_doc = dados_baixa.get('numero_nota')
                cte_k = dados_baixa.get('chave_cte')
                ok_comp, msg_comp = enviar_comprovante_frete_sac(
                    config=config,
                    headers=headers,
                    freight_id=freight_id,
                    numero_doc=numero_doc,
                    cte_k=cte_k,
                    url_foto=url_foto
                )
                if ok_comp:
                    atualizar_historico('SUCESSO')
                    return f"[SAC] Comprovante de frete integrado com sucesso: {msg_comp}"
                else:
                    atualizar_historico('ERRO', msg_comp)
                    return f"[SAC] Falha ao enviar comprovante de frete: {msg_comp}"
            elif not chave_acesso:
                msg = "Erro: Impossível enviar comprovante para minuta sem chave de acesso e sem ID de frete."
                atualizar_historico('ERRO', msg)
                return msg
            else:
                URL_ESL = f"https://{config.dominio_esl}/api/freight_invoice_delivery_receipts"
                payload = {
                    "freight_invoice_delivery_receipt": {
                        "invoice": {
                            "key": chave_acesso,
                            "delivery_receipt_url": url_foto
                        }
                    }
                }
                logger.info(f"[SAC] Enviando APENAS comprovante para NF {chave_acesso}")
            
        else:
            # -------------------------------------------------------------
            # ENVIO DE OCORRÊNCIA (+ FOTO SE HOUVER)
            # -------------------------------------------------------------
            if not chave_acesso and freight_id:
                # Para minutas sem chave, usar endpoint alternativo de frete (ocorrência pura)
                URL_ESL = f"https://{config.dominio_esl}/api/v1/freights/{freight_id}/invoice_occurrences"
            else:
                URL_ESL = f"https://{config.dominio_esl}/api/invoice_occurrences"
            
            codigo_ocorrencia = dados_baixa.get('ocorrencia_codigo')
            codigo_ocorrencia = limpar_codigo_ocorrencia(codigo_ocorrencia)
            nome_autor = dados_baixa.get('nome_autor', 'SAC')
            observacao = dados_baixa.get('observacao', '')
            data_ocorrencia_str = dados_baixa.get('data_ocorrencia') # Já deve vir no formato YYYY-MM-DDTHH:MM:SS.000-03:00
            
            # Lógica de fotos:
            # Para notas com chave de acesso, a foto vai no invoice.
            # Para minutas sem chave de acesso (Frete), a ocorrência é enviada limpa e a foto vai via /api/freight_attachments
            if not chave_acesso and freight_id:
                invoice_data = None
                freight_data = None
            else:
                if codigo_ocorrencia in [1, 2]:
                    invoice_data = {
                        "key": chave_acesso,
                        "delivery_receipt_url": url_foto
                    }
                    freight_data = {}
                else:
                    invoice_data = {
                        "key": chave_acesso,
                        "delivery_receipt_url": ""
                    }
                    freight_data = {
                        "delivery_receipt_url": url_foto,
                        "occurrence": {
                            "code": codigo_ocorrencia
                        }
                    } if url_foto else {}

            comentario = f"[BAIXA SAC] Operador: {nome_autor}. Obs: {observacao}"

            payload = {
                "invoice_occurrence": {
                    "receiver": "SAC",
                    "comments": comentario,
                    "occurrence_at": data_ocorrencia_str,
                    "occurrence": {
                        "code": codigo_ocorrencia
                    }
                }
            }
            
            if invoice_data:
                payload["invoice_occurrence"]["invoice"] = invoice_data
            
            # Se for buscar do TMS não enviamos manifesto.
            if freight_data:
                payload["invoice_occurrence"]["freight"] = freight_data
                
            logger.info(f"[SAC] Enviando Ocorrência {codigo_ocorrencia} para ID {chave_acesso or freight_id} - Operador: {nome_autor}")

        # ENVIO
        response = requests.post(URL_ESL, json=payload, headers=headers, timeout=30)
        
        # Se falhar com 422 (Unprocessable Entity) devido a ocorrência rejeitada/em branco,
        # e o código enviado não for o padrão, tenta novamente com o código 1
        if not somente_comprovante and response.status_code == 422 and codigo_ocorrencia and codigo_ocorrencia != 1:
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
                        f"[SAC] Ocorrência {codigo_ocorrencia} rejeitada pela ESL. "
                        "Tentando novamente com o código padrão 1."
                    )
                    # Atualiza o código tanto no nível raiz quanto no nível freight (se houver)
                    codigo_ocorrencia = 1
                    if "occurrence" in payload["invoice_occurrence"]:
                        payload["invoice_occurrence"]["occurrence"]["code"] = 1
                    if "freight" in payload["invoice_occurrence"] and "occurrence" in payload["invoice_occurrence"]["freight"]:
                        payload["invoice_occurrence"]["freight"]["occurrence"]["code"] = 1
                        
                    logger.info(f"[SAC] Payload de Fallback: {json.dumps(payload)}")
                    response = requests.post(URL_ESL, json=payload, headers=headers, timeout=30)
            except Exception as ex_fallback:
                logger.error(f"[SAC] Erro ao processar fallback de ocorrência: {ex_fallback}")
                
        response.raise_for_status()

        # 📸 Se foi envio de ocorrência por Frete e possui foto, envia o comprovante (CT-e com chave ou Anexo sem chave)
        if not chave_acesso and (freight_id or dados_baixa.get('numero_nota')) and url_foto and not somente_comprovante:
            numero_doc = dados_baixa.get('numero_nota')
            cte_k = dados_baixa.get('chave_cte')
            enviar_comprovante_frete_sac(
                config=config,
                headers=headers,
                freight_id=freight_id,
                numero_doc=numero_doc,
                cte_k=cte_k,
                url_foto=url_foto
            )

        atualizar_historico('SUCESSO')
        return f"[SAC] Envio do documento {chave_acesso or freight_id} concluído com sucesso."

    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
        detalhe = exc.response.text if hasattr(exc, 'response') and exc.response is not None else str(exc)
        msg_erro = f"Erro {status_code}: {detalhe}"

        logger.error(f"[SAC] Erro HTTP ao enviar NF {chave_acesso}: {msg_erro}")

        # Em caso de erro 4xx, pode notificar (se tiver notificação ativa)
        if status_code and 400 <= status_code < 500:
            atualizar_historico('ERRO', msg_erro)
            return f"Erro de validação ESL (SAC): {msg_erro}"

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60)

        atualizar_historico('ERRO', msg_erro)
        return f"Falha definitiva ESL (SAC): {msg_erro}"

    except Exception as e:
        msg = f"Erro inesperado (SAC): {str(e)}"
        logger.error(msg)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)
            
        atualizar_historico('ERRO', msg)
        raise e

@shared_task(bind=True, max_retries=2)
def processar_canhoto_sac_task(self, historico_id, dados_baixa):
    """
    Passa a imagem original do SAC pelo YOLO executando o script run_ia.py via subprocess,
    da mesma forma que a task do motorista.
    """
    from .models import HistoricoBaixaSAC
    from django.conf import settings
    from configuracao.utils import get_config
    import os
    import requests
    import numpy as np
    import cv2
    import subprocess
    from AgenteIa.tasks import upload_via_ftp_agente
    from django.utils import timezone
    
    try:
        hist = HistoricoBaixaSAC.objects.get(id=historico_id)
        url_original = hist.url_foto_original
        
        if not url_original:
            logger.warning(f"Histórico {historico_id} sem URL original. Passando adiante.")
            processar_envio_sac_tms_task.delay(dados_baixa)
            return "Sem URL Original"

        config = get_config()
        
        # Se YOLO estiver desligado, pula a IA
        if not config.processar_yolo:
            logger.info("YOLO desligado nas configurações. Passando adiante sem IA.")
            processar_envio_sac_tms_task.delay(dados_baixa)
            return "YOLO Desligado"

        # 1. Baixa a imagem
        resp = requests.get(url_original)
        img_array = np.frombuffer(resp.content, np.uint8)
        img_original = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        if img_original is None:
            logger.error("Erro ao decodificar imagem para IA.")
            processar_envio_sac_tms_task.delay(dados_baixa)
            return "Erro Decode IA"

        # 2. Prepara Tarja
        data_local = timezone.localtime(hist.data_criacao)
        data_str = data_local.strftime('%d/%m/%Y %H:%M:%S')
        operador_nome = hist.usuario.username if hist.usuario else "SAC"
        nf_num = hist.numero_nota or ""
        
        watermark_text = f"Baixa SAC - {data_str} Operador: {operador_nome} NFE {nf_num}".replace("  ", " ").strip()

        # 3. Salva temporariamente
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_ia_sac')
        os.makedirs(temp_dir, exist_ok=True)
        img_path = os.path.join(temp_dir, f"sac_temp_{hist.id}.jpg")
        cv2.imwrite(img_path, img_original)

        # 4. Chama script externo
        script_path = os.path.join(settings.BASE_DIR, 'AgenteIa', 'run_ia.py')
        skip_ocr = "skip_ocr" if not config.processar_ocr else ""
        
        logger.info(f"Iniciando YOLO Externo para SAC Hist {hist.id}")
        run_result = subprocess.run(['python', script_path, img_path, watermark_text, nf_num, skip_ocr], capture_output=True, text=True)
        out = run_result.stdout.strip()
        err = run_result.stderr.strip()

        found_canhoto = False
        nome_arquivo = f"sac_ia_{hist.id}.jpg"

        # 5. Verifica sucesso
        if "SUCESSO:" in out:
            crop_path = out.split("SUCESSO:")[1].strip()
            if os.path.exists(crop_path):
                with open(crop_path, 'rb') as f:
                    buffer_crop = f.read()
                    
                # Upload para FTP
                caminho_sucesso = 'public_html/uploads/AgenteIA/Sucesso'
                nova_url = upload_via_ftp_agente(buffer_crop, f"RECORTADO_{nome_arquivo}", caminho_sucesso)
                
                if nova_url:
                    hist.url_foto_recortada = nova_url
                    dados_baixa['url_foto'] = nova_url
                
                found_canhoto = True
                os.remove(crop_path)

        # Atualiza Status
        hist.ia_yolo_status = "INFO:YOLO_SUCESSO" in out
        hist.save(update_fields=['url_foto_recortada', 'ia_yolo_status'])
        
        # Limpa temporario
        if os.path.exists(img_path):
            os.remove(img_path)

        # Trata falha
        if not found_canhoto:
            logger.warning(f"YOLO (SAC) Falhou. Out: {out}")
            caminho_erro = 'public_html/uploads/AgenteIA/ErroLeitura'
            _, buffer_err = cv2.imencode('.jpg', img_original)
            upload_via_ftp_agente(buffer_err.tobytes(), f"FALHA_{nome_arquivo}", caminho_erro)

        # 6. Segue fluxo ESL
        processar_envio_sac_tms_task.delay(dados_baixa)
        return "Processamento de IA do SAC concluído."

    except HistoricoBaixaSAC.DoesNotExist:
        logger.error(f"[SAC IA] Histórico {historico_id} não encontrado.")
        processar_envio_sac_tms_task.delay(dados_baixa)
        return "Histórico não encontrado"
    except Exception as exc:
        logger.error(f"[SAC IA] Erro no processamento IA para hist {historico_id}: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
            
        logger.warning(f"[SAC IA] Esgotou retries. Seguindo para ESL com foto original.")
        processar_envio_sac_tms_task.delay(dados_baixa)
        return "Esgotou retries IA"
@shared_task(bind=True, max_retries=1)
def executar_rebusca_filial_task(self, filial_id, tipo='AUTOMATICA', schema_name=None):
    from manifesto.models import Manifesto, ManifestoBuscaLog
    from usuarios.models import Filial
    from sac_mobile.models import LogRebuscaFilial
    from integracoes.registry import get_tms_adapter
    from django.utils import timezone
    from django_tenants.utils import schema_context
    from django.db import connection
    from django.db.models import Q
    import logging
    
    logger = logging.getLogger(__name__)
    target_schema = schema_name or getattr(connection, 'schema_name', 'public')

    def _executar_no_schema():
        try:
            filial = Filial.objects.get(id=filial_id)
        except Filial.DoesNotExist:
            logger.error(f"[Rebusca] Filial ID {filial_id} não encontrada no schema '{target_schema}'.")
            return f"Filial {filial_id} não encontrada no schema {target_schema}."
            
        log_rebusca = LogRebuscaFilial.objects.create(
            filial=filial,
            tipo=tipo,
            status='PROCESSANDO'
        )
        
        try:
            adapter = get_tms_adapter()
            if not adapter:
                log_rebusca.status = 'ERRO'
                log_rebusca.concluido_em = timezone.now()
                log_rebusca.detalhes_manifestos = [{"erro": "TMS Adapter não configurado para o schema."}]
                log_rebusca.save()
                logger.error(f"[Rebusca] TMS Adapter não configurado para o schema '{target_schema}'.")
                return "TMS Adapter não encontrado."
                
            # Busca ampla de manifestos ativos dos últimos 30 dias da filial
            import datetime
            import time
            limite_dias = timezone.now() - datetime.timedelta(days=30)
            
            filtro_filial = Q(filial=filial) | Q(motorista__filial=filial)
            if filial.id_filial_tms:
                filtro_filial |= Q(filial__id_filial_tms=str(filial.id_filial_tms).strip()) | Q(motorista__filial__id_filial_tms=str(filial.id_filial_tms).strip())
            if filial.nome:
                filtro_filial |= Q(filial__nome__iexact=filial.nome.strip())
                
            manifestos = list(Manifesto.objects.filter(filtro_filial).filter(
                status='EM_TRANSPORTE',
                finalizado=False,
                data_criacao__gte=limite_dias
            ).select_related('motorista', 'filial').order_by('-data_criacao').distinct())
            
            detalhes = []
            
            for manifesto in manifestos:
                if not manifesto.motorista:
                    continue
                    
                # Garante vínculo de filial correto no manifesto se estava nulo
                if not manifesto.filial:
                    manifesto.filial = filial
                    manifesto.save(update_fields=['filial'])
                    
                # update_or_create para respeitar unique_together (numero_manifesto, motorista)
                busca_log, _ = ManifestoBuscaLog.objects.update_or_create(
                    numero_manifesto=manifesto.numero_manifesto,
                    motorista=manifesto.motorista,
                    defaults={'status': 'PROCESSANDO', 'mensagem_erro': None}
                )
                
                try:
                    notas_antes = manifesto.notas_fiscais.count()
                    resultado = adapter.buscar_manifesto_completo(busca_log.id)
                    notas_depois = manifesto.notas_fiscais.count()
                    
                    diff = notas_depois - notas_antes
                    inseridas = diff if diff > 0 else 0
                    removidas = abs(diff) if diff < 0 else 0
                    
                    # Recarrega o manifesto e o log da busca para verificar o estado final
                    manifesto.refresh_from_db()
                    busca_log.refresh_from_db()
                    
                    if manifesto.status == 'FINALIZADO' or manifesto.finalizado:
                        msg_res = "Fechado no TMS (finalizado no app)"
                    elif busca_log.status == 'ERRO' and busca_log.mensagem_erro:
                        msg_res = busca_log.mensagem_erro
                    elif inseridas > 0 or removidas > 0:
                        msg_res = f"Atualizado (+{inseridas} novas, -{removidas} baixadas)"
                    else:
                        msg_res = "Sincronizado (sem alterações)"
                    
                    detalhes.append({
                        "manifesto": manifesto.numero_manifesto,
                        "motorista": manifesto.motorista.nome_completo if manifesto.motorista else '-',
                        "inseridas": inseridas,
                        "removidas": removidas,
                        "resultado": msg_res
                    })
                    
                    # Intervalo seguro de 2.0s entre cada manifesto para respeitar a taxa da ESL
                    time.sleep(2.0)
                    
                except Exception as e:
                    logger.error(f"[Rebusca] Erro ao buscar manifesto {manifesto.numero_manifesto}: {e}")
                    detalhes.append({
                        "manifesto": manifesto.numero_manifesto,
                        "erro": str(e)
                    })
                    
            log_rebusca.detalhes_manifestos = detalhes
            log_rebusca.status = 'CONCLUIDO'
            log_rebusca.concluido_em = timezone.now()
            log_rebusca.save(update_fields=['detalhes_manifestos', 'status', 'concluido_em'])
            
            logger.info(f"[Rebusca] Concluída filial {filial.nome} (Schema: {target_schema}). {len(manifestos)} manifestos verificados.")
            return f"Rebusca filial {filial.nome} concluída. {len(manifestos)} manifestos verificados."
        except Exception as ex:
            logger.error(f"[Rebusca] Erro geral na execução da filial {filial.nome}: {ex}")
            log_rebusca.status = 'ERRO'
            log_rebusca.concluido_em = timezone.now()
            log_rebusca.detalhes_manifestos = [{"erro": f"Erro interno: {str(ex)}"}]
            log_rebusca.save()
            return f"Erro: {ex}"

    if target_schema and target_schema != 'public':
        with schema_context(target_schema):
            return _executar_no_schema()
    else:
        return _executar_no_schema()


@shared_task
def verificar_agendamentos_rebusca_task():
    from django_tenants.utils import get_tenant_model, schema_context
    from usuarios.models import Filial
    from django.utils import timezone
    import logging
    
    logger = logging.getLogger(__name__)
    agora_br = timezone.localtime(timezone.now())
    hora_atual_str = agora_br.strftime('%H:%M')
    
    TenantModel = get_tenant_model()
    tenants = list(TenantModel.objects.exclude(schema_name='public'))
    
    schemas_para_verificar = [t.schema_name for t in tenants]
    if not schemas_para_verificar:
        schemas_para_verificar = ['public']
        
    for schema_name in schemas_para_verificar:
        try:
            with schema_context(schema_name):
                filiais = Filial.objects.exclude(horario_rebusca_esl__isnull=True)
                for filial in filiais:
                    if not filial.horario_rebusca_esl:
                        continue
                    horario_str = filial.horario_rebusca_esl.strftime('%H:%M')
                    if hora_atual_str == horario_str:
                        logger.info(f"⏰ [Rebusca Automática] Disparando rebusca para filial '{filial.nome}' (Schema: {schema_name}) às {hora_atual_str}")
                        executar_rebusca_filial_task.delay(filial.id, 'AUTOMATICA', schema_name=schema_name)
        except Exception as e:
            logger.error(f"❌ [Rebusca Automática] Erro no schema {schema_name}: {e}")
