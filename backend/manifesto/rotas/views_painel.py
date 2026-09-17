from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from manifesto.models import Manifesto
from usuarios.models import Filial, Motorista
from django.db.models import Count, Q


def _higienizar_filiais_duplicadas():
    """
    Higieniza automaticamente filiais criadas indevidamente com razão social longa do TMS
    ou com CNPJ gravado na coluna id_filial_tms (ex: RD EXPRESSO TRANSPORTES - EIRELI com id_filial_tms=14977687000124).
    Re-vincula manifestos, motoristas e logs na filial oficial cadastrada e remove as duplicatas.
    """
    try:
        from usuarios.models import Filial, Motorista
        from manifesto.models import Manifesto
        from django.db.models import Q
        import re

        FILIAIS_OFICIAIS = [
            {
                'nome': 'RD EXPRESSO',
                'id_filial_tms': '237988',
                'cnpj': '14977687000124',
                'dups_query': (
                    Q(nome__icontains='RD EXPRESSO TRANSPORTES') |
                    Q(id_filial_tms='14977687000124') |
                    (Q(nome__icontains='RD EXPRESSO') & ~Q(nome='RD EXPRESSO'))
                )
            },
            {
                'nome': 'QUICK SAO PAULO',
                'id_filial_tms': '237978',
                'cnpj': '14539546000120',
                'dups_query': (
                    Q(nome__icontains='QUICK DELIVERY SAO PAULO') |
                    Q(id_filial_tms='14539546000120') |
                    (Q(nome__icontains='SAO PAULO') & ~Q(nome='QUICK SAO PAULO'))
                )
            },
            {
                'nome': 'QUICK BRASILIA',
                'id_filial_tms': '237973',
                'cnpj': '08296144000149,08296144000734',
                'dups_query': (
                    Q(nome__icontains='QUICK DELIVERY BRASILIA') |
                    Q(id_filial_tms__in=['08296144000149', '08296144000734']) |
                    (Q(nome__icontains='BRASILIA') & ~Q(nome='QUICK BRASILIA'))
                )
            },
            {
                'nome': 'QUICK GOIANIA',
                'id_filial_tms': '237974',
                'cnpj': None,
                'dups_query': (
                    (Q(nome__icontains='GOIANIA') & ~Q(nome='QUICK GOIANIA'))
                )
            },
        ]

        for conf in FILIAIS_OFICIAIS:
            nome_oficial = conf['nome']
            id_tms_oficial = conf['id_filial_tms']
            cnpj_oficial = conf['cnpj']
            dups_query = conf['dups_query']

            # 1. Encontra a filial oficial
            oficial = Filial.objects.filter(nome__iexact=nome_oficial).first()
            if not oficial and id_tms_oficial:
                oficial = Filial.objects.filter(id_filial_tms=id_tms_oficial).first()
            if not oficial and cnpj_oficial:
                cnpjs_lista = [c.strip() for c in cnpj_oficial.split(',') if c.strip()]
                for c in cnpjs_lista:
                    oficial = Filial.objects.filter(cnpj__icontains=c).first()
                    if oficial:
                        break

            if not oficial:
                continue

            # Garante que dados oficiais estejam corretos
            campos = []
            if oficial.nome != nome_oficial:
                oficial.nome = nome_oficial
                campos.append('nome')
            if id_tms_oficial and oficial.id_filial_tms != id_tms_oficial:
                oficial.id_filial_tms = id_tms_oficial
                campos.append('id_filial_tms')
            if cnpj_oficial:
                if not oficial.cnpj or cnpj_oficial not in oficial.cnpj:
                    oficial.cnpj = cnpj_oficial
                    campos.append('cnpj')
            if not oficial.operacao_ativa:
                oficial.operacao_ativa = True
                campos.append('operacao_ativa')
            if campos:
                oficial.save(update_fields=campos)

            # 2. Encontra e mescla duplicatas
            duplicatas = Filial.objects.filter(dups_query).exclude(id=oficial.id)
            for d in duplicatas:
                # Copia dados cadastrais úteis se a oficial não possuir
                update_oficial = []
                for attr in ['cidade', 'uf', 'cep', 'logradouro', 'numero', 'bairro', 'latitude', 'longitude', 'whatsapp_operacional', 'whatsapp_sac']:
                    if not getattr(oficial, attr) and getattr(d, attr):
                        setattr(oficial, attr, getattr(d, attr))
                        update_oficial.append(attr)
                if update_oficial:
                    oficial.save(update_fields=update_oficial)

                # Re-vincula tudo para a filial oficial
                Manifesto.objects.filter(filial=d).update(filial=oficial)
                Manifesto.objects.filter(filial_operacao=d).update(filial_operacao=oficial)
                Motorista.objects.filter(filial=d).update(filial=oficial)
                try:
                    from sac_mobile.models import LogRebuscaFilial
                    LogRebuscaFilial.objects.filter(filial=d).update(filial=oficial)
                except Exception:
                    pass
                try:
                    from suporte.models import TicketSuporte
                    TicketSuporte.objects.filter(filial=d).update(filial=oficial)
                except Exception:
                    pass
                try:
                    from mobile.models import Notificacao
                    Notificacao.objects.filter(filial=d).update(filial=oficial)
                except Exception:
                    pass
                d.delete()
    except Exception:
        pass


