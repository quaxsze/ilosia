from django.contrib import admin

from .models import ServiceDefinition


@admin.register(ServiceDefinition)
class ServiceDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_enabled", "updated_at")
    list_filter = ("is_enabled",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
