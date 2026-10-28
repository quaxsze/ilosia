from urllib.parse import urlencode

from django.conf import settings


def logout_url(request):
    query = urlencode(
        {
            "client_id": settings.OIDC_RP_CLIENT_ID,
            "post_logout_redirect_uri": settings.OIDC_POST_LOGOUT_REDIRECT_URI,
        }
    )
    return f"{settings.OIDC_PUBLIC_BASE_URL}/protocol/openid-connect/logout?{query}"
