from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import ServiceDefinition
from infrastructure.exceptions import HelmInstallError, HelmUninstallError

from .models import ServiceEnvironmentVariable, ServiceInstance
from .services import _pods_status


class WorkloadViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="alice", password="correct-horse-battery-staple"
        )
        cls.other_user = user_model.objects.create_user(
            username="bob", password="another-correct-password"
        )
        cls.definition = ServiceDefinition.objects.get(slug="jupyter")

    def setUp(self):
        self.client.force_login(self.user)

    def instance_for(self, user, name):
        instance = ServiceInstance.objects.create(
            user=user,
            service_definition=self.definition,
            display_name=name,
            cpu_units=1,
            memory_mib=2048,
            storage_mib=10240,
            status=ServiceInstance.Status.RUNNING,
        )
        instance.release_name = f"jupyter-{instance.id.hex}"
        instance.namespace = f"user-{user.pk}"
        instance.public_url = f"http://{instance.release_name}.localhost:8080/"
        instance.save(
            update_fields=("release_name", "namespace", "public_url", "updated_at")
        )
        return instance

    def test_launch_requires_authentication(self):
        self.client.logout()

        response = self.client.get(
            reverse("workloads:launch", kwargs={"slug": "jupyter"})
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    @override_settings(
        S3_ENDPOINT_URL="http://s3:9000",
        S3_ACCESS_KEY="access",
        S3_SECRET_KEY="secret",
    )
    @patch("workloads.services.StorageClient")
    @patch("workloads.services.KubernetesClient")
    @patch("workloads.services.HelmClient")
    def test_valid_launch_installs_jupyter(
        self, helm_client_class, kubernetes_client_class, storage_client_class
    ):
        response = self.client.post(
            reverse("workloads:launch", kwargs={"slug": "jupyter"}),
            {
                "display_name": "my-notebook",
                "cpu_units": 2,
                "memory_gib": 4,
                "storage_gib": 10,
                "environment_variables": "MODE=development",
                "secret_variables": "OPENAI_API_KEY=super-secret",
            },
        )

        instance = ServiceInstance.objects.get()
        self.assertRedirects(
            response, reverse("workloads:detail", kwargs={"service_id": instance.id})
        )
        self.assertEqual(instance.user, self.user)
        self.assertEqual(instance.status, ServiceInstance.Status.RUNNING)
        self.assertEqual(instance.memory_mib, 4096)
        self.assertEqual(instance.storage_mib, 10240)
        self.assertEqual(instance.namespace, f"user-{self.user.pk}")
        self.assertTrue(instance.release_name.startswith("jupyter-"))
        self.assertNotIn("token", instance.public_url)
        variables = {item.name: item for item in instance.environment_variables.all()}
        self.assertEqual(variables["MODE"].value, "development")
        self.assertFalse(variables["MODE"].is_secret)
        self.assertEqual(variables["OPENAI_API_KEY"].value, "")
        self.assertTrue(variables["OPENAI_API_KEY"].is_secret)

        kubernetes = kubernetes_client_class.return_value
        storage_client_class.return_value.ensure_bucket.assert_called_once_with(
            f"user-{self.user.pk}"
        )
        kubernetes.ensure_namespace.assert_called_once_with(
            instance.namespace,
            quota={
                "requests.cpu": "20",
                "requests.memory": "40Gi",
                "requests.storage": "100Gi",
                "pods": "10",
            },
        )
        secret_call = kubernetes.create_secret.call_args.kwargs
        self.assertEqual(secret_call["namespace"], instance.namespace)
        self.assertEqual(secret_call["name"], f"{instance.release_name}-environment")
        self.assertEqual(secret_call["string_data"]["OPENAI_API_KEY"], "super-secret")
        self.assertEqual(
            secret_call["string_data"]["S3_BUCKET"], f"user-{self.user.pk}"
        )
        self.assertIn("JUPYTER_TOKEN", secret_call["string_data"])

        install_call = helm_client_class.return_value.install.call_args.kwargs
        self.assertEqual(install_call["release_name"], instance.release_name)
        self.assertEqual(install_call["namespace"], instance.namespace)
        self.assertEqual(install_call["values"]["resources"]["limits"]["cpu"], "2")
        self.assertEqual(
            install_call["values"]["resources"]["limits"]["memory"], "4096Mi"
        )
        self.assertEqual(install_call["values"]["storage"]["size"], "10240Mi")
        self.assertEqual(install_call["values"]["environment"], {"MODE": "development"})
        self.assertIn("OPENAI_API_KEY", install_call["values"]["secretEnvironment"])
        self.assertIn("S3_SECRET_KEY", install_call["values"]["secretEnvironment"])
        self.assertNotIn("super-secret", repr(install_call["values"]))

        detail_response = self.client.get(
            reverse("workloads:detail", kwargs={"service_id": instance.id})
        )
        self.assertContains(detail_response, f"{instance.public_url}?token=")
        self.assertContains(detail_response, "development")
        self.assertContains(detail_response, "Secret value hidden")
        self.assertNotContains(detail_response, "super-secret")

    @patch("workloads.services.KubernetesClient")
    @patch("workloads.services.HelmClient")
    def test_failed_helm_install_marks_instance_failed(
        self, helm_client_class, kubernetes_client_class
    ):
        helm_client_class.return_value.install.side_effect = HelmInstallError("failed")

        with self.assertLogs("workloads.services", level="ERROR"):
            response = self.client.post(
                reverse("workloads:launch", kwargs={"slug": "jupyter"}),
                {
                    "display_name": "broken-notebook",
                    "cpu_units": 1,
                    "memory_gib": 2,
                    "storage_gib": 5,
                    "secret_variables": "API_KEY=secret",
                },
            )

        instance = ServiceInstance.objects.get()
        self.assertRedirects(
            response, reverse("workloads:detail", kwargs={"service_id": instance.id})
        )
        self.assertEqual(instance.status, ServiceInstance.Status.FAILED)
        kubernetes_client_class.return_value.delete_secret.assert_called_once()

    def test_out_of_range_resources_are_rejected(self):
        invalid_values = (
            {"cpu_units": 5, "memory_gib": 4, "storage_gib": 10},
            {"cpu_units": 1, "memory_gib": 9, "storage_gib": 10},
            {"cpu_units": 1, "memory_gib": 4, "storage_gib": 21},
        )
        for values in invalid_values:
            with self.subTest(values=values):
                response = self.client.post(
                    reverse("workloads:launch", kwargs={"slug": "jupyter"}),
                    {"display_name": "invalid", **values},
                )
                self.assertEqual(response.status_code, 200)

        self.assertFalse(ServiceInstance.objects.exists())

    @override_settings(MAX_SERVICES_PER_USER=1)
    @patch("workloads.services.KubernetesClient")
    def test_user_service_quota_is_enforced_before_kubernetes(self, client_class):
        self.instance_for(self.user, "Existing notebook")

        response = self.client.post(
            reverse("workloads:launch", kwargs={"slug": "jupyter"}),
            {
                "display_name": "one-too-many",
                "cpu_units": 1,
                "memory_gib": 2,
                "storage_gib": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A user can run at most 1 services.")
        self.assertEqual(ServiceInstance.objects.count(), 1)
        client_class.assert_not_called()

    def test_blank_name_is_rejected(self):
        response = self.client.post(
            reverse("workloads:launch", kwargs={"slug": "jupyter"}),
            {
                "display_name": "   ",
                "cpu_units": 1,
                "memory_gib": 2,
                "storage_gib": 10,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceInstance.objects.exists())

    def test_name_with_unsupported_characters_is_rejected(self):
        response = self.client.post(
            reverse("workloads:launch", kwargs={"slug": "jupyter"}),
            {
                "display_name": "invalid/name",
                "cpu_units": 1,
                "memory_gib": 2,
                "storage_gib": 10,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceInstance.objects.exists())

    def test_invalid_or_duplicated_environment_variables_are_rejected(self):
        invalid_variables = (
            {"environment_variables": "INVALID-NAME=value"},
            {"environment_variables": "MISSING_EQUALS"},
            {"secret_variables": "JUPYTER_TOKEN=forbidden"},
            {
                "environment_variables": "SAME=regular",
                "secret_variables": "SAME=secret",
            },
        )
        for variables in invalid_variables:
            with self.subTest(variables=variables):
                response = self.client.post(
                    reverse("workloads:launch", kwargs={"slug": "jupyter"}),
                    {
                        "display_name": "invalid-env",
                        "cpu_units": 1,
                        "memory_gib": 2,
                        "storage_gib": 5,
                        **variables,
                    },
                )
                self.assertEqual(response.status_code, 200)

        self.assertFalse(ServiceInstance.objects.exists())

    def test_model_rejects_resources_outside_catalog_limits(self):
        instance = ServiceInstance(
            user=self.user,
            service_definition=self.definition,
            display_name="oversized",
            cpu_units=self.definition.max_cpu_units + 1,
            memory_mib=self.definition.default_memory_mib,
            storage_mib=self.definition.default_storage_mib,
        )

        with self.assertRaises(ValidationError):
            instance.full_clean()

    def test_service_list_only_displays_current_users_services(self):
        self.instance_for(self.user, "Alice notebook")
        self.instance_for(self.other_user, "Bob notebook")

        response = self.client.get(reverse("workloads:list"))

        self.assertContains(response, "Alice notebook")
        self.assertNotContains(response, "Bob notebook")

    def test_detail_shows_actions_for_the_current_state(self):
        service = self.instance_for(self.user, "Alice notebook")
        url = reverse("workloads:detail", kwargs={"service_id": service.id})

        running_response = self.client.get(url)
        self.assertContains(running_response, ">Stop<", html=False)
        self.assertNotContains(running_response, ">Restart<", html=False)

        service.status = ServiceInstance.Status.STOPPED
        service.save(update_fields=("status", "updated_at"))
        stopped_response = self.client.get(url)
        self.assertContains(stopped_response, ">Restart<", html=False)
        self.assertContains(stopped_response, "Delete service and data")
        self.assertNotContains(stopped_response, ">Stop<", html=False)

    def test_user_cannot_view_another_users_service(self):
        service = self.instance_for(self.other_user, "Bob notebook")

        response = self.client.get(
            reverse("workloads:detail", kwargs={"service_id": service.id})
        )

        self.assertEqual(response.status_code, 404)

    @patch("workloads.services.KubernetesClient")
    def test_status_endpoint_uses_kubernetes(self, client_class):
        service = self.instance_for(self.user, "Alice notebook")
        client_class.return_value.list_pods.return_value = [
            {
                "status": {
                    "phase": "Pending",
                    "containerStatuses": [{"ready": False}],
                }
            }
        ]

        response = self.client.get(
            reverse("workloads:status", kwargs={"service_id": service.id})
        )

        self.assertContains(response, "Installing")
        service.refresh_from_db()
        self.assertEqual(service.status, ServiceInstance.Status.INSTALLING)

    @patch("workloads.services.KubernetesClient")
    def test_stopped_status_does_not_query_kubernetes(self, client_class):
        service = self.instance_for(self.user, "Alice notebook")
        service.status = ServiceInstance.Status.STOPPED
        service.save(update_fields=("status", "updated_at"))

        response = self.client.get(
            reverse("workloads:status", kwargs={"service_id": service.id})
        )

        self.assertContains(response, "Stopped")
        client_class.assert_not_called()

    @patch("workloads.services.KubernetesClient")
    def test_logs_are_limited_and_html_escaped(self, client_class):
        service = self.instance_for(self.user, "Alice notebook")
        client_class.return_value.get_pod_logs.return_value = (
            "<script>alert(1)</script>"
        )

        response = self.client.get(
            reverse("workloads:logs", kwargs={"service_id": service.id}),
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "&lt;script&gt;", html=False)
        self.assertNotContains(response, "<script>alert(1)</script>", html=False)
        client_class.return_value.get_pod_logs.assert_called_once_with(
            namespace=service.namespace,
            release_name=service.release_name,
            tail_lines=200,
        )

    @patch("workloads.services.KubernetesClient")
    @patch("workloads.services.HelmClient")
    def test_stop_uninstalls_release_and_keeps_data(
        self, helm_client_class, kubernetes_client_class
    ):
        service = self.instance_for(self.user, "Alice notebook")

        response = self.client.post(
            reverse("workloads:stop", kwargs={"service_id": service.id})
        )

        self.assertRedirects(
            response, reverse("workloads:detail", kwargs={"service_id": service.id})
        )
        service.refresh_from_db()
        self.assertEqual(service.status, ServiceInstance.Status.STOPPED)
        helm_client_class.return_value.uninstall.assert_called_once_with(
            release_name=service.release_name,
            namespace=service.namespace,
        )
        kubernetes_client_class.assert_not_called()

    @patch("workloads.services.HelmClient")
    def test_failed_stop_is_reported_and_not_marked_stopped(self, helm_client_class):
        service = self.instance_for(self.user, "Alice notebook")
        helm_client_class.return_value.uninstall.side_effect = HelmUninstallError(
            "failed"
        )

        with self.assertLogs("workloads.services", level="ERROR"):
            response = self.client.post(
                reverse("workloads:stop", kwargs={"service_id": service.id})
            )

        self.assertRedirects(
            response, reverse("workloads:detail", kwargs={"service_id": service.id})
        )
        service.refresh_from_db()
        self.assertEqual(service.status, ServiceInstance.Status.UNKNOWN)

    @override_settings(S3_ENDPOINT_URL="http://s3:9000")
    @patch("workloads.services.HelmClient")
    def test_restart_reuses_release_pvc_and_environment(self, helm_client_class):
        service = self.instance_for(self.user, "Alice notebook")
        service.status = ServiceInstance.Status.STOPPED
        service.save(update_fields=("status", "updated_at"))
        ServiceEnvironmentVariable.objects.create(
            service_instance=service,
            name="MODE",
            value="development",
        )
        ServiceEnvironmentVariable.objects.create(
            service_instance=service,
            name="API_KEY",
            is_secret=True,
        )

        response = self.client.post(
            reverse("workloads:restart", kwargs={"service_id": service.id})
        )

        self.assertRedirects(
            response, reverse("workloads:detail", kwargs={"service_id": service.id})
        )
        service.refresh_from_db()
        self.assertEqual(service.status, ServiceInstance.Status.RUNNING)
        install = helm_client_class.return_value.install.call_args.kwargs
        self.assertEqual(install["release_name"], service.release_name)
        self.assertEqual(install["namespace"], service.namespace)
        self.assertEqual(install["values"]["environment"], {"MODE": "development"})
        self.assertIn("API_KEY", install["values"]["secretEnvironment"])
        self.assertIn("S3_BUCKET", install["values"]["secretEnvironment"])

    @patch("workloads.services.HelmClient")
    def test_failed_restart_remains_stopped(self, helm_client_class):
        service = self.instance_for(self.user, "Alice notebook")
        service.status = ServiceInstance.Status.STOPPED
        service.save(update_fields=("status", "updated_at"))
        helm_client_class.return_value.install.side_effect = HelmInstallError("failed")

        with self.assertLogs("workloads.services", level="ERROR"):
            response = self.client.post(
                reverse("workloads:restart", kwargs={"service_id": service.id})
            )

        self.assertRedirects(
            response, reverse("workloads:detail", kwargs={"service_id": service.id})
        )
        service.refresh_from_db()
        self.assertEqual(service.status, ServiceInstance.Status.STOPPED)

    @patch("workloads.services.KubernetesClient")
    @patch("workloads.services.HelmClient")
    def test_delete_removes_release_pvc_and_secret(
        self, helm_client_class, kubernetes_client_class
    ):
        service = self.instance_for(self.user, "Alice notebook")

        response = self.client.post(
            reverse("workloads:delete", kwargs={"service_id": service.id})
        )

        self.assertRedirects(response, reverse("workloads:list"))
        service.refresh_from_db()
        self.assertEqual(service.status, ServiceInstance.Status.DELETED)
        helm_client_class.return_value.uninstall.assert_called_once_with(
            release_name=service.release_name,
            namespace=service.namespace,
        )
        kubernetes = kubernetes_client_class.return_value
        kubernetes.delete_persistent_volume_claim.assert_called_once_with(
            namespace=service.namespace,
            name=f"{service.release_name}-data",
        )
        kubernetes.delete_secret.assert_called_once_with(
            namespace=service.namespace,
            name=f"{service.release_name}-environment",
        )

    def test_lifecycle_actions_reject_get(self):
        service = self.instance_for(self.user, "Alice notebook")

        for action in ("stop", "restart", "delete"):
            with self.subTest(action=action):
                response = self.client.get(
                    reverse(f"workloads:{action}", kwargs={"service_id": service.id})
                )
                self.assertEqual(response.status_code, 405)

    @patch("workloads.services.HelmClient")
    def test_delete_handles_an_old_database_only_service(self, helm_client_class):
        service = ServiceInstance.objects.create(
            user=self.user,
            service_definition=self.definition,
            display_name="Old notebook",
            cpu_units=1,
            memory_mib=2048,
            storage_mib=10240,
        )

        response = self.client.post(
            reverse("workloads:delete", kwargs={"service_id": service.id})
        )

        self.assertRedirects(response, reverse("workloads:list"))
        service.refresh_from_db()
        self.assertEqual(service.status, ServiceInstance.Status.DELETED)
        helm_client_class.return_value.uninstall.assert_not_called()

    @patch("workloads.views.refresh_service_status")
    @patch("workloads.services.HelmClient")
    def test_user_cannot_manage_another_users_service(
        self, helm_client_class, refresh_service_status
    ):
        service = self.instance_for(self.other_user, "Bob notebook")
        urls = (
            reverse("workloads:status", kwargs={"service_id": service.id}),
            reverse("workloads:logs", kwargs={"service_id": service.id}),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

        for action in ("stop", "restart", "delete"):
            with self.subTest(action=action):
                response = self.client.post(
                    reverse(f"workloads:{action}", kwargs={"service_id": service.id})
                )
                self.assertEqual(response.status_code, 404)
        helm_client_class.return_value.uninstall.assert_not_called()
        refresh_service_status.assert_not_called()


class PodStatusTests(TestCase):
    def test_pod_status_mapping(self):
        cases = (
            ([], ServiceInstance.Status.UNKNOWN),
            (
                [{"status": {"phase": "Pending"}}],
                ServiceInstance.Status.INSTALLING,
            ),
            (
                [{"status": {"phase": "Unknown"}}],
                ServiceInstance.Status.UNKNOWN,
            ),
            (
                [
                    {
                        "status": {
                            "phase": "Running",
                            "containerStatuses": [{"ready": True}],
                        }
                    }
                ],
                ServiceInstance.Status.RUNNING,
            ),
            (
                [
                    {
                        "status": {
                            "phase": "Pending",
                            "containerStatuses": [
                                {
                                    "ready": False,
                                    "state": {
                                        "waiting": {"reason": "ImagePullBackOff"}
                                    },
                                }
                            ],
                        }
                    }
                ],
                ServiceInstance.Status.FAILED,
            ),
        )
        for pods, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(_pods_status(pods), expected)
