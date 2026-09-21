import os
# Importamos a versão Tenant-Aware do Celery (Multi-SaaS)
from tenant_schemas_celery.app import CeleryApp as TenantAwareCelery

# Configura o settings do Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Inicializa o Celery inteligente para tenants (troca do Celery padrão)
app = TenantAwareCelery("core")

# Pega configurações do settings com prefixo CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Descobre tasks automaticamente nos apps instalados
app.autodiscover_tasks()

# Registra módulos de tasks com nomes não-padrão (que o autodiscover_tasks não encontra sozinho)
app.autodiscover_tasks(['manifesto'], related_name='tasks_auto_recovery')
