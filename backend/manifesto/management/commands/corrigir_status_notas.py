from django.core.management.base import BaseCommand
from manifesto.models import NotaFiscal, BaixaNF, Ocorrencia
from django.db.models import Q

class Command(BaseCommand):
    help = 'Corrige retroativamente o status de notas fiscais finalizadas com ocorrencias de sucesso (01/02/1/2/Realizada)'

    def handle(self, *args, **options):
        self.stdout.write("Buscando notas com status 'OCORRENCIA' para verificação de sucesso...")
        
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
        
        # Atualiza as notas fiscais
        nfs_para_corrigir = NotaFiscal.objects.filter(baixas__in=baixas_sucesso).distinct()
        total = 0
        for nf in nfs_para_corrigir:
            if nf.status != 'BAIXADA':
                nf.status = 'BAIXADA'
                nf.save(update_fields=['status'])
                total += 1
                
        self.stdout.write(self.style.SUCCESS(f"Recalculo concluído com sucesso! {total} notas fiscais corrigidas para status 'BAIXADA' (VERDE)."))
