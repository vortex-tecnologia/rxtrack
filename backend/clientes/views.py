# clientes/views.py
# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.db.models import Q, Count
from datetime import timedelta
import json

from .decorators import apenas_cliente
from .models import UsuarioCliente, VinculoPagador
from manifesto.models import NotaFiscal, Manifesto, BaixaNF, HistoricoOcorrencia, Frete


# ============================================================
# DASHBOARD PRINCIPAL DO PORTAL DO CLIENTE
# ============================================================

@login_required
@apenas_cliente
def portal_cliente_view(request):
    """
    Renderiza a dashboard principal do Portal do Cliente.
    Todos os dados são carregados via AJAX pela API api_cargas_cliente.
    """
    cliente = request.user.cliente_perfil

    # Atualiza último acesso
    cliente.ultimo_acesso = timezone.now()
    UsuarioCliente.objects.filter(pk=cliente.pk).update(ultimo_acesso=timezone.now())

    # Lista de pagadores vinculados (para exibir na sidebar)
    pagadores = list(
        cliente.vinculos.filter(ativo=True).values_list('pagador_nome', flat=True)
    )

    context = {
        'cliente_nome': cliente.nome_completo,
        'cliente_email': cliente.email,
        'pagadores': pagadores,
        'qtd_pagadores': len(pagadores),
    }

    return render(request, 'clientes/portal.html', context)


def get_filtro_cliente_qs(pagadores, pagador_filtro=None):
    """
    Constrói o filtro Q abrangente para capturar todas as operações do cliente:
    - Entregas onde ele é o pagador do frete ou remetente
    - Coletas onde ele é o solicitante/destinatário (tipo_operacao='COLETA')
    - Notas fiscais onde ele é o destinatário direto
    """
    alvos = [pagador_filtro] if pagador_filtro else pagadores
    filtro = Q()
    for p in alvos:
        if not p:
            continue
        p_clean = p.strip()
        filtro |= Q(frete__pagador_nome__iexact=p_clean)
        filtro |= Q(frete__remetente__iexact=p_clean)
        filtro |= Q(frete__pagador_nome__icontains=p_clean)
        filtro |= Q(frete__remetente__icontains=p_clean)
        filtro |= Q(tipo_operacao='COLETA', destinatario__icontains=p_clean)
        filtro |= Q(destinatario__iexact=p_clean)
        filtro |= Q(destinatario__icontains=p_clean)
    return filtro


def get_cargo_group_key(nota):
    """
    Retorna uma chave única para consolidar todas as pernas/manifestos da mesma carga:
    - NF-e com chave de acesso: 'CHAVE:<chave>'
    - Coleta: 'COLETA:<numero_coleta ou nota>:<destinatario>'
    - Outros: 'NF:<numero_nota>:<destinatario>'
    """
    chave = (nota.chave_acesso or '').strip()
    if chave and len(chave) >= 20:
        return f"CHAVE:{chave}"
    
    is_coleta = (nota.tipo_operacao == 'COLETA')
    if is_coleta:
        doc = (nota.numero_coleta or nota.numero_nota or str(nota.id)).strip()
        dest = (nota.destinatario or '').strip().upper()
        return f"COLETA:{doc}:{dest}"
    
    doc = (nota.numero_nota or str(nota.id)).strip()
    dest = (nota.destinatario or '').strip().upper()
    return f"NF:{doc}:{dest}"


