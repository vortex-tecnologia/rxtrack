from django.db.models.signals import post_save
from django.dispatch import receiver
from configuracao.models import ConfiguracaoSistema
from configuracao.utils import invalidar_cache_config


@receiver(post_save, sender=ConfiguracaoSistema)
def limpar_cache_ao_salvar(sender, **kwargs):
    """
    Quando o admin salva uma configuração, 
    limpa o cache para que a próxima chamada pegue os dados frescos.
    """
    invalidar_cache_config()
