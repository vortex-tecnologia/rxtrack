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


MAPA_ID_ESL_UF = {
    '237988': 'RJ',  # RD EXPRESSO (Matriz RJ)
    '237978': 'SP',  # QUICK SAO PAULO
    '237973': 'DF',  # QUICK BRASILIA
    '237974': 'GO',  # QUICK GOIANIA
}


def _uf_por_texto_filial(texto):
    """Infere a UF a partir do nome/apelido da filial emissora."""
    if not texto:
        return None
    nome = str(texto).upper().strip()
    if 'GOIANIA' in nome or 'GOIÂNIA' in nome or 'APARECIDA DE GOIANIA' in nome:
        return 'GO'
    if 'BRASILIA' in nome or 'BRASÍLIA' in nome or 'DISTRITO FEDERAL' in nome:
        return 'DF'
    if 'SAO PAULO' in nome or 'SÃO PAULO' in nome or 'GUARULHOS' in nome:
        return 'SP'
    if 'RIO DE JANEIRO' in nome or 'RD EXPRESSO' in nome or 'DUQUE DE CAXIAS' in nome:
        return 'RJ'
    ufs = [
        'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS',
        'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC',
        'SP', 'SE', 'TO',
    ]
    for uf in ufs:
        if nome.endswith(f' {uf}') or nome.endswith(f'-{uf}') or nome.endswith(f'/{uf}') or nome == uf:
            return uf
    return None


def _uf_da_filial(filial):
    """Extrai a UF da filial de operação/emissora. Retorna 'OUTROS' se não definida."""
    if not filial:
        return 'OUTROS'
    if getattr(filial, 'uf', None):
        return filial.uf.upper().strip()
    id_tms = str(getattr(filial, 'id_filial_tms', '') or '').strip()
    if id_tms in MAPA_ID_ESL_UF:
        return MAPA_ID_ESL_UF[id_tms]
    uf_nome = _uf_por_texto_filial(getattr(filial, 'nome', None))
    if uf_nome:
        return uf_nome
    return 'OUTROS'


def _uf_emissora_da_nota(nf):
    """
    Determina a UF da filial emissora do frete/nota fiscal (vinda do GraphQL ESL).
    Prioridade:
    1. Filial emissora vinculada à NotaFiscal ou ao Frete (`filial_emissora`)
    2. `id_filial_emissora_tms` (corporationId da ESL: 237974=GO, 237978=SP, 237973=DF, 237988=RJ)
    3. `nome_filial_emissora_tms` (nickname da filial na ESL)
    Retorna None caso a nota ainda não possua dados de filial emissora.
    """
    if not nf:
        return None
    frete = getattr(nf, 'frete', None)

    filial_obj = getattr(nf, 'filial_emissora', None) or (getattr(frete, 'filial_emissora', None) if frete else None)
    if filial_obj:
        uf = _uf_da_filial(filial_obj)
        if uf and uf != 'OUTROS':
            return uf

    corp_id = str(
        getattr(nf, 'id_filial_emissora_tms', None)
        or (getattr(frete, 'id_filial_emissora_tms', None) if frete else None)
        or ''
    ).strip()
    if corp_id in MAPA_ID_ESL_UF:
        return MAPA_ID_ESL_UF[corp_id]

    corp_nome = (
        getattr(nf, 'nome_filial_emissora_tms', None)
        or (getattr(frete, 'nome_filial_emissora_tms', None) if frete else None)
    )
    uf_texto = _uf_por_texto_filial(corp_nome)
    if uf_texto:
        return uf_texto

    return None


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


def _tarifa_efetiva_uf(uf, filial_padrao, data_ref):
    """
    Obtém a tarifa vigente para uma UF específica, com fallback para a filial padrão do manifesto.
    """
    from usuarios.models import Filial
    if uf and uf != 'OUTROS':
        filial_uf = Filial.objects.filter(uf__iexact=uf, operacao_ativa=True).first() or Filial.objects.filter(uf__iexact=uf).first()
        if filial_uf:
            t = _obter_tarifa_filial(filial_uf, data_ref)
            if t:
                return t
    if filial_padrao:
        return _obter_tarifa_filial(filial_padrao, data_ref)
    return None


