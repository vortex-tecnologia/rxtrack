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
        local_cache = {}

        for nf in nfs_sem_coords:
            try:
                cep_str = str(nf.cep or '').strip()
                end_str = str(nf.endereco_entrega or '').strip()
                if not cep_str and not end_str:
                    continue

                key = f"{cep_str}_{end_str}"
                if key in local_cache:
                    lat, lng = local_cache[key]
                else:
                    lat, lng = buscar_lat_lng_endereco(cep=cep_str, endereco=end_str)
                    local_cache[key] = (lat, lng)
                    # Respeita o rate-limit de 1 requisição por segundo apenas quando faz chamada HTTP
                    time.sleep(1.0)

                if lat is not None and lng is not None:
                    nf.latitude = lat
                    nf.longitude = lng
                    nf.save(update_fields=['latitude', 'longitude'])
                    total += 1
                    self.stdout.write(f"    ✓ NF #{nf.numero_nota} (CEP: {cep_str}) -> Lat: {lat}, Lng: {lng}")
            except Exception as item_err:
                self.stdout.write(f"    ⚠ Ignorando NF #{getattr(nf, 'numero_nota', 'N/A')}: {item_err}")
                continue

        return total
