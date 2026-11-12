# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# backend/financeiro/tasks.py

import datetime
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="financeiro.tasks.verificar_fechamento_diario_automatico_task")
def verificar_fechamento_diario_automatico_task():
    """
    Roda a cada minuto via Celery Beat e verifica se chegou o Horário de Corte Diário
    configurado em ConfiguracaoFinanceiro (padrão 20:00 no horário de Brasília).
    Quando atingido, executa automaticamente a apuração/fechamento diário de agregados.
    """
    from django_tenants.utils import get_tenant_model, schema_context
    from financeiro.models import ConfiguracaoFinanceiro, FechamentoAgregado
    from financeiro.services import gerar_fechamento

    agora_br = timezone.localtime(timezone.now())
    hoje = agora_br.date()
    hora_atual = agora_br.time()

    TenantModel = get_tenant_model()
    tenants = list(TenantModel.objects.exclude(schema_name='public'))
    schemas = [t.schema_name for t in tenants] or ['public']

    for schema_name in schemas:
        try:
            with schema_context(schema_name):
                config = ConfiguracaoFinanceiro.load()
                if not config.fechamento_diario_automatico_ativo:
                    continue

                horario_corte = config.horario_corte_diario or datetime.time(20, 0)
                if hora_atual >= horario_corte and config.ultimo_fechamento_diario_em != hoje:
                    logger.info(
                        f"🕗 [Fechamento Diário Automático] Executando corte diário de agregados "
                        f"em '{schema_name}' para {hoje.strftime('%d/%m/%Y')} (Corte: {horario_corte.strftime('%H:%M')})"
                    )
                    # Atualiza todos os fechamentos ativos que cobrem a data de hoje
                    fechamentos_ativos = list(
                        FechamentoAgregado.objects.filter(
                            periodo_inicio__lte=hoje,
                            periodo_fim__gte=hoje,
                        ).select_related('filial', 'criado_por')
                    )

                    if fechamentos_ativos:
                        for f in fechamentos_ativos:
                            gerar_fechamento(
                                periodo_inicio=f.periodo_inicio,
                                periodo_fim=f.periodo_fim,
                                usuario=f.criado_por,
                                filial=f.filial,
                            )
                    else:
                        # Caso não exista fechamento cobrindo hoje, gera/atualiza o fechamento do mês vigente até hoje
                        inicio_mes = hoje.replace(day=1)
                        gerar_fechamento(
                            periodo_inicio=inicio_mes,
                            periodo_fim=hoje,
                            usuario=None,
                            filial=None,
                        )

                    config.ultimo_fechamento_diario_em = hoje
                    config.save(update_fields=['ultimo_fechamento_diario_em', 'atualizado_em'])
        except Exception as e:
            logger.error(f"❌ [Fechamento Diário Automático] Erro no schema {schema_name}: {e}")
