# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# financeiro/services.py

"""
Motor de cálculo do fechamento de agregados.
Replica a lógica das fórmulas da planilha Excel original.
"""

import logging
from decimal import Decimal
from collections import defaultdict

from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone

logger = logging.getLogger(__name__)


def _obter_tarifa_filial(filial, data_referencia):
    """
    Busca a tarifa vigente para a filial na data de referência.
    Prioriza a tarifa com vigência mais recente que seja <= data_referencia.
    """
    from financeiro.models import TarifaAgregado
    
    tarifa = TarifaAgregado.objects.filter(
        filial=filial,
        vigencia_inicio__lte=data_referencia
    ).order_by('-vigencia_inicio').first()
    
    if tarifa:
        return tarifa
    
    # Fallback: tarifa mais recente da filial (mesmo que futura)
    return TarifaAgregado.objects.filter(filial=filial).order_by('-vigencia_inicio').first()


def _obter_ocorrencias_pagamento():
    """
    Retorna os IDs das ocorrências que contam como pagamento para entregas e coletas.
    """
    from financeiro.models import ConfiguracaoFinanceiro
    
    config = ConfiguracaoFinanceiro.load()
    
    ids_entrega = set(config.ocorrencias_pagamento_entrega.values_list('id', flat=True))
    ids_coleta = set(config.ocorrencias_pagamento_coleta.values_list('id', flat=True))
    
    return ids_entrega, ids_coleta


def _uf_da_filial(filial):
    """Extrai a UF da filial de operação. Retorna 'OUTROS' se não definida."""
    if filial and filial.uf:
        return filial.uf.upper().strip()
    if filial and filial.nome:
        # Tenta extrair UF do nome da filial como fallback
        nome = filial.nome.upper().strip()
        ufs = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS',
               'MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC',
               'SP','SE','TO']
        for uf in ufs:
            if nome.endswith(f' {uf}') or nome.endswith(f'-{uf}') or nome == uf:
                return uf
    return 'OUTROS'


def sincronizar_clientes_pagadores():
    """
    Varre todos os Fretes e Coletas do sistema e cadastra os clientes pagadores
    em ClienteBasePagadora caso ainda não existam.
    Retorna a quantidade de novos clientes cadastrados.
    """
    from financeiro.models import ClienteBasePagadora
    from manifesto.models import Frete, NotaFiscal

    existentes = set(ClienteBasePagadora.objects.values_list('nome', flat=True))
    novos = set()

    # 1. Pagadores de Frete
    for nome in Frete.objects.exclude(pagador_nome__isnull=True).exclude(pagador_nome='').values_list('pagador_nome', flat=True).distinct()[:1000]:
        c = (nome or '').strip().upper()
        if c and c not in existentes:
            novos.add(c)

    # 2. Remetentes de Frete
    for nome in Frete.objects.exclude(remetente__isnull=True).exclude(remetente='').values_list('remetente', flat=True).distinct()[:1000]:
        c = (nome or '').strip().upper()
        if c and c not in existentes:
            novos.add(c)

    # 3. Solicitantes de Coletas
    for nome in NotaFiscal.objects.filter(tipo_operacao='COLETA').exclude(destinatario__isnull=True).exclude(destinatario='').values_list('destinatario', flat=True).distinct()[:1000]:
        c = (nome or '').strip().upper()
        if c and c not in existentes:
            novos.add(c)

    # Insere em lote
    objetos = [ClienteBasePagadora(nome=n) for n in novos]
    ClienteBasePagadora.objects.bulk_create(objetos, ignore_conflicts=True)

    logger.info(f"✅ Sincronização concluída: {len(objetos)} novos clientes adicionados ao Financeiro.")
    return len(objetos)


