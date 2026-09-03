# manifesto/tasks_auto_recovery.py
"""
==========================================================================
 SENTINELA DE BAIXAS PENDENTES DE ANÁLISE DA IA
 (Task periódica do Celery Beat — roda a cada 2 minutos, 24h)
==========================================================================
 Monitora continuamente todas as baixas com qualidade_canhoto='PENDENTE_ANALISE'
 e re-enfileira na fila do Celery para processamento pela IA.

 Isso protege contra:
   - Celery que travou/reiniciou e perdeu tasks da fila
   - Redis que perdeu mensagens
   - Worker que morreu no meio do processamento
   - Qualquer falha silenciosa que deixe a baixa órfã

 Regras:
   - Só re-enfileira baixas com mais de 3 minutos em PENDENTE_ANALISE
     (para não duplicar uma task que acabou de ser disparada e está rodando)
   - Ignora baixas com solicitar_nova_foto=True (já foram rejeitadas pela IA,
     estão aguardando o motorista tirar nova foto)
==========================================================================
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta


@shared_task
def auto_recuperar_baixas_pendentes_ia():
    """
    Sentinela 24h: Varre todos os tenants e re-enfileira na IA
    qualquer baixa que ainda esteja em PENDENTE_ANALISE.
    """
    from django_tenants.utils import schema_context
    from tenants.models import Client

    tenants = list(Client.objects.exclude(schema_name='public'))
    if not tenants:
        return

    agora = timezone.now()
    # Só pega baixas com mais de 3 minutos em PENDENTE_ANALISE
    # (evita re-enfileirar algo que acabou de entrar e está sendo processado agora)
    limite = agora - timedelta(minutes=3)

    total_reenfileiradas = 0

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            from manifesto.models import BaixaNF

            baixas_pendentes = BaixaNF.objects.filter(
                qualidade_canhoto='PENDENTE_ANALISE',
                solicitar_nova_foto=False,      # Ignora as que já foram rejeitadas (aguardando refoto)
                data_baixa__lt=limite           # Há mais de 3 minutos
            ).select_related('nota_fiscal', 'nota_fiscal__manifesto')

            for b in baixas_pendentes:
                nf_num = b.nota_fiscal.numero_nota if b.nota_fiscal else '?'
                mft_num = b.nota_fiscal.manifesto.numero_manifesto if b.nota_fiscal and b.nota_fiscal.manifesto else '?'
                tempo_min = int((agora - b.data_baixa).total_seconds() / 60) if b.data_baixa else '?'

                try:
                    from AgenteIa.tasks import task_processar_canhoto_ia
                    task_processar_canhoto_ia.delay(b.id, schema_name=tenant.schema_name)

                    print(f"[SENTINELA-IA] RE-ENFILEIRADO Baixa #{b.id} "
                          f"(NF {nf_num}, Mft #{mft_num}) "
                          f"pendente há {tempo_min} min "
                          f"no tenant '{tenant.schema_name}'.")

                    total_reenfileiradas += 1
                except Exception as e:
                    print(f"[SENTINELA-IA] Erro ao re-enfileirar Baixa #{b.id}: {e}")

    if total_reenfileiradas > 0:
        print(f"[SENTINELA-IA] Total: {total_reenfileiradas} baixa(s) re-enfileirada(s) para processamento IA.")


@shared_task
def auto_finalizar_manifestos_concluidos_task():
    """
    Sentinela 24h: Varre periodicamente manifestos em transporte.
    Se todas as notas foram baixadas e todas as fotos foram validadas/aprovadas pela IA,
    finaliza o manifesto automaticamente sem depender do motorista no aplicativo.
    """
    try:
        from django_tenants.utils import get_tenant_model, schema_context
        tenants = list(get_tenant_model().objects.exclude(schema_name='public'))
        if tenants:
            for tenant in tenants:
                try:
                    with schema_context(tenant.schema_name):
                        _varrer_e_finalizar_manifestos_tenant(tenant.schema_name)
                except Exception as t_err:
                    print(f"⚠️ [SENTINELA] Erro no tenant '{tenant.schema_name}': {t_err}")
            return
    except Exception as e_ten:
        print(f"⚠️ [SENTINELA] Aviso tenants: {e_ten}")

    # Fallback para schema public caso não utilize multi-tenancy ou tenants estejam vazios
    try:
        _varrer_e_finalizar_manifestos_tenant('public')
    except Exception as e_pub:
        print(f"⚠️ [SENTINELA] Erro schema public: {e_pub}")


def _varrer_e_finalizar_manifestos_tenant(schema_name=None):
    from manifesto.models import Manifesto, NotaFiscal
    from manifesto.services import tentar_autofinalizar_manifesto
    from django.db.models import Q

    # Pega qualquer manifesto que ainda não esteja marcado como FINALIZADO
    manifestos_ativos = Manifesto.objects.exclude(
        status='FINALIZADO'
    ).filter(
        Q(finalizado=False) | Q(finalizado__isnull=True)
    )

    schema_str = f" [{schema_name}]" if schema_name else ""

    for mft in manifestos_ativos:
        try:
            total_notas = mft.notas_fiscais.count()
            if total_notas == 0:
                continue

            sucesso, msg = tentar_autofinalizar_manifesto(mft)
            if sucesso:
                print(f"🏁 [SENTINELA AUTO-FINALIZAÇÃO]{schema_str} Manifesto #{mft.numero_manifesto}: FINALIZADO COM SUCESSO! ({msg})")
            else:
                print(f"ℹ️ [SENTINELA AUTO-FINALIZAÇÃO]{schema_str} Manifesto #{mft.numero_manifesto}: Não finalizado -> {msg}")
        except Exception as e:
            print(f"⚠️ [SENTINELA AUTO-FINALIZAÇÃO]{schema_str} Erro ao verificar Manifesto #{mft.numero_manifesto}: {e}")


