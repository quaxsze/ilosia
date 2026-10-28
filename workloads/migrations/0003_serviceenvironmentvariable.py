import django.db.models.deletion
from django.db import migrations, models

import workloads.models


class Migration(migrations.Migration):
    dependencies = [("workloads", "0002_serviceinstance_kubernetes_fields")]

    operations = [
        migrations.CreateModel(
            name="ServiceEnvironmentVariable",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        max_length=253,
                        validators=[workloads.models.environment_name_validator],
                    ),
                ),
                ("value", models.TextField(blank=True)),
                ("is_secret", models.BooleanField(default=False)),
                (
                    "service_instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="environment_variables",
                        to="workloads.serviceinstance",
                    ),
                ),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.AddConstraint(
            model_name="serviceenvironmentvariable",
            constraint=models.UniqueConstraint(
                fields=("service_instance", "name"),
                name="workload_environment_name_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="serviceenvironmentvariable",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("is_secret", False), ("value", ""), _connector="OR"
                ),
                name="workload_secret_value_not_stored",
            ),
        ),
    ]
