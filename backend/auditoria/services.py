from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q, F
from manifesto.models import Manifesto, NotaFiscal, BaixaNF
from usuarios.models import Filial, Motorista


def calcular_metricas_manifesto(m, agora=None):
    """
    Calcula telemetria, cadência operacional, previsão de término (ETA),
    auditoria de IA e score de conformidade do motorista para o manifesto.
    """
    agora = agora or timezone.now()

    # 1. Hardware & Conexão
    bateria = m.ultima_bateria
    rede = m.ultima_rede
    ultimo_acesso = m.ultimo_acesso
    lat = m.ultima_lat
    lng = m.ultima_lng

    # Fallback para o cadastro do motorista se o manifesto não tiver telemetria específica
    if bateria is None and m.motorista:
        bateria = m.motorista.ultima_bateria
    if not rede and m.motorista:
        rede = m.motorista.ultima_rede
    if not ultimo_acesso and m.motorista:
        ultimo_acesso = m.motorista.ultimo_acesso
    if lat is None and m.motorista:
        lat = m.motorista.ultima_lat
    if lng is None and m.motorista:
        lng = m.motorista.ultima_lng

    minutos_sem_sinal = None
    horas_sem_sinal = None
    status_cor = 'success'
    status_texto = 'Sinal recente'

    if ultimo_acesso:
        diff_segundos = (agora - ultimo_acesso).total_seconds()
        minutos_sem_sinal = max(0, int(diff_segundos / 60))
        horas_sem_sinal = round(diff_segundos / 3600, 1)

        if minutos_sem_sinal <= 15:
            status_cor = 'success'
            status_texto = f'Sinal há {minutos_sem_sinal} min' if minutos_sem_sinal > 0 else 'Sinal agora'
        elif minutos_sem_sinal <= 60:
            status_cor = 'info'
            status_texto = f'Sinal há {minutos_sem_sinal} min'
        elif minutos_sem_sinal <= 240:
            status_cor = 'warning'
            status_texto = f'Sem sinal há {horas_sem_sinal}h'
        else:
            status_cor = 'danger'
            status_texto = f'CRÍTICO: Sem sinal há {int(horas_sem_sinal)}h'
    else:
        status_cor = 'secondary'
        status_texto = 'Sem telemetria'

    # 2. Breakdown de Notas e Tipos de Operação
    total_notas = getattr(m, 'total_notas', None)
    if total_notas is None:
        total_notas = m.notas_fiscais.count()

    notas_pendentes = getattr(m, 'notas_pendentes', None)
    if notas_pendentes is None:
        notas_pendentes = m.notas_fiscais.filter(status='PENDENTE').count()

    notas_baixadas = getattr(m, 'notas_baixadas', None)
    if notas_baixadas is None:
        notas_baixadas = m.notas_fiscais.filter(status__in=['BAIXADA', 'OCORRENCIA']).count()

    progresso = int((notas_baixadas / total_notas) * 100) if total_notas > 0 else 0

    # Contagem por tipo de operação no manifesto
    qtd_entrega = getattr(m, 'qtd_entrega', 0) or m.notas_fiscais.filter(tipo_operacao='ENTREGA').count()
    qtd_coleta = getattr(m, 'qtd_coleta', 0) or m.notas_fiscais.filter(tipo_operacao='COLETA').count()
    qtd_despacho = getattr(m, 'qtd_despacho', 0) or m.notas_fiscais.filter(tipo_operacao__in=['DESPACHO', 'TRANSFERENCIA']).count()

    # 3. Cadência Operacional (Ritmo) & Previsão de Término (ETA)
    inicio = m.data_criacao
    tempo_em_rota_horas = max(0.2, (agora - inicio).total_seconds() / 3600)
    ritmo_entregas_hora = round(notas_baixadas / tempo_em_rota_horas, 1) if notas_baixadas > 0 else 0.0

    eta_str = "--:--"
    if notas_pendentes == 0:
        eta_str = "Finalizado"
    elif ritmo_entregas_hora >= 0.3:
        horas_restantes = notas_pendentes / ritmo_entregas_hora
        if horas_restantes <= 24:
            eta_datetime = agora + timedelta(hours=horas_restantes)
            eta_str = eta_datetime.strftime('%H:%M')
        else:
            eta_str = "+24h"
    elif tempo_em_rota_horas >= 1.0 and notas_baixadas == 0:
        eta_str = "Atrasado (Sem baixas)"

    # 4. Auditoria de Qualidade da IA & Fotos
    baixas_qs = BaixaNF.objects.filter(nota_fiscal__manifesto=m)
    total_canhotos = baixas_qs.count()
    aprovados_ia = baixas_qs.filter(qualidade_canhoto__in=['APROVADO', 'APROVADO_MANUAL']).count()
    reprovados_ia = baixas_qs.filter(solicitar_nova_foto=True).count()
    em_analise_ia = baixas_qs.filter(qualidade_canhoto='PENDENTE_ANALISE').count()
    taxa_qualidade_ia = int((aprovados_ia / total_canhotos) * 100) if total_canhotos > 0 else 100

    # 5. Auditoria de Penalidades (Desleixo)
    penalidades_count = baixas_qs.filter(motivo_baixa='MOTORISTA_DESLEIXO').count()

    # 6. Score de Conformidade (0 a 100)
    score = 100

    # Penalização por falta de sinal
    if minutos_sem_sinal is not None:
        if minutos_sem_sinal > 240:
            score -= 30
        elif minutos_sem_sinal > 120:
            score -= 20
        elif minutos_sem_sinal > 45:
            score -= 10

    # Penalização por bateria baixa
    if bateria is not None:
        if bateria < 10:
            score -= 15
        elif bateria < 20:
            score -= 5

    # Penalização por fotos reprovadas / ilegíveis
    score -= min(25, reprovados_ia * 10)

    # Penalização severa por desleixo
    score -= (penalidades_count * 25)

    score = max(5, min(100, score))

    if score >= 90:
        score_badge = 'success'
        score_label = 'Excelente'
    elif score >= 75:
        score_badge = 'primary'
        score_label = 'Bom'
    elif score >= 60:
        score_badge = 'warning'
        score_label = 'Regular'
    else:
        score_badge = 'danger'
        score_label = 'Crítico'

    # Foto do perfil do motorista
    foto_url = None
    if m.motorista and m.motorista.foto_perfil:
        try:
            foto_url = m.motorista.foto_perfil.url
        except Exception:
            foto_url = None

    return {
        'obj': m,
        'motorista_nome': m.motorista.nome_completo if m.motorista else 'Não Identificado',
        'motorista_categoria': m.motorista.categoria if m.motorista else 'OUTROS',
        'motorista_telefone': m.motorista.telefone if m.motorista else '',
        'motorista_foto': foto_url,
        'placa': m.veiculo.placa if m.veiculo else '--',
        'filial_nome': m.filial_operacao.nome if m.filial_operacao else (m.filial.nome if m.filial else 'Matriz'),
        'filial_id': m.filial_operacao_id or (m.filial_id if m.filial else None),
        
        # Hardware
        'bateria': bateria,
        'rede': rede or '4G',
        'ultimo_acesso': ultimo_acesso,
        'minutos_sem_sinal': minutos_sem_sinal,
        'horas_sem_sinal': horas_sem_sinal,
        'status_cor': status_cor,
        'status_texto': status_texto,
        'lat': lat,
        'lng': lng,

        # Progresso & Tipos
        'total_notas': total_notas,
        'notas_pendentes': notas_pendentes,
        'notas_baixadas': notas_baixadas,
        'progresso': progresso,
        'qtd_entrega': qtd_entrega,
        'qtd_coleta': qtd_coleta,
        'qtd_despacho': qtd_despacho,

        # Cadência & ETA
        'tempo_em_rota_horas': round(tempo_em_rota_horas, 1),
        'ritmo_entregas_hora': ritmo_entregas_hora,
        'eta_str': eta_str,

        # Qualidade IA
        'total_canhotos': total_canhotos,
        'aprovados_ia': aprovados_ia,
        'reprovados_ia': reprovados_ia,
        'em_analise_ia': em_analise_ia,
        'taxa_qualidade_ia': taxa_qualidade_ia,
        'penalidades_count': penalidades_count,

        # Score
        'score': score,
        'score_badge': score_badge,
        'score_label': score_label,
    }


