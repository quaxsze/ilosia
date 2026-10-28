from django.contrib import admin

from .models import OidcIdentity


@admin.register(OidcIdentity)
class OidcIdentityAdmin(admin.ModelAdmin):
    list_display = ("subject", "user")
    search_fields = ("subject", "user__username", "user__email")
