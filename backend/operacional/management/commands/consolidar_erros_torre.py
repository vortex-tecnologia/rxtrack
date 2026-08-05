from django.core.management.base import BaseCommand
from operacional.services import consolidar_erros_existentes

class Command(BaseCommand):
    help = 'Consolida erros idênticos repetidos em aberto na Torre de Controle de Erros'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando consolidação e agrupamento de erros duplicados...")
        qtd = consolidar_erros_existentes()
        self.stdout.write(self.style.SUCCESS(f"Consolidação concluída com sucesso! Total de {qtd} registros duplicados mesclados/removidos."))
