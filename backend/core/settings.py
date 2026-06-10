# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
"""
Django settings for core project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import timedelta

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

INSTALLED_APPS = [
    'daphne',                  # 1º: SEMPRE o Daphne (para habilitar ASGI)
    'channels',                # 2º: Camada de comunicação
    'unfold',                  # 3º: O Admin bonito (ele continua funcionando 100%)
    'unfold.contrib.filters',
    'unfold.contrib.forms',  
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'manifesto.apps.ManifestoConfig',
    
    
    # Terceiros
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt', # Adicionado para JWT
    'rest_framework_simplejwt.token_blacklist',
    'django_celery_beat',
    'corsheaders',
    
    'pwa',

    
    # Nossas Apps
    'usuarios',
    #'manifesto',   # CORREÇÃO: Deve ser 'manifestos' (plural)
    'mobile',
    'operacional',
    'AgenteIa',
    'configuracao',
    'suporte',
    'sac_mobile',
    'auditoria',
]
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')

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
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.mysql'),
        'NAME': os.getenv('DB_NAME', 'st63136_dev_app_transportadora'),
        'USER': os.getenv('DB_USER', 'st63136_quickdelivery'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST', 'host.docker.internal'),
        'PORT': os.getenv('DB_PORT', '3308'),
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
        },
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
TIME_ZONE = os.getenv('TIME_ZONE', 'America/Sao_Paulo')
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# CORREÇÃO CRÍTICA: Diretório onde o collectstatic vai copiar todos os arquivos
STATIC_ROOT = BASE_DIR / 'staticfiles' 
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
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


# --- Configurações JWT (JSON Web Token) ---
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=365),

    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,

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

UNFOLD = {
    "SITE_TITLE": "Quick Track",
    "SITE_HEADER": "Painel Logístico",
    "COLORS": {
        "primary": {
            "50": "250 252 255",
            "100": "240 247 255",
            "500": "13 110 253", # Seu azul padrão
            "900": "10 30 100",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
    }
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