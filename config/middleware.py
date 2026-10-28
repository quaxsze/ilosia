from django.conf import settings


class PublicHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public_host = settings.DJANGO_PUBLIC_HOST
        if request.META.get("HTTP_X_ILOSIA_HOST") == public_host:
            request.META["HTTP_HOST"] = public_host
        return self.get_response(request)
