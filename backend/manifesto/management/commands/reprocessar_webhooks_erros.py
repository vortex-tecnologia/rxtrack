import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reprocessa eventos de WebhookEventoManifestoESL que falharam (status ERRO)'

    def add_arguments(self, parser):
        parser.add_argument('--manifesto', type=str, help='Filtrar por número específico do manifesto')
        parser.add_argument('--limite', type=int, default=200, help='Limite de eventos a reprocessar (padrão 200)')
        parser.add_argument('--async', action='store_true', dest='rodar_async', help='Enfileirar no Celery em vez de executar síncrono')

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("🔄 Iniciando rotina de reprocessamento de webhooks com erro..."))

        try:
            from django_tenants.utils import get_tenant_model, schema_context
            tenants = list(get_tenant_model().objects.exclude(schema_name='public'))
            if tenants:
                for tenant in tenants:
                    with schema_context(tenant.schema_name):
                        self.stdout.write(self.style.HTTP_INFO(f"\n🏢 Tenant: {tenant.schema_name}"))
                        self._reprocessar(options)
                return
        except Exception as e:
            logger.debug(f"Multi-tenant não ativo ou erro: {e}")

        self._reprocessar(options)

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
