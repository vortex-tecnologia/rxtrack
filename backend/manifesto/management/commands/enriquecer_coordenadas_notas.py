from django.core.management.base import BaseCommand
from manifesto.models import NotaFiscal
from common.geocoding import buscar_lat_lng_endereco
import time

class Command(BaseCommand):
    help = 'Busca e salva retroativamente a Latitude e Longitude de todas as Notas Fiscais sem coordenadas'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando geolocalização automática de notas fiscais...")
        
        total_geocodificadas = 0
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            TenantModel = get_tenant_model()
            for tenant in TenantModel.objects.all():
                try:
                    with schema_context(tenant.schema_name):
                        qtd = self._processar_schema()
                        self.stdout.write(f"  -> Schema '{tenant.schema_name}': {qtd} notas enriquecidas com coordenadas.")
                        total_geocodificadas += qtd
                except Exception as e:
                    self.stdout.write(f"  -> Erro no schema '{tenant.schema_name}': {e}")
        except Exception:
            total_geocodificadas = self._processar_schema()

        self.stdout.write(self.style.SUCCESS(f"Concluído! Total de {total_geocodificadas} notas fiscais com Latitude e Longitude gravadas."))

    def _processar_schema(self):
        nfs_sem_coords = NotaFiscal.objects.filter(latitude__isnull=True, longitude__isnull=True)
        total = 0
        for nf in nfs_sem_coords:
            if not nf.cep and not nf.endereco_entrega:
                continue

            lat, lng = buscar_lat_lng_endereco(cep=nf.cep, endereco=nf.endereco_entrega)
            if lat is not None and lng is not None:
                nf.latitude = lat
                nf.longitude = lng
                nf.save(update_fields=['latitude', 'longitude'])
                total += 1
                self.stdout.write(f"    ✓ NF #{nf.numero_nota} (CEP: {nf.cep}) -> Lat: {lat}, Lng: {lng}")
                # Pausa leve para não sobrecarregar API pública
                time.sleep(0.3)

        return total
