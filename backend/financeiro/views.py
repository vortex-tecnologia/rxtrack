# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# financeiro/views.py

import json
from decimal import Decimal
from datetime import datetime

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from financeiro.models import (
    ConfiguracaoFinanceiro, TarifaAgregado, FechamentoAgregado,
    LinhaFechamento, ResumoMotorista, DadosBancariosAgregado,
    ClienteBasePagadora
)
from financeiro.services import gerar_fechamento, sincronizar_clientes_pagadores, recalcular_resumo_motorista, _tarifa_efetiva_uf
from financeiro.export_excel import exportar_fechamento_excel
from usuarios.models import Motorista, Filial
from manifesto.models import Ocorrencia


def parse_decimal(val, default='0.00'):
    """Converte com segurança strings (inclusive com vírgula ou vazias) para Decimal."""
    if val is None:
        return Decimal(default)
    s = str(val).replace('R$', '').replace(' ', '').replace(',', '.').strip()
    if not s:
        return Decimal(default)
    try:
        return Decimal(s)
    except Exception:
        return Decimal(default)


def verificar_permissao_financeiro(user):
    """
    Verifica se o usuário tem permissão para acessar o módulo financeiro.
    Regra:
    - Superusuário
    - OU tipo_usuario == 'FINANCEIRO'
    - OU cargo in ['GESTOR', 'GERENTE', 'ADMINISTRADOR']
    """
    if user.is_superuser:
        return True
    
    perfil = getattr(user, 'motorista_perfil', None)
    if not perfil:
        return False
    
    if perfil.tipo_usuario == 'FINANCEIRO':
        return True
    
    if perfil.cargo in ['GESTOR', 'GERENTE', 'ADMINISTRADOR']:
        return True
    
    return False


@login_required
def fechamento_agregados_view(request):
    """
    Página principal do Fechamento de Agregados.
    Exibe:
    - Tab 1: Detalhamento por Motorista (espelho da aba do Excel)
    - Tab 2: Resultado Fatura (consolidado com dados bancários e bases)
    - Tab 3: Configuração de Tarifas por Filial
    - Tab 4: Configuração de Ocorrências Pagas
    """
    if not verificar_permissao_financeiro(request.user):
        return render(request, 'desktop/paginas/sem_permissao.html', {
            'mensagem': 'Acesso restrito ao setor Financeiro e Gestão.'
        }, status=403)

    # Fechamento selecionado ou o mais recente
    fechamento_id = request.GET.get('fechamento_id')
    fechamento = None
    if fechamento_id:
        fechamento = FechamentoAgregado.objects.filter(id=fechamento_id).first()
    if not fechamento:
        fechamento = FechamentoAgregado.objects.first()

    # Histórico de fechamentos para o seletor
    todos_fechamentos = FechamentoAgregado.objects.all()[:20]

    # Motoristas agregados cadastrados
    motoristas_agregados = Motorista.objects.filter(categoria='AGREGADO').order_by('nome_completo')

    # Dados do fechamento atual
    linhas = []
    resumos = []
    todas_bases = set()
    dados_bancarios_map = {}

    if fechamento:
        linhas = fechamento.linhas.select_related(
            'motorista', 'manifesto', 'filial_operacao', 'manifesto__veiculo'
        ).order_by('motorista__nome_completo', 'data')
        
        resumos = fechamento.resumos.select_related('motorista').order_by('motorista__nome_completo')
        
        for l in linhas:
            for b in (l.breakdown_bases or {}).keys():
                if b and b != 'OUTROS':
                    todas_bases.add(b.upper().strip())

        # Mapa de dados bancários
        for db in DadosBancariosAgregado.objects.filter(motorista__in=motoristas_agregados):
            dados_bancarios_map[db.motorista_id] = db

    # Garante que as bases padrão e ativas sempre existam na lista
    ufs_filiais = set(Filial.objects.filter(operacao_ativa=True).exclude(uf__isnull=True).exclude(uf='').values_list('uf', flat=True))
    for padrao_uf in ['RJ', 'SP', 'DF', 'GO']:
        ufs_filiais.add(padrao_uf)
    lista_bases = sorted(list(todas_bases.union(ufs_filiais)))

    # Totais consolidados por unidade de negócios para o rodapé da Fatura Consolidada
    totais_bases_fatura = {b: Decimal('0.00') for b in lista_bases}
    total_geral_fatura = Decimal('0.00')
    for r in resumos:
        bk_r = r.breakdown_bases or {}
        for b in lista_bases:
            v_b = Decimal(str((bk_r.get(b) or {}).get('valor_total', 0) or 0))
            totais_bases_fatura[b] += v_b
        total_geral_fatura += (r.total_final or Decimal('0.00'))

    # Tarifas cadastradas mapeadas por filial
    tarifas = TarifaAgregado.objects.select_related('filial').all()
    tarifas_map = {t.filial_id: t for t in tarifas}
    filiais = Filial.objects.filter(operacao_ativa=True).order_by('nome')

    # Configuração de ocorrências
    config_fin = ConfiguracaoFinanceiro.load()
    ocorrencias_todas = Ocorrencia.objects.all().order_by('codigo_tms')
    ocs_entrega_ids = list(config_fin.ocorrencias_pagamento_entrega.values_list('id', flat=True))
    ocs_coleta_ids = list(config_fin.ocorrencias_pagamento_coleta.values_list('id', flat=True))

    context = {
        'fechamento': fechamento,
        'todos_fechamentos': todos_fechamentos,
        'motoristas_agregados': motoristas_agregados,
        'linhas': linhas,
        'resumos': resumos,
        'lista_bases': lista_bases,
        'totais_bases_fatura': totais_bases_fatura,
        'total_geral_fatura': total_geral_fatura,
        'dados_bancarios_map': dados_bancarios_map,
        'tarifas': tarifas,
        'tarifas_map': tarifas_map,
        'filiais': filiais,
        'ocorrencias_todas': ocorrencias_todas,
        'ocs_entrega_ids': ocs_entrega_ids,
        'ocs_coleta_ids': ocs_coleta_ids,
        'hoje': timezone.now().date(),
    }
    return render(request, 'desktop/paginas/fechamento_agregados.html', context)