def recalcular_resumo_motorista(fechamento, motorista, valor_pedagio=None, valor_desconto=None, observacao=None):
    """
    Calcula (ou recalcula) o ResumoMotorista consolidando todas as LinhaFechamento do motorista no período.
    Regra oficial de rateio por Filial Emissora:
    - Cada filial emissora (RJ, SP, DF, GO) paga pelas suas próprias entregas e coletas com ocorrência paga.
    - O valor total das diárias (+ pedágio e descontos) é rateado proporcionalmente em %
      pela quantidade de serviços pagos (entregas + coletas válidas) de cada filial emissora.
    """
    from financeiro.models import LinhaFechamento, ResumoMotorista

    linhas = list(
        LinhaFechamento.objects.filter(fechamento=fechamento, motorista=motorista)
        .select_related('filial_operacao', 'manifesto')
    )

    resumo_existente = ResumoMotorista.objects.filter(fechamento=fechamento, motorista=motorista).first()
    if valor_pedagio is None:
        valor_pedagio = resumo_existente.valor_pedagio if resumo_existente else Decimal('0.00')
    if valor_desconto is None:
        valor_desconto = resumo_existente.valor_desconto if resumo_existente else Decimal('0.00')
    if observacao is None and resumo_existente:
        observacao = resumo_existente.observacao

    # Garante que desconto seja tratado sempre subtraindo (mesmo se digitado positivo ou negativo)
    desconto_abs = abs(Decimal(str(valor_desconto or '0')))
    valor_desconto_neg = -desconto_abs if desconto_abs > 0 else Decimal('0.00')

    total_diarias = sum((l.valor_diaria for l in linhas), Decimal('0.00'))
    total_servicos = sum((l.total_embarques for l in linhas), 0)
    total_dias = sum((l.total_dia for l in linhas), Decimal('0.00'))

    total_parcial_com_pedagio = total_dias + Decimal(str(valor_pedagio or '0'))
    if total_servicos > 0:
        diaria_por_servico = (total_diarias + Decimal(str(valor_pedagio or '0'))) / Decimal(str(total_servicos))
    else:
        diaria_por_servico = Decimal('0.00')

    total_final = total_parcial_com_pedagio + valor_desconto_neg

    # Consolida entregas e coletas pagas por UF emissora
    breakdown_total = defaultdict(lambda: {
        'entregas': 0,
        'coletas': 0,
        'servicos': 0,
        'percentual': 0.0,
        'valor_diaria': 0.0,
        'valor_entregas': 0.0,
        'valor_coletas': 0.0,
        'valor_extra': 0.0,
        'valor_total': 0.0,
    })

    filial_padrao_mot = (linhas[0].filial_operacao if linhas else None) or getattr(motorista, 'filial', None)
    uf_padrao_mot = _uf_da_filial(filial_padrao_mot)
    if uf_padrao_mot == 'OUTROS':
        uf_padrao_mot = 'RJ'

    for linha in linhas:
        for uf, dados in (linha.breakdown_bases or {}).items():
            uf_key = (uf or '').upper().strip() or uf_padrao_mot
            ent = int(dados.get('entregas', 0) or 0)
            col = int(dados.get('coletas', 0) or 0)
            if ent > 0 or col > 0:
                breakdown_total[uf_key]['entregas'] += ent
                breakdown_total[uf_key]['coletas'] += col

    # Se não houve nenhum serviço pago no período mas há diária/valores, aloca 100% na UF base do motorista
    if not breakdown_total and (total_diarias > 0 or total_final != 0):
        breakdown_total[uf_padrao_mot]['entregas'] = 0
        breakdown_total[uf_padrao_mot]['coletas'] = 0

    # Soma de extras sem UF específica (para ratear proporcionalmente) e com UF específica
    extras_por_uf = defaultdict(lambda: Decimal('0.00'))
    extras_sem_uf = Decimal('0.00')
    for l in linhas:
        if l.valor_extra and l.valor_extra != 0:
            loc = (l.localidade_extra or '').upper().strip()
            if loc:
                extras_por_uf[loc] += l.valor_extra
                if loc not in breakdown_total:
                    breakdown_total[loc]  # garante que a UF do extra exista no dicionário
            else:
                extras_sem_uf += l.valor_extra

    # Calcula valores por UF emissora:
    # % da Filial = (entregas_uf + coletas_uf) / total_servicos
    # Diária rateada da Filial = (total_diarias + valor_pedagio) * (% da Filial)
    soma_acumulada = Decimal('0.00')
    uf_maior_peso = None
    maior_servicos = -1

    for uf, dados in breakdown_total.items():
        servicos_uf = dados['entregas'] + dados['coletas']
        dados['servicos'] = servicos_uf
        if servicos_uf > maior_servicos:
            maior_servicos = servicos_uf
            uf_maior_peso = uf

        if total_servicos > 0:
            proporcao = Decimal(str(servicos_uf)) / Decimal(str(total_servicos))
        else:
            proporcao = Decimal('1.0') if uf == uf_padrao_mot else Decimal('0.0')

        percentual_uf = (proporcao * Decimal('100')).quantize(Decimal('0.01'))

        tarifa_uf = _tarifa_efetiva_uf(uf, filial_padrao_mot, fechamento.periodo_fim)
        vpe = tarifa_uf.valor_por_entrega if tarifa_uf else Decimal('5.00')
        vpc = tarifa_uf.valor_por_coleta if tarifa_uf else Decimal('10.00')

        val_entregas = (Decimal(str(dados['entregas'])) * vpe).quantize(Decimal('0.01'))
        val_coletas = (Decimal(str(dados['coletas'])) * vpc).quantize(Decimal('0.01'))
        val_diaria_uf = ((total_diarias + Decimal(str(valor_pedagio or '0'))) * proporcao).quantize(Decimal('0.01'))
        val_desconto_uf = (valor_desconto_neg * proporcao).quantize(Decimal('0.01'))
        val_extra_uf = (extras_por_uf.get(uf, Decimal('0.00')) + (extras_sem_uf * proporcao)).quantize(Decimal('0.01'))

        val_total_uf = (val_diaria_uf + val_entregas + val_coletas + val_extra_uf + val_desconto_uf).quantize(Decimal('0.01'))
        soma_acumulada += val_total_uf

        dados['percentual'] = float(percentual_uf)
        dados['valor_diaria'] = float(val_diaria_uf)
        dados['valor_entregas'] = float(val_entregas)
        dados['valor_coletas'] = float(val_coletas)
        dados['valor_extra'] = float(val_extra_uf)
        dados['valor_total'] = float(val_total_uf)

    # Ajuste fino de centavos residuais de dízima (ex: R$ 0,01) na filial de maior participação
    diferenca_centavos = (total_final - soma_acumulada).quantize(Decimal('0.01'))
    if diferenca_centavos != Decimal('0.00') and uf_maior_peso and uf_maior_peso in breakdown_total:
        breakdown_total[uf_maior_peso]['valor_diaria'] = round(
            breakdown_total[uf_maior_peso]['valor_diaria'] + float(diferenca_centavos), 2
        )
        breakdown_total[uf_maior_peso]['valor_total'] = round(
            breakdown_total[uf_maior_peso]['valor_total'] + float(diferenca_centavos), 2
        )

    breakdown_serializado = {uf: dict(d) for uf, d in breakdown_total.items()}

    resumo_obj, _ = ResumoMotorista.objects.update_or_create(
        fechamento=fechamento,
        motorista=motorista,
        defaults={
            'total_diarias': total_diarias,
            'total_servicos': total_servicos,
            'diaria_por_servico': diaria_por_servico,
            'total_parcial': total_parcial_com_pedagio,
            'valor_pedagio': Decimal(str(valor_pedagio or '0')),
            'valor_desconto': valor_desconto_neg,
            'total_final': total_final,
            'breakdown_bases': breakdown_serializado,
            'observacao': observacao,
        }
    )
    return resumo_obj


