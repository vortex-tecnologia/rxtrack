# suporte/utils.py
from ftplib import FTP
from io import BytesIO
from django.conf import settings
import uuid
from datetime import datetime


# Mapeamento de tipo de mídia para subpasta FTP
TIPO_PASTA_MAP = {
    'IMAGEM': 'Fotos',
    'AUDIO': 'Audios',
    'VIDEO': 'videos',
}

FTP_SUPORTE_BASE_PATH = 'domains/st63136.ispot.cc/public_html/uploads/Suporte_app_entregas'
FTP_SUPORTE_BASE_URL = 'https://st63136.ispot.cc/uploads/Suporte_app_entregas'


def upload_suporte_ftp(arquivo_bytes, nome_arquivo, tipo_midia='IMAGEM'):
    """
    Faz upload de midia do suporte para o FTP na pasta correta.
    tipo_midia: 'IMAGEM', 'AUDIO', 'VIDEO'
    Retorna a URL publica do arquivo ou None em caso de erro.
    """
    subpasta = TIPO_PASTA_MAP.get(tipo_midia, 'Fotos')
    
    try:
        ftp = FTP(settings.FTP_HOST, timeout=30)
        ftp.login(user=settings.FTP_USER, passwd=settings.FTP_PASS)
        
        caminho = f"{FTP_SUPORTE_BASE_PATH}/{subpasta}"
        
        try:
            ftp.cwd(caminho)
        except Exception:
            # Fallback: tenta sem o prefixo domains/
            ftp.cwd(f"public_html/uploads/Suporte_app_entregas/{subpasta}")
        
        ftp.storbinary(f"STOR {nome_arquivo}", BytesIO(arquivo_bytes))
        ftp.quit()
        
        url = f"{FTP_SUPORTE_BASE_URL}/{subpasta}/{nome_arquivo}"
        return url
    except Exception as e:
        print(f"Erro no Upload FTP Suporte: {e}")
        return None


def gerar_nome_arquivo(ticket_id, tipo_midia, extensao='jpg'):
    """Gera nome unico para arquivo de suporte."""
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    uid = uuid.uuid4().hex[:6]
    return f"ticket_{ticket_id}_{ts}_{uid}.{extensao}"
