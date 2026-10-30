from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from catalog.models import ServiceDefinition
from infrastructure.exceptions import (
    ClusterUnavailableError,
    HelmInstallError,
    HelmUninstallError,
    ServiceQuotaExceeded,
    StorageError,
)

from .forms import LaunchServiceForm
from .models import ServiceInstance
from .services import (
    delete_service_and_data,
    get_service_access_url,
    get_service_logs,
    launch_service,
    refresh_service_status,
    restart_service,
    stop_service,
)


@login_required
def launch(request, slug):
    definition = get_object_or_404(ServiceDefinition, slug=slug, is_enabled=True)
    form = LaunchServiceForm(
        request.POST or None,
        definition=definition,
    )
    if request.method == "POST" and form.is_valid():
        try:
            instance = launch_service(
                user=request.user,
                definition=definition,
                data=form.cleaned_data,
            )
        except (ServiceQuotaExceeded, ValueError) as error:
            form.add_error(None, str(error))
            return render(
                request,
                "workloads/launch.html",
                {"definition": definition, "form": form},
            )
        if instance.status in {
            ServiceInstance.Status.FAILED,
            ServiceInstance.Status.UNKNOWN,
        }:
            messages.error(request, "The service could not be launched.")
        else:
            messages.success(request, f"{instance.display_name} is running.")
        return redirect("workloads:detail", service_id=instance.id)

    return render(
        request,
        "workloads/launch.html",
        {"definition": definition, "form": form},
    )


@login_required
def service_list(request):
    services = ServiceInstance.objects.filter(user=request.user).select_related(
        "service_definition"
    )
    return render(request, "workloads/list.html", {"services": services})


@login_required
def service_detail(request, service_id):
    service = get_object_or_404(
        ServiceInstance.objects.select_related("service_definition").prefetch_related(
            "environment_variables"
        ),
        id=service_id,
        user=request.user,
    )
    open_url = ""
    if service.status == ServiceInstance.Status.RUNNING:
        open_url = get_service_access_url(service)
    agent_access = None
    if service.service_definition.slug == "agent-workspace":
        agent_access = {
            "alias": f"ilosia-{service.id.hex[:8]}",
            "host": settings.WARPGATE_SSH_HOST,
            "port": settings.WARPGATE_SSH_PORT,
            "user": f"u-{request.user.pk}:aw-{service.id.hex}",
        }
    return render(
        request,
        "workloads/detail.html",
        {"service": service, "open_url": open_url, "agent_access": agent_access},
    )


@login_required
@require_GET
def service_status(request, service_id):
    service = get_object_or_404(
        ServiceInstance.objects.select_related("service_definition"),
        id=service_id,
        user=request.user,
    )
    refresh_service_status(service)
    open_url = ""
    if service.status == ServiceInstance.Status.RUNNING:
        open_url = get_service_access_url(service)
    if request.GET.get("badge"):
        return render(
            request,
            "workloads/components/status_badge.html",
            {"service": service},
        )
    return render(
        request,
        "workloads/components/status.html",
        {"service": service, "open_url": open_url},
    )


@login_required
@require_GET
def service_logs(request, service_id):
    service = get_object_or_404(
        ServiceInstance.objects.select_related("service_definition"),
        id=service_id,
        user=request.user,
    )
    if request.headers.get("HX-Request"):
        return render(
            request,
            "workloads/components/logs.html",
            {"service": service, "logs": get_service_logs(service)},
        )
    return render(request, "workloads/logs.html", {"service": service})


@login_required
@require_POST
def service_stop(request, service_id):
    service = get_object_or_404(
        ServiceInstance,
        id=service_id,
        user=request.user,
    )
    try:
        stop_service(service)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect("workloads:detail", service_id=service.id)
    except HelmUninstallError:
        messages.error(request, "The service could not be stopped.")
        return redirect("workloads:detail", service_id=service.id)

    messages.success(request, f"{service.display_name} was stopped. Its data was kept.")
    return redirect("workloads:detail", service_id=service.id)


@login_required
@require_POST
def service_restart(request, service_id):
    service = get_object_or_404(
        ServiceInstance,
        id=service_id,
        user=request.user,
    )
    try:
        restart_service(service)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect("workloads:detail", service_id=service.id)
    except (ClusterUnavailableError, HelmInstallError, StorageError):
        messages.error(request, "The service could not be restarted.")
        return redirect("workloads:detail", service_id=service.id)

    messages.success(request, f"{service.display_name} is running again.")
    return redirect("workloads:detail", service_id=service.id)


@login_required
@require_POST
def service_delete(request, service_id):
    service = get_object_or_404(
        ServiceInstance,
        id=service_id,
        user=request.user,
    )
    try:
        delete_service_and_data(service)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect("workloads:detail", service_id=service.id)
    except (ClusterUnavailableError, HelmUninstallError):
        messages.error(request, "The service and its data could not be deleted.")
        return redirect("workloads:detail", service_id=service.id)

    messages.success(request, f"{service.display_name} and its data were deleted.")
    return redirect("workloads:list")
