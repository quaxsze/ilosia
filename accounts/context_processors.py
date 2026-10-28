from django.conf import settings


def oidc(request):
    return {"oidc_enabled": settings.OIDC_ENABLED}
