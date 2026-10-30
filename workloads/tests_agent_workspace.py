from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import OidcIdentity
from catalog.models import ServiceDefinition
from infrastructure.exceptions import (
    ClusterUnavailableError,
    HelmInstallError,
    HelmUninstallError,
    WarpgateError,
)

from .models import ServiceInstance
from .services import get_service_logs, refresh_service_status


@override_settings(
    WARPGATE_PUBLIC_KEYS=["ssh-ed25519 test warpgate"],
    AGENT_WORKSPACE_IMAGE_REPOSITORY="ilosia-agent-workspace",
    AGENT_WORKSPACE_IMAGE_TAG="test",
    AGENT_WORKSPACE_IMAGE_PULL_POLICY="Never",
)
class AgentWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="alice", email="alice@example.com", password="password"
        )
        OidcIdentity.objects.create(user=cls.user, subject="keycloak-alice")
        cls.definition = ServiceDefinition.objects.get(slug="agent-workspace")

    def setUp(self):
        self.client.force_login(self.user)

    def launch_data(self):
        return {
            "display_name": "project agents",
            "repository_url": "https://github.com/quaxsze/ilosia.git",
            "cpu_units": 2,
            "memory_gib": 4,
            "storage_gib": 20,
        }

    def gateway(self, gateway_class):
        gateway = gateway_class.return_value
        gateway.ensure_user.return_value = {"id": "user-id"}
        gateway.ensure_role.return_value = {"id": "role-id"}
        gateway.ensure_ssh_target.return_value = {"id": "target-id"}
        return gateway

    @patch("workloads.agent_workspace_services.HelmClient")
    @patch("workloads.agent_workspace_services.KubernetesClient")
    @patch("workloads.agent_workspace_services.WarpgateClient")
    def test_launch_installs_workspace_and_configures_remote_access(
        self, gateway_class, kubernetes_class, helm_class
    ):
        gateway = self.gateway(gateway_class)

        response = self.client.post(
            reverse("workloads:launch", kwargs={"slug": "agent-workspace"}),
            self.launch_data(),
        )

        instance = ServiceInstance.objects.get()
        self.assertRedirects(
            response, reverse("workloads:detail", kwargs={"service_id": instance.id})
        )
        self.assertEqual(instance.status, ServiceInstance.Status.RUNNING)
        self.assertEqual(instance.repository_url, self.launch_data()["repository_url"])
        self.assertEqual(instance.release_name, f"agent-{instance.id.hex}")
        self.assertEqual(instance.namespace, f"user-{self.user.pk}")
        gateway.ensure_user.assert_called_once_with(
            username=f"u-{self.user.pk}", description=f"Ilosia user {self.user.pk}"
        )
        gateway.ensure_sso_credential.assert_called_once_with(
            user={"id": "user-id"}, provider="keycloak-aw0", email=self.user.email
        )
        gateway.ensure_ssh_target.assert_called_once_with(
            name=f"aw-{instance.id.hex}",
            host=f"{instance.release_name}.{instance.namespace}.svc.cluster.local",
            description=f"Ilosia Agent Workspace {instance.id}",
        )
        install = helm_class.return_value.install.call_args.kwargs
        self.assertEqual(install["release_name"], instance.release_name)
        self.assertEqual(
            install["values"]["repository"]["url"], instance.repository_url
        )
        self.assertEqual(
            install["values"]["warpgate"]["publicKeys"], ["ssh-ed25519 test warpgate"]
        )
        self.assertEqual(install["values"]["resources"]["limits"]["memory"], "4096Mi")

        detail = self.client.get(response.url)
        self.assertContains(detail, f"u-{self.user.pk}:aw-{instance.id.hex}")
        self.assertContains(detail, "ControlPersist 10m")
        self.assertContains(detail, "codex login --device-auth")
        self.assertContains(detail, "danger-full-access")

    def test_repository_url_is_restricted_to_public_github_https(self):
        invalid_urls = (
            "http://github.com/quaxsze/ilosia",
            "https://gitlab.com/quaxsze/ilosia",
            "https://user:pass@github.com/quaxsze/ilosia",
            "https://github.com:444/quaxsze/ilosia",
            "https://github.com/quaxsze/ilosia?ref=main",
            "https://github.com/quaxsze/ilosia#readme",
            "https://127.0.0.1/quaxsze/ilosia",
        )
        for repository_url in invalid_urls:
            with self.subTest(repository_url=repository_url):
                data = self.launch_data() | {"repository_url": repository_url}
                response = self.client.post(
                    reverse("workloads:launch", kwargs={"slug": "agent-workspace"}),
                    data,
                )
                self.assertEqual(response.status_code, 200)
        self.assertFalse(ServiceInstance.objects.exists())

    @patch("workloads.agent_workspace_services.HelmClient")
    @patch("workloads.agent_workspace_services.KubernetesClient")
    @patch("workloads.agent_workspace_services.WarpgateClient")
    def test_warpgate_failure_after_helm_rolls_back_workload(
        self, gateway_class, kubernetes_class, helm_class
    ):
        gateway = self.gateway(gateway_class)
        gateway.ensure_ssh_target.side_effect = WarpgateError("unavailable")

        with self.assertLogs("workloads.agent_workspace_services", level="ERROR"):
            self.client.post(
                reverse("workloads:launch", kwargs={"slug": "agent-workspace"}),
                self.launch_data(),
            )

        instance = ServiceInstance.objects.get()
        self.assertEqual(instance.status, ServiceInstance.Status.FAILED)
        helm_class.return_value.uninstall.assert_called_once_with(
            release_name=instance.release_name, namespace=instance.namespace
        )

    @patch("workloads.agent_workspace_services.HelmClient")
    @patch("workloads.agent_workspace_services.KubernetesClient")
    @patch("workloads.agent_workspace_services.WarpgateClient")
    def test_warpgate_failure_before_helm_creates_no_workload(
        self, gateway_class, kubernetes_class, helm_class
    ):
        gateway_class.return_value.ensure_user.side_effect = WarpgateError("failed")

        with self.assertLogs("workloads.agent_workspace_services", level="ERROR"):
            self.client.post(
                reverse("workloads:launch", kwargs={"slug": "agent-workspace"}),
                self.launch_data(),
            )

        self.assertEqual(
            ServiceInstance.objects.get().status, ServiceInstance.Status.FAILED
        )
        kubernetes_class.return_value.ensure_namespace.assert_not_called()
        helm_class.return_value.install.assert_not_called()
        helm_class.return_value.uninstall.assert_not_called()

    @patch("workloads.agent_workspace_services.HelmClient")
    @patch("workloads.agent_workspace_services.KubernetesClient")
    @patch("workloads.agent_workspace_services.WarpgateClient")
    def test_failed_rollback_marks_workspace_unknown(
        self, gateway_class, kubernetes_class, helm_class
    ):
        gateway = self.gateway(gateway_class)
        gateway.ensure_ssh_target.side_effect = WarpgateError("unavailable")
        helm_class.return_value.uninstall.side_effect = HelmUninstallError("failed")

        with self.assertLogs("workloads.agent_workspace_services", level="ERROR"):
            self.client.post(
                reverse("workloads:launch", kwargs={"slug": "agent-workspace"}),
                self.launch_data(),
            )

        self.assertEqual(
            ServiceInstance.objects.get().status, ServiceInstance.Status.UNKNOWN
        )

    @patch("workloads.agent_workspace_services.HelmClient")
    @patch("workloads.agent_workspace_services.KubernetesClient")
    @patch("workloads.agent_workspace_services.WarpgateClient")
    def test_helm_failure_runs_explicit_rollback(
        self, gateway_class, kubernetes_class, helm_class
    ):
        self.gateway(gateway_class)
        helm_class.return_value.install.side_effect = HelmInstallError("failed")

        with self.assertLogs("workloads.agent_workspace_services", level="ERROR"):
            self.client.post(
                reverse("workloads:launch", kwargs={"slug": "agent-workspace"}),
                self.launch_data(),
            )

        instance = ServiceInstance.objects.get()
        self.assertEqual(instance.status, ServiceInstance.Status.FAILED)
        helm_class.return_value.uninstall.assert_called_once_with(
            release_name=instance.release_name, namespace=instance.namespace
        )

    @patch("workloads.services.KubernetesClient")
    def test_logs_use_workspace_container(self, kubernetes_class):
        instance = ServiceInstance.objects.create(
            user=self.user,
            service_definition=self.definition,
            display_name="workspace",
            cpu_units=2,
            memory_mib=4096,
            storage_mib=20480,
            repository_url="https://github.com/quaxsze/ilosia",
            release_name="agent-123",
            namespace=f"user-{self.user.pk}",
        )
        get_service_logs(instance)
        kubernetes_class.return_value.get_pod_logs.assert_called_once_with(
            namespace=instance.namespace,
            release_name=instance.release_name,
            container_name="workspace",
            tail_lines=200,
        )

    @patch("workloads.services.HelmClient")
    def test_jupyter_lifecycle_routes_cannot_mutate_workspace(self, helm_class):
        instance = ServiceInstance.objects.create(
            user=self.user,
            service_definition=self.definition,
            display_name="workspace",
            cpu_units=2,
            memory_mib=4096,
            storage_mib=20480,
            repository_url="https://github.com/quaxsze/ilosia",
            release_name="agent-123",
            namespace=f"user-{self.user.pk}",
            status=ServiceInstance.Status.RUNNING,
        )
        for action in ("stop", "restart", "delete"):
            with self.subTest(action=action):
                response = self.client.post(
                    reverse(f"workloads:{action}", kwargs={"service_id": instance.id})
                )
                self.assertRedirects(
                    response,
                    reverse("workloads:detail", kwargs={"service_id": instance.id}),
                )
        helm_class.assert_not_called()

    def test_cluster_outage_is_not_persisted(self):
        instance = ServiceInstance.objects.create(
            user=self.user,
            service_definition=self.definition,
            display_name="workspace",
            cpu_units=2,
            memory_mib=4096,
            storage_mib=20480,
            repository_url="https://github.com/quaxsze/ilosia",
            release_name="agent-123",
            namespace=f"user-{self.user.pk}",
            status=ServiceInstance.Status.RUNNING,
        )
        client = Mock()
        client.list_pods.side_effect = ClusterUnavailableError()

        self.assertEqual(
            refresh_service_status(instance, client=client),
            ServiceInstance.Status.UNKNOWN,
        )
        instance.refresh_from_db()
        self.assertEqual(instance.status, ServiceInstance.Status.RUNNING)
