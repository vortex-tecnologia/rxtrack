import re
import requests
import logging

logger = logging.getLogger(__name__)

def buscar_lat_lng_endereco(cep=None, endereco=None):
    """
    Busca Latitude e Longitude a partir do CEP e/ou Endereço de entrega
    usando APIs públicas gratuitas (ViaCEP + OpenStreetMap Nominatim).
    Retorna (latitude, longitude) ou (None, None).
    """
    lat, lng = None, None
    cep_clean = re.sub(r'\D', '', str(cep or ''))

    headers = {
        'User-Agent': 'RXTrackGeocodingService/1.0 (vortex-tecnologia)'
    }

    # 1. Busca direta por CEP no Nominatim OpenStreetMap
    if cep_clean and len(cep_clean) == 8:
        try:
            url_nom = f"https://nominatim.openstreetmap.org/search?postalcode={cep_clean}&country=Brazil&format=json&limit=1"
            resp = requests.get(url_nom, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    lat = round(float(data[0]['lat']), 6)
                    lng = round(float(data[0]['lon']), 6)
                    return lat, lng
        except Exception as e:
            logger.warning(f"Erro na busca por CEP Nominatim: {e}")

    # 2. Se não achou só com o CEP, consulta o ViaCEP para obter logradouro/bairro/cidade/UF
    endereco_busca = ""
    if cep_clean and len(cep_clean) == 8:
        try:
            resp_via = requests.get(f"https://viacep.com.br/ws/{cep_clean}/json/", timeout=5)
            if resp_via.status_code == 200:
                vdata = resp_via.json()
                if not vdata.get('erro'):
                    logra = vdata.get('logradouro', '')
                    bairro = vdata.get('bairro', '')
                    cidade = vdata.get('localidade', '')
                    uf = vdata.get('uf', '')
                    endereco_busca = f"{logra}, {bairro}, {cidade} - {uf}, Brasil"
        except Exception as e:
            logger.warning(f"Erro no ViaCEP: {e}")

    # Fallback: usa o texto de endereço informado na nota
    if not endereco_busca and endereco:
        # Limpa o endereço para evitar ruídos de texto
        end_clean = str(endereco).replace("ENDEREÇO NÃO INFORMADO", "").strip()
        if end_clean:
            endereco_busca = f"{end_clean}, Brasil"

    # 3. Consulta Nominatim com o Endereço completo obtido
    if endereco_busca:
        try:
            url_nom = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': endereco_busca,
                'format': 'json',
                'limit': 1
            }
            resp = requests.get(url_nom, headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    lat = round(float(data[0]['lat']), 6)
                    lng = round(float(data[0]['lon']), 6)
                    return lat, lng
        except Exception as e:
            logger.warning(f"Erro na busca por Endereço Nominatim: {e}")

    return lat, lng
