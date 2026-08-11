from django.apps import AppConfig
import sys

class AgenteIaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'AgenteIa'

    def ready(self):
        # Para evitar problemas pesados de paralelismo e SIGILL no Celery (sinal 4),
        # as instâncias do YOLO e EasyOCR serão feitas DENTRO da própria task.
        self.model_yolo = None
        self.reader_ocr = None