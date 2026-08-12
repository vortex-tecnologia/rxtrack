# agente_ia/tasks.py
from celery import shared_task
from django.conf import settings
from django.apps import apps
from manifesto.models import BaixaNF
from manifesto.tasks import enviar_baixa_esl_task, enviar_baixa_minuta_task
import cv2
import numpy as np
import requests
import os
from ftplib import FTP
from io import BytesIO

@shared_task
def task_processar_canhoto_ia(baixa_id, somente_comprovante=False):
    """
    Interceptor do Agente IA: 
    Processa a foto antes do envio final para o TMS.
    """
    try:
        baixa = BaixaNF.objects.get(id=baixa_id)
    except BaixaNF.DoesNotExist:
        return

    try:
        url_original = baixa.comprovante_foto_url
        if not url_original:
            baixa.qualidade_canhoto = 'APROVADO'
            baixa.solicitar_nova_foto = False
            baixa.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])
            return finalizar_fluxo_tms(baixa, somente_comprovante=somente_comprovante)

        # 1.1 O YOLO/OCR é acionado se a ocorrência estiver na lista de códigos ativadores (ex: 01, 02, 1, 2) ou se for um recadastro de comprovante
        from configuracao.utils import get_config
        config = get_config()

        cod_ref = str(getattr(baixa.ocorrencia, 'codigo_referencia', '') or '').strip()
        cod_tms = str(getattr(baixa.ocorrencia, 'codigo_tms', '') or '').strip()
        
        # SOMENTE Ocorrência 01 é analisada pela IA (02 - Coleta e outras ocorrências seguem direto)
        is_yolo_habilitado = (
            cod_ref in ['01', '1'] or
            cod_tms in ['01', '1'] or
            (baixa.tipo == 'ENTREGA' and cod_tms not in ['02', '2', '050', '055']) or
            somente_comprovante is True
        )

        if not is_yolo_habilitado:
            print(f"Ocorrência (TMS:{cod_tms}/Ref:{cod_ref}) não é 01 (Entrega). Pulando YOLO/OCR e enviando foto diretamente ao TMS.")
            baixa.ia_yolo_status = False
            baixa.ia_ocr_status = False
            baixa.qualidade_canhoto = 'APROVADO'
            baixa.solicitar_nova_foto = False
            baixa.save(update_fields=['ia_yolo_status', 'ia_ocr_status', 'qualidade_canhoto', 'solicitar_nova_foto'])
            return finalizar_fluxo_tms(baixa, somente_comprovante=somente_comprovante)

        # 2. Baixa a imagem da URL original para a memória
        resp = requests.get(url_original)
        img_array = np.frombuffer(resp.content, np.uint8)
        img_original = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        if img_original is None:
            baixa.qualidade_canhoto = 'APROVADO'
            baixa.solicitar_nova_foto = False
            baixa.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])
            return finalizar_fluxo_tms(baixa, somente_comprovante=somente_comprovante)

        # 3. Monta o texto da Tarja Preta
        from django.utils import timezone
        data_local = timezone.localtime(baixa.data_baixa) if baixa.data_baixa else timezone.now()
        data_str = data_local.strftime('%d/%m/%Y %H:%M:%S')
        
        lat = str(baixa.latitude) if baixa.latitude else ""
        lng = str(baixa.longitude) if baixa.longitude else ""
        
        motorista_nome = ""
        nfe_num = ""
        if baixa.nota_fiscal:
            nfe_num = baixa.nota_fiscal.numero_nota or ""
            if baixa.nota_fiscal.manifesto and baixa.nota_fiscal.manifesto.motorista:
                motorista_nome = getattr(baixa.nota_fiscal.manifesto.motorista, 'nome_completo', '') or getattr(baixa.nota_fiscal.manifesto.motorista, 'nome_motorista', '')

        watermark_text = f"RXTrack - {data_str} {lat}, {lng} {motorista_nome} NFE {nfe_num}".replace("  ", " ").strip()
        
        # 4. Salva a imagem original num arquivo temporario para o script externo ler
        import tempfile
        import subprocess
        
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_ia')
        os.makedirs(temp_dir, exist_ok=True)
        
        # Limpeza automática: Remove arquivos temporários com mais de 1 hora (proteção contra crash)
        import time
        agora = time.time()
        for f in os.listdir(temp_dir):
            caminho_f = os.path.join(temp_dir, f)
            if os.path.isfile(caminho_f) and (agora - os.path.getmtime(caminho_f)) > 3600:
                try:
                    os.remove(caminho_f)
                except:
                    pass
        
        # img_path será enviado pro run_ia.py
        img_path = os.path.join(temp_dir, f"temp_{baixa.id}.jpg")
        cv2.imwrite(img_path, img_original)
        
        # 5. Chama o script Python isolado que não sofre do bug de multiprocessing do Celery
        from configuracao.utils import get_config
        config = get_config()
        
        # Se YOLO estiver desligado, pula o processamento da IA e vai direto pro TMS
        if not config.processar_yolo:
            print(f"YOLO desligado nas configurações. Enviando foto original para TMS.")
            baixa.ia_yolo_status = False
            baixa.ia_ocr_status = False
            baixa.qualidade_canhoto = 'APROVADO'
            baixa.solicitar_nova_foto = False
            baixa.save(update_fields=['ia_yolo_status', 'ia_ocr_status', 'qualidade_canhoto', 'solicitar_nova_foto'])
            if os.path.exists(img_path):
                os.remove(img_path)
            return finalizar_fluxo_tms(baixa)
        
        script_path = os.path.join(settings.BASE_DIR, 'AgenteIa', 'run_ia.py')
        skip_ocr = "skip_ocr" if not config.processar_ocr else "with_ocr"
        codigo_oc_passar = cod_tms or cod_ref
        if not codigo_oc_passar:
            codigos_banco = config.get_codigos_yolo_list()
            codigo_oc_passar = codigos_banco[0] if codigos_banco else ""
        print(f"Iniciando YOLO Externo para Baixa #{baixa.id} (Ocorrência Banco: '{codigo_oc_passar}', OCR: {'ON' if config.processar_ocr else 'OFF'})...")
        import sys
        run_result = subprocess.run([sys.executable, script_path, img_path, watermark_text, nfe_num, skip_ocr, codigo_oc_passar], capture_output=True, text=True)
        out = run_result.stdout.strip()
        err = run_result.stderr.strip()
        
        found_canhoto = False
        nome_arquivo = f"ia_{baixa.id}.jpg"

        # Se o script imprimiu SUCESSO:caminho_da_imagem
        if "SUCESSO:" in out:
            crop_path = out.split("SUCESSO:")[1].strip()
            if os.path.exists(crop_path):
                with open(crop_path, 'rb') as f:
                    buffer_crop = f.read()
                    
                # 5. UPLOAD SUCESSO
                caminho_sucesso = 'public_html/uploads/AgenteIA/Sucesso'
                nova_url = upload_via_ftp_agente(buffer_crop, f"RECORTADO_{nome_arquivo}", caminho_sucesso)
                
                if nova_url:
                    baixa.comprovante_foto_url = nova_url
                
                found_canhoto = True
                os.remove(crop_path)
                
        # --- ATUALIZA STATUS E DADOS EXTRAÍDOS PELA IA NO BANCO ---
        baixa.ia_yolo_status = "INFO:YOLO_SUCESSO" in out
        baixa.ia_ocr_status = "INFO:OCR_SUCESSO" in out or "FLORENCE_QUALIDADE:BOA" in out

        # Extrai métricas e motivos do Florence-2
        qualidade_ia = "BOA"
        motivo_rejeicao = ""
        score_nitidez_val = None

        for line in out.split('\n'):
            line = line.strip()
            if line.startswith("FLORENCE_QUALIDADE:"):
                qualidade_ia = line.split("FLORENCE_QUALIDADE:")[1].strip()
            elif line.startswith("FLORENCE_MOTIVO:"):
                motivo_rejeicao = line.split("FLORENCE_MOTIVO:")[1].strip()
            elif line.startswith("FLORENCE_NITIDEZ:"):
                try:
                    score_nitidez_val = float(line.split("FLORENCE_NITIDEZ:")[1].strip())
                except Exception:
                    pass

        baixa.score_nitidez = score_nitidez_val
        baixa.motivo_rejeicao_ia = motivo_rejeicao if motivo_rejeicao else None

        # Extrai Recebedor e Documento lidos pelo Florence-2 caso o motorista não tenha informado
        if "FLORENCE_RECEBEDOR:" in out and not baixa.recebedor:
            for line in out.split('\n'):
                if line.startswith("FLORENCE_RECEBEDOR:"):
                    rec_val = line.split("FLORENCE_RECEBEDOR:")[1].strip()
                    if rec_val:
                        baixa.recebedor = rec_val[:100]
                    break

        if "FLORENCE_DOCUMENTO:" in out and not baixa.documento_recebedor:
            for line in out.split('\n'):
                if line.startswith("FLORENCE_DOCUMENTO:"):
                    doc_val = line.split("FLORENCE_DOCUMENTO:")[1].strip()
                    if doc_val:
                        baixa.documento_recebedor = doc_val[:20]
                    break

        # Limpa arquivo temporario
        if os.path.exists(img_path):
            os.remove(img_path)

        # 6. CASO DE FALHA YOLO: Salva original na pasta de Erro para Treinamento futuro do modelo
        if not found_canhoto:
            print(f"[IA] YOLO não detectou canhoto na Baixa #{baixa.id}. Foto original será enviada ao TMS sem recorte. Out: {out[:200]}")
            caminho_erro = 'public_html/uploads/AgenteIA/ErroLeitura'
            _, buffer_err = cv2.imencode('.jpg', img_original)
            upload_via_ftp_agente(buffer_err.tobytes(), f"FALHA_{nome_arquivo}", caminho_erro)

        # --- 7. REGRAS DO GUARDIÃO DE CANHOTOS (OCORRÊNCIA 01 / LIMITE 3X / RETENÇÃO TMS) ---
        is_ocorrencia_01 = (
            cod_ref in ['01', '1'] or
            cod_tms in ['01', '1'] or
            (baixa.tipo == 'ENTREGA' and not baixa.ocorrencia)
        )

        if is_ocorrencia_01:
            if qualidade_ia == "BOA":
                baixa.qualidade_canhoto = 'APROVADO'
                baixa.solicitar_nova_foto = False
                baixa.save()
                print(f"[IA-GUARDIÃO] Canhoto da Baixa #{baixa.id} (NF {nfe_num}) APROVADO! Enviando ao TMS.")
                if baixa.nota_fiscal and baixa.nota_fiscal.manifesto:
                    try:
                        from manifesto.services import enviar_painel
                        enviar_painel(baixa.nota_fiscal.manifesto)
                    except Exception:
                        pass
                finalizar_fluxo_tms(baixa, somente_comprovante=somente_comprovante)
            else:
                # Foto reprovada (desfocada ou ilegível)
                if (baixa.tentativa_foto or 1) < 3:
                    baixa.qualidade_canhoto = 'ILEGIVEL'
                    baixa.solicitar_nova_foto = True
                    baixa.save()
                    print(f"[IA-GUARDIÃO] Canhoto da Baixa #{baixa.id} (NF {nfe_num}) REPROVADO ({qualidade_ia}/{motivo_rejeicao}). Tentativa {baixa.tentativa_foto}/3. Retendo envio ao TMS.")
                    disparar_notificacao_canhoto_reprovado(baixa)
                    if baixa.nota_fiscal and baixa.nota_fiscal.manifesto:
                        try:
                            from manifesto.services import enviar_painel
                            enviar_painel(baixa.nota_fiscal.manifesto)
                        except Exception:
                            pass
                else:
                    # 3ª Tentativa atingida: libera envio ao TMS para não travar a rotina
                    baixa.qualidade_canhoto = 'REPROVADO_LIMITE_3X'
                    baixa.solicitar_nova_foto = False
                    baixa.save()
                    print(f"[IA-GUARDIÃO] Baixa #{baixa.id} (NF {nfe_num}) atingiu o limite de 3 tentativas. Liberando envio ao TMS com auditoria.")
                    if baixa.nota_fiscal and baixa.nota_fiscal.manifesto:
                        try:
                            from manifesto.services import enviar_painel
                            enviar_painel(baixa.nota_fiscal.manifesto)
                        except Exception:
                            pass
                    finalizar_fluxo_tms(baixa, somente_comprovante=somente_comprovante)
        else:
            baixa.qualidade_canhoto = 'APROVADO'
            baixa.solicitar_nova_foto = False
            baixa.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])
            finalizar_fluxo_tms(baixa, somente_comprovante=somente_comprovante)
    except Exception as err:
        print(f"[IA-GUARDIÃO] Erro inesperado ao processar canhoto da Baixa #{baixa_id}: {err}")
        try:
            baixa = BaixaNF.objects.get(id=baixa_id)
            if baixa.qualidade_canhoto == 'PENDENTE_ANALISE':
                baixa.qualidade_canhoto = 'APROVADO'
                baixa.solicitar_nova_foto = False
                baixa.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])
                finalizar_fluxo_tms(baixa, somente_comprovante=somente_comprovante)
        except Exception:
            pass


