from django.db import migrations


def create_agent_workspace(apps, schema_editor):
    ServiceDefinition = apps.get_model("catalog", "ServiceDefinition")
    ServiceDefinition.objects.update_or_create(
        slug="agent-workspace",
        defaults={
            "name": "Agent Workspace",
            "description": "Persistent remote workspace for Herdr and Codex agents",
            "icon_name": "terminal",
            "default_cpu_units": 2,
            "min_cpu_units": 1,
            "max_cpu_units": 4,
            "default_memory_mib": 4096,
            "min_memory_mib": 2048,
            "max_memory_mib": 8192,
            "default_storage_mib": 20480,
            "min_storage_mib": 10240,
            "max_storage_mib": 51200,
            "is_enabled": True,
        },
    )


def remove_agent_workspace(apps, schema_editor):
    ServiceDefinition = apps.get_model("catalog", "ServiceDefinition")
    ServiceDefinition.objects.filter(slug="agent-workspace").delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0002_seed_jupyter")]

    operations = [migrations.RunPython(create_agent_workspace, remove_agent_workspace)]
