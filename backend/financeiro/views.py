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
    LinhaFechamento, ResumoMotorista, DadosBancariosAgregado
)
from financeiro.services import gerar_fechamento
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
            linha.breakdown_bases = data['breakdown_bases']

        linha.calcular_total()
        linha.save()

        # Recalcula o resumo do motorista
        resumo = ResumoMotorista.objects.filter(
            fechamento=linha.fechamento,
            motorista=linha.motorista
        ).first()

        if resumo:
            linhas_mot = LinhaFechamento.objects.filter(
                fechamento=linha.fechamento,
                motorista=linha.motorista
            )
            resumo.total_diarias = sum(l.valor_diaria for l in linhas_mot)
            resumo.total_servicos = sum(l.total_embarques for l in linhas_mot)
            total_parcial = sum(l.total_dia for l in linhas_mot)
            resumo.total_parcial = total_parcial + resumo.valor_pedagio
            
            if resumo.total_servicos > 0:
                resumo.diaria_por_servico = (resumo.total_diarias + resumo.valor_pedagio) / Decimal(str(resumo.total_servicos))
            else:
                resumo.diaria_por_servico = Decimal('0')

            resumo.total_final = resumo.total_parcial + resumo.valor_desconto

            # Recalcula o rateio por base no resumo
            from collections import defaultdict
            breakdown_total = defaultdict(lambda: {
                'entregas': 0, 'coletas': 0,
                'valor_entregas': 0.0, 'valor_coletas': 0.0, 'valor_total': 0.0
            })
            for l in linhas_mot:
                for uf, dados_b in (l.breakdown_bases or {}).items():
                    breakdown_total[uf]['entregas'] += int(dados_b.get('entregas', 0))
                    breakdown_total[uf]['coletas'] += int(dados_b.get('coletas', 0))

            for uf, dados_b in breakdown_total.items():
                filial_uf = Filial.objects.filter(uf__iexact=uf).first()
                tarifa_uf = TarifaAgregado.objects.filter(filial=filial_uf).order_by('-vigencia_inicio').first() if filial_uf else None
                vpe = float(tarifa_uf.valor_por_entrega) if tarifa_uf else 5.0
                vpc = float(tarifa_uf.valor_por_coleta) if tarifa_uf else 10.0
                val_ent = dados_b['entregas'] * vpe
                val_col = dados_b['coletas'] * vpc
                servicos_uf = dados_b['entregas'] + dados_b['coletas']
                val_diaria_uf = float(resumo.diaria_por_servico) * servicos_uf
                extras_uf = float(sum(l.valor_extra for l in linhas_mot if (l.localidade_extra or '').upper().strip() == uf))
                dados_b['valor_entregas'] = val_ent
                dados_b['valor_coletas'] = val_col
                dados_b['valor_total'] = val_ent + val_col + val_diaria_uf + extras_uf

            resumo.breakdown_bases = dict(breakdown_total)
            resumo.save()

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

        if 'valor_pedagio' in data:
            resumo.valor_pedagio = parse_decimal(data.get('valor_pedagio'), '0.00')
        if 'valor_desconto' in data:
            resumo.valor_desconto = parse_decimal(data.get('valor_desconto'), '0.00')
        if 'observacao' in data:
            resumo.observacao = data.get('observacao')

        # Recalcula
        linhas_mot = LinhaFechamento.objects.filter(
            fechamento=resumo.fechamento,
            motorista=resumo.motorista
        )
        total_dias = sum(l.total_dia for l in linhas_mot)
        resumo.total_parcial = total_dias + resumo.valor_pedagio

        if resumo.total_servicos > 0:
            resumo.diaria_por_servico = (resumo.total_diarias + resumo.valor_pedagio) / Decimal(str(resumo.total_servicos))
        else:
            resumo.diaria_por_servico = Decimal('0')

        resumo.total_final = resumo.total_parcial + resumo.valor_desconto
        resumo.save()

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
