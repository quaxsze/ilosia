import logging
from urllib.parse import urlencode, urlunsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.crypto import salted_hmac

from infrastructure.exceptions import (
    ClusterUnavailableError,
    HelmInstallError,
    HelmUninstallError,
    ServiceQuotaExceeded,
    StorageError,
)
from infrastructure.helm_client import HelmClient
from infrastructure.kubernetes_client import KubernetesClient
from infrastructure.storage_client import GarageAdminClient, StorageClient, user_bucket

from .metrics import (
    service_delete_total,
    service_launch_failed_total,
    service_launch_total,
)
from .models import ServiceEnvironmentVariable, ServiceInstance

logger = logging.getLogger(__name__)

FAILED_CONTAINER_REASONS = {
    "CrashLoopBackOff",
    "CreateContainerConfigError",
    "ErrImagePull",
    "ImagePullBackOff",
}
S3_ENVIRONMENT_NAMES = {
    "S3_ENDPOINT",
    "S3_BUCKET",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
}


def get_service_access_url(instance):
    if not instance.public_url:
        return ""
    token = salted_hmac("workloads.jupyter-token", str(instance.id)).hexdigest()
    return f"{instance.public_url}?{urlencode({'token': token})}"


def build_jupyter_values(instance, *, environment=None, secret_names=()):
    host = f"{instance.release_name}.{settings.WORKLOAD_BASE_DOMAIN}"
    return {
        "ingress": {"host": host},
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
        "environment": environment or {},
        "secretEnvironment": sorted(secret_names),
    }


def _public_url(host):
    port = settings.WORKLOAD_INGRESS_PORT
    default_port = 443 if settings.WORKLOAD_INGRESS_SCHEME == "https" else 80
    netloc = host if port == default_port else f"{host}:{port}"
    return urlunsplit((settings.WORKLOAD_INGRESS_SCHEME, netloc, "/", "", ""))


def _workload_s3_environment(user):
    if not settings.S3_ENDPOINT_URL:
        return {}
    # Serializing per user prevents two simultaneous launches from creating two keys.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        bucket = user_bucket(user)
        StorageClient().ensure_bucket(bucket)
        access_key, secret_key = GarageAdminClient().ensure_bucket_access(
            bucket=bucket,
            key_name=f"ilosia-user-{user.pk}",
            owner_access_key=settings.S3_ACCESS_KEY,
        )
    return {
        "S3_ENDPOINT": settings.S3_ENDPOINT_URL,
        "S3_BUCKET": bucket,
        "S3_ACCESS_KEY": access_key,
        "S3_SECRET_KEY": secret_key,
    }


