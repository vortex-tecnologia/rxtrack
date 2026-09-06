"""
test_roteirizacao_suite.py
Validação automatizada das 10 regras de negócio da Roteirização Manual do RXTrack.
"""

import math
import urllib.parse
import json
import unittest

LIMITE_SEGMENTO_GOOGLE = 10

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def coord_valida(lat, lng):
    if lat is None or lng is None:
        return False
    try:
        n_lat = float(lat)
        n_lng = float(lng)
        if math.isnan(n_lat) or math.isnan(n_lng):
            return False
        return -90 <= n_lat <= 90 and -180 <= n_lng <= 180 and not (n_lat == 0 and n_lng == 0)
    except (ValueError, TypeError):
        return False

def sanitizar_endereco(end, cep=None):
    if not end:
        return f"CEP {cep}, Brasil" if cep else ""
    txt = " ".join(str(end).split())
    if "ENDEREÇO NÃO INFORMADO" in txt.upper():
        return f"CEP {cep}, Brasil" if cep else ""
    if "brasil" not in txt.lower():
        txt += ", Brasil"
    return txt

def recalcular_estados_rota(paradas):
    achou_atual = False
    for idx, p in enumerate(paradas):
        p['ordem'] = idx + 1
        if p.get('selecionada') is False:
            p['estado'] = 'DESMARCADA'
        elif p.get('concluida') is True:
            p['estado'] = 'CONCLUIDA'
        elif not achou_atual:
            p['estado'] = 'ATUAL'
            achou_atual = True
        else:
            p['estado'] = 'PENDENTE'

def gerar_url_waze(paradas):
    parada_alvo = next((p for p in paradas if p.get('estado') == 'ATUAL' and p.get('selecionada', True)), None)
    if not parada_alvo:
        parada_alvo = next((p for p in paradas if p.get('selecionada', True) and not p.get('concluida', False)), None)
    if not parada_alvo:
        return None

    lat = parada_alvo.get('latitude')
    lng = parada_alvo.get('longitude')
    if coord_valida(lat, lng):
        url = f"https://waze.com/ul?ll={lat},{lng}&navigate=yes"
    else:
        end_enc = urllib.parse.quote(sanitizar_endereco(parada_alvo.get('endereco'), parada_alvo.get('cep')))
        url = f"https://waze.com/ul?q={end_enc}&navigate=yes"
    return {'url': url, 'parada': parada_alvo}

def gerar_url_google_maps(paradas, motorista_pos=None, indice_segmento=0):
    paradas_pendentes = [p for p in paradas if p.get('selecionada', True) and not p.get('concluida', False)]
    if not paradas_pendentes:
        return None

    total_pendentes = len(paradas_pendentes)
    total_segmentos = math.ceil(total_pendentes / LIMITE_SEGMENTO_GOOGLE)
    if indice_segmento >= total_segmentos:
        indice_segmento = 0

    inicio = indice_segmento * LIMITE_SEGMENTO_GOOGLE
    fim = min(inicio + LIMITE_SEGMENTO_GOOGLE, total_pendentes)
    lote = paradas_pendentes[inicio:fim]

    def formatar_ponto(p):
        lat = p.get('latitude')
        lng = p.get('longitude')
        if coord_valida(lat, lng):
            return f"{lat},{lng}"
        return urllib.parse.quote(sanitizar_endereco(p.get('endereco'), p.get('cep')))

    origin_param = ""
    if motorista_pos and coord_valida(motorista_pos.get('lat'), motorista_pos.get('lng')):
        origin_param = f"{motorista_pos['lat']},{motorista_pos['lng']}"

    if len(lote) == 1:
        dest_param = formatar_ponto(lote[0])
        waypoints_param = ""
    else:
        dest_param = formatar_ponto(lote[-1])
        intermediarios = lote[:-1]
        waypoints_param = "|".join(formatar_ponto(p) for p in intermediarios)

    url = "https://www.google.com/maps/dir/?api=1&travelmode=driving"
    if origin_param:
        url += f"&origin={origin_param}"
    if dest_param:
        url += f"&destination={dest_param}"
    if waypoints_param:
        url += f"&waypoints={waypoints_param}"

    return {
        'url': url,
        'segmento_index': indice_segmento,
        'total_segmentos': total_segmentos,
        'lote': lote,
        'total_pendentes': total_pendentes
    }


