from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import ServiceDefinition


@login_required
def catalog_list(request):
    services = ServiceDefinition.objects.filter(is_enabled=True)
    return render(request, "catalog/list.html", {"services": services})
