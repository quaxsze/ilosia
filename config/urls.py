from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from .views import healthz

urlpatterns = [
    path("", include("django_prometheus.urls")),
    path("healthz/", healthz, name="healthz"),
    path("", RedirectView.as_view(pattern_name="catalog:list"), name="home"),
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("catalog/", include("catalog.urls")),
    path("storage/", include("storage_app.urls")),
    path("", include("workloads.urls")),
]

if settings.OIDC_ENABLED:
    urlpatterns.insert(4, path("oidc/", include("mozilla_django_oidc.urls")))
