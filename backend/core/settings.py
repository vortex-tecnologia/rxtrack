# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
"""
Django settings for core project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import timedelta
from celery.schedules import crontab

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# BASE_DIR aponta para o diretório raiz do projeto (BackendAPP/)
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError('A variável SECRET_KEY não está definida no .env! Gere uma chave segura.')
DEBUG = os.getenv('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

_csrf_origins = os.getenv('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(',') if o.strip()]

# Application definition

SHARED_APPS = [
    'django_tenants',          # 1º: Obrigatório primeiro para roteamento
    'tenants',                 # Novo app de gestão de clientes/domínios
    'tutoriais',               # Novo app de vídeos de treinamento compartilhados
    
    'daphne',                  # Daphne (ASGI)
    'channels',                # Camada de comunicação
    'jazzmin',                 # Admin bonito (Bootstrap)
    'drf_spectacular',         # API Docs (Swagger/ReDoc)
    
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

TENANT_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',

    'jazzmin',

    'django.contrib.admin',
    'django.contrib.staticfiles',

    'daphne',
    'channels',
    
    'manifesto.apps.ManifestoConfig',
    
    # Terceiros
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_celery_beat',
    'corsheaders',
    'pwa',
    
    # Nossas Apps
    'usuarios',
    'mobile',
    'operacional',
    'AgenteIa',
    'configuracao',
    'suporte',
    'sac_mobile',
    'auditoria',
    'integracoes.apps.IntegracoesConfig',
    'whatsbot.apps.WhatsbotConfig',
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = 'tenants.Client'
TENANT_DOMAIN_MODEL = 'tenants.Domain'

DATABASE_ROUTERS = (
    'django_tenants.routers.TenantSyncRouter',
)

PUBLIC_SCHEMA_URLCONF = 'core.urls_public'
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')

# ===== CELERY BEAT — Tarefas Agendadas =====
CELERY_BEAT_SCHEDULE = {
    # Rodadas COM busca no TMS (atualiza JSON)
    'bot-whatsapp-11h': {
        'task': 'whatsbot.tasks.bot_buscar_tms_e_notificar',
        'schedule': crontab(hour=11, minute=0),
    },
    'bot-whatsapp-14h': {
        'task': 'whatsbot.tasks.bot_buscar_tms_e_notificar',
        'schedule': crontab(hour=14, minute=0),
    },
    'bot-whatsapp-16h': {
        'task': 'whatsbot.tasks.bot_buscar_tms_e_notificar',
        'schedule': crontab(hour=16, minute=0),
    },
    # Rodadas SEM busca no TMS (releitura do cache local)
    'bot-whatsapp-12h': {
        'task': 'whatsbot.tasks.bot_reler_cache_e_notificar',
        'schedule': crontab(hour=12, minute=0),
    },
    'bot-whatsapp-15h': {
        'task': 'whatsbot.tasks.bot_reler_cache_e_notificar',
        'schedule': crontab(hour=15, minute=0),
    },
    # Lembrete diário de finalização de rota
    'bot-whatsapp-20h': {
        'task': 'whatsbot.tasks.bot_lembrete_finalizacao_20h',
        'schedule': crontab(hour=20, minute=0),
    },
    # Relatório diário da operação enviado aos Grupos
    'bot-relatorio-diario-22h': {
        'task': 'whatsbot.tasks.bot_relatorio_diario_grupos',
        'schedule': crontab(hour=22, minute=0),
    },
    # Sincronização diária das fotos de perfil dos motoristas via WhatsApp
    'sincronizar-fotos-motoristas-3am': {
        'task': 'whatsbot.tasks.sincronizar_fotos_motoristas_whatsapp_task',
        'schedule': crontab(hour=3, minute=0),
    },
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [os.getenv('REDIS_URL', 'redis://redis:6379/0')],
        },
    },
}
# Configurações do Web Push
WEBPUSH_SETTINGS = {
    "VAPID_PUBLIC_KEY": os.getenv('VAPID_PUBLIC_KEY', ''),
    "VAPID_PRIVATE_KEY": os.getenv('VAPID_PRIVATE_KEY', ''),
    "VAPID_ADMIN_EMAIL": os.getenv('VAPID_ADMIN_EMAIL', 'admin@quickdelivery.com.br')
}


# (Deve ser a URL da sua página HTML de login)
LOGIN_URL = '/login/'
# URL para onde o Django deve REDIRECIONAR o usuário APÓS o login bem-sucedido
# (Não é estritamente necessário para a API, mas bom para evitar redirecionamentos embutidos)
LOGIN_REDIRECT_URL = '/app/'

MIDDLEWARE = [
    'django_tenants.middleware.main.TenantMainMiddleware', # Roteador do Multi-SaaS
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Configurações de Sessão para manter o motorista logado no PWA/APK
SESSION_COOKIE_AGE = 31536000  # 1 ano
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True
_cors_origins = os.getenv('CORS_ALLOWED_ORIGINS', '')
if _cors_origins:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(',') if o.strip()]
else:
    CORS_ALLOW_ALL_ORIGINS = DEBUG  # Só permite tudo em desenvolvimento
CORS_ALLOW_CREDENTIALS = True

# Configuração para servir arquivos de mídia (Fotos de comprovantes) em ambiente de desenvolvimento
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'



DATABASES = {
    'default': {
        'ENGINE': 'django_tenants.postgresql_backend',
        'NAME': os.getenv('DB_NAME', 'quicktrack_homolog'),
        'USER': os.getenv('DB_USER', 'quicktrack'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'VxQtHom2026#Pg'),
        'HOST': os.getenv('DB_HOST', 'qt_homolog_postgres'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# FTP Configuration
FTP_HOST = os.getenv('FTP_HOST', 'st63136.ispot.cc')
FTP_USER = os.getenv('FTP_USER')
FTP_PASS = os.getenv('FTP_PASS')
FTP_BASE_URL = os.getenv('FTP_BASE_URL', 'https://st63136.ispot.cc/uploads/comprovantes-quickdelivery/')


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'

# CORREÇÃO CRÍTICA: Diretório onde o collectstatic vai copiar todos os arquivos
STATIC_ROOT = BASE_DIR / 'staticfiles' 
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
    # Caso precise de arquivos estáticos globais
]


# Configuração de Arquivos de Mídia (Uploads de usuário: fotos de comprovantes)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- Configurações de Celery ---
# CELERY_BROKER_URL já definido acima (linha 62) a partir do .env
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE


REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication', 
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/minute',
        'user': '120/minute',
    }
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Quicktrack API',
    'DESCRIPTION': 'Documentação oficial das integrações e recursos do sistema Quicktrack TMS.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': True,
    },
}


# --- Configurações JWT (JSON Web Token) ---
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=365),

    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': False,

    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Configuraçao de email (SMTP) para envio de emails
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@quickdelivery.com.br')

# Configurações do PWA
PWA_APP_NAME = 'Quick Track'
PWA_APP_DESCRIPTION = "Aplicativo para gestão de entregas e manifestos"
PWA_APP_THEME_COLOR = '#0d6efd' # Cor azul do seu app
PWA_APP_BACKGROUND_COLOR = '#ffffff'
PWA_APP_DISPLAY = 'standalone'
PWA_APP_SCOPE = '/app/'
PWA_APP_ORIENTATION = 'portrait'
PWA_APP_START_URL = '/app/' # Página inicial do motorista
PWA_APP_STATUS_BAR_COLOR = 'default'

# Ícones (você precisará criar essas imagens na sua pasta static)
PWA_APP_ICONS = [
    {
        'src': '/static/images/icon-160x160.png',
        'sizes': '160x160'
    },
    {
        'src': '/static/images/icon-512x512.png',
        'sizes': '512x512'
    }
]

PWA_SERVICE_WORKER_PATH = 'static/js/serviceworker.js'

JAZZMIN_SETTINGS = {
    # ── Branding ──
    "site_title": "QuickTrack",
    "site_header": "QuickTrack",
    "site_brand": "QuickTrack",
    "welcome_sign": "Bem-vindo ao painel QuickTrack",
    "copyright": "Vortex Tecnologia",
    "search_model": ["manifesto.Manifesto", "manifesto.NotaFiscal", "usuarios.Motorista"],

    # ── Layout ──
    "show_ui_builder": False,
    "navigation_expanded": False,
    "topmenu_links": [
        {"name": "Início", "url": "admin:index", "permissions": ["auth.view_user"]},
    ],
    "changeform_format": "horizontal_tabs",
    "related_modal_active": True,

    # ── Organização do Menu Lateral ──
    "order_with_respect_to": [
        "configuracao",
        "manifesto",
        "usuarios",
        "sac_mobile",
        "mobile",
        "suporte",
        "tutoriais",
        "auth",
        "authtoken",
        "tenants",
        "django_celery_beat",
        "token_blacklist",
    ],

    # ── Esconder models técnicos/desnecessários ──
    "hide_apps": [
        "token_blacklist",
    ],
    "hide_models": [
        "auth.Group",
        "manifesto.WebhookTokenControl",
        "mobile.WebPushSubscription",
    ],

    # ── Ícones (Font Awesome 5) ──
    "icons": {
        # Sistema
        "auth": "fas fa-shield-alt",
        "auth.user": "fas fa-user-shield",
        "auth.Group": "fas fa-users",
        "authtoken": "fas fa-key",
        "authtoken.Token": "fas fa-key",
        "configuracao": "fas fa-sliders-h",
        "configuracao.ConfiguracaoSistema": "fas fa-cogs",

        # Tenants (Painel Global)
        "tenants": "fas fa-server",
        "tenants.Client": "fas fa-building",
        "tenants.Domain": "fas fa-globe-americas",

        # Operação de Manifestos
        "manifesto": "fas fa-shipping-fast",
        "manifesto.Manifesto": "fas fa-file-alt",
        "manifesto.NotaFiscal": "fas fa-file-invoice-dollar",
        "manifesto.BaixaNF": "fas fa-check-double",
        "manifesto.Ocorrencia": "fas fa-exclamation-triangle",
        "manifesto.HistoricoOcorrencia": "fas fa-history",
        "manifesto.ManifestoBuscaLog": "fas fa-search",
        "manifesto.WebhookEventoManifestoESL": "fas fa-satellite-dish",
        "manifesto.WebhookTokenControl": "fas fa-key",

        # Equipe & Motoristas
        "usuarios": "fas fa-users",
        "usuarios.Motorista": "fas fa-id-card",
        "usuarios.Filial": "fas fa-map-marker-alt",
        "usuarios.PermissaoUsuario": "fas fa-user-lock",
        "usuarios.PreCadastroSAC": "fas fa-user-plus",

        # SAC & Suporte
        "sac_mobile": "fas fa-headset",
        "sac_mobile.HistoricoBaixaSAC": "fas fa-clipboard-check",
        "suporte": "fas fa-life-ring",
        "suporte.TicketSuporte": "fas fa-ticket-alt",

        # Mobile & Notificações
        "mobile": "fas fa-mobile-alt",
        "mobile.BuscaDiariaManifestos": "fas fa-sync-alt",
        "mobile.ManifestoNotificado": "fas fa-bell",
        "mobile.WebPushSubscription": "fas fa-paper-plane",

        # Tutoriais
        "tutoriais": "fas fa-graduation-cap",
        "tutoriais.VideoTreinamento": "fas fa-video",

        # Celery Beat
        "django_celery_beat": "fas fa-clock",
    },
    "default_icon_parents": "fas fa-folder-open",
    "default_icon_children": "fas fa-angle-right",
}

# ── Tema Visual Escuro Premium ──
JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": True,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-dark",
    "accent": "accent-primary",
    "navbar": "navbar-dark",
    "no_navbar_border": True,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "darkly",
    "dark_mode_theme": "darkly",
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-outline-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Garante que o Django gere URLs estáticas com HTTPS quando necessário
if not DEBUG: # Ou remova o 'if' se quiser testar no ngrok agora
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


WHITENOISE_MANIFEST_STRICT = False
X_FRAME_OPTIONS = 'ALLOWALL'