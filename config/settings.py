import json
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes"}

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DEBUG is false")
    SECRET_KEY = "insecure-development-key"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"
    ).split(",")
    if host.strip()
]
if pod_ip := os.getenv("POD_IP"):
    ALLOWED_HOSTS.append(pod_ip)
DJANGO_PUBLIC_HOST = os.getenv("DJANGO_PUBLIC_HOST", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_prometheus",
    "mozilla_django_oidc",
    "accounts",
    "catalog",
    "storage_app",
    "workloads",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "config.middleware.PublicHostMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.oidc",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django_prometheus.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "ilosia"),
        "USER": os.getenv("POSTGRES_USER", "ilosia"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "ilosia"),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "55432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "catalog:list"
LOGOUT_REDIRECT_URL = "login"

OIDC_ENABLED = os.getenv("OIDC_ENABLED", "false").lower() in {"1", "true", "yes"}
OIDC_PUBLIC_BASE_URL = os.getenv("OIDC_PUBLIC_BASE_URL", "").rstrip("/")
OIDC_INTERNAL_BASE_URL = os.getenv(
    "OIDC_INTERNAL_BASE_URL", OIDC_PUBLIC_BASE_URL
).rstrip("/")
OIDC_REALM = os.getenv("OIDC_REALM", "ilosia")
OIDC_REALM_PUBLIC_URL = f"{OIDC_PUBLIC_BASE_URL}/realms/{OIDC_REALM}"
OIDC_REALM_INTERNAL_URL = f"{OIDC_INTERNAL_BASE_URL}/realms/{OIDC_REALM}"
OIDC_RP_CLIENT_ID = os.getenv("OIDC_RP_CLIENT_ID", "ilosia")
OIDC_RP_CLIENT_SECRET = os.getenv("OIDC_RP_CLIENT_SECRET", "")
if OIDC_ENABLED and not all(
    (OIDC_PUBLIC_BASE_URL, OIDC_INTERNAL_BASE_URL, OIDC_RP_CLIENT_SECRET)
):
    raise ImproperlyConfigured(
        "OIDC public/internal URLs and client secret are required when OIDC is enabled"
    )
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_OP_AUTHORIZATION_ENDPOINT = f"{OIDC_REALM_PUBLIC_URL}/protocol/openid-connect/auth"
OIDC_OP_TOKEN_ENDPOINT = f"{OIDC_REALM_INTERNAL_URL}/protocol/openid-connect/token"
OIDC_OP_USER_ENDPOINT = f"{OIDC_REALM_INTERNAL_URL}/protocol/openid-connect/userinfo"
OIDC_OP_JWKS_ENDPOINT = f"{OIDC_REALM_INTERNAL_URL}/protocol/openid-connect/certs"
OIDC_USE_PKCE = True
OIDC_TIMEOUT = 5
OIDC_OP_LOGOUT_URL_METHOD = "accounts.oidc.logout_url"
OIDC_POST_LOGOUT_REDIRECT_URI = os.getenv(
    "OIDC_POST_LOGOUT_REDIRECT_URI", "http://ilosia.localhost:8080/login/"
)
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
if OIDC_ENABLED:
    AUTHENTICATION_BACKENDS.append("accounts.backends.KeycloakAuthenticationBackend")

JUPYTER_CHART_PATH = BASE_DIR / "charts" / "jupyter"
AGENT_WORKSPACE_CHART_PATH = BASE_DIR / "charts" / "agent-workspace"
WORKLOAD_CHART_PATH = JUPYTER_CHART_PATH
WORKLOAD_BASE_DOMAIN = os.getenv("WORKLOAD_BASE_DOMAIN", "localhost")
WORKLOAD_INGRESS_SCHEME = os.getenv("WORKLOAD_INGRESS_SCHEME", "http")
WORKLOAD_INGRESS_PORT = int(os.getenv("WORKLOAD_INGRESS_PORT", "8080"))
MAX_SERVICES_PER_USER = int(os.getenv("MAX_SERVICES_PER_USER", "5"))
USER_NAMESPACE_QUOTA = {
    "requests.cpu": os.getenv("USER_QUOTA_CPU", "20"),
    "requests.memory": os.getenv("USER_QUOTA_MEMORY", "40Gi"),
    "requests.storage": os.getenv("USER_QUOTA_STORAGE", "100Gi"),
    "pods": os.getenv("USER_QUOTA_PODS", "10"),
}

WARPGATE_URL = os.getenv(
    "WARPGATE_URL", "https://warpgate.warpgate.svc.cluster.local:8888"
)
WARPGATE_API_TOKEN = os.getenv("WARPGATE_API_TOKEN", "")
WARPGATE_CA_BUNDLE = os.getenv("WARPGATE_CA_BUNDLE", "")
WARPGATE_SSO_PROVIDER = os.getenv("WARPGATE_SSO_PROVIDER", "keycloak-aw0")
WARPGATE_SSH_HOST = os.getenv("WARPGATE_SSH_HOST", "127.0.0.1")
WARPGATE_SSH_PORT = int(os.getenv("WARPGATE_SSH_PORT", "2222"))
try:
    WARPGATE_PUBLIC_KEYS = json.loads(os.getenv("WARPGATE_PUBLIC_KEYS", "[]"))
except json.JSONDecodeError as error:
    raise ImproperlyConfigured("WARPGATE_PUBLIC_KEYS must be a JSON array") from error
if not isinstance(WARPGATE_PUBLIC_KEYS, list) or not all(
    isinstance(key, str) for key in WARPGATE_PUBLIC_KEYS
):
    raise ImproperlyConfigured("WARPGATE_PUBLIC_KEYS must be a JSON array of strings")
AGENT_WORKSPACE_IMAGE_REPOSITORY = os.getenv(
    "AGENT_WORKSPACE_IMAGE_REPOSITORY", "ilosia-agent-workspace"
)
AGENT_WORKSPACE_IMAGE_TAG = os.getenv("AGENT_WORKSPACE_IMAGE_TAG", "dev")
AGENT_WORKSPACE_IMAGE_PULL_POLICY = os.getenv(
    "AGENT_WORKSPACE_IMAGE_PULL_POLICY", "Never"
)

S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
S3_PUBLIC_ENDPOINT_URL = os.getenv("S3_PUBLIC_ENDPOINT_URL", "")
S3_BROWSER_ENDPOINT_URL = os.getenv("S3_BROWSER_ENDPOINT_URL", "")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
GARAGE_ADMIN_ENDPOINT_URL = os.getenv("GARAGE_ADMIN_ENDPOINT_URL", "")
GARAGE_ADMIN_TOKEN = os.getenv("GARAGE_ADMIN_TOKEN", "")
