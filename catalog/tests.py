from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import ServiceDefinition


class HealthCheckTests(SimpleTestCase):
    def test_health_check_does_not_require_authentication(self):
        response = self.client.get(reverse("healthz"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_metrics_do_not_require_authentication(self):
        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "django_http_requests_before_middlewares_total")
        self.assertContains(response, "ilosia_service_launch_total")


class CatalogViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="alice", password="correct-horse-battery-staple"
        )

    def test_catalog_requires_authentication(self):
        response = self.client.get(reverse("catalog:list"))

        self.assertRedirects(response, f"{reverse('login')}?next=/catalog/")

    def test_catalog_only_displays_enabled_services(self):
        ServiceDefinition.objects.create(
            slug="disabled",
            name="Disabled service",
            description="Should not be visible",
            default_cpu_units=1,
            min_cpu_units=1,
            max_cpu_units=1,
            default_memory_mib=1024,
            min_memory_mib=1024,
            max_memory_mib=1024,
            default_storage_mib=1024,
            min_storage_mib=1024,
            max_storage_mib=1024,
            is_enabled=False,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("catalog:list"))

        self.assertContains(response, "JupyterLab")
        self.assertContains(response, "Agent Workspace")
        self.assertNotContains(response, "Disabled service")


class ServiceDefinitionModelTests(TestCase):
    def test_memory_and_storage_require_whole_gib_values(self):
        definition = ServiceDefinition(
            slug="invalid-units",
            name="Invalid units",
            default_cpu_units=1,
            min_cpu_units=1,
            max_cpu_units=1,
            default_memory_mib=1536,
            min_memory_mib=1024,
            max_memory_mib=2048,
            default_storage_mib=1024,
            min_storage_mib=1024,
            max_storage_mib=1024,
        )

        with self.assertRaises(ValidationError):
            definition.full_clean()
