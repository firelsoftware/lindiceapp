"""Configuracoes principais do projeto."""

import os
from pathlib import Path

# Caminho base usado para localizar arquivos do projeto.
BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)

    if value is None:
        return default

    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name, default=0):
    value = os.environ.get(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def env_list(name, default=None):
    value = os.environ.get(name)

    if not value:
        return default or []

    return [item.strip() for item in value.split(",") if item.strip()]


# Chave interna do Django. Em producao, deve vir de variavel de ambiente.
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-c-2qn2n(^^!xr7maaxn#f7ry_lspwh#m+#b-qgp5&+2jdi_$zy",
)

# Modo de desenvolvimento. Deve ser False em producao.
DEBUG = env_bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if not DEBUG:
    production_allowed_hosts = [".onrender.com", ".lindice.com.br", "app.lindice.com.br"]
    production_csrf_origins = [
        "https://*.onrender.com",
        "https://*.lindice.com.br",
        "https://app.lindice.com.br",
    ]

    for host in production_allowed_hosts:
        if host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host)

    for origin in production_csrf_origins:
        if origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(origin)


# Aplicativos habilitados no projeto.

INSTALLED_APPS = [
    "accounts",

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"
CSRF_FAILURE_VIEW = "accounts.views.csrf_failure"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Banco de dados usado pelo projeto.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    import dj_database_url

    DATABASES["default"] = dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )


# Regras de validacao para senhas dos usuarios.

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Idioma e fuso horario do sistema.

LANGUAGE_CODE = "pt-br"

TIME_ZONE = "America/Sao_Paulo"

USE_I18N = True

USE_TZ = True


# Arquivos estaticos do projeto.

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "")
SUPABASE_STORAGE_ENDPOINT_URL = os.environ.get("SUPABASE_STORAGE_ENDPOINT_URL", "")
SUPABASE_S3_ACCESS_KEY_ID = os.environ.get("SUPABASE_S3_ACCESS_KEY_ID", "")
SUPABASE_S3_SECRET_ACCESS_KEY = os.environ.get("SUPABASE_S3_SECRET_ACCESS_KEY", "")
SUPABASE_STORAGE_REGION = os.environ.get("SUPABASE_STORAGE_REGION", "")

USE_SUPABASE_STORAGE = all(
    [
        SUPABASE_STORAGE_BUCKET,
        SUPABASE_STORAGE_ENDPOINT_URL,
        SUPABASE_S3_ACCESS_KEY_ID,
        SUPABASE_S3_SECRET_ACCESS_KEY,
        SUPABASE_STORAGE_REGION,
    ]
)

STATICFILES_BACKEND = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
    if not DEBUG
    else "django.contrib.staticfiles.storage.StaticFilesStorage"
)

if USE_SUPABASE_STORAGE:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": SUPABASE_STORAGE_BUCKET,
                "endpoint_url": SUPABASE_STORAGE_ENDPOINT_URL,
                "region_name": SUPABASE_STORAGE_REGION,
                "access_key": SUPABASE_S3_ACCESS_KEY_ID,
                "secret_key": SUPABASE_S3_SECRET_ACCESS_KEY,
                "addressing_style": "path",
                "signature_version": "s3v4",
                "default_acl": None,
                "file_overwrite": False,
                "querystring_auth": True,
                "querystring_expire": 3600,
                "object_parameters": {
                    "CacheControl": "max-age=86400",
                },
            },
        },
        "staticfiles": {
            "BACKEND": STATICFILES_BACKEND,
        },
    }
elif not DEBUG:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": STATICFILES_BACKEND,
        },
    }

AUTH_USER_MODEL = "accounts.User"

LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
LOGIN_URL = "login"
CPF_HASH_SECRET = SECRET_KEY
SHOE_SUPPLIER_CATALOG_URL = os.environ.get("SHOE_SUPPLIER_CATALOG_URL", "")
SHOE_SUPPLIER_CATALOG_FORMAT = os.environ.get("SHOE_SUPPLIER_CATALOG_FORMAT", "csv")
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN", "")
PUBLIC_SITE_URL = os.environ.get("PUBLIC_SITE_URL", "")
STORE_CONTACT_EMAIL = os.environ.get("STORE_CONTACT_EMAIL", "lindicecalcados@gmail.com")
STORE_RESPONSIBLE_NAME = os.environ.get("STORE_RESPONSIBLE_NAME", "Fabrício Pereira da Silva Alves")
PHONE_VERIFICATION_REQUIRED = env_bool("PHONE_VERIFICATION_REQUIRED", default=True)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", default=0 if DEBUG else 3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
