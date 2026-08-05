from django.core.management.base import BaseCommand
from manifesto.models import NotaFiscal, BaixaNF
from django.db.models import Q

class Command(BaseCommand):
    help = 'Corrige status de notas com baixa 01/02 que ficaram como OCORRENCIA para BAIXADA'

    def handle(self, *args, **options):
        total = 0
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            for tenant in get_tenant_model().objects.all():
                try:
                    with schema_context(tenant.schema_name):
                        # Notas com status OCORRENCIA que tem baixa registrada com codigo 01 ou 02
                        nfs = NotaFiscal.objects.filter(
                            status='OCORRENCIA',
                            baixa_info__ocorrencia__codigo_tms__in=['01', '02', '1', '2']
                        ).distinct()
                        qtd = nfs.update(status='BAIXADA')
                        total += qtd
                        if qtd > 0:
                            self.stdout.write(f"  {tenant.schema_name}: {qtd} notas corrigidas")
                except Exception:
                    pass
        except Exception:
            pass

        self.stdout.write(self.style.SUCCESS(f"Concluido! {total} notas alteradas de OCORRENCIA para BAIXADA."))
