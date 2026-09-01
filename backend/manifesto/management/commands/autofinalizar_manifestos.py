from django.core.management.base import BaseCommand
from manifesto.models import Manifesto, NotaFiscal, BaixaNF
from manifesto.services import tentar_autofinalizar_manifesto
from django.db.models import Q

class Command(BaseCommand):
    help = 'Varre e finaliza automaticamente manifestos cujas notas foram 100% baixadas e fotos verificadas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--manifesto',
            type=str,
            help='Número ou ID específico de um manifesto para tentar auto-finalizar',
        )

    def handle(self, *args, **options):
        num_mft = options.get('manifesto')
        if num_mft:
            self.stdout.write(self.style.NOTICE(f"🔍 Buscando manifesto #{num_mft} em todos os schemas/tenants..."))
            encontrado = False
            try:
                from django_tenants.utils import get_tenant_model, schema_context
                for tenant in get_tenant_model().objects.exclude(schema_name='public'):
                    with schema_context(tenant.schema_name):
                        m = Manifesto.objects.filter(
                            Q(numero_manifesto=str(num_mft)) | Q(id=str(num_mft))
                        ).first()
                        if m:
                            encontrado = True
                            self.stdout.write(self.style.HTTP_INFO(f"🏢 Encontrado no Tenant: {tenant.schema_name}"))
                            sucesso, msg = tentar_autofinalizar_manifesto(m)
                            if sucesso:
                                self.stdout.write(self.style.SUCCESS(f"✅ {msg}"))
                            else:
                                self.stdout.write(self.style.ERROR(f"❌ {msg}"))
                            break
            except Exception as e_ten:
                pass

            if not encontrado:
                self.stdout.write(self.style.ERROR(f"❌ Manifesto #{num_mft} não encontrado em nenhum tenant."))
            return

        self.stdout.write(self.style.NOTICE("🔍 Iniciando varredura de auto-finalização em todos os manifestos ativos..."))

        try:
            from django_tenants.utils import get_tenant_model, schema_context
            tenants = list(get_tenant_model().objects.exclude(schema_name='public'))
            if tenants:
                for tenant in tenants:
                    self.stdout.write(self.style.HTTP_INFO(f"\n🏢 Tenant: {tenant.schema_name}"))
                    with schema_context(tenant.schema_name):
                        self._processar_manifestos(tenant.schema_name)
                return
        except Exception as e_tenants:
            self.stdout.write(self.style.WARNING(f"Aviso tenants: {e_tenants}."))

    def _processar_manifestos(self, schema_name=None):
        manifestos = Manifesto.objects.exclude(
            status='FINALIZADO'
        ).filter(
            Q(finalizado=False) | Q(finalizado__isnull=True)
        )

        total = manifestos.count()
        self.stdout.write(f"Encontrados {total} manifestos ativos para análise.")

        finalizados = 0
        pendentes = 0

        for mft in manifestos:
            total_notas = mft.notas_fiscais.count()
            if total_notas == 0:
                continue

            sucesso, msg = tentar_autofinalizar_manifesto(mft)
            if sucesso:
                finalizados += 1
                self.stdout.write(self.style.SUCCESS(f"  ✅ [FINALIZADO] Manifesto #{mft.numero_manifesto}: {msg}"))
            else:
                pendentes += 1
                self.stdout.write(self.style.WARNING(f"  ⏳ [PENDENTE] Manifesto #{mft.numero_manifesto}: {msg}"))

        self.stdout.write(self.style.SUCCESS(f"\n🏁 Concluído! {finalizados} finalizados, {pendentes} ainda pendentes."))
