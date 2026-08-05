import re
import time
import requests
import logging

logger = logging.getLogger(__name__)

def buscar_lat_lng_endereco(cep=None, endereco=None):
    """
    Busca Latitude e Longitude a partir do CEP e/ou Endereço de entrega.
    Se não encontrar, retorna (None, None) e segue.
    """
    cep_clean = re.sub(r'\D', '', str(cep or ''))
    end_clean = str(endereco or '').replace("ENDEREÇO NÃO INFORMADO", "").strip()

    if not cep_clean and not end_clean:
        return None, None

    headers = {
        'User-Agent': 'RXTrackGeocodingService/1.0 (vortex-tecnologia)'
    }

    # 1. Busca direta por CEP no Nominatim
    if cep_clean and len(cep_clean) == 8:
        try:
            time.sleep(1.2)
            resp = requests.get(
                f"https://nominatim.openstreetmap.org/search?postalcode={cep_clean}&country=Brazil&format=json&limit=1",
                headers=headers, timeout=(2, 3)
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    return round(float(data[0]['lat']), 6), round(float(data[0]['lon']), 6)
            elif resp.status_code in (429, 403):
                time.sleep(10)
        except Exception:
            pass

    # 2. ViaCEP para montar endereço completo
    endereco_busca = ""
    if cep_clean and len(cep_clean) == 8:
        try:
            resp_via = requests.get(f"https://viacep.com.br/ws/{cep_clean}/json/", timeout=(2, 3))
            if resp_via.status_code == 200:
                vdata = resp_via.json()
                if not vdata.get('erro'):
                    logra = vdata.get('logradouro', '')
                    bairro = vdata.get('bairro', '')
                    cidade = vdata.get('localidade', '')
                    uf = vdata.get('uf', '')
                    endereco_busca = f"{logra}, {bairro}, {cidade} - {uf}, Brasil"
        except Exception:
            pass

    # Fallback: usa o endereco da nota
    if not endereco_busca and end_clean:
        endereco_busca = f"{end_clean}, Brasil"

    # 3. Busca por endereço no Nominatim
    if endereco_busca:
        try:
            time.sleep(1.2)
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                headers=headers,
                params={'q': endereco_busca, 'format': 'json', 'limit': 1},
                timeout=(2, 3)
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    return round(float(data[0]['lat']), 6), round(float(data[0]['lon']), 6)
            elif resp.status_code in (429, 403):
                time.sleep(10)
        except Exception:
            pass

    return None, None