class TestRoteirizacaoManual(unittest.TestCase):

    def setUp(self):
        # 5 notas de teste no Rio de Janeiro
        self.notas_iniciais = [
            {'id': 1, 'numero': '1001', 'destinatario': 'Drogaria Rio Centro', 'endereco': 'Av Rio Branco, 100, Centro, RJ', 'cep': '20040-002', 'latitude': -22.9068, 'longitude': -43.1729, 'selecionada': True, 'concluida': False},
            {'id': 2, 'numero': '1002', 'destinatario': 'Farmácia Tijuca', 'endereco': 'Rua Conde de Bonfim, 300, Tijuca, RJ', 'cep': '20520-054', 'latitude': -22.9234, 'longitude': -43.2345, 'selecionada': True, 'concluida': False},
            {'id': 3, 'numero': '1003', 'destinatario': 'Drogaria Botafogo', 'endereco': 'Rua Voluntários da Pátria, 200, Botafogo, RJ', 'cep': '22270-010', 'latitude': -22.9510, 'longitude': -43.1840, 'selecionada': True, 'concluida': False},
            {'id': 4, 'numero': '1004', 'destinatario': 'Droga Raia Copacabana', 'endereco': 'Av N S de Copacabana, 500, Copacabana, RJ', 'cep': '22020-001', 'latitude': -22.9698, 'longitude': -43.1868, 'selecionada': True, 'concluida': False},
            {'id': 5, 'numero': '1005', 'destinatario': 'Drogaria Ipanema (Sem GPS)', 'endereco': 'Rua Visconde de Pirajá, 150, Ipanema, RJ', 'cep': '22410-000', 'latitude': None, 'longitude': None, 'selecionada': True, 'concluida': False},
        ]
        self.posicao_motorista = {'lat': -22.9000, 'lng': -43.1700}

    def test_01_estados_iniciais_e_apenas_uma_atual(self):
        paradas = [dict(n) for n in self.notas_iniciais]
        recalcular_estados_rota(paradas)

        self.assertEqual(paradas[0]['estado'], 'ATUAL', "Primeira nota deve ser ATUAL")
        self.assertEqual(paradas[0]['ordem'], 1)

        for p in paradas[1:]:
            self.assertEqual(p['estado'], 'PENDENTE', f"Nota {p['numero']} deve estar PENDENTE")

        atuais = [p for p in paradas if p['estado'] == 'ATUAL']
        self.assertEqual(len(atuais), 1, "Exatamente UMA nota pode ser ATUAL por vez")

    def test_02_reordenacao_manual_5_notas_sincronizacao(self):
        """
        Reordena manualmente as 5 notas: Move Nota 4 (Copacabana) para a primeira posição!
        Nova ordem: Nota 4, Nota 1, Nota 2, Nota 3, Nota 5.
        Verifica:
        - Lista e numeração (1..5)
        - Estado ATUAL transferido para a Nota 4
        - Waze apontando exatamente para Nota 4 com suas coordenadas
        - Google Maps respeitando a ordem exata (origem -> waypoints: 4, 1, 2, 3 -> destino: 5)
        """
        paradas = [dict(n) for n in self.notas_iniciais]
        # Driver arrasta o item 3 (Nota 4) para o índice 0
        item_movido = paradas.pop(3) # Nota 4 Copacabana
        paradas.insert(0, item_movido)

        recalcular_estados_rota(paradas)

        # 1. Numeração e Sequência
        self.assertEqual([p['numero'] for p in paradas], ['1004', '1001', '1002', '1003', '1005'])
        self.assertEqual([p['ordem'] for p in paradas], [1, 2, 3, 4, 5])

        # 2. Estados
        self.assertEqual(paradas[0]['estado'], 'ATUAL')
        self.assertEqual(paradas[0]['numero'], '1004')
        for p in paradas[1:]:
            self.assertEqual(p['estado'], 'PENDENTE')

        # 3. Waze
        waze_res = gerar_url_waze(paradas)
        self.assertIsNotNone(waze_res)
        self.assertEqual(waze_res['parada']['numero'], '1004')
        self.assertIn("ll=-22.9698,-43.1868", waze_res['url'], "Waze deve enviar coordenadas exatas da Nota 1004")

        # 4. Google Maps
        gmaps_res = gerar_url_google_maps(paradas, self.posicao_motorista)
        self.assertIsNotNone(gmaps_res)
        url = gmaps_res['url']
        # Waypoints devem ser: 1004 (-22.9698,-43.1868) | 1001 (-22.9068,-43.1729) | 1002 (-22.9234,-43.2345) | 1003 (-22.951,-43.184)
        # Destino deve ser: 1005 (endereço sanitizado porque lat/lng é None)
        self.assertIn("origin=-22.9,-43.17", url)
        self.assertIn("-22.9698,-43.1868|-22.9068,-43.1729|-22.9234,-43.2345|-22.951,-43.184", url)
        self.assertIn("destination=", url)

    def test_03_baixa_avanco_automatico_e_promocao_proxima(self):
        """
        Após a entrega da nota ATUAL (1004):
        - Nota 1004 marcada como CONCLUIDA
        - Nota seguinte (1001) promovida automaticamente para ATUAL
        - Waze atualizado para apontar para a Nota 1001
        """
        paradas = [dict(n) for n in self.notas_iniciais]
        # Reordena para 1004 primeiro
        item_movido = paradas.pop(3)
        paradas.insert(0, item_movido)
        recalcular_estados_rota(paradas)

        # Simula baixa da nota 1004
        paradas[0]['concluida'] = True
        recalcular_estados_rota(paradas)

        self.assertEqual(paradas[0]['estado'], 'CONCLUIDA')
        self.assertEqual(paradas[1]['estado'], 'ATUAL', "Nota 1001 deve ser promovida para ATUAL")
        self.assertEqual(paradas[1]['numero'], '1001')
        self.assertEqual(paradas[2]['estado'], 'PENDENTE')

        # Waze agora deve apontar para 1001
        waze_res = gerar_url_waze(paradas)
        self.assertEqual(waze_res['parada']['numero'], '1001')
        self.assertIn("ll=-22.9068,-43.1729", waze_res['url'])

    def test_04_fallback_endereco_quando_sem_coordenadas(self):
        """
        Nota 1005 não possui latitude/longitude.
        Verifica se fallback usa endereço sanitizado no Waze e no Google Maps.
        """
        nota_sem_gps = {'id': 5, 'numero': '1005', 'destinatario': 'Drogaria Ipanema', 'endereco': 'Rua Visconde de Pirajá, 150, Ipanema, RJ', 'cep': '22410-000', 'latitude': None, 'longitude': None, 'selecionada': True, 'concluida': False, 'estado': 'ATUAL'}
        waze_res = gerar_url_waze([nota_sem_gps])
        self.assertIn("https://waze.com/ul?q=", waze_res['url'])
        self.assertIn("Visconde%20de%20Piraj", waze_res['url'])

        gmaps_res = gerar_url_google_maps([nota_sem_gps])
        self.assertIn("destination=Rua%20Visconde%20de%20Piraj", gmaps_res['url'])

    def test_05_estrategia_segmentos_google_maps_mais_de_10_paradas(self):
        """
        Cria 15 notas para testar segmentação do Google Maps:
        - Segmento 0: Paradas 1 a 10
        - Segmento 1: Paradas 11 a 15
        Nenhuma nota deve ser descartada, e a sequência original deve ser 100% mantida.
        """
        quinze_notas = []
        for i in range(1, 16):
            quinze_notas.append({
                'id': i,
                'numero': f"NF_{i:02d}",
                'destinatario': f"Cliente {i}",
                'endereco': f"Rua Teste {i}, Rio de Janeiro, RJ",
                'cep': '20000-000',
                'latitude': -22.9000 - (i * 0.005),
                'longitude': -43.1700 - (i * 0.005),
                'selecionada': True,
                'concluida': False
            })

        recalcular_estados_rota(quinze_notas)

        # Trecho 1
        seg1 = gerar_url_google_maps(quinze_notas, indice_segmento=0)
        self.assertEqual(seg1['total_segmentos'], 2)
        self.assertEqual(len(seg1['lote']), 10)
        self.assertEqual(seg1['lote'][0]['numero'], 'NF_01')
        self.assertEqual(seg1['lote'][-1]['numero'], 'NF_10')

        # Trecho 2
        seg2 = gerar_url_google_maps(quinze_notas, indice_segmento=1)
        self.assertEqual(len(seg2['lote']), 5)
        self.assertEqual(seg2['lote'][0]['numero'], 'NF_11')
        self.assertEqual(seg2['lote'][-1]['numero'], 'NF_15')

        # Conclusão dos 10 primeiros
        for i in range(10):
            quinze_notas[i]['concluida'] = True
        recalcular_estados_rota(quinze_notas)

        # Agora restam 5 pendentes -> cabe em 1 único segmento de 5 paradas
        seg_restante = gerar_url_google_maps(quinze_notas, indice_segmento=0)
        self.assertEqual(seg_restante['total_segmentos'], 1)
        self.assertEqual(len(seg_restante['lote']), 5)
        self.assertEqual(seg_restante['lote'][0]['numero'], 'NF_11')
        self.assertEqual(quinze_notas[10]['estado'], 'ATUAL')


if __name__ == '__main__':
    unittest.main()