def launch_service(*, user, definition, data):
    if definition.slug != "jupyter":
        raise ValueError(f"Unsupported service definition: {definition.slug}")

    environment = data.get("environment_variables", {})
    secrets = data.get("secret_variables", {})
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        active_services = ServiceInstance.objects.filter(user=user).exclude(
            status=ServiceInstance.Status.DELETED
        )
        if active_services.count() >= settings.MAX_SERVICES_PER_USER:
            raise ServiceQuotaExceeded(
                f"A user can run at most {settings.MAX_SERVICES_PER_USER} services."
            )

        instance = ServiceInstance(
            user=user,
            service_definition=definition,
            display_name=data["display_name"],
            cpu_units=data["cpu_units"],
            memory_mib=data["memory_gib"] * 1024,
            storage_mib=data["storage_gib"] * 1024,
            status=ServiceInstance.Status.INSTALLING,
        )
        instance.release_name = f"jupyter-{instance.id.hex}"
        instance.namespace = f"user-{user.pk}"
        host = f"{instance.release_name}.{settings.WORKLOAD_BASE_DOMAIN}"
        instance.public_url = _public_url(host)
        instance.full_clean()
        instance.save()

        ServiceEnvironmentVariable.objects.bulk_create(
            [
                ServiceEnvironmentVariable(
                    service_instance=instance,
                    name=name,
                    value=value,
                )
                for name, value in environment.items()
            ]
            + [
                ServiceEnvironmentVariable(
                    service_instance=instance,
                    name=name,
                    is_secret=True,
                )
                for name in secrets
            ]
        )

    # shortcut: launch blocks one web worker; add a job queue when launches become long-running.
    kubernetes = KubernetesClient()
    secret_created = False
    service_launch_total.inc()
    try:
        kubernetes.ensure_namespace(
            instance.namespace,
            quota=settings.USER_NAMESPACE_QUOTA,
        )
        s3_environment = _workload_s3_environment(user)
        kubernetes.create_secret(
            namespace=instance.namespace,
            name=f"{instance.release_name}-environment",
            string_data={
                "JUPYTER_TOKEN": salted_hmac(
                    "workloads.jupyter-token", str(instance.id)
                ).hexdigest(),
                **s3_environment,
                **secrets,
            },
            release_name=instance.release_name,
        )
        secret_created = True
        HelmClient().install(
            release_name=instance.release_name,
            chart_path=settings.WORKLOAD_CHART_PATH,
            namespace=instance.namespace,
            values=build_jupyter_values(
                instance,
                environment=environment,
                secret_names=secrets.keys() | s3_environment.keys(),
            ),
        )
    except (ClusterUnavailableError, HelmInstallError, StorageError):
        service_launch_failed_total.inc()
        logger.exception("Jupyter launch failed for service %s", instance.id)
        if secret_created:
            try:
                kubernetes.delete_secret(
                    namespace=instance.namespace,
                    name=f"{instance.release_name}-environment",
                )
            except ClusterUnavailableError:
                logger.exception("Secret cleanup failed for service %s", instance.id)
        instance.status = ServiceInstance.Status.FAILED
    else:
        instance.status = ServiceInstance.Status.RUNNING
    instance.save(update_fields=("status", "updated_at"))
    return instance


def refresh_service_status(instance, *, client=None):
    if instance.status in {
        ServiceInstance.Status.STOPPING,
        ServiceInstance.Status.STOPPED,
        ServiceInstance.Status.DELETING,
        ServiceInstance.Status.DELETED,
    }:
        return instance.status
    if not instance.namespace or not instance.release_name:
        return instance.status

    client = client or KubernetesClient()
    try:
        pods = client.list_pods(
            namespace=instance.namespace,
            release_name=instance.release_name,
        )
    except ClusterUnavailableError:
        logger.warning("Kubernetes status unavailable for service %s", instance.id)
        status = ServiceInstance.Status.UNKNOWN
    else:
        status = _pods_status(pods)

    if instance.status != status:
        instance.status = status
        instance.save(update_fields=("status", "updated_at"))
    return status


def _pods_status(pods):
    statuses = []
    for pod in pods:
        pod_status = pod.get("status", {})
        phase = pod_status.get("phase")
        container_statuses = pod_status.get("containerStatuses", [])
        waiting_reasons = {
            item.get("state", {}).get("waiting", {}).get("reason")
            for item in container_statuses
        }
        if (
            phase == "Running"
            and container_statuses
            and all(item.get("ready") for item in container_statuses)
        ):
            statuses.append(ServiceInstance.Status.RUNNING)
        elif phase == "Unknown":
            statuses.append(ServiceInstance.Status.UNKNOWN)
        elif phase in {"Failed", "Succeeded"} or (
            waiting_reasons & FAILED_CONTAINER_REASONS
        ):
            statuses.append(ServiceInstance.Status.FAILED)
        else:
            statuses.append(ServiceInstance.Status.INSTALLING)

    if ServiceInstance.Status.RUNNING in statuses:
        return ServiceInstance.Status.RUNNING
    if ServiceInstance.Status.FAILED in statuses:
        return ServiceInstance.Status.FAILED
    if ServiceInstance.Status.INSTALLING in statuses:
        return ServiceInstance.Status.INSTALLING
    return ServiceInstance.Status.UNKNOWN


def get_service_logs(instance):
    if not instance.namespace or not instance.release_name:
        return "This service has no Kubernetes workload."
    try:
        return KubernetesClient().get_pod_logs(
            namespace=instance.namespace,
            release_name=instance.release_name,
            tail_lines=200,
        )
    except ClusterUnavailableError:
        logger.warning("Kubernetes logs unavailable for service %s", instance.id)
        return "Logs are temporarily unavailable."