def gerar_benchmarking_filiais():
    """
    Gera as estatísticas de disputa e benchmarking entre todas as filiais.
    Compara entregas, coletas, eficiência, melhores e piores motoristas.
    """
    hoje = timezone.now().date()
    filiais = Filial.objects.all().order_by('nome')

    dados_filiais = []
    campeao_entregas = {'nome': '--', 'valor': 0}
    campeao_coletas = {'nome': '--', 'valor': 0}
    campeao_eficiencia = {'nome': '--', 'valor': 0}

    for f in filiais:
        # Manifestos da filial hoje (operacao ou fiscal)
        mfts = Manifesto.objects.filter(
            Q(filial_operacao=f) | (Q(filial_operacao__isnull=True) & Q(filial=f)),
            data_criacao__date=hoje
        )
        total_mfts = mfts.count()
        mfts_ativos = mfts.filter(status='EM_TRANSPORTE').count()
        mfts_concluidos = mfts.filter(status='FINALIZADO').count()

        # Notas vinculadas a esses manifestos
        nfs = NotaFiscal.objects.filter(manifesto__in=mfts)
        total_entregas = nfs.filter(tipo_operacao='ENTREGA').count()
        entregas_feitas = nfs.filter(tipo_operacao='ENTREGA', status__in=['BAIXADA', 'OCORRENCIA']).count()
        
        total_coletas = nfs.filter(tipo_operacao='COLETA').count()
        coletas_feitas = nfs.filter(tipo_operacao='COLETA', status__in=['BAIXADA', 'OCORRENCIA']).count()

        total_notas = total_entregas + total_coletas
        concluidas = entregas_feitas + coletas_feitas
        taxa_eficiencia = int((concluidas / total_notas) * 100) if total_notas > 0 else (100 if mfts_concluidos > 0 else 0)

        # Auditoria de Canhotos na Filial
        baixas = BaixaNF.objects.filter(nota_fiscal__in=nfs)
        canhotos_aprovados = baixas.filter(qualidade_canhoto__in=['APROVADO', 'APROVADO_MANUAL']).count()
        canhotos_reprovados = baixas.filter(solicitar_nova_foto=True).count()
        taxa_ia_filial = int((canhotos_aprovados / baixas.count()) * 100) if baixas.exists() else 100

        # Alertas críticos na filial
        criticos = mfts.filter(status='EM_TRANSPORTE', ultimo_acesso__lt=timezone.now() - timedelta(hours=4)).count()

        dados_f = {
            'id': f.id,
            'nome': f.nome,
            'total_manifestos': total_mfts,
            'ativos': mfts_ativos,
            'concluidos': mfts_concluidos,
            'total_entregas': total_entregas,
            'entregas_feitas': entregas_feitas,
            'total_coletas': total_coletas,
            'coletas_feitas': coletas_feitas,
            'taxa_eficiencia': taxa_eficiencia,
            'taxa_ia': taxa_ia_filial,
            'reprovados_ia': canhotos_reprovados,
            'criticos': criticos,
        }
        dados_filiais.append(dados_f)

        # Campeões
        if entregas_feitas > campeao_entregas['valor']:
            campeao_entregas = {'nome': f.nome, 'valor': entregas_feitas}
        if coletas_feitas > campeao_coletas['valor']:
            campeao_coletas = {'nome': f.nome, 'valor': coletas_feitas}
        if taxa_eficiencia > campeao_eficiencia['valor'] and total_notas >= 5:
            campeao_eficiencia = {'nome': f.nome, 'valor': taxa_eficiencia}

    # Ordena filiais por taxa de eficiência decrescente
    dados_filiais.sort(key=lambda x: (x['taxa_eficiencia'], x['entregas_feitas']), reverse=True)

    # Hall da Fama (Top 5 Motoristas de Maior Eficiência hoje)
    manifestos_ativos = Manifesto.objects.filter(status='EM_TRANSPORTE').select_related('motorista', 'filial', 'filial_operacao', 'veiculo')
    metricas_motoristas = [calcular_metricas_manifesto(m) for m in manifestos_ativos]

    hall_da_fama = sorted(
        [d for d in metricas_motoristas if d['total_notas'] > 0],
        key=lambda x: (x['score'], x['progresso'], x['ritmo_entregas_hora']),
        reverse=True
    )[:5]

    radar_atencao = sorted(
        [d for d in metricas_motoristas if d['total_notas'] > 0 and (d['score'] < 75 or d['status_cor'] in ['warning', 'danger'] or d['penalidades_count'] > 0)],
        key=lambda x: (x['score'], -x['minutos_sem_sinal'] if x['minutos_sem_sinal'] else 0)
    )[:5]

    return {
        'filiais': dados_filiais,
        'campeao_entregas': campeao_entregas,
        'campeao_coletas': campeao_coletas,
        'campeao_eficiencia': campeao_eficiencia,
        'hall_da_fama': hall_da_fama,
        'radar_atencao': radar_atencao,
    }


