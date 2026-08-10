# manifesto/management/commands/sincronizar_status_manifestos_ativos.py
import json
import logging
import requests
import time
from django.core.management.base import BaseCommand
from manifesto.models import Manifesto, Veiculo
from integracoes.registry import get_tms_adapter

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sincroniza o status no TMS (pending/in_transit/closed) e placas de todos os manifestos atualmente ativos no aplicativo'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("🔍 Iniciando sincronização de status dos manifestos ativos com o TMS..."))

        # Suporte a Multi-Tenant (se aplicável)
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            tenants = list(get_tenant_model().objects.exclude(schema_name='public'))
            if tenants:
                for tenant in tenants:
                    with schema_context(tenant.schema_name):
                        self.stdout.write(self.style.HTTP_INFO(f"\n🏢 Tenant: {tenant.schema_name}"))
                        self._processar_manifestos_ativos()
                return
        except Exception:
            pass

        self._processar_manifestos_ativos()

    def _processar_manifestos_ativos(self):
        adapter = get_tms_adapter()
        if not adapter:
            self.stdout.write(self.style.ERROR("❌ Provedor TMS não está configurado ou ativo."))
            return

        config = adapter.config
        token = config.token_analytics
        dominio = config.dominio_esl
        report_id = config.report_validacao

        url = f"https://{dominio}/api/analytics/reports/{report_id}/data"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # Busca todos os manifestos em transporte ativos
        manifestos_ativos = Manifesto.objects.filter(
            status='EM_TRANSPORTE',
            finalizado=False
        ).select_related('motorista', 'filial', 'veiculo')

        total = manifestos_ativos.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("Nenhum manifesto ativo em transporte encontrado."))
            return

        self.stdout.write(f"Encontrados {total} manifestos ativos em transporte. Consultando TMS...")

        atualizados = 0
        erros = 0

        for mft in manifestos_ativos:
            num_visual = str(mft.numero_manifesto).strip()
            mot_nome = mft.motorista.nome_completo if mft.motorista else "Sem Motorista"
            filial_nome = mft.filial.nome if mft.filial else "Sem Filial"

            try:
                # Sequence code numérico
                num_seq = int(num_visual)
            except ValueError:
                self.stdout.write(self.style.WARNING(f"⚠️ Manifesto {num_visual} não possui sequence_code numérico. Ignorando."))
                continue

            payload = {
                "search": {
                    "manifests": {
                        "sequence_code": num_seq,
                        "service_date": "2024-01-01 - 2050-12-31"
                    }
                },
                "page": "1",
                "per": "10"
            }

            try:
                res = requests.get(url, headers=headers, data=json.dumps(payload), timeout=25)
                if res.status_code != 200:
                    self.stdout.write(self.style.ERROR(f"❌ Erro HTTP {res.status_code} ao consultar manifesto {num_visual}"))
                    erros += 1
                    continue

                dados = res.json()
                if not dados:
                    self.stdout.write(self.style.WARNING(f"⚠️ Manifesto {num_visual} não encontrado no TMS."))
                    continue

                info_tms = dados[0]
                status_tms_real = str(info_tms.get('status', 'in_transit')).strip().lower()
                placa_tms = info_tms.get('mft_vie_license_plate')

                # Vincula ou cria Veículo
                veiculo_obj = mft.veiculo
                if placa_tms:
                    placa_limpa = str(placa_tms).strip().upper().replace(' ', '').replace('-', '')
                    if placa_limpa:
                        veiculo_obj, _ = Veiculo.objects.get_or_create(
                            placa=placa_limpa,
                            defaults={'tipo': 'CAVALO'}
                        )

                # Atualiza no manifesto
                mft.status_tms = status_tms_real
                mft.veiculo = veiculo_obj
                mft.save(update_fields=['status_tms', 'veiculo'])

                placa_str = veiculo_obj.placa if veiculo_obj else "Sem Placa"
                status_color = self.style.SUCCESS if status_tms_real == 'in_transit' else (self.style.WARNING if status_tms_real == 'pending' else self.style.ERROR)

                self.stdout.write(
                    f"  Manifesto #{num_visual:<8} | Motorista: {mot_nome:<20} | Filial: {filial_nome:<15} | "
                    f"Status TMS: {status_color(status_tms_real.upper())} | Placa: {placa_str}"
                )
                atualizados += 1
                time.sleep(1.0)  # Evita rate-limit no TMS

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Falha ao processar manifesto {num_visual}: {e}"))
                erros += 1

        self.stdout.write(self.style.SUCCESS(f"\n✅ Sincronização concluída! {atualizados}/{total} manifestos sincronizados com o TMS. ({erros} erros)"))
