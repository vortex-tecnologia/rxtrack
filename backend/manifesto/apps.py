from django.apps import AppConfig
# manifesto/apps.py

class ManifestoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'manifesto'

    def ready(self):
        # Isso garante que o Django carregue o arquivo de sinais assim que o app iniciar
        import manifesto.signals