def stop_service(instance):
    if instance.status == ServiceInstance.Status.STOPPED:
        return
    if instance.status not in {
        ServiceInstance.Status.RUNNING,
        ServiceInstance.Status.UNKNOWN,
    }:
        raise ValueError("Only running services can be stopped.")

    instance.status = ServiceInstance.Status.STOPPING
    instance.save(update_fields=("status", "updated_at"))
    # shortcut: stopping blocks one web worker; add a job queue when operations become long-running.
    try:
        HelmClient().uninstall(
            release_name=instance.release_name,
            namespace=instance.namespace,
        )
    except HelmUninstallError:
        logger.exception("Jupyter stop failed for service %s", instance.id)
        instance.status = ServiceInstance.Status.UNKNOWN
        instance.save(update_fields=("status", "updated_at"))
        raise

    instance.status = ServiceInstance.Status.STOPPED
    instance.save(update_fields=("status", "updated_at"))


def restart_service(instance):
    if instance.status != ServiceInstance.Status.STOPPED:
        raise ValueError("Only stopped services can be restarted.")
    if not instance.namespace or not instance.release_name:
        raise ValueError("This service has no Kubernetes workload to restart.")

    variables = instance.environment_variables.all()
    environment = {
        variable.name: variable.value
        for variable in variables
        if not variable.is_secret
    }
    secret_names = {variable.name for variable in variables if variable.is_secret}

    instance.status = ServiceInstance.Status.INSTALLING
    instance.save(update_fields=("status", "updated_at"))
    try:
        s3_environment = _workload_s3_environment(instance.user)
        if s3_environment:
            KubernetesClient().patch_secret(
                namespace=instance.namespace,
                name=f"{instance.release_name}-environment",
                string_data=s3_environment,
            )
            secret_names.update(S3_ENVIRONMENT_NAMES)
        HelmClient().install(
            release_name=instance.release_name,
            chart_path=settings.WORKLOAD_CHART_PATH,
            namespace=instance.namespace,
            values=build_jupyter_values(
                instance,
                environment=environment,
                secret_names=secret_names,
            ),
        )
    except (ClusterUnavailableError, HelmInstallError, StorageError):
        logger.exception("Jupyter restart failed for service %s", instance.id)
        instance.status = ServiceInstance.Status.STOPPED
        instance.save(update_fields=("status", "updated_at"))
        raise

    instance.status = ServiceInstance.Status.RUNNING
    instance.save(update_fields=("status", "updated_at"))


def delete_service_and_data(instance):
    if instance.status == ServiceInstance.Status.DELETED:
        return
    if not instance.namespace or not instance.release_name:
        instance.status = ServiceInstance.Status.DELETED
        instance.save(update_fields=("status", "updated_at"))
        return

    instance.status = ServiceInstance.Status.DELETING
    instance.save(update_fields=("status", "updated_at"))
    # shortcut: deletion blocks one web worker; add a job queue when operations become long-running.
    try:
        HelmClient().uninstall(
            release_name=instance.release_name,
            namespace=instance.namespace,
        )
    except HelmUninstallError:
        logger.exception("Jupyter deletion failed for service %s", instance.id)
        instance.status = ServiceInstance.Status.UNKNOWN
        instance.save(update_fields=("status", "updated_at"))
        raise

    kubernetes = KubernetesClient()
    try:
        kubernetes.delete_persistent_volume_claim(
            namespace=instance.namespace,
            name=f"{instance.release_name}-data",
        )
        kubernetes.delete_secret(
            namespace=instance.namespace,
            name=f"{instance.release_name}-environment",
        )
    except ClusterUnavailableError:
        logger.exception("Jupyter data deletion failed for service %s", instance.id)
        instance.status = ServiceInstance.Status.UNKNOWN
        instance.save(update_fields=("status", "updated_at"))
        raise

    instance.status = ServiceInstance.Status.DELETED
    instance.save(update_fields=("status", "updated_at"))
    service_delete_total.inc()
