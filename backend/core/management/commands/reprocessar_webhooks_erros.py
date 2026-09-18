import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reprocessa eventos de WebhookEventoManifestoESL que falharam (status ERRO) e limpa duplicatas de ID interno TMS'

    def add_arguments(self, parser):
        parser.add_argument('--manifesto', type=str, help='Filtrar por número específico do manifesto')
        parser.add_argument('--limite', type=int, default=200, help='Limite de eventos a reprocessar (padrão 200)')
        parser.add_argument('--async', action='store_true', dest='rodar_async', help='Enfileirar no Celery em vez de executar síncrono')

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("🔄 Iniciando rotina de reprocessamento de webhooks e limpeza de duplicatas..."))

        try:
            from django_tenants.utils import get_tenant_model, schema_context
            tenants = list(get_tenant_model().objects.exclude(schema_name='public'))
            if tenants:
                for tenant in tenants:
                    with schema_context(tenant.schema_name):
                        self.stdout.write(self.style.HTTP_INFO(f"\n🏢 Tenant: {tenant.schema_name}"))
                        self._limpar_manifestos_duplicados_id_tms()
                        self._reprocessar(options)
                        self._limpar_manifestos_duplicados_id_tms()
                return
        except Exception as e:
            logger.debug(f"Multi-tenant não ativo ou erro: {e}")

        self._limpar_manifestos_duplicados_id_tms()
        self._reprocessar(options)
        self._limpar_manifestos_duplicados_id_tms()

    def _limpar_manifestos_duplicados_id_tms(self):
        """
        Detecta e limpa manifestos criados com ID interno de 7 dígitos da ESL (ex: #6905108),
        unificando-os com o manifesto de número visual correspondente (ex: #69016).
        """
        from manifesto.models import Manifesto
        from integracoes.factory import get_tms_adapter

        manifestos_longos = list(Manifesto.objects.filter(numero_manifesto__regex=r'^\d{7,}$'))
        if not manifestos_longos:
            return

        self.stdout.write(self.style.NOTICE(f"🔍 Verificando {len(manifestos_longos)} manifestos criados com ID interno do TMS..."))
        adapter = get_tms_adapter()

        for m_int in manifestos_longos:
            num_int = str(m_int.numero_manifesto).strip()
            
            # 1. Verifica se já existe um manifesto com este ID gravado em manifesto_id_tms
            m_vis = Manifesto.objects.filter(manifesto_id_tms=num_int).exclude(id=m_int.id).first()

            # 2. Se não encontrou, tenta descobrir o número visual oficial na ESL
            if not m_vis and adapter and hasattr(adapter, 'resolver_numero_visual_manifesto'):
                try:
                    info_esl = adapter.resolver_numero_visual_manifesto(num_int)
                    if info_esl and info_esl.get('sequence_code'):
                        seq = str(info_esl['sequence_code']).strip()
                        m_vis = Manifesto.objects.filter(numero_manifesto=seq).exclude(id=m_int.id).first()
                        if not m_vis:
                            # Não existe o visual: renomeia o próprio manifesto interno para o visual!
                            m_int.numero_manifesto = seq
                            m_int.manifesto_id_tms = num_int
                            m_int.save(update_fields=['numero_manifesto', 'manifesto_id_tms'])
                            self.stdout.write(self.style.SUCCESS(f"  🏷️ Manifesto #{num_int} renomeado para número visual #{seq}"))
                            continue
                except Exception as e:
                    logger.debug(f"Erro ao resolver visual para {num_int}: {e}")

            if m_vis:
                self.stdout.write(self.style.WARNING(f"  🗑️ Removendo duplicata #{num_int} pois o oficial visual #{m_vis.numero_manifesto} já existe."))
                m_int.delete()

    def _reprocessar(self, options):
        from manifesto.models import WebhookEventoManifestoESL
        from manifesto.tasks import processar_webhook_manifesto_task

        qs = WebhookEventoManifestoESL.objects.filter(status='ERRO')
        if options.get('manifesto'):
            qs = qs.filter(numero_manifesto=options['manifesto'])

        limite = options.get('limite', 200)
        eventos = list(qs.order_by('id')[:limite])

        total = len(eventos)
        if total == 0:
            self.stdout.write(self.style.WARNING("Nenhum webhook com status ERRO encontrado."))
            return

        self.stdout.write(self.style.NOTICE(f"Encontrados {total} webhooks com erro. Reprocessando..."))

        sucessos = 0
        erros = 0

        for idx, event in enumerate(eventos, 1):
            num = event.numero_manifesto or 'SEM_NUMERO'
            self.stdout.write(f"[{idx}/{total}] Reprocessando evento #{event.id} (Manifesto #{num})...")

            event.status = 'PENDENTE'
            event.erro = None
            event.save(update_fields=['status', 'erro'])

            if options.get('rodar_async'):
                processar_webhook_manifesto_task.delay(event.id)
                sucessos += 1
                self.stdout.write(self.style.SUCCESS(f"  -> Evento #{event.id} enfileirado no Celery."))
            else:
                try:
                    resultado = processar_webhook_manifesto_task(event.id)
                    event.refresh_from_db()
                    if event.status == 'PROCESSADO':
                        sucessos += 1
                        self.stdout.write(self.style.SUCCESS(f"  -> OK: {resultado}"))
                    else:
                        erros += 1
                        self.stdout.write(self.style.ERROR(f"  -> Falha ao processar: {event.erro}"))
                except Exception as ex:
                    erros += 1
                    self.stdout.write(self.style.ERROR(f"  -> Exceção ao executar: {ex}"))

        self.stdout.write(self.style.SUCCESS(f"\n✅ Reprocessamento finalizado: {sucessos} com sucesso, {erros} com erro."))
