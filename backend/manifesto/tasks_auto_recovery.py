# manifesto/tasks_auto_recovery.py
"""
==========================================================================
 AUTO-RECUPERAÇÃO DE BAIXAS TRAVADAS EM PENDENTE_ANALISE
 (Task periódica do Celery Beat — roda a cada 2 minutos)
==========================================================================
 Detecta baixas que ficaram presas no status PENDENTE_ANALISE porque
 a task do Agente IA nunca executou (worker caiu, Redis perdeu fila, etc).

 Fluxo:
   - Travada há >3 min e <5 min  → Re-enfileira task_processar_canhoto_ia (retry)
   - Travada há >5 min           → Libera como APROVADO + envia ao TMS
==========================================================================
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta


@shared_task
def auto_recuperar_baixas_pendentes_ia():
    """Varre todos os tenants e recupera baixas travadas em PENDENTE_ANALISE."""
    from django_tenants.utils import schema_context
    from tenants.models import Client

    tenants = list(Client.objects.exclude(schema_name='public'))
    if not tenants:
        return

    agora = timezone.now()
    limite_retry = agora - timedelta(minutes=3)    # Travada há mais de 3 min → retry
    limite_liberar = agora - timedelta(minutes=5)   # Travada há mais de 5 min → liberar forçado

    total_retried = 0
    total_liberadas = 0

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            from manifesto.models import BaixaNF

            # ---- FASE 1: Liberar forçado (>5 min travada) ----
            baixas_liberar = BaixaNF.objects.filter(
                qualidade_canhoto='PENDENTE_ANALISE',
                data_baixa__lt=limite_liberar
            ).select_related('nota_fiscal', 'nota_fiscal__manifesto')

            for b in baixas_liberar:
                b.qualidade_canhoto = 'APROVADO'
                b.solicitar_nova_foto = False
                b.save(update_fields=['qualidade_canhoto', 'solicitar_nova_foto'])

                nf_num = b.nota_fiscal.numero_nota if b.nota_fiscal else '?'
                mft_num = b.nota_fiscal.manifesto.numero_manifesto if b.nota_fiscal and b.nota_fiscal.manifesto else '?'
                tempo_min = int((agora - b.data_baixa).total_seconds() / 60) if b.data_baixa else '?'

                print(f"[AUTO-RECOVERY] LIBERADO Baixa #{b.id} (NF {nf_num}, Mft #{mft_num}) "
                      f"travada há {tempo_min} min no tenant '{tenant.schema_name}'. "
                      f"Enviando ao TMS.")

                # Dispara integração TMS
                if not b.integrado_tms:
                    try:
                        from AgenteIa.tasks import finalizar_fluxo_tms
                        finalizar_fluxo_tms(b)
                    except Exception as e:
                        print(f"[AUTO-RECOVERY] Erro ao enviar TMS para Baixa #{b.id}: {e}")

                # Atualiza painel WebSocket
                if b.nota_fiscal and b.nota_fiscal.manifesto:
                    try:
                        from manifesto.services import enviar_painel
                        enviar_painel(b.nota_fiscal.manifesto)
                    except Exception:
                        pass

                total_liberadas += 1

            # ---- FASE 2: Re-enfileirar (>3 min e <5 min travada) ----
            baixas_retry = BaixaNF.objects.filter(
                qualidade_canhoto='PENDENTE_ANALISE',
                data_baixa__lt=limite_retry,
                data_baixa__gte=limite_liberar
            )

            for b in baixas_retry:
                nf_num = b.nota_fiscal.numero_nota if b.nota_fiscal else '?'
                print(f"[AUTO-RECOVERY] RE-ENFILEIRANDO Baixa #{b.id} (NF {nf_num}) "
                      f"no tenant '{tenant.schema_name}' (travada >3 min).")

                try:
                    from AgenteIa.tasks import task_processar_canhoto_ia
                    task_processar_canhoto_ia.delay(b.id, schema_name=tenant.schema_name)
                except Exception as e:
                    print(f"[AUTO-RECOVERY] Erro ao re-enfileirar Baixa #{b.id}: {e}")

                total_retried += 1

    if total_retried > 0 or total_liberadas > 0:
        print(f"[AUTO-RECOVERY] Resumo: {total_retried} re-enfileirada(s), {total_liberadas} liberada(s) forçado.")
