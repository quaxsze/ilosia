from django.contrib import admin

from .models import ServiceInstance


@admin.register(ServiceInstance)
class ServiceInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "service_definition",
        "user",
        "status",
        "created_at",
    )
    list_filter = ("status", "service_definition")
    search_fields = ("display_name", "user__username")
    readonly_fields = (
        "id",
        "release_name",
        "namespace",
        "public_url",
        "created_at",
        "updated_at",
    )
