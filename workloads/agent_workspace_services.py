import logging

from django.conf import settings

from accounts.models import OidcIdentity
from infrastructure.exceptions import (
    ClusterUnavailableError,
    HelmInstallError,
    HelmUninstallError,
    WarpgateError,
)
from infrastructure.helm_client import HelmClient
from infrastructure.kubernetes_client import KubernetesClient
from infrastructure.warpgate_client import WarpgateClient

from .metrics import service_launch_failed_total, service_launch_total
from .models import ServiceInstance
from .services import _create_service_instance

logger = logging.getLogger(__name__)


def build_agent_workspace_values(instance, user):
    return {
        "image": {
            "repository": settings.AGENT_WORKSPACE_IMAGE_REPOSITORY,
            "tag": settings.AGENT_WORKSPACE_IMAGE_TAG,
            "pullPolicy": settings.AGENT_WORKSPACE_IMAGE_PULL_POLICY,
        },
        "repository": {"url": instance.repository_url},
        "git": {
            "userName": user.get_full_name() or user.get_username(),
            "userEmail": user.email,
        },
        "warpgate": {"publicKeys": settings.WARPGATE_PUBLIC_KEYS},
        "resources": {
            "requests": {
                "cpu": str(instance.cpu_units),
                "memory": f"{instance.memory_mib}Mi",
            },
            "limits": {
                "cpu": str(instance.cpu_units),
                "memory": f"{instance.memory_mib}Mi",
            },
        },
        "storage": {"size": f"{instance.storage_mib}Mi"},
    }


def launch_agent_workspace(*, user, definition, data):
    if not user.email or not OidcIdentity.objects.filter(user=user).exists():
        raise ValueError("Agent Workspace requires a verified Keycloak account.")
    if not settings.WARPGATE_PUBLIC_KEYS:
        raise ValueError("Agent Workspace remote access is not configured.")

    instance = _create_service_instance(
        user=user,
        definition=definition,
        data=data,
        release_prefix="agent",
    )

    service_launch_total.inc()
    helm_started = False
    kubernetes = KubernetesClient()
    helm = HelmClient()
    try:
        gateway = WarpgateClient()
        gateway_user = gateway.ensure_user(
            username=f"u-{user.pk}", description=f"Ilosia user {user.pk}"
        )
        gateway.ensure_sso_credential(
            user=gateway_user,
            provider=settings.WARPGATE_SSO_PROVIDER,
            email=user.email,
        )
        role = gateway.ensure_role(
            name=f"ilosia-user-{user.pk}",
            description=f"Ilosia Agent Workspaces for user {user.pk}",
        )
        gateway.ensure_user_role(user=gateway_user, role=role)
        kubernetes.ensure_namespace(
            instance.namespace, quota=settings.USER_NAMESPACE_QUOTA
        )
        helm_started = True
        helm.install(
            release_name=instance.release_name,
            chart_path=settings.AGENT_WORKSPACE_CHART_PATH,
            namespace=instance.namespace,
            values=build_agent_workspace_values(instance, user),
        )
        target = gateway.ensure_ssh_target(
            name=f"aw-{instance.id.hex}",
            host=f"{instance.release_name}.{instance.namespace}.svc.cluster.local",
            description=f"Ilosia Agent Workspace {instance.id}",
        )
        gateway.ensure_target_role(target=target, role=role)
    except (ClusterUnavailableError, HelmInstallError, WarpgateError):
        service_launch_failed_total.inc()
        logger.exception("Agent Workspace launch failed for service %s", instance.id)
        instance.status = ServiceInstance.Status.FAILED
        if helm_started:
            try:
                helm.uninstall(
                    release_name=instance.release_name,
                    namespace=instance.namespace,
                )
            except HelmUninstallError:
                logger.exception(
                    "Agent Workspace rollback failed for service %s", instance.id
                )
                instance.status = ServiceInstance.Status.UNKNOWN
    else:
        instance.status = ServiceInstance.Status.RUNNING
    instance.save(update_fields=("status", "updated_at"))
    return instance
