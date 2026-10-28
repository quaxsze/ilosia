from django.db import migrations


def create_jupyter(apps, schema_editor):
    ServiceDefinition = apps.get_model("catalog", "ServiceDefinition")
    ServiceDefinition.objects.update_or_create(
        slug="jupyter",
        defaults={
            "name": "JupyterLab",
            "description": "Interactive Python notebook environment",
            "icon_name": "journal-code",
            "default_cpu_units": 1,
            "min_cpu_units": 1,
            "max_cpu_units": 4,
            "default_memory_mib": 2048,
            "min_memory_mib": 2048,
            "max_memory_mib": 8192,
            "default_storage_mib": 10240,
            "min_storage_mib": 5120,
            "max_storage_mib": 20480,
            "is_enabled": True,
        },
    )


def remove_jupyter(apps, schema_editor):
    ServiceDefinition = apps.get_model("catalog", "ServiceDefinition")
    ServiceDefinition.objects.filter(slug="jupyter").delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [migrations.RunPython(create_jupyter, remove_jupyter)]