@login_required(login_url='/login/')
def painel_monitoramento(request):
    hoje = timezone.now().date()
    _higienizar_filiais_duplicadas()

    try:
        from manifesto.services import sincronizar_manifestos_webhook_divergentes
        sincronizar_manifestos_webhook_divergentes()
    except Exception:
        pass

    # 1. Identificar a filial do usuário logado (se houver perfil)
    usuario_filial = None
    if request.user.is_authenticated:
        try:
            perfil = getattr(request.user, 'motorista_perfil', None) or Motorista.objects.select_related('filial').filter(user=request.user).first()
            if perfil:
                usuario_filial = perfil.filial
        except Exception:
            pass

    # 2. Carregar todas as filiais cadastradas com contagem de manifestos ativos (em transporte + aguardando)
    #    Usa filial_operacao (base física) com fallback para filial (fiscal)
    from datetime import timedelta
    limite_48h = timezone.now() - timedelta(hours=48)

    filiais_qs = Filial.objects.filter(operacao_ativa=True).order_by('nome')
    filiais_data = []
    for f in filiais_qs:
        total_ativos = Manifesto.objects.filter(
            Q(filial_operacao=f) | (Q(filial_operacao__isnull=True) & Q(filial=f)),
            status__in=['AGUARDANDO', 'EM_TRANSPORTE']
        ).exclude(
            status='AGUARDANDO', data_criacao__lt=limite_48h
        ).count()
        filiais_data.append({
            'id': f.id,
            'nome': f.nome,
            'total_ativos': total_ativos,
        })

    # 3. Definir qual filial inicia ativa (Prioridade: URL param -> Filial do Usuário -> 1ª Filial da lista)
    filial_param_id = request.GET.get('filial')
    filial_ativa_id = None
    
    if filial_param_id and filial_param_id.isdigit():
        filial_ativa_id = int(filial_param_id)
    elif usuario_filial:
        filial_ativa_id = usuario_filial.id
    elif filiais_data:
        filial_ativa_id = filiais_data[0]['id']

    # 4. Busca todos os manifestos ativos (AGUARDANDO e EM_TRANSPORTE) de todas as filiais
    manifestos = Manifesto.objects.filter(
        status__in=['AGUARDANDO', 'EM_TRANSPORTE']
    ).select_related('motorista', 'filial', 'filial_operacao', 'veiculo').prefetch_related(
        'notas_fiscais'
    ).annotate(
        total_nfe=Count('notas_fiscais', distinct=True),
        baixadas=Count('notas_fiscais', filter=Q(notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA']), distinct=True),
        total_ilegivel=Count('notas_fiscais__baixa_info', filter=Q(notas_fiscais__baixa_info__solicitar_nova_foto=True), distinct=True),
        calc_entrega=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='ENTREGA'), distinct=True),
        calc_coleta=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='COLETA'), distinct=True),
        calc_transf=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='TRANSFERENCIA'), distinct=True),
        calc_despacho=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='DESPACHO'), distinct=True),
        calc_retirada=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='RETIRADA'), distinct=True),
    ).order_by('status', 'filial', 'motorista__user__first_name')

    # 4.1 Processamento proativo no Backend:
    manifestos_ativos = []
    for m in manifestos:
        # A. Limpeza proativa de manifestos em AGUARDANDO há mais de 48h
        if m.status == 'AGUARDANDO' and m.data_criacao and m.data_criacao < limite_48h:
            try:
                m.status = 'CANCELADO'
                m.finalizado = True
                m.data_finalizacao = timezone.now()
                m.save(update_fields=['status', 'finalizado', 'data_finalizacao'])
                from manifesto.services import enviar_painel
                enviar_painel(m)
            except Exception:
                pass
            continue  # Expirado e cancelado! Sai da grade ativa da torre

        # B. Auto-finalização proativa de manifestos 100% concluídos:
        if m.total_nfe > 0 and m.baixadas >= m.total_nfe and m.total_ilegivel == 0:
            try:
                from manifesto.services import tentar_autofinalizar_manifesto
                sucesso, _ = tentar_autofinalizar_manifesto(m)
                if sucesso:
                    continue  # Foi finalizado com sucesso! Sai da grade de viagens ativas
            except Exception:
                pass

        # C. Contagens oficiais de Carga (ESL Style):
        if m.total_nfe > 0:
            c_ent = m.calc_entrega or 0
            c_col = m.calc_coleta or 0
            c_tra = m.calc_transf or 0
            c_des = m.calc_despacho or 0
            c_ret = m.calc_retirada or 0
            if c_ent == 0 and c_col == 0 and c_tra == 0 and c_des == 0 and c_ret == 0:
                c_ent = m.total_nfe
        else:
            c_ent = m.qtd_entrega or 0
            c_col = m.qtd_coleta or 0
            c_tra = m.qtd_transferencia or 0
            c_des = m.qtd_despacho or 0
            c_ret = m.qtd_retirada or 0
        m.count_entrega = c_ent
        m.count_coleta = c_col
        m.count_transferencia = c_tra
        m.count_despacho = c_des
        m.count_retirada = c_ret

        manifestos_ativos.append(m)
    manifestos = manifestos_ativos

    context = {
        'manifestos': manifestos,
        'filiais': filiais_data,
        'filial_ativa_id': filial_ativa_id,
        'hoje': hoje,
        'titulo': 'Torre de Controle Live',
        'usuario_nome': request.user.get_full_name() or request.user.username,
        'filial_selecionada': 'todas', # Conecta o socket ao grupo geral para escutar todas as filiais
    }
    return render(request, 'desktop/paginas/painel/monitoramento.html', context)


