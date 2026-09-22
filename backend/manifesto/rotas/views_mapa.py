# manifesto/rotas/views_mapa.py
"""
=================================================================
 MAPA DE MONITORAMENTO EM TEMPO REAL
 Página fullscreen com mapa Leaflet + sidebar flutuante
=================================================================
 - View principal: renderiza página HTML do mapa
 - API veículos: posições de todos os veículos ativos
 - API rota: detalhamento da rota de um manifesto específico
=================================================================
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import localtime
from django.db.models import Count, Q
from datetime import timedelta

from manifesto.models import Manifesto, NotaFiscal, BaixaNF
from usuarios.models import Filial, Motorista


def _coordenadas_validas_brasil(lat, lng):
    """Valida se as coordenadas estão dentro do território brasileiro."""
    if lat is None or lng is None:
        return False
    try:
        lat = float(lat)
        lng = float(lng)
    except (ValueError, TypeError):
        return False
    if lat == 0 and lng == 0:
        return False
    return -34.0 <= lat <= 5.5 and -74.0 <= lng <= -34.0


@login_required(login_url='/login/')
def mapa_monitoramento(request):
    """Renderiza a página fullscreen do mapa de monitoramento."""
    # Identificar filial do usuário logado (com fallback)
    usuario_filial = None
    if request.user.is_authenticated:
        try:
            perfil = getattr(request.user, 'motorista_perfil', None) or Motorista.objects.select_related('filial').filter(user=request.user).first()
            if perfil and perfil.filial:
                usuario_filial = perfil.filial
        except Exception:
            pass

    # Filiais ativas
    filiais_qs = Filial.objects.filter(operacao_ativa=True).order_by('nome')
    filiais_data = []
    for f in filiais_qs:
        lat_val = str(f.latitude).replace(',', '.') if f.latitude else ''
        lng_val = str(f.longitude).replace(',', '.') if f.longitude else ''
        filiais_data.append({
            'id': f.id,
            'nome': f.nome,
            'lat': lat_val,
            'lng': lng_val,
        })

    # Filial ativa inicial
    filial_param_id = request.GET.get('filial')
    filial_ativa_id = None

    if filial_param_id and filial_param_id.isdigit():
        filial_ativa_id = int(filial_param_id)
    elif usuario_filial:
        filial_ativa_id = usuario_filial.id
    elif filiais_data:
        filial_ativa_id = filiais_data[0]['id']

    # Lat/lng da filial ativa para centralizar o mapa
    centro_lat = "-22.9"
    centro_lng = "-43.2"
    for f in filiais_data:
        if f['id'] == filial_ativa_id and f['lat'] and f['lng']:
            centro_lat = f['lat']
            centro_lng = f['lng']
            break

    context = {
        'titulo': 'Mapa de Monitoramento',
        'usuario_nome': request.user.get_full_name() or request.user.username,
        'filiais': filiais_data,
        'filial_ativa_id': filial_ativa_id,
        'centro_lat': str(centro_lat).replace(',', '.'),
        'centro_lng': str(centro_lng).replace(',', '.'),
    }
    return render(request, 'desktop/paginas/painel/mapa_monitoramento.html', context)


@login_required(login_url='/login/')
def api_mapa_veiculos(request):
    """
    Retorna JSON com posições de todos os veículos ativos (manifestos em transporte).
    Filtro opcional por filial via ?filial=ID
    Compatível com django_tenants (executa no schema do tenant corrente).
    """
    filial_id = request.GET.get('filial')
    limite_48h = timezone.now() - timedelta(hours=48)

    qs = Manifesto.objects.filter(
        status__in=['AGUARDANDO', 'EM_TRANSPORTE']
    ).select_related(
        'motorista', 'filial', 'filial_operacao', 'veiculo'
    ).annotate(
        total_nfe=Count('notas_fiscais', distinct=True),
        baixadas=Count('notas_fiscais', filter=Q(
            notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA']
        ), distinct=True),
    ).exclude(
        status='AGUARDANDO', data_criacao__lt=limite_48h
    )

    if filial_id and str(filial_id).isdigit():
        fid = int(filial_id)
        qs = qs.filter(
            Q(filial_operacao_id=fid) |
            (Q(filial_operacao__isnull=True) & Q(filial_id=fid))
        )

    veiculos = []
    for m in qs:
        lat = m.ultima_lat
        lng = m.ultima_lng

        # Se não tem GPS gravado no manifesto, tenta obter do motorista
        if not _coordenadas_validas_brasil(lat, lng) and m.motorista:
            lat = m.motorista.ultima_lat
            lng = m.motorista.ultima_lng

        tipo_veiculo = 'OUTRO'
        placa = ''
        if m.veiculo:
            tipo_veiculo = m.veiculo.tipo or 'OUTRO'
            placa = m.veiculo.placa or ''

        filial_efetiva = m.filial_operacao or m.filial
        ultimo_acesso_str = ''
        if m.ultimo_acesso:
            ultimo_acesso_str = localtime(m.ultimo_acesso).strftime('%H:%M')

        foto_motorista = None
        if m.motorista and m.motorista.foto_perfil:
            try:
                foto_motorista = m.motorista.foto_perfil.url
            except Exception:
                foto_motorista = None

        veiculos.append({
            'manifesto_id': str(m.numero_manifesto),
            'motorista': m.motorista.nome_completo if m.motorista else 'Sem Motorista',
            'motorista_id': m.motorista.id if m.motorista else None,
            'foto_motorista': foto_motorista,
            'placa': placa,
            'tipo_veiculo': tipo_veiculo,
            'lat': float(lat) if _coordenadas_validas_brasil(lat, lng) else None,
            'lng': float(lng) if _coordenadas_validas_brasil(lat, lng) else None,
            'ultimo_acesso': ultimo_acesso_str,
            'ultimo_acesso_iso': m.ultimo_acesso.isoformat() if m.ultimo_acesso else None,
            'bateria': m.ultima_bateria,
            'rede': m.ultima_rede,
            'baixadas': m.baixadas,
            'total_nfe': m.total_nfe,
            'status': m.status,
            'filial_id': str(filial_efetiva.id) if filial_efetiva else '',
            'filial_nome': filial_efetiva.nome if filial_efetiva else '',
        })

    return JsonResponse({
        'veiculos': veiculos,
        'timestamp': timezone.now().isoformat(),
    })


@login_required(login_url='/login/')
def api_mapa_rota_manifesto(request, manifesto_id):
    """
    Retorna JSON com rota detalhada de um manifesto específico.
    Compatível com busca por numero_manifesto ou por pk.
    Inclui entregas realizadas (com lat/lng da baixa ou fallback NF) e pendentes (com lat/lng do destino NF).
    Compatível com django_tenants (executa no schema do tenant corrente).
    """
    manifesto = (
        Manifesto.objects.select_related(
            'filial', 'filial_operacao', 'motorista', 'motorista__filial', 'veiculo'
        )
        .filter(
            Q(numero_manifesto=manifesto_id) |
            (Q(id=int(manifesto_id)) if str(manifesto_id).isdigit() else Q(pk__isnull=True))
        )
        .first()
    )

    if not manifesto:
        return JsonResponse({'erro': 'Manifesto não encontrado'}, status=404)

    # Filial base (ponto de partida)
    filial_base = manifesto.filial_operacao
    if not filial_base or not filial_base.latitude or not filial_base.longitude:
        if manifesto.motorista and manifesto.motorista.filial:
            mot_filial = manifesto.motorista.filial
            if mot_filial.latitude and mot_filial.longitude:
                filial_base = mot_filial
        if not filial_base or not filial_base.latitude or not filial_base.longitude:
            if manifesto.filial and manifesto.filial.latitude and manifesto.filial.longitude:
                filial_base = manifesto.filial

    dados_filial = {
        'nome': filial_base.nome if filial_base else "Base",
        'lat': float(filial_base.latitude) if (filial_base and filial_base.latitude) else -22.7873755,
        'lng': float(filial_base.longitude) if (filial_base and filial_base.longitude) else -43.2886202,
    }

    # Posição atual do motorista
    posicao_atual = None
    lat_atual = manifesto.ultima_lat
    lng_atual = manifesto.ultima_lng
    if not _coordenadas_validas_brasil(lat_atual, lng_atual) and manifesto.motorista:
        lat_atual = manifesto.motorista.ultima_lat
        lng_atual = manifesto.motorista.ultima_lng

    if _coordenadas_validas_brasil(lat_atual, lng_atual):
        posicao_atual = {
            'lat': float(lat_atual),
            'lng': float(lng_atual),
            'battery': manifesto.ultima_bateria,
            'network': manifesto.ultima_rede,
            'last_seen': localtime(manifesto.ultimo_acesso).strftime('%H:%M') if manifesto.ultimo_acesso else None,
            'last_seen_iso': manifesto.ultimo_acesso.isoformat() if manifesto.ultimo_acesso else None,
        }

    # Tipo de veículo
    tipo_veiculo = 'OUTRO'
    placa = ''
    if manifesto.veiculo:
        tipo_veiculo = manifesto.veiculo.tipo or 'OUTRO'
        placa = manifesto.veiculo.placa or ''

    # Entregas realizadas (BAIXADA ou OCORRENCIA)
    entregas_realizadas = []
    notas_baixadas = manifesto.notas_fiscais.filter(
        status__in=['BAIXADA', 'OCORRENCIA']
    ).prefetch_related('baixa_info')

    for nf in notas_baixadas:
        baixas = list(nf.baixa_info.all())
        baixas.sort(key=lambda b: b.data_baixa or timezone.now(), reverse=True)
        baixa = baixas[0] if baixas else None

        lat_b = None
        lng_b = None
        horario = ''
        data_hora = ''
        tipo_baixa = 'ENTREGA' if nf.status == 'BAIXADA' else 'OCORRENCIA'

        if baixa:
            lat_b = float(baixa.latitude) if baixa.latitude else None
            lng_b = float(baixa.longitude) if baixa.longitude else None
            horario = localtime(baixa.data_baixa).strftime('%H:%M') if baixa.data_baixa else ''
            data_hora = localtime(baixa.data_baixa).strftime('%d/%m %H:%M') if baixa.data_baixa else ''
            tipo_baixa = baixa.tipo or tipo_baixa

        # Fallback: se a baixa não tem coordenadas GPS válidas, usa o destino da NF
        if not _coordenadas_validas_brasil(lat_b, lng_b):
            lat_b = float(nf.latitude) if nf.latitude else None
            lng_b = float(nf.longitude) if nf.longitude else None

        entregas_realizadas.append({
            'nota': nf.numero_nota,
            'destinatario': nf.destinatario or '',
            'endereco': nf.endereco_entrega or '',
            'lat': lat_b if _coordenadas_validas_brasil(lat_b, lng_b) else None,
            'lng': lng_b if _coordenadas_validas_brasil(lat_b, lng_b) else None,
            'horario': horario,
            'data_hora': data_hora,
            'tipo_baixa': tipo_baixa,
            'status': nf.status,
            'ordem_ts': baixa.data_baixa.timestamp() if (baixa and baixa.data_baixa) else 0,
        })

    # Ordena entregas realizadas pela data/hora da baixa
    entregas_realizadas.sort(key=lambda x: x['ordem_ts'])

    # Entregas pendentes (PENDENTE) — usa lat/lng da NotaFiscal (destino da entrega)
    entregas_pendentes = []
    notas_pendentes = manifesto.notas_fiscais.filter(
        status='PENDENTE'
    ).order_by('id')

    for nf in notas_pendentes:
        lat_nf = float(nf.latitude) if nf.latitude else None
        lng_nf = float(nf.longitude) if nf.longitude else None

        entregas_pendentes.append({
            'nota': nf.numero_nota,
            'destinatario': nf.destinatario or '',
            'endereco': nf.endereco_entrega or '',
            'lat': lat_nf if _coordenadas_validas_brasil(lat_nf, lng_nf) else None,
            'lng': lng_nf if _coordenadas_validas_brasil(lat_nf, lng_nf) else None,
            'status': nf.status,
        })

    # Contagens
    total_nfe = manifesto.notas_fiscais.count()
    total_baixadas = len(entregas_realizadas)
    total_pendentes = len(entregas_pendentes)

    return JsonResponse({
        'manifesto_id': str(manifesto.numero_manifesto),
        'motorista': manifesto.motorista.nome_completo if manifesto.motorista else 'Sem Motorista',
        'placa': placa,
        'tipo_veiculo': tipo_veiculo,
        'status': manifesto.status,
        'filial': dados_filial,
        'posicao_atual': posicao_atual,
        'entregas_realizadas': entregas_realizadas,
        'entregas_pendentes': entregas_pendentes,
        'total_nfe': total_nfe,
        'total_baixadas': total_baixadas,
        'total_pendentes': total_pendentes,
    })
