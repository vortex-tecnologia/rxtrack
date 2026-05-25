from django.apps import AppConfig

class ConfiguracaoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'configuracao'
    verbose_name = 'Configurações do Sistema'

    def ready(self):
        import configuracao.signals  # noqa: F401
