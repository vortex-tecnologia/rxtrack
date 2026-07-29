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

@shared_task(queue='ai_queue')
def task_processar_canhoto_ia(baixa_id):
    """
    Interceptor do Agente IA: 
    Processa a foto antes do envio final para o TMS.
    """
    try:
        baixa = BaixaNF.objects.get(id=baixa_id)
    except BaixaNF.DoesNotExist:
        return

    url_original = baixa.comprovante_foto_url
    if not url_original:
        return finalizar_fluxo_tms(baixa)

    # 2. Baixa a imagem da URL original para a memória
    resp = requests.get(url_original)
    img_array = np.frombuffer(resp.content, np.uint8)
    img_original = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    
    if img_original is None:
        return finalizar_fluxo_tms(baixa)

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

    watermark_text = f"Aplicativo - {data_str} {lat}, {lng} {motorista_nome} NFE {nfe_num}".replace("  ", " ").strip()
    
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
        baixa.save()
        if os.path.exists(img_path):
            os.remove(img_path)
        return finalizar_fluxo_tms(baixa)
    
    script_path = os.path.join(settings.BASE_DIR, 'AgenteIa', 'run_ia.py')
    skip_ocr = "skip_ocr" if not config.processar_ocr else ""
    print(f"Iniciando YOLO Externo para Baixa {baixa.id}... (OCR: {'ON' if config.processar_ocr else 'OFF'})")
    run_result = subprocess.run(['python', script_path, img_path, watermark_text, nfe_num, skip_ocr], capture_output=True, text=True)
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
            
    # --- ATUALIZA STATUS DA IA NO BANCO ---
    baixa.ia_yolo_status = "INFO:YOLO_SUCESSO" in out
    baixa.ia_ocr_status = "INFO:OCR_SUCESSO" in out
    baixa.save()
            
    # Limpa arquivo temporario
    if os.path.exists(img_path):
        os.remove(img_path)

    # 6. CASO DE FALHA: Salva original na pasta de Erro para seu Treinamento
    if not found_canhoto:
        print(f"YOLO Falhou ou nao encontrou classe 0. Out: {out}")
        caminho_erro = 'public_html/uploads/AgenteIA/ErroLeitura'
        _, buffer_err = cv2.imencode('.jpg', img_original)
        upload_via_ftp_agente(buffer_err.tobytes(), f"FALHA_{nome_arquivo}", caminho_erro)

    # 7. Finaliza enviando para o TMS
    finalizar_fluxo_tms(baixa)


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

def finalizar_fluxo_tms(baixa):
    """Dispara a integração final com o delay necessário (controlado pela flag enviar_tms)"""
    from configuracao.utils import get_config
    config = get_config()
    
    if not config.enviar_tms:
        print(f"TMS: Envio DESLIGADO nas configurações. Baixa {baixa.id} salva apenas localmente.")
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
