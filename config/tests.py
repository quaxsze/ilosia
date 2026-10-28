from django.test import RequestFactory, SimpleTestCase, override_settings

from .middleware import PublicHostMiddleware


class PublicHostMiddlewareTests(SimpleTestCase):
    @override_settings(
        ALLOWED_HOSTS=["ilosia.localhost"],
        DJANGO_PUBLIC_HOST="ilosia.localhost:8080",
    )
    def test_uses_the_configured_public_host_from_the_ingress(self):
        request = RequestFactory().get("/", HTTP_X_ILOSIA_HOST="ilosia.localhost:8080")

        PublicHostMiddleware(lambda received: received)(request)

        self.assertEqual(request.get_host(), "ilosia.localhost:8080")