def consolidar_etapas_carga(etapas):
    """
    Consolida uma lista de etapas (NotaFiscal) da mesma carga física/documento
    em um único objeto com o status real vigente e histórico completo.
    """
    if not etapas:
        return None
    
    # Ordena cronologicamente pela criação do manifesto (ou id)
    etapas_ordenadas = sorted(
        etapas, 
        key=lambda n: n.manifesto.data_criacao if (n.manifesto and n.manifesto.data_criacao) else timezone.now()
    )
    
    # Procura etapa ativa em transporte
    etapa_ativa = next(
        (n for n in reversed(etapas_ordenadas) 
         if n.status == 'PENDENTE' and n.manifesto and n.manifesto.status == 'EM_TRANSPORTE' and not n.manifesto.finalizado),
        None
    )
    # Procura etapa com ocorrência recente
    etapa_ocorrencia = next(
        (n for n in reversed(etapas_ordenadas) if n.status == 'OCORRENCIA'),
        None
    )
    # Procura etapa aguardando saída
    etapa_aguardando = next(
        (n for n in reversed(etapas_ordenadas) 
         if n.status == 'PENDENTE' and n.manifesto and n.manifesto.status == 'AGUARDANDO'),
        None
    )

    # Nota representativa para dados de cabeçalho
    if etapa_ativa:
        n_rep = etapa_ativa
    elif etapa_ocorrencia and not any(n.status == 'BAIXADA' for n in etapas_ordenadas[etapas_ordenadas.index(etapa_ocorrencia):]):
        n_rep = etapa_ocorrencia
    elif etapa_aguardando:
        n_rep = etapa_aguardando
    else:
        n_rep = etapas_ordenadas[-1]

    is_coleta = (n_rep.tipo_operacao == 'COLETA')
    numero_doc = n_rep.numero_coleta if (is_coleta and n_rep.numero_coleta) else n_rep.numero_nota

    # Filiais envolvidas
    filial_origem = ''
    if etapas_ordenadas[0].manifesto and etapas_ordenadas[0].manifesto.filial:
        filial_origem = etapas_ordenadas[0].manifesto.filial.nome

    filial_atual = ''
    if n_rep.manifesto and n_rep.manifesto.filial:
        filial_atual = n_rep.manifesto.filial.nome
    elif etapas_ordenadas[-1].manifesto and etapas_ordenadas[-1].manifesto.filial:
        filial_atual = etapas_ordenadas[-1].manifesto.filial.nome

    # Verifica se houve transferência operacional entre filiais
    tem_transferencia = (
        len(etapas_ordenadas) > 1 or 
        any(n.tipo_operacao in ['TRANSFERENCIA', 'DESPACHO'] for n in etapas_ordenadas) or
        (filial_origem and filial_atual and filial_origem != filial_atual)
    )

    # Determina o status consolidado
    data_saida = ''
    if n_rep.manifesto and n_rep.manifesto.data_criacao:
        data_saida = timezone.localtime(n_rep.manifesto.data_criacao).strftime('%d/%m/%Y %H:%M')
    elif etapas_ordenadas[0].manifesto and etapas_ordenadas[0].manifesto.data_criacao:
        data_saida = timezone.localtime(etapas_ordenadas[0].manifesto.data_criacao).strftime('%d/%m/%Y %H:%M')

    data_entrega = ''
    recebedor = ''
    observacao = ''
    comprovante_url = ''
    ocorrencia_desc = ''
    tipo_baixa = ''

    if etapa_ativa:
        status_code = 'em_rota'
        status_display = 'A Coletar' if is_coleta else 'Em Rota'
        status_class = 'primary'
    elif etapa_ocorrencia:
        status_code = 'ocorrencia'
        status_display = 'Ocorrência na Coleta' if is_coleta else 'Ocorrência'
        status_class = 'warning'
        baixa_oc = etapa_ocorrencia.baixa_info.all().last() if hasattr(etapa_ocorrencia, 'baixa_info') else None
        if baixa_oc and baixa_oc.ocorrencia:
            ocorrencia_desc = baixa_oc.ocorrencia.descricao
    elif n_rep.status == 'PENDENTE' and n_rep.manifesto and n_rep.manifesto.status == 'AGUARDANDO':
        status_code = 'aguardando'
        status_display = 'Solicitação Recebida' if is_coleta else 'Aguardando Saída'
        status_class = 'secondary'
    elif n_rep.status == 'BAIXADA':
        baixa_final = n_rep.baixa_info.all().last() if hasattr(n_rep, 'baixa_info') else None
        desc_oc = (baixa_final.ocorrencia.descricao or '').lower() if (baixa_final and baixa_final.ocorrencia) else ''
        is_baixa_transf = (
            n_rep.tipo_operacao in ['TRANSFERENCIA', 'DESPACHO'] or
            any(w in desc_oc for w in ['transferencia', 'despacho', 'redespacho', 'embarque'])
        )

        if is_baixa_transf and len(etapas_ordenadas) == 1:
            status_code = 'transferencia'
            status_display = 'Em Transferência'
            status_class = 'info'
        else:
            status_code = 'entregue'
            if is_coleta:
                status_display = 'Coleta Realizada'
            elif baixa_final and baixa_final.tipo == 'ENTREGA':
                status_display = 'Entregue'
            else:
                status_display = 'Concluída'
            status_class = 'success'

            if baixa_final:
                if baixa_final.data_baixa:
                    data_entrega = timezone.localtime(baixa_final.data_baixa).strftime('%d/%m/%Y %H:%M')
                recebedor = baixa_final.recebedor or ''
                observacao = baixa_final.observacao or ''
                tipo_baixa = baixa_final.tipo or ''
                if baixa_final.comprovante_foto_url:
                    comprovante_url = baixa_final.comprovante_foto_url
                elif baixa_final.comprovante_original_url:
                    comprovante_url = baixa_final.comprovante_original_url
                elif baixa_final.comprovante_foto:
                    comprovante_url = baixa_final.comprovante_foto.url
                if baixa_final.ocorrencia:
                    ocorrencia_desc = baixa_final.ocorrencia.descricao
    else:
        status_code = 'outros'
        status_display = 'Pendente'
        status_class = 'secondary'

    # Cidade / UF
    endereco = n_rep.endereco_entrega or ''
    cidade_uf = ''
    if endereco:
        partes = endereco.split(',')
        if len(partes) >= 2:
            cidade_uf = partes[-1].strip()
        else:
            cidade_uf = endereco[:50]

    pagador_exibicao = ''
    if n_rep.frete and n_rep.frete.pagador_nome:
        pagador_exibicao = n_rep.frete.pagador_nome
    elif is_coleta:
        pagador_exibicao = n_rep.destinatario or ''

    # Data de referência para ordenação
    sort_dt = n_rep.manifesto.data_criacao if (n_rep.manifesto and n_rep.manifesto.data_criacao) else timezone.now()

    return {
        'id': n_rep.id,
        'chave_cargo': get_cargo_group_key(n_rep),
        'numero_nota': n_rep.numero_nota,
        'numero_coleta': n_rep.numero_coleta or '',
        'numero_doc': numero_doc,
        'tipo_operacao': n_rep.tipo_operacao or 'ENTREGA',
        'is_coleta': is_coleta,
        'numero_cte': n_rep.numero_cte or '',
        'destinatario': n_rep.destinatario or '',
        'endereco': endereco,
        'cidade_uf': cidade_uf,
        'cep': n_rep.cep or '',
        'pagador': pagador_exibicao,
        'data_saida': data_saida,
        'data_entrega': data_entrega,
        'status': status_display,
        'status_code': status_code,
        'status_class': status_class,
        'recebedor': recebedor,
        'observacao': observacao,
        'comprovante_url': comprovante_url,
        'tem_foto_comprovante': bool(comprovante_url),
        'ocorrencia': ocorrencia_desc,
        'tipo_baixa': tipo_baixa,
        'tem_transferencia': tem_transferencia,
        'filial_origem': filial_origem,
        'filial_atual': filial_atual,
        'qtd_etapas': len(etapas_ordenadas),
        'sort_dt': sort_dt,
    }