@login_required(login_url='/login/')
def painel_sync(request):
    """
    Endpoint leve de reconciliação para a Torre de Controle Live.
    Retorna JSON com todos os manifestos ativos (AGUARDANDO + EM_TRANSPORTE)
    para que o frontend possa remover cards fantasma e criar cards novos
    quando o navegador volta de standby ou após perda de conexão WebSocket.
    """
    from datetime import timedelta
    from django.http import JsonResponse
    from django.utils.timezone import localtime
    from manifesto.models import BaixaNF

    limite_48h = timezone.now() - timedelta(hours=48)

    manifestos = Manifesto.objects.filter(
        status__in=['AGUARDANDO', 'EM_TRANSPORTE']
    ).select_related('motorista', 'filial', 'filial_operacao', 'veiculo').prefetch_related(
        'notas_fiscais'
    ).annotate(
        total_nfe=Count('notas_fiscais', distinct=True),
        baixadas=Count('notas_fiscais', filter=Q(notas_fiscais__status__in=['BAIXADA', 'OCORRENCIA']), distinct=True),
        total_ilegivel=Count('notas_fiscais__baixa_info', filter=Q(notas_fiscais__baixa_info__solicitar_nova_foto=True), distinct=True),
        calc_entrega=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='ENTREGA'), distinct=True),
        calc_coleta=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='COLETA'), distinct=True),
        calc_transf=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='TRANSFERENCIA'), distinct=True),
        calc_despacho=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='DESPACHO'), distinct=True),
        calc_retirada=Count('notas_fiscais', filter=Q(notas_fiscais__tipo_operacao='RETIRADA'), distinct=True),
    )

    resultado = []
    for m in manifestos:
        # Exclui manifestos AGUARDANDO com mais de 48h (serão cancelados proativamente)
        if m.status == 'AGUARDANDO' and m.data_criacao and m.data_criacao < limite_48h:
            continue

        filial_efetiva = m.filial_operacao or m.filial
        porcentagem = int((m.baixadas / m.total_nfe) * 100) if m.total_nfe else 0

        # Data de criação para análise de manifesto antigo
        data_criacao_iso = m.data_criacao.isoformat() if m.data_criacao else None
        ultimo_acesso_iso = localtime(m.ultimo_acesso).isoformat() if m.ultimo_acesso else None

        # Calcula se é antigo (>12h para alerta, >24h para vermelho)
        horas_criado = (timezone.now() - m.data_criacao).total_seconds() / 3600 if m.data_criacao else 0
        is_viagem = getattr(m, 'is_viagem', False)

        # Contagens de cargas/operações
        if m.total_nfe > 0:
            c_ent = m.calc_entrega or 0
            c_col = m.calc_coleta or 0
            c_tra = m.calc_transf or 0
            c_des = m.calc_despacho or 0
            c_ret = m.calc_retirada or 0
            if c_ent == 0 and c_col == 0 and c_tra == 0 and c_des == 0 and c_ret == 0:
                c_ent = m.total_nfe
        else:
            c_ent = m.qtd_entrega or 0
            c_col = m.qtd_coleta or 0
            c_tra = m.qtd_transferencia or 0
            c_des = m.qtd_despacho or 0
            c_ret = m.qtd_retirada or 0

        resultado.append({
            'manifesto_id': str(m.numero_manifesto),
            'status': m.status,
            'filial_id': str(filial_efetiva.id) if filial_efetiva else '',
            'filial_nome': filial_efetiva.nome if filial_efetiva else 'Sem Filial',
            'motorista_id': str(m.motorista.id) if m.motorista else '',
            'motorista_nome': m.motorista.nome_completo if m.motorista else 'Desconhecido',
            'motorista_categoria': m.motorista.categoria if (m.motorista and m.motorista.categoria) else 'EMPRESA',
            'foto_motorista': m.motorista.foto_perfil.url if (m.motorista and m.motorista.foto_perfil) else None,
            'icone_dispositivo': m.motorista.icone_dispositivo_html if m.motorista else '',
            'placa_veiculo': m.veiculo.placa if (m.veiculo and m.veiculo.placa) else None,
            'tipo_veiculo': m.veiculo.tipo if (m.veiculo and m.veiculo.tipo) else None,
            'baixadas': m.baixadas,
            'total': m.total_nfe,
            'porcentagem': porcentagem,
            'total_ilegivel': m.total_ilegivel,
            'data_criacao_iso': data_criacao_iso,
            'ultimo_acesso_iso': ultimo_acesso_iso,
            'data_registro': localtime(m.data_criacao).strftime('%d/%m/%Y %H:%M') if m.data_criacao else '',
            'is_antigo': horas_criado >= 12 and not is_viagem,
            'dias_criado': int(horas_criado / 24),
            'is_viagem': is_viagem,
            'uf_destino_viagem': getattr(m, 'uf_destino_viagem', '') or '',
            'qtd_entrega': c_ent,
            'qtd_coleta': c_col,
            'qtd_transferencia': c_tra,
            'qtd_despacho': c_des,
            'qtd_retirada': c_ret,
        })

    # Contagem de ativos por filial
    filiais_count = {}
    for item in resultado:
        fid = item['filial_id']
        if fid:
            filiais_count[fid] = filiais_count.get(fid, 0) + 1

    return JsonResponse({
        'manifestos_ativos': resultado,
        'filiais_count': filiais_count,
        'timestamp': timezone.now().isoformat(),
    })