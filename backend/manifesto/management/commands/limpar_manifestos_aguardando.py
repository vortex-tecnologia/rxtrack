# manifesto/management/commands/limpar_manifestos_aguardando.py
import logging
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from manifesto.models import Manifesto
from manifesto.services import enviar_painel

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Cancela manifestos que estão parados no status AGUARDANDO há mais de X horas (padrão: 48h)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--horas',
            type=int,
            default=48,
            help='Número de horas limite para considerar o manifesto expirado (padrão: 48)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Apenas simula e exibe os manifestos elegíveis sem alterar o banco de dados',
        )

    def handle(self, *args, **options):
        horas = options.get('horas') or 48
        dry_run = options.get('dry_run', False)

        tag_modo = "[SIMULAÇÃO / DRY-RUN] " if dry_run else ""
        self.stdout.write(self.style.NOTICE(f"{tag_modo}🔍 Iniciando varredura de manifestos em AGUARDANDO há mais de {horas}h..."))

        total_encontrados = 0
        total_cancelados = 0

        # Suporte Multi-Tenant (django-tenants)
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            tenants = list(get_tenant_model().objects.exclude(schema_name='public'))
            if tenants:
                for tenant in tenants:
                    self.stdout.write(self.style.HTTP_INFO(f"\n🏢 Tenant: {tenant.schema_name}"))
                    with schema_context(tenant.schema_name):
                        enc, canc = self._processar_tenant(tenant.schema_name, horas, dry_run)
                        total_encontrados += enc
                        total_cancelados += canc

                self._resumo_final(total_encontrados, total_cancelados, dry_run)
                return
        except Exception as e_tenants:
            self.stdout.write(self.style.WARNING(f"Aviso multi-tenant: {e_tenants}. Executando no schema atual."))

        # Execução padrão / fallback schema public
        enc, canc = self._processar_tenant('public', horas, dry_run)
        total_encontrados += enc
        total_cancelados += canc
        self._resumo_final(total_encontrados, total_cancelados, dry_run)

    def _processar_tenant(self, schema_name, horas, dry_run):
        limite = timezone.now() - timedelta(hours=horas)
        manifestos = list(
            Manifesto.objects.filter(
                status='AGUARDANDO',
                data_criacao__lt=limite
            ).select_related('motorista', 'filial', 'veiculo').order_by('data_criacao')
        )

        total = len(manifestos)
        if total == 0:
            self.stdout.write(self.style.SUCCESS("  Nenhum manifesto expirado encontrado neste schema."))
            return 0, 0

        self.stdout.write(self.style.WARNING(f"  Encontrado(s) {total} manifesto(s) em AGUARDANDO há mais de {horas}h:"))

        agora = timezone.now()
        cancelados = 0

        for m in manifestos:
            dif_horas = int((agora - m.data_criacao).total_seconds() // 3600) if m.data_criacao else horas
            mot_nome = m.motorista.nome_completo if m.motorista else "Sem Motorista"
            filial_nome = m.filial.nome if m.filial else "Sem Filial"
            criado_em = m.data_criacao.strftime('%d/%m/%Y %H:%M') if m.data_criacao else "--"

            info_str = (
                f"    • MFT #{m.numero_manifesto:<8} | Criado em: {criado_em} ({dif_horas}h atrás) | "
                f"Motorista: {mot_nome:<22} | Filial: {filial_nome}"
            )

            if dry_run:
                self.stdout.write(self.style.NOTICE(f"[SIMULADO] {info_str}"))
            else:
                m.status = 'CANCELADO'
                m.finalizado = True
                m.data_finalizacao = agora
                m.save(update_fields=['status', 'finalizado', 'data_finalizacao'])

                try:
                    enviar_painel(m)
                except Exception as ws_err:
                    logger.warning(f"Erro WebSocket ao limpar mft #{m.numero_manifesto}: {ws_err}")

                self.stdout.write(self.style.SUCCESS(f"  [CANCELADO] {info_str}"))
                cancelados += 1

        return total, cancelados

    def _resumo_final(self, total_encontrados, total_cancelados, dry_run):
        self.stdout.write("\n" + "=" * 60)
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"🏁 [SIMULAÇÃO FINALIZADA] {total_encontrados} manifesto(s) elegível(is) para cancelamento. "
                    f"Nenhuma alteração foi gravada no banco."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"🏁 [CONCLUÍDO COM SUCESSO] {total_cancelados}/{total_encontrados} manifesto(s) cancelado(s) e "
                    f"removidos da Torre de Controle."
                )
            )
        self.stdout.write("=" * 60)