# ============================================================
# API: CARGAS DO CLIENTE (JSON)
# ============================================================

@login_required
@apenas_cliente
def api_cargas_cliente(request):
    """
    Retorna JSON com todas as cargas (notas fiscais e coletas) do cliente logado.
    Consolida as diferentes etapas/manifestos da mesma carga física (ex: transferência entre bases
    seguida de saída para entrega final), evitando duplicações e apresentando status real e preciso.
    """
    cliente = request.user.cliente_perfil

    # Pagadores vinculados ao cliente
    pagadores = list(
        cliente.vinculos.filter(ativo=True).values_list('pagador_nome', flat=True)
    )

    if not pagadores:
        return JsonResponse({
            'cargas': [],
            'resumo': {'em_rota': 0, 'entregues': 0, 'ocorrencias': 0, 'total': 0},
            'pagadores': [],
        })

    # Parâmetros de filtro
    q = request.GET.get('q', '').strip()
    status_filtro = request.GET.get('status', 'todos')
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')
    pagador_filtro = request.GET.get('pagador', '')
    page = int(request.GET.get('page', 1))
    per_page = 50

    # Query base: todas as notas e coletas vinculadas aos pagadores do cliente
    filtro_cliente = get_filtro_cliente_qs(pagadores, pagador_filtro)

    notas_qs = NotaFiscal.objects.filter(
        filtro_cliente
    ).select_related(
        'manifesto', 'manifesto__filial', 'frete'
    ).prefetch_related(
        'baixa_info__ocorrencia'
    )

    # Filtro por período
    if data_inicio:
        notas_qs = notas_qs.filter(manifesto__data_criacao__date__gte=data_inicio)
    if data_fim:
        notas_qs = notas_qs.filter(manifesto__data_criacao__date__lte=data_fim)

    # Filtro por busca textual
    if q:
        notas_qs = notas_qs.filter(
            Q(numero_nota__icontains=q) |
            Q(numero_coleta__icontains=q) |
            Q(numero_cte__icontains=q) |
            Q(chave_acesso__icontains=q) |
            Q(destinatario__icontains=q) |
            Q(endereco_entrega__icontains=q)
        )

    # Agrupa etapas da mesma carga (manifestos de transferência + manifesto de entrega final)
    grupos = {}
    for n in notas_qs.order_by('manifesto__data_criacao', 'id'):
        chave = get_cargo_group_key(n)
        if chave not in grupos:
            grupos[chave] = []
        grupos[chave].append(n)

    # Consolida cada grupo em uma única carga
    cargas_consolidadas = []
    for chave, etapas in grupos.items():
        c = consolidar_etapas_carga(etapas)
        if c:
            cargas_consolidadas.append(c)

    # Contadores KPI (calculados sobre as cargas únicas consolidadas)
    em_rota = sum(1 for c in cargas_consolidadas if c['status_code'] == 'em_rota')
    entregues = sum(1 for c in cargas_consolidadas if c['status_code'] == 'entregue')
    ocorrencias = sum(1 for c in cargas_consolidadas if c['status_code'] == 'ocorrencia')
    total = len(cargas_consolidadas)

    # Aplica filtro de status selecionado pelo usuário
    if status_filtro == 'em_rota':
        cargas_filtradas = [c for c in cargas_consolidadas if c['status_code'] == 'em_rota']
    elif status_filtro == 'entregue':
        cargas_filtradas = [c for c in cargas_consolidadas if c['status_code'] == 'entregue']
    elif status_filtro == 'ocorrencia':
        cargas_filtradas = [c for c in cargas_consolidadas if c['status_code'] == 'ocorrencia']
    else:
        cargas_filtradas = cargas_consolidadas

    # Ordenação: cargas Em Rota primeiro, depois da mais recente para a mais antiga
    cargas_filtradas.sort(
        key=lambda c: (
            0 if c['status_code'] == 'em_rota' else 1,
            -c['sort_dt'].timestamp() if c.get('sort_dt') else 0
        )
    )

    # Paginação
    total_filtrado = len(cargas_filtradas)
    start = (page - 1) * per_page
    end = start + per_page
    cargas_page = cargas_filtradas[start:end]

    # Remove o objeto datetime antes de serializar JSON
    for c in cargas_page:
        c.pop('sort_dt', None)

    return JsonResponse({
        'cargas': cargas_page,
        'resumo': {
            'em_rota': em_rota,
            'entregues': entregues,
            'ocorrencias': ocorrencias,
            'total': total,
        },
        'pagadores': list(pagadores),
        'paginacao': {
            'page': page,
            'per_page': per_page,
            'total': total_filtrado,
            'total_pages': max(1, (total_filtrado + per_page - 1) // per_page),
        }
    })


# ============================================================
# API: DETALHE DE UMA CARGA COM RASTREAMENTO INTERNO COMPLETO
# ============================================================

@login_required
@apenas_cliente
def api_detalhe_carga(request, nota_id):
    """
    Retorna JSON com os detalhes completos e o RASTREAMENTO INTERNO da carga:
    - Agrupa todas as etapas (manifestos de transferência + entrega final)
    - Linha do tempo completa (origem -> transferência -> saída para entrega -> entrega final)
    - Distinção entre comprovante final de entrega e baixa interna de transferência
    """
    cliente = request.user.cliente_perfil
    pagadores = list(
        cliente.vinculos.filter(ativo=True).values_list('pagador_nome', flat=True)
    )

    filtro_cliente = get_filtro_cliente_qs(pagadores)

    try:
        nota = NotaFiscal.objects.select_related(
            'manifesto', 'manifesto__filial', 'frete'
        ).prefetch_related(
            'baixa_info__ocorrencia', 'historico'
        ).get(
            Q(id=nota_id) & filtro_cliente
        )
    except NotaFiscal.DoesNotExist:
        return JsonResponse({'erro': 'Carga não encontrada'}, status=404)

    # Busca todas as etapas (manifestos) dessa mesma carga física
    chave_cargo = get_cargo_group_key(nota)
    if chave_cargo.startswith('CHAVE:'):
        chave = chave_cargo.replace('CHAVE:', '')
        etapas_qs = NotaFiscal.objects.filter(chave_acesso=chave)
    elif chave_cargo.startswith('COLETA:'):
        etapas_qs = NotaFiscal.objects.filter(
            tipo_operacao='COLETA',
            destinatario=nota.destinatario
        )
        if nota.numero_coleta:
            etapas_qs = etapas_qs.filter(numero_coleta=nota.numero_coleta)
        else:
            etapas_qs = etapas_qs.filter(numero_nota=nota.numero_nota)
    else:
        etapas_qs = NotaFiscal.objects.filter(
            numero_nota=nota.numero_nota,
            destinatario=nota.destinatario
        )

    etapas = list(
        etapas_qs.select_related(
            'manifesto', 'manifesto__filial', 'frete'
        ).prefetch_related(
            'baixa_info__ocorrencia', 'historico'
        ).order_by('manifesto__data_criacao', 'id')
    )
    if not etapas:
        etapas = [nota]

    # Identifica etapa ativa ou mais recente
    etapa_ativa = next(
        (e for e in reversed(etapas) 
         if e.status == 'PENDENTE' and e.manifesto and e.manifesto.status == 'EM_TRANSPORTE' and not e.manifesto.finalizado),
        None
    )
    nota_principal = etapa_ativa or etapas[-1]
    is_coleta = (nota_principal.tipo_operacao == 'COLETA')
    numero_doc = nota_principal.numero_coleta if (is_coleta and nota_principal.numero_coleta) else nota_principal.numero_nota

    # Filiais
    filial_origem = etapas[0].manifesto.filial.nome if (etapas[0].manifesto and etapas[0].manifesto.filial) else ''
    filial_atual = nota_principal.manifesto.filial.nome if (nota_principal.manifesto and nota_principal.manifesto.filial) else ''
    tem_transferencia = (
        len(etapas) > 1 or 
        any(e.tipo_operacao in ['TRANSFERENCIA', 'DESPACHO'] for e in etapas) or
        (filial_origem and filial_atual and filial_origem != filial_atual)
    )

    # ------------------------------------------------------------
    # CONSTRUÇÃO DO RASTREAMENTO INTERNO (LINHA DO TEMPO COMPLETA)
    # ------------------------------------------------------------
    timeline = []

    for idx, e in enumerate(etapas):
        f_nome = e.manifesto.filial.nome if (e.manifesto and e.manifesto.filial) else 'Base Operacional'
        mf_num = e.manifesto.numero_manifesto if e.manifesto else ''
        baixas = list(e.baixa_info.all()) if hasattr(e, 'baixa_info') else []
        baixa_e = baixas[-1] if baixas else None

        desc_oc = (baixa_e.ocorrencia.descricao or '').lower() if (baixa_e and baixa_e.ocorrencia) else ''
        is_transf = (
            e.tipo_operacao in ['TRANSFERENCIA', 'DESPACHO'] or
            any(w in desc_oc for w in ['transferencia', 'despacho', 'redespacho', 'embarque'])
        )

        # Evento 1: Saída / Criação da perna
        if e.manifesto and e.manifesto.data_criacao:
            dt_saida = timezone.localtime(e.manifesto.data_criacao).strftime('%d/%m/%Y %H:%M')
            if is_transf:
                timeline.append({
                    'data': dt_saida,
                    'titulo': f'Saída em Transferência Operacional — Filial {f_nome}',
                    'filial': f_nome,
                    'badge': 'Transferência',
                    'badge_class': 'info',
                    'icone': 'bi-arrow-left-right',
                    'detalhes': f'Manifesto #{mf_num}. Mercadoria despachada da base {f_nome} para transbordo/filial de destino.',
                })
            elif e.tipo_operacao == 'COLETA':
                timeline.append({
                    'data': dt_saida,
                    'titulo': f'Ordem de Coleta em Atendimento — Filial {f_nome}',
                    'filial': f_nome,
                    'badge': 'Coleta',
                    'badge_class': 'info',
                    'icone': 'bi-box-seam',
                    'detalhes': f'Manifesto #{mf_num}. Motorista em rota para realização da coleta no local indicado.',
                })
            else:
                timeline.append({
                    'data': dt_saida,
                    'titulo': f'Carga Saiu para Entrega ao Destinatário — Filial {f_nome}',
                    'filial': f_nome,
                    'badge': 'Em Rota',
                    'badge_class': 'primary',
                    'icone': 'bi-truck',
                    'detalhes': f'Manifesto #{mf_num}. Carga carregada no veículo e em rota de entrega ao cliente final.',
                })

        # Evento 2: Eventos históricos TMS (se houver)
        for h in e.historico.all().order_by('data_ocorrencia'):
            dt_h = timezone.localtime(h.data_ocorrencia).strftime('%d/%m/%Y %H:%M') if h.data_ocorrencia else ''
            timeline.append({
                'data': dt_h,
                'titulo': h.comentarios or f'Ocorrência TMS {h.codigo_tms}',
                'filial': f_nome,
                'badge': 'Rastreio',
                'badge_class': 'secondary',
                'icone': 'bi-clock-history',
                'detalhes': '',
            })

        # Evento 3: Conclusão da etapa (Baixa / Ocorrência / Transferência Concluída)
        if baixa_e and baixa_e.data_baixa:
            dt_bx = timezone.localtime(baixa_e.data_baixa).strftime('%d/%m/%Y %H:%M')
            if is_transf:
                rec = f' (Recebido por: {baixa_e.recebedor})' if baixa_e.recebedor else ''
                oc_nome = f' — {baixa_e.ocorrencia.descricao}' if baixa_e.ocorrencia else ''
                timeline.append({
                    'data': dt_bx,
                    'titulo': f'Transferência Concluída / Despacho Realizado{oc_nome}',
                    'filial': f_nome,
                    'badge': 'Transferido',
                    'badge_class': 'info',
                    'icone': 'bi-check2-circle',
                    'detalhes': f'Transferência operacional concluída na base {f_nome}.{rec} Carga sob custódia operacional para roteirização de entrega final.',
                })
            elif e.status == 'BAIXADA':
                titulo = 'Coleta Realizada com Sucesso' if e.tipo_operacao == 'COLETA' else 'Entrega Concluída com Sucesso'
                rec = f'Recebedor: {baixa_e.recebedor}' if baixa_e.recebedor else ''
                timeline.append({
                    'data': dt_bx,
                    'titulo': f'{titulo} — Filial {f_nome}',
                    'filial': f_nome,
                    'badge': 'Concluído',
                    'badge_class': 'success',
                    'icone': 'bi-check-circle-fill',
                    'detalhes': f'{rec}. {baixa_e.observacao or ""}'.strip(),
                })
            elif e.status == 'OCORRENCIA':
                oc_desc = baixa_e.ocorrencia.descricao if baixa_e.ocorrencia else 'Ocorrência registrada'
                timeline.append({
                    'data': dt_bx,
                    'titulo': f'Ocorrência Operacional: {oc_desc}',
                    'filial': f_nome,
                    'badge': 'Ocorrência',
                    'badge_class': 'warning',
                    'icone': 'bi-exclamation-triangle-fill',
                    'detalhes': baixa_e.observacao or 'Não foi possível concluir a operação nesta tentativa.',
                })

    # Se a carga ainda está em transporte na última etapa, adiciona passo futuro "Aguardando Entrega"
    if etapa_ativa:
        timeline.append({
            'data': 'Em Rota',
            'titulo': 'Previsão de Entrega no Destinatário',
            'filial': filial_atual or 'Base de Destino',
            'badge': 'Aguardando',
            'badge_class': 'primary',
            'icone': 'bi-geo-alt-fill',
            'detalhes': 'Veículo em atendimento na região. Entrega programada no endereço do cliente.',
        })

    # ------------------------------------------------------------
    # COMPROVANTE DE ENTREGA AO DESTINATÁRIO
    # ------------------------------------------------------------
    # Procura se existe baixa de entrega final legítima ao cliente
    baixa_entrega_final = None
    for e in reversed(etapas):
        if e.status == 'BAIXADA' and e.tipo_operacao not in ['TRANSFERENCIA', 'DESPACHO']:
            b = e.baixa_info.all().last() if hasattr(e, 'baixa_info') else None
            desc_b = (b.ocorrencia.descricao or '').lower() if (b and b.ocorrencia) else ''
            if not any(w in desc_b for w in ['transferencia', 'despacho', 'redespacho', 'embarque']):
                baixa_entrega_final = (e, b)
                break

    baixa_data = None
    if baixa_entrega_final and baixa_entrega_final[1]:
        e_final, b_final = baixa_entrega_final
        comprovante_url = ''
        if b_final.comprovante_foto_url:
            comprovante_url = b_final.comprovante_foto_url
        elif b_final.comprovante_original_url:
            comprovante_url = b_final.comprovante_original_url
        elif b_final.comprovante_foto:
            comprovante_url = b_final.comprovante_foto.url

        baixa_data = {
            'tem_comprovante': True,
            'situacao': 'entregue',
            'tipo': b_final.tipo,
            'data_baixa': timezone.localtime(b_final.data_baixa).strftime('%d/%m/%Y %H:%M') if b_final.data_baixa else '',
            'recebedor': b_final.recebedor or '',
            'documento_recebedor': b_final.documento_recebedor or '',
            'observacao': b_final.observacao or '',
            'comprovante_url': comprovante_url,
            'tem_foto': bool(comprovante_url),
            'ocorrencia': b_final.ocorrencia.descricao if b_final.ocorrencia else '',
        }
    elif etapa_ativa:
        baixa_data = {
            'tem_comprovante': False,
            'situacao': 'em_rota',
            'mensagem': f'Carga em rota de entrega pela filial {filial_atual}. O comprovante de entrega e assinatura do destinatário estarão disponíveis assim que a entrega for finalizada pelo motorista.',
        }
    elif tem_transferencia and all(e.status == 'BAIXADA' for e in etapas) and not baixa_entrega_final:
        baixa_data = {
            'tem_comprovante': False,
            'situacao': 'em_transferencia',
            'mensagem': f'Carga em processo de transferência operacional (Origem: {filial_origem} ➔ Destino: {filial_atual}). Aguardando inclusão na rota de entrega final.',
        }
    else:
        baixa_data = {
            'tem_comprovante': False,
            'situacao': 'pendente',
            'mensagem': 'Comprovante ainda não disponível para esta operação.',
        }

    # Dados básicos da carga
    mf_rep = nota_principal.manifesto
    data_saida = ''
    if mf_rep and mf_rep.data_criacao:
        data_saida = timezone.localtime(mf_rep.data_criacao).strftime('%d/%m/%Y %H:%M')
    elif etapas[0].manifesto and etapas[0].manifesto.data_criacao:
        data_saida = timezone.localtime(etapas[0].manifesto.data_criacao).strftime('%d/%m/%Y %H:%M')

    data_finalizacao = ''
    if mf_rep and mf_rep.data_finalizacao:
        data_finalizacao = timezone.localtime(mf_rep.data_finalizacao).strftime('%d/%m/%Y %H:%M')

    pagador_exibicao = ''
    if nota_principal.frete and nota_principal.frete.pagador_nome:
        pagador_exibicao = nota_principal.frete.pagador_nome
    elif is_coleta:
        pagador_exibicao = nota_principal.destinatario or ''

    return JsonResponse({
        'nota': {
            'id': nota_principal.id,
            'numero_nota': nota_principal.numero_nota,
            'numero_coleta': nota_principal.numero_coleta or '',
            'numero_doc': numero_doc,
            'tipo_operacao': nota_principal.tipo_operacao or 'ENTREGA',
            'is_coleta': is_coleta,
            'numero_cte': nota_principal.numero_cte or '',
            'chave_acesso': nota_principal.chave_acesso or '',
            'destinatario': nota_principal.destinatario or '',
            'endereco': nota_principal.endereco_entrega or '',
            'cep': nota_principal.cep or '',
            'status': nota_principal.status,
            'pagador': pagador_exibicao,
            'tem_transferencia': tem_transferencia,
            'filial_origem': filial_origem,
            'filial_atual': filial_atual,
        },
        'manifesto': {
            'data_saida': data_saida,
            'data_finalizacao': data_finalizacao,
            'status': mf_rep.status if mf_rep else '',
            'filial': filial_atual or (mf_rep.filial.nome if mf_rep and mf_rep.filial else ''),
        },
        'frete': {
            'numero_cte': nota_principal.frete.numero_cte if nota_principal.frete else '',
            'valor_frete': str(nota_principal.frete.valor_frete) if nota_principal.frete and nota_principal.frete.valor_frete else '',
            'volumes': nota_principal.frete.volumes if nota_principal.frete else '',
            'peso': str(nota_principal.frete.peso_taxado) if nota_principal.frete and nota_principal.frete.peso_taxado else '',
            'remetente': nota_principal.frete.remetente if nota_principal.frete else '',
        },
        'baixa': baixa_data,
        'historico': timeline,
        'tem_transferencia': tem_transferencia,
        'filial_origem': filial_origem,
        'filial_atual': filial_atual,
    })


# ============================================================
# API: EXPORTAR EXCEL DAS CARGAS
# ============================================================

@login_required
@apenas_cliente
def api_exportar_excel(request):
    """
    Exporta relatório Excel com o status de todas as cargas e coletas do cliente.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        return JsonResponse({'erro': 'Módulo openpyxl não instalado'}, status=500)

    cliente = request.user.cliente_perfil
    pagadores = list(
        cliente.vinculos.filter(ativo=True).values_list('pagador_nome', flat=True)
    )

    # Parâmetros de filtro
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')
    pagador_filtro = request.GET.get('pagador', '')

    filtro_cliente = get_filtro_cliente_qs(pagadores, pagador_filtro)

    notas_qs = NotaFiscal.objects.filter(
        filtro_cliente
    ).select_related(
        'manifesto', 'frete'
    ).prefetch_related(
        'baixa_info__ocorrencia'
    ).order_by('-manifesto__data_criacao')

    if data_inicio:
        notas_qs = notas_qs.filter(manifesto__data_criacao__date__gte=data_inicio)
    if data_fim:
        notas_qs = notas_qs.filter(manifesto__data_criacao__date__lte=data_fim)

    # Cria workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cargas e Coletas"

    # Cabeçalho
    headers = ['Operação', 'Documento', 'Ordem Coleta', 'CT-e', 'Destinatário / Solicitante', 'Endereço', 'CEP', 'Pagador',
               'Transferência', 'Base Atual', 'Data Saída / Solicitado', 'Data Conclusão', 'Status', 'Recebedor / Responsável', 'Ocorrência', 'Observação']

    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='11111D', end_color='11111D', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0')
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = thin_border

    # Agrupa e consolida cargas para evitar duplicatas
    grupos = {}
    for n in notas_qs[:5000]:
        chave = get_cargo_group_key(n)
        if chave not in grupos:
            grupos[chave] = []
        grupos[chave].append(n)

    cargas_consolidadas = []
    for chave, etapas in grupos.items():
        c = consolidar_etapas_carga(etapas)
        if c:
            cargas_consolidadas.append(c)

    # Dados
    row = 2
    for c in cargas_consolidadas:
        rota_transf = f"{c['filial_origem']} ➔ {c['filial_atual']}" if c['tem_transferencia'] else 'Direta'

        values = [
            'COLETA' if c['is_coleta'] else 'ENTREGA',
            c['numero_doc'],
            c['numero_coleta'] or '',
            c['numero_cte'] or '',
            c['destinatario'] or '',
            c['endereco'] or '',
            c['cep'] or '',
            c['pagador'] or '',
            rota_transf,
            c['filial_atual'] or '',
            c['data_saida'] or '',
            c['data_entrega'] or '',
            c['status'],
            c['recebedor'] or '',
            c['ocorrencia'] or '',
            c['observacao'] or '',
        ]

        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center')

        row += 1

    # Ajusta largura das colunas
    col_widths = [12, 14, 14, 12, 30, 40, 12, 25, 25, 20, 20, 20, 16, 20, 25, 30]
    for col, width in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = width

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    agora = timezone.localtime().strftime('%Y%m%d_%H%M')
    response['Content-Disposition'] = f'attachment; filename="cargas_{cliente.nome_completo}_{agora}.xlsx"'
    wb.save(response)
    return response


# ============================================================
# API: BUSCAR PAGADORES (Para cadastro de clientes)
# ============================================================

@login_required
def api_buscar_pagadores(request):
    """
    API usada pela tela de Gestão de Usuários para buscar pagadores de frete
    disponíveis no sistema. Retorna nomes únicos de pagadores.
    """
    # Somente operacional/gestor pode acessar
    if not hasattr(request.user, 'motorista_perfil'):
        return JsonResponse({'erro': 'Sem permissão'}, status=403)

    perfil = request.user.motorista_perfil
    if perfil.tipo_usuario not in ['OPERACIONAL', 'SAC', 'GESTOR', 'FINANCEIRO']:
        return JsonResponse({'erro': 'Sem permissão'}, status=403)

    q = request.GET.get('q', '').strip()

    # Busca pagadores únicos de Fretes
    pagadores_qs = Frete.objects.exclude(
        pagador_nome__isnull=True
    ).exclude(
        pagador_nome=''
    )

    if q:
        pagadores_qs = pagadores_qs.filter(pagador_nome__icontains=q)

    pagadores = list(
        pagadores_qs.values('pagador_nome', 'pagador_documento')
        .distinct()
        .order_by('pagador_nome')[:50]
    )

    # Deduplica por nome
    vistos = set()
    resultado = []
    for p in pagadores:
        nome = p['pagador_nome'].strip()
        if nome.lower() not in vistos:
            vistos.add(nome.lower())
            resultado.append({
                'nome': nome,
                'documento': p.get('pagador_documento', ''),
            })

    return JsonResponse({'pagadores': resultado})
