from django.urls import path

from . import views

app_name = "workloads"

urlpatterns = [
    path("catalog/<slug:slug>/launch/", views.launch, name="launch"),
    path("services/", views.service_list, name="list"),
    path(
        "services/<uuid:service_id>/status/",
        views.service_status,
        name="status",
    ),
    path(
        "services/<uuid:service_id>/logs/",
        views.service_logs,
        name="logs",
    ),
    path(
        "services/<uuid:service_id>/delete/",
        views.service_delete,
        name="delete",
    ),
    path("services/<uuid:service_id>/", views.service_detail, name="detail"),
]