@transaction.atomic
def gerar_fechamento(periodo_inicio, periodo_fim, usuario=None):
    """
    Gera (ou recalcula) um fechamento para o período informado.
    
    Regra Oficial (Rateio por Filial Emissora):
    1. Busca todos os manifestos no período onde motorista.categoria == 'AGREGADO'
    2. Para cada nota/coleta do manifesto, identifica a Filial Emissora real (RJ, SP, DF, GO)
    3. Contabiliza apenas notas e coletas cuja baixa possua ocorrência marcada como paga
    4. Rateia a diária em % pela quantidade de entregas + coletas pagas de cada filial emissora
    5. Gera as LinhaFechamento e ResumoMotorista
    
    Returns: FechamentoAgregado
    """
    from financeiro.models import (
        FechamentoAgregado, LinhaFechamento, ResumoMotorista
    )
    from manifesto.models import Manifesto, NotaFiscal, BaixaNF
    
    logger.info(f"📊 Gerando fechamento (por Filial Emissora): {periodo_inicio} a {periodo_fim}")
    
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
        for linha in fechamento.linhas.all():
            key = f"{linha.motorista_id}_{linha.manifesto_id}"
            if linha.valor_extra != 0 or linha.observacao:
                ajustes_manuais[key] = {
                    'valor_extra': linha.valor_extra,
                    'localidade_extra': linha.localidade_extra,
                    'observacao': linha.observacao,
                }
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
        'motorista', 'motorista__filial', 'filial_operacao', 'filial', 'veiculo'
    ).order_by('motorista__nome_completo', 'data_criacao')
    
    logger.info(f"   Encontrados {manifestos.count()} manifestos de agregados no período.")
    
    # Agrupa manifestos por motorista
    motoristas_linhas = defaultdict(list)
    
    for mft in manifestos:
        motorista = mft.motorista
        filial_op = mft.filial_operacao or mft.filial or getattr(motorista, 'filial', None)
        uf_base = _uf_da_filial(filial_op)
        if uf_base == 'OUTROS':
            uf_base = 'RJ'
        data_mft = mft.data_criacao.date()
        
        # Busca tarifa vigente para a filial de operação do manifesto
        tarifa = _obter_tarifa_filial(filial_op, data_mft) if filial_op else None
        valor_diaria = tarifa.valor_diaria if tarifa else Decimal('0')
        
        # Busca notas e coletas do manifesto com suas filiais emissoras
        notas = NotaFiscal.objects.filter(manifesto=mft).select_related(
            'frete', 'filial_emissora', 'frete__filial_emissora'
        ).prefetch_related('baixa_info')
        
        qtd_entregas = 0
        qtd_coletas = 0
        qtd_coletas_validas = 0
        qtd_ctes = 0
        qtd_ctes_realizados = 0
        breakdown = defaultdict(lambda: {'entregas': 0, 'coletas': 0})
        
        for nf in notas:
            tipo_nf = (nf.tipo_operacao or '').upper()
            # Determina a UF da Filial Emissora da nota ou coleta (com fallback seguro para a UF base do manifesto)
            nf_uf = _uf_emissora_da_nota(nf) or uf_base
            
            if tipo_nf == 'COLETA':
                qtd_coletas += 1
            else:
                qtd_ctes += 1
            
            # Verifica nas baixas da nota se houve ocorrência configurada como paga
            baixas = list(nf.baixa_info.all())
            paga = False
            for baixa in baixas:
                ocorrencia_id = baixa.ocorrencia_id
                if tipo_nf == 'COLETA':
                    if (ids_oc_coleta and ocorrencia_id in ids_oc_coleta) or (not ids_oc_coleta and ocorrencia_id):
                        paga = True
                        break
                else:
                    if (ids_oc_entrega and ocorrencia_id in ids_oc_entrega) or (not ids_oc_entrega and ocorrencia_id):
                        paga = True
                        break
            
            if paga:
                if tipo_nf == 'COLETA':
                    qtd_coletas_validas += 1
                    breakdown[nf_uf]['coletas'] += 1
                else:
                    qtd_entregas += 1
                    qtd_ctes_realizados += 1
                    breakdown[nf_uf]['entregas'] += 1
        
        total_embarques = qtd_entregas + qtd_coletas_validas
        
        # Calcula valor das entregas e coletas somando pela tarifa de cada filial emissora
        valor_entregas = Decimal('0.00')
        valor_coletas = Decimal('0.00')
        breakdown_detalhado = {}
        for uf_k, cont in breakdown.items():
            t_uf = _tarifa_efetiva_uf(uf_k, filial_op, data_mft)
            vpe_uf = t_uf.valor_por_entrega if t_uf else (tarifa.valor_por_entrega if tarifa else Decimal('5.00'))
            vpc_uf = t_uf.valor_por_coleta if t_uf else (tarifa.valor_por_coleta if tarifa else Decimal('10.00'))
            
            v_ent_uf = Decimal(str(cont['entregas'])) * vpe_uf
            v_col_uf = Decimal(str(cont['coletas'])) * vpc_uf
            valor_entregas += v_ent_uf
            valor_coletas += v_col_uf
            
            serv_uf = cont['entregas'] + cont['coletas']
            perc_uf = (Decimal(str(serv_uf)) / Decimal(str(total_embarques)) * Decimal('100')).quantize(Decimal('0.01')) if total_embarques > 0 else Decimal('0.00')
            diaria_uf = (valor_diaria * Decimal(str(serv_uf)) / Decimal(str(total_embarques))).quantize(Decimal('0.01')) if total_embarques > 0 else Decimal('0.00')
            
            breakdown_detalhado[uf_k] = {
                'entregas': cont['entregas'],
                'coletas': cont['coletas'],
                'servicos': serv_uf,
                'percentual': float(perc_uf),
                'valor_diaria': float(diaria_uf),
                'valor_entregas': float(v_ent_uf),
                'valor_coletas': float(v_col_uf),
                'valor_total': float(diaria_uf + v_ent_uf + v_col_uf),
            }
        
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
            breakdown_bases=breakdown_detalhado,
        )
        linha.save()
        motoristas_linhas[motorista.id].append(linha)
    
    # Gera os resumos consolidados por motorista
    for motorista_id, linhas in motoristas_linhas.items():
        motorista = linhas[0].motorista
        ajuste_resumo = resumos_manuais.get(motorista_id, {})
        recalcular_resumo_motorista(
            fechamento=fechamento,
            motorista=motorista,
            valor_pedagio=ajuste_resumo.get('valor_pedagio', Decimal('0')),
            valor_desconto=ajuste_resumo.get('valor_desconto', Decimal('0')),
            observacao=ajuste_resumo.get('observacao', None),
        )
    
    logger.info(f"✅ Fechamento gerado: {len(motoristas_linhas)} motoristas, {sum(len(v) for v in motoristas_linhas.values())} linhas.")
    
    return fechamento
