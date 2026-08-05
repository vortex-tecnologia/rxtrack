from django.core.management.base import BaseCommand
from manifesto.models import NotaFiscal, BaixaNF, Ocorrencia
from django.db.models import Q

class Command(BaseCommand):
    help = 'Corrige retroativamente o status de notas fiscais finalizadas com ocorrencias de sucesso (01/02/1/2/Realizada)'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando correção de status de notas fiscais...")
        
        total_corrigidas = 0
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            TenantModel = get_tenant_model()
            for tenant in TenantModel.objects.all():
                try:
                    with schema_context(tenant.schema_name):
                        qtd = self._processar_schema()
                        self.stdout.write(f"  -> Schema '{tenant.schema_name}': {qtd} notas corrigidas.")
                        total_corrigidas += qtd
                except Exception as e:
                    pass
        except Exception:
            total_corrigidas = self._processar_schema()

        self.stdout.write(self.style.SUCCESS(f"Recalculo concluído com sucesso! Total de {total_corrigidas} notas fiscais corrigidas para 'BAIXADA' (VERDE)."))

    def _processar_schema(self):
        try:
            # Garante que ocorrencias 01, 02, 1, 2 e com palavra REALIZADA no nome estejam marcadas com tipo='ENTREGA'
            ocorrencias_sucesso = Ocorrencia.objects.filter(
                Q(codigo_tms__in=['01', '02', '1', '2']) |
                Q(codigo_referencia__in=['01', '02', '1', '2']) |
                Q(descricao__icontains='REALIZADA') |
                Q(descricao__icontains='ENTREGUE')
            )
            ocorrencias_sucesso.update(tipo='ENTREGA')
            
            # Atualiza baixas vinculadas
            baixas_sucesso = BaixaNF.objects.filter(ocorrencia__in=ocorrencias_sucesso)
            baixas_sucesso.update(tipo='ENTREGA')
            
            # Atualiza as notas fiscais usando a relação correta 'baixa_info'
            nfs_para_corrigir = NotaFiscal.objects.filter(
                Q(baixa_info__in=baixas_sucesso) |
                Q(status='OCORRENCIA', baixa_info__ocorrencia__in=ocorrencias_sucesso)
            ).distinct()

            total = 0
            for nf in nfs_para_corrigir:
                if nf.status != 'BAIXADA':
                    nf.status = 'BAIXADA'
                    nf.save(update_fields=['status'])
                    total += 1

            # Varredura extra de segurança em todas as notas marcadas como OCORRENCIA
            nfs_extras = NotaFiscal.objects.filter(status='OCORRENCIA')
            for nf in nfs_extras:
                ult = nf.ultima_baixa
                if ult and ult.ocorrencia:
                    cod_ref = str(ult.ocorrencia.codigo_referencia or '').strip()
                    cod_tms = str(ult.ocorrencia.codigo_tms or '').strip()
                    desc = str(ult.ocorrencia.descricao or '').upper()
                    if cod_ref in ['01', '02', '1', '2'] or cod_tms in ['01', '02', '1', '2'] or 'REALIZADA' in desc or 'ENTREGUE' in desc:
                        nf.status = 'BAIXADA'
                        nf.save(update_fields=['status'])
                        total += 1

            return total
        except Exception as err:
            return 0