def disparar_notificacao_canhoto_reprovado(baixa):
    """Dispara Notificação Push Nativa (FCM para APK e WebPush para PWA) informando canhoto ilegível."""
    try:
        motorista = None
        if baixa.nota_fiscal and baixa.nota_fiscal.manifesto:
            motorista = baixa.nota_fiscal.manifesto.motorista
        elif baixa.autor_baixa:
            motorista = baixa.autor_baixa

        nfe_num = baixa.nota_fiscal.numero_nota if baixa.nota_fiscal else ""
        tentativa_atual = baixa.tentativa_foto or 1
        titulo = "⚠️ RXTrack - Canhoto Ilegível"
        mensagem = f"A foto do canhoto da NF #{nfe_num} ficou fora de foco ou ilegível (Tentativa {tentativa_atual}/3). Toque para tirar uma nova foto."
        payload = {
            'tipo': 'CANHOTO_ILEGIVEL',
            'nota_fiscal': str(nfe_num),
            'baixa_id': str(baixa.id),
            'tentativa': str(tentativa_atual),
            'chave_acesso': str(baixa.nota_fiscal.chave_acesso if baixa.nota_fiscal else '')
        }

        # 1. FCM Push para quem usa APK
        if motorista and motorista.fcm_token:
            from common.fcm_service import enviar_notificacao_push
            enviar_notificacao_push(motorista, titulo, mensagem, tipo='ALERTA', dados_payload=payload)

        # 2. WebPush para quem usa PWA instalado
        if motorista and getattr(motorista, 'user', None):
            from mobile.services.webpush_service import enviar_notificacao_usuario
            enviar_notificacao_usuario(motorista.user, {
                'title': titulo,
                'body': mensagem,
                'data': payload
            })
    except Exception as e:
        print(f"[IA-GUARDIÃO] Aviso: Não foi possível disparar push de canhoto reprovado: {e}")