def obter_detalhes_360_manifesto(manifesto_id):
    """
    Retorna a ficha técnica 360º de um manifesto para o Drawer lateral,
    incluindo dados do motorista, veículo, telemetria viva e a timeline
    completa de todas as notas com canhotos inspecionáveis.
    """
    from django.db.models import Q
    manifesto = Manifesto.objects.filter(
        Q(id=str(manifesto_id)) | Q(numero_manifesto=str(manifesto_id))
    ).select_related('motorista', 'filial', 'filial_operacao', 'veiculo').first()

    if not manifesto:
        return None

    metricas = calcular_metricas_manifesto(manifesto)

    # Timeline de Notas
    notas_qs = manifesto.notas_fiscais.all().order_by('id')
    timeline_notas = []

    for nf in notas_qs:
        baixa = nf.baixa_info.all().last()
        item = {
            'id': nf.id,
            'numero_nota': nf.numero_nota,
            'chave_acesso': nf.chave_acesso or '',
            'destinatario': nf.destinatario,
            'endereco': nf.endereco_entrega,
            'cep': nf.cep or '',
            'tipo_operacao': nf.tipo_operacao,
            'status': nf.status,
            'ja_baixada': baixa is not None,
            'data_baixa': baixa.data_baixa.strftime('%d/%m %H:%M') if (baixa and baixa.data_baixa) else None,
            'ocorrencia_nome': baixa.ocorrencia.descricao if (baixa and baixa.ocorrencia) else None,
            'ocorrencia_codigo': baixa.ocorrencia.codigo_tms if (baixa and baixa.ocorrencia) else None,
            'recebedor': baixa.recebedor if baixa else None,
            'observacao': baixa.observacao if baixa else None,
            'motivo_baixa': baixa.motivo_baixa if baixa else None,
            'autor_baixa': baixa.autor_baixa.nome_completo if (baixa and baixa.autor_baixa) else None,
            'foto_url': baixa.comprovante_foto_url if baixa else None,
            'qualidade_canhoto': baixa.qualidade_canhoto if baixa else None,
            'solicitar_nova_foto': baixa.solicitar_nova_foto if baixa else False,
            'tentativa_foto': baixa.tentativa_foto if baixa else 1,
            'lat_baixa': float(baixa.latitude) if (baixa and baixa.latitude) else None,
            'lng_baixa': float(baixa.longitude) if (baixa and baixa.longitude) else None,
            'lat_destino': float(nf.latitude) if nf.latitude else None,
            'lng_destino': float(nf.longitude) if nf.longitude else None,
        }
        timeline_notas.append(item)

    metricas['timeline'] = timeline_notas
    metricas['total_itens_timeline'] = len(timeline_notas)
    return metricas
