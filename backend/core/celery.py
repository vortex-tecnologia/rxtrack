import os
from celery import Celery

# Configura o settings do Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

# Pega configurações do settings com prefixo CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Descobre tasks automaticamente nos apps instalados
app.autodiscover_tasks()