def upload_via_ftp_agente(imagem_bytes, nome_arquivo, caminho_destino):
    """Sua função de FTP adaptada para caminhos dinâmicos"""
    try:
        ftp = FTP(settings.FTP_HOST, timeout=30)
        ftp.login(user=settings.FTP_USER, passwd=settings.FTP_PASS)
        
        # Tenta acessar o caminho completo da Interserver
        try:
            ftp.cwd(f"domains/st63136.ispot.cc/{caminho_destino}")
        except:
            ftp.cwd(caminho_destino)

        ftp.storbinary(f"STOR {nome_arquivo}", BytesIO(imagem_bytes))
        ftp.quit()

        # Monta a URL baseada na subpasta para o banco de dados
        pasta_final = "Sucesso" if "Sucesso" in caminho_destino else "ErroLeitura"
        return f"https://st63136.ispot.cc/uploads/AgenteIA/{pasta_final}/{nome_arquivo}"
    except Exception as e:
        print(f"Erro no Upload FTP AgenteIA: {e}")
        return None

def finalizar_fluxo_tms(baixa, somente_comprovante=False):
    """Dispara a integração final com o delay necessário (controlado pela flag enviar_tms)"""
    from configuracao.utils import get_config
    from manifesto.tasks import enviar_comprovante_esl_task
    config = get_config()
    
    if not config.enviar_tms:
        print(f"TMS: Envio DESLIGADO nas configurações. Baixa {baixa.id} salva apenas localmente.")
        return

    if somente_comprovante:
        enviar_comprovante_esl_task.apply_async(args=[baixa.id], countdown=2)
        print(f"TMS: Recadastro exclusivo de comprovante para Baixa #{baixa.id} despachado.")
        return
    
    nf = baixa.nota_fiscal
    if nf and nf.tipo_operacao and str(nf.tipo_operacao).upper() == 'DESPACHO':
        enviar_baixa_minuta_task.apply_async(args=[baixa.id], countdown=2)
        print(f"TMS: Despacho {nf.numero_nota} despachado para Frete Endpoint.")
    elif nf and nf.chave_acesso:
        enviar_baixa_esl_task.apply_async(args=[baixa.id], countdown=2)
        print(f"TMS: Fluxo de baixa de NF-e {nf.chave_acesso} despachado.")
    elif nf:
        enviar_baixa_minuta_task.apply_async(args=[baixa.id], countdown=2)
        print(f"TMS: Fluxo de baixa de Minuta {nf.numero_nota} despachado.")
