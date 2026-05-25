from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from manifesto.models import BaixaNF , Manifesto , NotaFiscal
from manifesto.services import enviar_painel


@receiver(post_save, sender=BaixaNF)
def atualizar_painel_monitoramento(sender, instance, created, **kwargs):
    if created:
        print(">>> SIGNAL DISPARADO BaixaNF")

        manifesto = instance.nota_fiscal.manifesto

        # Espera o banco confirmar tudo
        transaction.on_commit(
            lambda: enviar_painel(manifesto)
        )

@receiver(post_save, sender=Manifesto)
def manifesto_criado(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: enviar_painel(instance)
        )

@receiver(post_save, sender=Manifesto)
def manifesto_atualizado(sender, instance, **kwargs):
    transaction.on_commit(
        lambda: enviar_painel(instance)
    )

@receiver(post_save, sender=NotaFiscal)
def atualizar_painel_quando_criar_nota(sender, instance, created, **kwargs):
    if created:
        manifesto = instance.manifesto
        transaction.on_commit(lambda m=manifesto: enviar_painel(m))