@login_required
@require_POST
def api_gerar_fechamento(request):
    """Gera ou recalcula o fechamento para o período."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        inicio_str = data.get('periodo_inicio')
        fim_str = data.get('periodo_fim')
        
        if not inicio_str or not fim_str:
            return JsonResponse({'sucesso': False, 'erro': 'Informe data de início e fim.'}, status=400)
        
        dt_inicio = datetime.strptime(inicio_str, '%Y-%m-%d').date()
        dt_fim = datetime.strptime(fim_str, '%Y-%m-%d').date()

        if dt_inicio > dt_fim:
            return JsonResponse({'sucesso': False, 'erro': 'Data de início não pode ser maior que fim.'}, status=400)

        fechamento = gerar_fechamento(dt_inicio, dt_fim, usuario=request.user)

        return JsonResponse({
            'sucesso': True,
            'fechamento_id': fechamento.id,
            'mensagem': f'Fechamento gerado com sucesso para o período {dt_inicio.strftime("%d/%m/%Y")} a {dt_fim.strftime("%d/%m/%Y")}!'
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_POST
def api_salvar_linha(request):
    """Atualiza ajustes manuais de uma linha de manifesto (valor_extra, localidade_extra, observacao, breakdown_bases)."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        linha_id = data.get('linha_id')
        linha = get_object_or_404(LinhaFechamento, id=linha_id)

        if 'valor_extra' in data:
            linha.valor_extra = parse_decimal(data.get('valor_extra'), '0.00')
        if 'localidade_extra' in data:
            linha.localidade_extra = (data.get('localidade_extra') or '').strip().upper()
        if 'observacao' in data:
            linha.observacao = data.get('observacao')

        if 'breakdown_bases' in data and isinstance(data['breakdown_bases'], dict):
            bk_input = data['breakdown_bases']
            novo_entregas = sum(int((v or {}).get('entregas', 0) or 0) for v in bk_input.values())
            novo_coletas = sum(int((v or {}).get('coletas', 0) or 0) for v in bk_input.values())
            total_emb = novo_entregas + novo_coletas

            val_ent_total = Decimal('0.00')
            val_col_total = Decimal('0.00')
            bk_detalhado = {}
            for uf_k, v in bk_input.items():
                ent_u = int((v or {}).get('entregas', 0) or 0)
                col_u = int((v or {}).get('coletas', 0) or 0)
                if ent_u == 0 and col_u == 0:
                    continue
                t_uf = _tarifa_efetiva_uf(uf_k, linha.filial_operacao, linha.data)
                vpe_uf = t_uf.valor_por_entrega if t_uf else Decimal('5.00')
                vpc_uf = t_uf.valor_por_coleta if t_uf else Decimal('10.00')

                v_ent_u = Decimal(str(ent_u)) * vpe_uf
                v_col_u = Decimal(str(col_u)) * vpc_uf
                val_ent_total += v_ent_u
                val_col_total += v_col_u

                serv_u = ent_u + col_u
                perc_u = (Decimal(str(serv_u)) / Decimal(str(total_emb)) * Decimal('100')).quantize(Decimal('0.01')) if total_emb > 0 else Decimal('0.00')
                diaria_u = (linha.valor_diaria * Decimal(str(serv_u)) / Decimal(str(total_emb))).quantize(Decimal('0.01')) if total_emb > 0 else Decimal('0.00')

                bk_detalhado[uf_k] = {
                    'entregas': ent_u,
                    'coletas': col_u,
                    'servicos': serv_u,
                    'percentual': float(perc_u),
                    'valor_diaria': float(diaria_u),
                    'valor_entregas': float(v_ent_u),
                    'valor_coletas': float(v_col_u),
                    'valor_total': float(diaria_u + v_ent_u + v_col_u),
                }

            linha.qtd_entregas = novo_entregas
            linha.qtd_ctes_realizados = novo_entregas
            linha.qtd_coletas_validas = novo_coletas
            linha.total_embarques = total_emb
            linha.valor_entregas = val_ent_total
            linha.valor_coletas = val_col_total
            linha.breakdown_bases = bk_detalhado

        linha.calcular_total()
        linha.save()

        # Recalcula o resumo consolidado do motorista (com % de diária por filial emissora)
        resumo = recalcular_resumo_motorista(linha.fechamento, linha.motorista)

        return JsonResponse({
            'sucesso': True,
            'total_dia': float(linha.total_dia),
            'total_final_motorista': float(resumo.total_final) if resumo else None
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_POST
def api_salvar_resumo(request):
    """Atualiza pedágio, descontos ou observação geral de um motorista no fechamento."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        resumo_id = data.get('resumo_id')
        resumo = get_object_or_404(ResumoMotorista, id=resumo_id)

        v_ped = parse_decimal(data.get('valor_pedagio'), '0.00') if 'valor_pedagio' in data else resumo.valor_pedagio
        v_desc = parse_decimal(data.get('valor_desconto'), '0.00') if 'valor_desconto' in data else resumo.valor_desconto
        obs = data.get('observacao') if 'observacao' in data else resumo.observacao

        resumo = recalcular_resumo_motorista(
            fechamento=resumo.fechamento,
            motorista=resumo.motorista,
            valor_pedagio=v_ped,
            valor_desconto=v_desc,
            observacao=obs,
        )

        return JsonResponse({
            'sucesso': True,
            'total_parcial': float(resumo.total_parcial),
            'diaria_por_servico': float(resumo.diaria_por_servico),
            'total_final': float(resumo.total_final)
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_POST
def api_salvar_dados_bancarios(request):
    """Salva/atualiza dados bancários e chave PIX de um motorista agregado."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        motorista_id = data.get('motorista_id')
        motorista = get_object_or_404(Motorista, id=motorista_id)

        dados_banc, _ = DadosBancariosAgregado.objects.get_or_create(motorista=motorista)
        dados_banc.dados_bancarios = data.get('dados_bancarios', '')
        dados_banc.chave_pix = data.get('chave_pix', '')
        dados_banc.titular_pagamento = data.get('titular_pagamento', '')
        dados_banc.save()

        return JsonResponse({'sucesso': True, 'mensagem': 'Dados bancários salvos com sucesso!'})
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_POST
def api_salvar_tarifa(request):
    """Cria ou atualiza a tarifa de agregado para uma filial."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        filial_id = data.get('filial_id')
        filial = get_object_or_404(Filial, id=filial_id)

        v_diaria = parse_decimal(data.get('valor_diaria'), '0.00')
        v_entrega = parse_decimal(data.get('valor_por_entrega'), '5.00')
        v_coleta = parse_decimal(data.get('valor_por_coleta'), '10.00')

        tarifa = TarifaAgregado.objects.filter(filial=filial).order_by('-vigencia_inicio').first()
        if tarifa:
            tarifa.valor_diaria = v_diaria
            tarifa.valor_por_entrega = v_entrega
            tarifa.valor_por_coleta = v_coleta
            tarifa.save()
        else:
            tarifa = TarifaAgregado.objects.create(
                filial=filial,
                valor_diaria=v_diaria,
                valor_por_entrega=v_entrega,
                valor_por_coleta=v_coleta,
                vigencia_inicio=timezone.now().date(),
                criado_por=request.user,
            )

        return JsonResponse({
            'sucesso': True,
            'valor_diaria': float(tarifa.valor_diaria),
            'valor_por_entrega': float(tarifa.valor_por_entrega),
            'valor_por_coleta': float(tarifa.valor_por_coleta),
            'mensagem': f'Tarifas da filial {filial.nome} salvas com sucesso!'
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_POST
def api_salvar_config_ocorrencias(request):
    """Define quais ocorrências contam como pagamento para entregas e coletas."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        ids_entrega = data.get('ocorrencias_entrega', [])
        ids_coleta = data.get('ocorrencias_coleta', [])

        config = ConfiguracaoFinanceiro.load()
        config.ocorrencias_pagamento_entrega.set(ids_entrega)
        config.ocorrencias_pagamento_coleta.set(ids_coleta)
        config.atualizado_por = request.user
        config.save()

        return JsonResponse({
            'sucesso': True,
            'mensagem': 'Configuração de ocorrências pagas salva com sucesso!'
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_GET
def api_exportar_excel(request):
    """Gera e faz o download do arquivo .xlsx do fechamento."""
    if not verificar_permissao_financeiro(request.user):
        return HttpResponse('Sem permissão.', status=403)

    fechamento_id = request.GET.get('fechamento_id')
    fechamento = get_object_or_404(FechamentoAgregado, id=fechamento_id)

    excel_bytes = exportar_fechamento_excel(fechamento)

    nome_arquivo = f"AGREGADOS_RESUMO_{fechamento.periodo_inicio.strftime('%d-%m')}_A_{fechamento.periodo_fim.strftime('%d-%m-%Y')}.xlsx"

    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return response


@login_required
@require_POST
def api_salvar_cliente_filial(request):
    """Vincula um cliente pagador à filial responsável pela sua cobrança/custo."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        cliente_id = data.get('cliente_id')
        filial_id = data.get('filial_id')

        cliente = get_object_or_404(ClienteBasePagadora, id=cliente_id)

        if filial_id:
            filial = get_object_or_404(Filial, id=filial_id)
            cliente.filial_responsavel = filial
        else:
            cliente.filial_responsavel = None

        cliente.save()

        pendentes = ClienteBasePagadora.objects.filter(filial_responsavel__isnull=True).count()

        return JsonResponse({
            'sucesso': True,
            'filial_nome': cliente.filial_responsavel.nome if cliente.filial_responsavel else None,
            'filial_uf': cliente.filial_responsavel.uf if cliente.filial_responsavel else None,
            'pendentes_count': pendentes,
            'mensagem': f'Cliente "{cliente.nome}" vinculado com sucesso!'
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_POST
def api_sincronizar_clientes(request):
    """Varre os fretes e coletas para cadastrar novos clientes automaticamente."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        qtd_novos = sincronizar_clientes_pagadores()
        total = ClienteBasePagadora.objects.count()
        pendentes = ClienteBasePagadora.objects.filter(filial_responsavel__isnull=True).count()

        return JsonResponse({
            'sucesso': True,
            'novos': qtd_novos,
            'total': total,
            'pendentes': pendentes,
            'mensagem': f'Sincronização concluída: {qtd_novos} novos clientes adicionados. Total: {total} ({pendentes} pendentes de filial).'
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@require_POST
def api_salvar_uf_filial(request):
    """Atualiza a UF de uma filial para garantir o rateio correto."""
    if not verificar_permissao_financeiro(request.user):
        return JsonResponse({'sucesso': False, 'erro': 'Sem permissão.'}, status=403)

    try:
        data = json.loads(request.body)
        filial_id = data.get('filial_id')
        uf = (data.get('uf') or '').strip().upper()

        filial = get_object_or_404(Filial, id=filial_id)
        filial.uf = uf
        filial.save(update_fields=['uf'])

        return JsonResponse({
            'sucesso': True,
            'filial_id': filial.id,
            'uf': filial.uf,
            'mensagem': f'UF da filial {filial.nome} atualizada para {filial.uf}!'
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)

