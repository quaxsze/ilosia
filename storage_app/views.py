from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from infrastructure.exceptions import StorageError
from infrastructure.storage_client import StorageClient, user_bucket


def _object_key(request):
    key = request.GET.get("key") or request.POST.get("key")
    if not key or len(key) > 1024:
        raise Http404
    return key


@login_required
@require_GET
def storage_list(request):
    objects = []
    if not settings.S3_ENDPOINT_URL:
        messages.warning(request, "S3 storage is not configured yet.")
    else:
        try:
            client = StorageClient()
            bucket = user_bucket(request.user)
            client.ensure_bucket(bucket)
            objects = client.list_objects(bucket)
        except StorageError:
            messages.error(request, "Storage is temporarily unavailable.")
    return render(request, "storage_app/list.html", {"objects": objects})


@login_required
@require_GET
def storage_download(request):
    key = _object_key(request)
    if not settings.S3_ENDPOINT_URL:
        messages.warning(request, "S3 storage is not configured yet.")
        return redirect("storage:list")
    try:
        url = StorageClient().generate_presigned_url(user_bucket(request.user), key)
    except StorageError:
        messages.error(request, "The download link could not be created.")
        return redirect("storage:list")
    return redirect(url)


@login_required
@require_POST
def storage_delete(request):
    key = _object_key(request)
    if not settings.S3_ENDPOINT_URL:
        messages.warning(request, "S3 storage is not configured yet.")
        return redirect("storage:list")
    try:
        StorageClient().delete_object(user_bucket(request.user), key)
    except StorageError:
        messages.error(request, "The object could not be deleted.")
    else:
        messages.success(request, f"{key} was deleted.")
    return redirect("storage:list")
