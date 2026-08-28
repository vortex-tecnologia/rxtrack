from django.core.management.base import BaseCommand
from django.db.models import Count
from manifesto.models import Manifesto, NotaFiscal


class Command(BaseCommand):
    help = "Remove notas fiscais duplicadas dentro do mesmo manifesto, preservando as notas baixadas/entregues."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("🔍 Iniciando verificação de notas duplicadas..."))
        
        manifestos = Manifesto.objects.all()
        total_removidas = 0
        total_manifestos_afetados = 0

        for mft in manifestos:
            # Agrupa por numero_nota dentro deste manifesto
            duplicadas_info = (
                NotaFiscal.objects.filter(manifesto=mft)
                .values('numero_nota')
                .annotate(qtd=Count('id'))
                .filter(qtd__gt=1)
            )

            if not duplicadas_info:
                continue

            manifesto_teve_limpeza = False

            for item in duplicadas_info:
                num_nota = item['numero_nota']
                notas_mesmo_num = list(
                    NotaFiscal.objects.filter(manifesto=mft, numero_nota=num_nota).order_by('id')
                )

                # Prioriza manter notas que já têm baixa (BAIXADA ou OCORRENCIA)
                nota_principal = None
                for n in notas_mesmo_num:
                    if n.status in ['BAIXADA', 'OCORRENCIA'] or n.baixa_info.exists():
                        nota_principal = n
                        break

                if not nota_principal:
                    # Se todas forem PENDENTE, mantém a primeira
                    nota_principal = notas_mesmo_num[0]

                # Deleta as outras cópias duplicadas
                for n in notas_mesmo_num:
                    if n.id != nota_principal.id:
                        # Se a cópia era pendente, pode deletar com segurança
                        if n.status == 'PENDENTE' and not n.baixa_info.exists():
                            n.delete()
                            total_removidas += 1
                            manifesto_teve_limpeza = True

            if manifesto_teve_limpeza:
                total_manifestos_afetados += 1
                # Recalcula se o manifesto deve estar FINALIZADO
                total_nfs = mft.notas_fiscais.count()
                total_baixadas = mft.notas_fiscais.filter(status__in=['BAIXADA', 'OCORRENCIA']).count()
                if total_nfs > 0 and total_nfs == total_baixadas:
                    mft.status = 'FINALIZADO'
                    mft.save(update_fields=['status'])
                    self.stdout.write(
                        self.style.SUCCESS(f"✅ Manifesto #{mft.numero_manifesto}: todas as {total_nfs} notas baixadas. Status restaurado para FINALIZADO.")
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"🎉 Concluído com sucesso! {total_removidas} notas duplicadas removidas em {total_manifestos_afetados} manifesto(s)."
            )
        )