@transaction.atomic
def gerar_fechamento(periodo_inicio, periodo_fim, usuario=None):
    """
    Gera (ou recalcula) um fechamento para o período informado.
    
    1. Busca todos os manifestos no período onde motorista.categoria == 'AGREGADO'
    2. Para cada manifesto: conta BaixaNF com ocorrência que está na lista de pagamento
    3. Identifica o cliente pagador e a filial responsável pelo frete
    4. Aplica tarifas da filial
    5. Gera as LinhaFechamento e ResumoMotorista
    
    Returns: FechamentoAgregado
    """
    from financeiro.models import (
        FechamentoAgregado, LinhaFechamento, ResumoMotorista, ClienteBasePagadora
    )
    from manifesto.models import Manifesto, NotaFiscal, BaixaNF
    from usuarios.models import Motorista
    
    logger.info(f"📊 Gerando fechamento: {periodo_inicio} a {periodo_fim}")
    
    # Mapa de clientes para filiais responsáveis em memória
    clientes_map = {
        c.nome.upper().strip(): c
        for c in ClienteBasePagadora.objects.select_related('filial_responsavel').all()
    }
    
    # Busca ou cria o fechamento para este período
    fechamento, created = FechamentoAgregado.objects.get_or_create(
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        defaults={
            'status': 'ABERTO',
            'criado_por': usuario,
        }
    )
    
    # Se já existe, limpa linhas anteriores para recalcular (mas preserva ajustes manuais)
    ajustes_manuais = {}
    resumos_manuais = {}
    if not created:
        # Salva ajustes manuais existentes (valor_extra, observacao, localidade)
        for linha in fechamento.linhas.all():
            key = f"{linha.motorista_id}_{linha.manifesto_id}"
            if linha.valor_extra != 0 or linha.observacao:
                ajustes_manuais[key] = {
                    'valor_extra': linha.valor_extra,
                    'localidade_extra': linha.localidade_extra,
                    'observacao': linha.observacao,
                }
        # Salva ajustes de resumo (pedágio, descontos)
        for resumo in fechamento.resumos.all():
            resumos_manuais[resumo.motorista_id] = {
                'valor_pedagio': resumo.valor_pedagio,
                'valor_desconto': resumo.valor_desconto,
                'observacao': resumo.observacao,
            }
        fechamento.linhas.all().delete()
        fechamento.resumos.all().delete()
    
    # Ocorrências que contam como pagamento
    ids_oc_entrega, ids_oc_coleta = _obter_ocorrencias_pagamento()
    
    # Busca manifestos de motoristas AGREGADOS no período
    manifestos = Manifesto.objects.filter(
        motorista__categoria='AGREGADO',
        data_criacao__date__gte=periodo_inicio,
        data_criacao__date__lte=periodo_fim,
    ).select_related(
        'motorista', 'filial_operacao', 'filial', 'veiculo'
    ).order_by('motorista__nome_completo', 'data_criacao')
    
    logger.info(f"   Encontrados {manifestos.count()} manifestos de agregados no período.")
    
    # Agrupa manifestos por motorista
    motoristas_linhas = defaultdict(list)
    
    for mft in manifestos:
        motorista = mft.motorista
        filial_op = mft.filial_operacao or mft.filial
        uf_base = _uf_da_filial(filial_op)
        data_mft = mft.data_criacao.date()
        
        # Busca tarifa vigente para esta filial
        tarifa = _obter_tarifa_filial(filial_op, data_mft) if filial_op else None
        valor_diaria = tarifa.valor_diaria if tarifa else Decimal('0')
        valor_por_entrega = tarifa.valor_por_entrega if tarifa else Decimal('5.00')
        valor_por_coleta = tarifa.valor_por_coleta if tarifa else Decimal('10.00')
        
        # Conta entregas e coletas PAGAS no manifesto
        notas = NotaFiscal.objects.filter(manifesto=mft)
        
        qtd_entregas = 0
        qtd_coletas = 0
        qtd_coletas_validas = 0
        qtd_ctes = 0
        qtd_ctes_realizados = 0
        breakdown = defaultdict(lambda: {'entregas': 0, 'coletas': 0})
        
        for nf in notas:
            # Determina o cliente pagador e a UF da filial responsável
            cliente_nome = None
            tipo_nf = (nf.tipo_operacao or '').upper()
            if tipo_nf == 'COLETA':
                cliente_nome = nf.destinatario or (nf.frete.pagador_nome if nf.frete else None) or (nf.frete.remetente if nf.frete else None)
            else:
                cliente_nome = (nf.frete.pagador_nome if nf.frete else None) or (nf.frete.remetente if nf.frete else None) or nf.destinatario

            nf_uf = uf_base
            if cliente_nome:
                c_clean = cliente_nome.strip().upper()
                cli_obj = clientes_map.get(c_clean)
                if not cli_obj:
                    # Auto-registra o cliente no financeiro para o gestor poder atribuir
                    cli_obj, _ = ClienteBasePagadora.objects.get_or_create(nome=c_clean)
                    clientes_map[c_clean] = cli_obj

                if cli_obj.filial_responsavel:
                    nf_uf = _uf_da_filial(cli_obj.filial_responsavel)
            
            # CT-es: conta todos os fretes vinculados
            if nf.frete and nf.frete.numero_cte:
                qtd_ctes += 1
            
            # Busca baixas desta nota
            baixas = BaixaNF.objects.filter(nota_fiscal=nf).select_related('ocorrencia')
            
            for baixa in baixas:
                ocorrencia_id = baixa.ocorrencia_id if baixa.ocorrencia else None
                tipo_nf = (nf.tipo_operacao or '').upper()
                
                if tipo_nf == 'COLETA':
                    qtd_coletas += 1
                    # Verifica se é coleta válida (ocorrência na lista de pagamento)
                    if ids_oc_coleta and ocorrencia_id in ids_oc_coleta:
                        qtd_coletas_validas += 1
                        breakdown[nf_uf]['coletas'] += 1
                    elif not ids_oc_coleta:
                        # Se nenhuma ocorrência configurada, todas as baixas contam
                        qtd_coletas_validas += 1
                        breakdown[nf_uf]['coletas'] += 1
                else:
                    # Entrega / Transferência / Despacho / etc
                    if ids_oc_entrega and ocorrencia_id in ids_oc_entrega:
                        qtd_entregas += 1
                        qtd_ctes_realizados += 1
                        breakdown[nf_uf]['entregas'] += 1
                    elif not ids_oc_entrega:
                        # Se nenhuma ocorrência configurada, todas as baixas contam
                        qtd_entregas += 1
                        qtd_ctes_realizados += 1
                        breakdown[nf_uf]['entregas'] += 1
        
        total_embarques = qtd_entregas + qtd_coletas_validas
        
        # Calcula valores
        valor_entregas = Decimal(str(qtd_entregas)) * valor_por_entrega
        valor_coletas = Decimal(str(qtd_coletas_validas)) * valor_por_coleta
        
        # Restaura ajustes manuais se existiam
        key = f"{motorista.id}_{mft.id}"
        ajuste = ajustes_manuais.get(key, {})
        valor_extra = ajuste.get('valor_extra', Decimal('0'))
        localidade_extra = ajuste.get('localidade_extra', None)
        observacao_linha = ajuste.get('observacao', None)
        
        total_dia = valor_diaria + valor_entregas + valor_coletas + valor_extra
        
        linha = LinhaFechamento(
            fechamento=fechamento,
            motorista=motorista,
            manifesto=mft,
            filial_operacao=filial_op,
            data=data_mft,
            qtd_entregas=qtd_entregas,
            qtd_coletas=qtd_coletas,
            qtd_coletas_validas=qtd_coletas_validas,
            qtd_ctes=qtd_ctes,
            qtd_ctes_realizados=qtd_ctes_realizados,
            total_embarques=total_embarques,
            valor_diaria=valor_diaria,
            valor_entregas=valor_entregas,
            valor_coletas=valor_coletas,
            valor_extra=valor_extra,
            localidade_extra=localidade_extra,
            observacao=observacao_linha,
            total_dia=total_dia,
            breakdown_bases=dict(breakdown),
        )
        linha.save()
        motoristas_linhas[motorista.id].append(linha)
    
    # Gera os resumos por motorista
    for motorista_id, linhas in motoristas_linhas.items():
        motorista = linhas[0].motorista
        
        total_diarias = sum(l.valor_diaria for l in linhas)
        total_servicos = sum(l.total_embarques for l in linhas)
        total_parcial = sum(l.total_dia for l in linhas)
        
        # Restaura ajustes manuais do resumo
        ajuste_resumo = resumos_manuais.get(motorista_id, {})
        valor_pedagio = ajuste_resumo.get('valor_pedagio', Decimal('0'))
        valor_desconto = ajuste_resumo.get('valor_desconto', Decimal('0'))
        observacao_resumo = ajuste_resumo.get('observacao', None)
        
        total_parcial_com_pedagio = total_parcial + valor_pedagio
        
        # Diária por serviço (evita divisão por zero)
        if total_servicos > 0:
            diaria_por_servico = (total_diarias + valor_pedagio) / Decimal(str(total_servicos))
        else:
            diaria_por_servico = Decimal('0')
        
        total_final = total_parcial_com_pedagio + valor_desconto  # desconto já é negativo
        
        # Consolida breakdown por base
        breakdown_total = defaultdict(lambda: {
            'entregas': 0, 'coletas': 0,
            'valor_entregas': Decimal('0'), 'valor_coletas': Decimal('0'),
            'valor_total': Decimal('0')
        })
        
        for linha in linhas:
            for uf, dados in linha.breakdown_bases.items():
                breakdown_total[uf]['entregas'] += dados.get('entregas', 0)
                breakdown_total[uf]['coletas'] += dados.get('coletas', 0)
        
        # Calcula valor por base (entregas×tarifa + coletas×tarifa + diária/serviço × serviços_uf)
        for uf, dados in breakdown_total.items():
            # Busca tarifa da filial correspondente a essa UF
            from usuarios.models import Filial
            filial_uf = Filial.objects.filter(uf__iexact=uf).first()
            tarifa_uf = _obter_tarifa_filial(filial_uf, periodo_fim) if filial_uf else None
            
            vpe = tarifa_uf.valor_por_entrega if tarifa_uf else Decimal('5.00')
            vpc = tarifa_uf.valor_por_coleta if tarifa_uf else Decimal('10.00')
            
            val_entregas = Decimal(str(dados['entregas'])) * vpe
            val_coletas = Decimal(str(dados['coletas'])) * vpc
            servicos_uf = dados['entregas'] + dados['coletas']
            val_diaria_uf = diaria_por_servico * Decimal(str(servicos_uf))
            
            # Soma extras atribuídos a esta UF
            extras_uf = sum(
                l.valor_extra for l in linhas
                if l.localidade_extra and l.localidade_extra.upper().strip() == uf
            )
            
            dados['valor_entregas'] = float(val_entregas)
            dados['valor_coletas'] = float(val_coletas)
            dados['valor_total'] = float(val_entregas + val_coletas + val_diaria_uf + extras_uf)
        
        # Converte para dict serializável
        breakdown_serializado = {}
        for uf, dados in breakdown_total.items():
            breakdown_serializado[uf] = {
                'entregas': dados['entregas'],
                'coletas': dados['coletas'],
                'valor_entregas': dados['valor_entregas'],
                'valor_coletas': dados['valor_coletas'],
                'valor_total': dados['valor_total'],
            }
        
        ResumoMotorista.objects.create(
            fechamento=fechamento,
            motorista=motorista,
            total_diarias=total_diarias,
            total_servicos=total_servicos,
            diaria_por_servico=diaria_por_servico,
            total_parcial=total_parcial_com_pedagio,
            valor_pedagio=valor_pedagio,
            valor_desconto=valor_desconto,
            total_final=total_final,
            breakdown_bases=breakdown_serializado,
            observacao=observacao_resumo,
        )
    
    logger.info(f"✅ Fechamento gerado: {len(motoristas_linhas)} motoristas, {sum(len(v) for v in motoristas_linhas.values())} linhas.")
    
    return fechamento
