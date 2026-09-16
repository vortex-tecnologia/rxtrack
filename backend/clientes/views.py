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


# ============================================================
# API: CARGAS DO CLIENTE (JSON)
# ============================================================

@login_required
@apenas_cliente
def api_cargas_cliente(request):
    """
    Retorna JSON com todas as cargas (notas fiscais e coletas) do cliente logado.
    Filtra por pagador_nome, remetente e destinatário vinculado ao cliente.
    Sem filtro de filial — mostra cargas de todas as bases.
    
    Query params:
        - q: busca por NF, Coleta, CT-e ou destinatário
        - status: 'em_rota', 'entregue', 'ocorrencia', 'todos'
        - data_inicio: YYYY-MM-DD
        - data_fim: YYYY-MM-DD
        - pagador: filtrar por pagador específico (quando tem múltiplos)
        - page: número da página (paginação)
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

    # Filtro por status
    if status_filtro == 'em_rota':
        notas_qs = notas_qs.filter(
            status='PENDENTE',
            manifesto__status='EM_TRANSPORTE',
            manifesto__finalizado=False
        )
    elif status_filtro == 'entregue':
        notas_qs = notas_qs.filter(status='BAIXADA')
    elif status_filtro == 'ocorrencia':
        notas_qs = notas_qs.filter(status='OCORRENCIA')

    # Ordenação: em rota primeiro, depois por data mais recente
    notas_qs = notas_qs.order_by('-manifesto__data_criacao')

    # Contadores para os cards KPI (sobre o total sem paginação)
    total_notas = notas_qs.count()

    # Para os KPIs, contamos sobre o filtro base do cliente
    notas_kpi = NotaFiscal.objects.filter(filtro_cliente)
    if data_inicio:
        notas_kpi = notas_kpi.filter(manifesto__data_criacao__date__gte=data_inicio)
    if data_fim:
        notas_kpi = notas_kpi.filter(manifesto__data_criacao__date__lte=data_fim)
    if q:
        notas_kpi = notas_kpi.filter(
            Q(numero_nota__icontains=q) |
            Q(numero_coleta__icontains=q) |
            Q(numero_cte__icontains=q) |
            Q(destinatario__icontains=q)
        )

    em_rota = notas_kpi.filter(
        status='PENDENTE',
        manifesto__status='EM_TRANSPORTE',
        manifesto__finalizado=False
    ).count()

    entregues = notas_kpi.filter(status='BAIXADA').count()
    ocorrencias = notas_kpi.filter(status='OCORRENCIA').count()

    # Paginação
    start = (page - 1) * per_page
    end = start + per_page
    notas_page = notas_qs[start:end]

    # Monta os dados das cargas
    cargas = []
    for n in notas_page:
        mf = n.manifesto
        is_coleta = (n.tipo_operacao == 'COLETA')
        numero_doc = n.numero_coleta if (is_coleta and n.numero_coleta) else n.numero_nota

        # Data de saída (início do transporte ou solicitação)
        data_saida = ''
        if mf and mf.data_criacao:
            dt = timezone.localtime(mf.data_criacao)
            data_saida = dt.strftime('%d/%m/%Y %H:%M')

        # Data de entrega/coleta/baixa
        data_entrega = ''
        recebedor = ''
        observacao = ''
        comprovante_url = ''
        ocorrencia_desc = ''
        tipo_baixa = ''

        baixas = list(n.baixa_info.all()) if hasattr(n, 'baixa_info') else []
        baixa = baixas[-1] if baixas else None
        if baixa:
            if baixa.data_baixa:
                dt_b = timezone.localtime(baixa.data_baixa)
                data_entrega = dt_b.strftime('%d/%m/%Y %H:%M')
            recebedor = baixa.recebedor or ''
            observacao = baixa.observacao or ''
            tipo_baixa = baixa.tipo or ''

            # URL do comprovante
            if baixa.comprovante_foto_url:
                comprovante_url = baixa.comprovante_foto_url
            elif baixa.comprovante_original_url:
                comprovante_url = baixa.comprovante_original_url
            elif baixa.comprovante_foto:
                comprovante_url = baixa.comprovante_foto.url

            # Descrição da ocorrência
            if baixa.ocorrencia:
                ocorrencia_desc = baixa.ocorrencia.descricao or f"Código {baixa.ocorrencia.codigo_tms}"

        # Status amigável e contextualmente correto (Coleta vs Entrega)
        st = n.status or 'PENDENTE'
        if is_coleta:
            if st == 'PENDENTE' and mf and mf.status == 'EM_TRANSPORTE' and not mf.finalizado:
                status_display = 'A Coletar'
                status_class = 'primary'
            elif st == 'PENDENTE' and mf and (mf.status == 'AGUARDANDO'):
                status_display = 'Solicitação Recebida'
                status_class = 'secondary'
            elif st == 'BAIXADA':
                status_display = 'Coleta Realizada'
                status_class = 'success'
            elif st == 'OCORRENCIA':
                status_display = 'Ocorrência na Coleta'
                status_class = 'warning'
            else:
                status_display = 'Pendente'
                status_class = 'secondary'
        else:
            if st == 'PENDENTE' and mf and mf.status == 'EM_TRANSPORTE' and not mf.finalizado:
                status_display = 'Em Rota'
                status_class = 'primary'
            elif st == 'PENDENTE' and mf and (mf.status == 'AGUARDANDO'):
                status_display = 'Aguardando Saída'
                status_class = 'secondary'
            elif st == 'BAIXADA':
                if tipo_baixa == 'ENTREGA':
                    status_display = 'Entregue'
                else:
                    status_display = 'Concluída'
                status_class = 'success'
            elif st == 'OCORRENCIA':
                status_display = 'Ocorrência'
                status_class = 'warning'
            else:
                status_display = 'Pendente'
                status_class = 'secondary'

        # Extrai cidade/UF do endereço
        endereco = n.endereco_entrega or ''
        cidade_uf = ''
        if endereco:
            partes = endereco.split(',')
            if len(partes) >= 2:
                cidade_uf = partes[-1].strip()
            else:
                cidade_uf = endereco[:50]

        # Identifica pagador/cliente para exibição
        pagador_exibicao = ''
        if n.frete and n.frete.pagador_nome:
            pagador_exibicao = n.frete.pagador_nome
        elif is_coleta:
            pagador_exibicao = n.destinatario or ''

        cargas.append({
            'id': n.id,
            'numero_nota': n.numero_nota,
            'numero_coleta': n.numero_coleta or '',
            'numero_doc': numero_doc,
            'tipo_operacao': n.tipo_operacao or 'ENTREGA',
            'is_coleta': is_coleta,
            'numero_cte': n.numero_cte or '',
            'destinatario': n.destinatario or '',
            'endereco': endereco,
            'cidade_uf': cidade_uf,
            'cep': n.cep or '',
            'pagador': pagador_exibicao,
            'data_saida': data_saida,
            'data_entrega': data_entrega,
            'status': status_display,
            'status_class': status_class,
            'recebedor': recebedor,
            'observacao': observacao,
            'comprovante_url': comprovante_url,
            'tem_foto_comprovante': bool(comprovante_url),
            'ocorrencia': ocorrencia_desc,
            'tipo_baixa': tipo_baixa,
        })

    return JsonResponse({
        'cargas': cargas,
        'resumo': {
            'em_rota': em_rota,
            'entregues': entregues,
            'ocorrencias': ocorrencias,
            'total': notas_kpi.count(),
        },
        'pagadores': list(pagadores),
        'paginacao': {
            'page': page,
            'per_page': per_page,
            'total': total_notas,
            'total_pages': (total_notas + per_page - 1) // per_page,
        }
    })


# ============================================================
# API: DETALHE DE UMA CARGA (NF) COM TIMELINE
# ============================================================

@login_required
@apenas_cliente
def api_detalhe_carga(request, nota_id):
    """
    Retorna JSON com os detalhes completos de uma nota fiscal ou ordem de coleta:
    - Dados da NF / Coleta e CT-e
    - Histórico de ocorrências e timeline contextual (Coleta vs Entrega)
    - Comprovante/canhoto e dados do recebedor/responsável
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

    mf = nota.manifesto
    is_coleta = (nota.tipo_operacao == 'COLETA')
    numero_doc = nota.numero_coleta if (is_coleta and nota.numero_coleta) else nota.numero_nota

    # Dados básicos
    data_saida = ''
    if mf and mf.data_criacao:
        data_saida = timezone.localtime(mf.data_criacao).strftime('%d/%m/%Y %H:%M')

    data_finalizacao = ''
    if mf and mf.data_finalizacao:
        data_finalizacao = timezone.localtime(mf.data_finalizacao).strftime('%d/%m/%Y %H:%M')

    # Dados da baixa
    baixa_data = None
    baixas = list(nota.baixa_info.all()) if hasattr(nota, 'baixa_info') else []
    baixa = baixas[-1] if baixas else None
    if baixa:
        comprovante_url = ''
        if baixa.comprovante_foto_url:
            comprovante_url = baixa.comprovante_foto_url
        elif baixa.comprovante_original_url:
            comprovante_url = baixa.comprovante_original_url
        elif baixa.comprovante_foto:
            comprovante_url = baixa.comprovante_foto.url

        baixa_data = {
            'tipo': baixa.tipo,
            'data_baixa': timezone.localtime(baixa.data_baixa).strftime('%d/%m/%Y %H:%M') if baixa.data_baixa else '',
            'recebedor': baixa.recebedor or '',
            'documento_recebedor': baixa.documento_recebedor or '',
            'observacao': baixa.observacao or '',
            'comprovante_url': comprovante_url,
            'tem_foto': bool(comprovante_url),
            'ocorrencia': baixa.ocorrencia.descricao if baixa.ocorrencia else '',
            'ocorrencia_codigo': baixa.ocorrencia.codigo_tms if baixa.ocorrencia else '',
        }

    # Timeline de histórico (rastreamento estilo Correios)
    historico = []
    for h in nota.historico.all().order_by('-data_ocorrencia'):
        historico.append({
            'codigo': h.codigo_tms,
            'data': timezone.localtime(h.data_ocorrencia).strftime('%d/%m/%Y %H:%M') if h.data_ocorrencia else '',
            'comentarios': h.comentarios or '',
        })

    # Se não tem histórico TMS, cria timeline contextual com base no tipo_operacao
    if not historico:
        if is_coleta:
            if data_saida:
                historico.append({
                    'codigo': '—',
                    'data': data_saida,
                    'comentarios': 'Ordem de coleta em rota de atendimento',
                })
            if data_finalizacao:
                status_txt = 'Coleta realizada com sucesso' if nota.status == 'BAIXADA' else 'Rota de coleta finalizada'
                historico.append({
                    'codigo': '—',
                    'data': data_finalizacao,
                    'comentarios': status_txt,
                })
        else:
            if data_saida:
                historico.append({
                    'codigo': '—',
                    'data': data_saida,
                    'comentarios': 'Carga saiu para entrega',
                })
            if data_finalizacao:
                status_txt = 'Entrega concluída com sucesso' if nota.status == 'BAIXADA' else 'Rota finalizada'
                historico.append({
                    'codigo': '—',
                    'data': data_finalizacao,
                    'comentarios': status_txt,
                })

    # Identificação do pagador/solicitante para exibição
    pagador_exibicao = ''
    if nota.frete and nota.frete.pagador_nome:
        pagador_exibicao = nota.frete.pagador_nome
    elif is_coleta:
        pagador_exibicao = nota.destinatario or ''

    return JsonResponse({
        'nota': {
            'id': nota.id,
            'numero_nota': nota.numero_nota,
            'numero_coleta': nota.numero_coleta or '',
            'numero_doc': numero_doc,
            'tipo_operacao': nota.tipo_operacao or 'ENTREGA',
            'is_coleta': is_coleta,
            'numero_cte': nota.numero_cte or '',
            'chave_acesso': nota.chave_acesso or '',
            'destinatario': nota.destinatario or '',
            'endereco': nota.endereco_entrega or '',
            'cep': nota.cep or '',
            'status': nota.status,
            'pagador': pagador_exibicao,
        },
        'manifesto': {
            'data_saida': data_saida,
            'data_finalizacao': data_finalizacao,
            'status': mf.status if mf else '',
            'filial': mf.filial.nome if mf and mf.filial else '',
        },
        'frete': {
            'numero_cte': nota.frete.numero_cte if nota.frete else '',
            'valor_frete': str(nota.frete.valor_frete) if nota.frete and nota.frete.valor_frete else '',
            'volumes': nota.frete.volumes if nota.frete else '',
            'peso': str(nota.frete.peso_taxado) if nota.frete and nota.frete.peso_taxado else '',
            'remetente': nota.frete.remetente if nota.frete else '',
        },
        'baixa': baixa_data,
        'historico': historico,
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
               'Data Saída / Solicitado', 'Data Conclusão', 'Status', 'Recebedor / Responsável', 'Ocorrência', 'Observação']

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

    # Dados
    row = 2
    for n in notas_qs[:5000]:  # Limite de 5000 linhas
        mf = n.manifesto
        is_coleta = (n.tipo_operacao == 'COLETA')
        numero_doc = n.numero_coleta if (is_coleta and n.numero_coleta) else n.numero_nota

        baixas = list(n.baixa_info.all()) if hasattr(n, 'baixa_info') else []
        baixa = baixas[-1] if baixas else None

        data_saida = timezone.localtime(mf.data_criacao).strftime('%d/%m/%Y %H:%M') if mf and mf.data_criacao else ''
        data_entrega = timezone.localtime(baixa.data_baixa).strftime('%d/%m/%Y %H:%M') if baixa and baixa.data_baixa else ''

        st = n.status or 'PENDENTE'
        if is_coleta:
            if st == 'PENDENTE' and mf and mf.status == 'EM_TRANSPORTE':
                status_display = 'A Coletar'
            elif st == 'BAIXADA':
                status_display = 'Coleta Realizada'
            elif st == 'OCORRENCIA':
                status_display = 'Ocorrência na Coleta'
            else:
                status_display = 'Pendente'
        else:
            if st == 'PENDENTE' and mf and mf.status == 'EM_TRANSPORTE':
                status_display = 'Em Rota'
            elif st == 'BAIXADA':
                status_display = 'Entregue'
            elif st == 'OCORRENCIA':
                status_display = 'Ocorrência'
            else:
                status_display = 'Pendente'

        recebedor = baixa.recebedor or '' if baixa else ''
        ocorrencia = baixa.ocorrencia.descricao if baixa and baixa.ocorrencia else ''
        observacao = baixa.observacao or '' if baixa else ''

        pagador_val = n.frete.pagador_nome if n.frete else (n.destinatario if is_coleta else '')

        values = [
            'COLETA' if is_coleta else 'ENTREGA',
            numero_doc,
            n.numero_coleta or '',
            n.numero_cte or '',
            n.destinatario or '',
            n.endereco_entrega or '',
            n.cep or '',
            pagador_val,
            data_saida,
            data_entrega,
            status_display,
            recebedor,
            ocorrencia,
            observacao,
        ]

        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center')

        row += 1

    # Ajusta largura das colunas
    col_widths = [12, 14, 14, 12, 30, 40, 12, 25, 20, 20, 16, 20, 25, 30]
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
