import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("catalog", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceInstance",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "display_name",
                    models.CharField(
                        max_length=63,
                        validators=[
                            django.core.validators.RegexValidator(
                                message=(
                                    "Use letters, numbers, spaces, dots, "
                                    "underscores or hyphens."
                                ),
                                regex="^[\\w][\\w .-]{0,62}$",
                            )
                        ],
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("INSTALLING", "Installing"),
                            ("RUNNING", "Running"),
                            ("FAILED", "Failed"),
                            ("DELETING", "Deleting"),
                            ("DELETED", "Deleted"),
                            ("UNKNOWN", "Unknown"),
                        ],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                (
                    "cpu_units",
                    models.PositiveSmallIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                (
                    "memory_mib",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                (
                    "storage_mib",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)]
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "service_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="instances",
                        to="catalog.servicedefinition",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="service_instances",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("cpu_units__gt", 0)),
                        name="workload_cpu_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("memory_mib__gt", 0)),
                        name="workload_memory_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("storage_mib__gt", 0)),
                        name="workload_storage_positive",
                    ),
                ],
            },
        )
    ]
