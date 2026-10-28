from django.urls import path

from . import views

app_name = "storage"

urlpatterns = [
    path("", views.storage_list, name="list"),
    path("download/", views.storage_download, name="download"),
    path("delete/", views.storage_delete, name="delete"),
]
