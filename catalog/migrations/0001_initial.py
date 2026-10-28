from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ServiceDefinition",
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
                ("slug", models.SlugField(unique=True)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("icon_name", models.CharField(blank=True, max_length=50)),
                (
                    "default_cpu_units",
                    models.PositiveSmallIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "min_cpu_units",
                    models.PositiveSmallIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "max_cpu_units",
                    models.PositiveSmallIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "default_memory_mib",
                    models.PositiveIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "min_memory_mib",
                    models.PositiveIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "max_memory_mib",
                    models.PositiveIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "default_storage_mib",
                    models.PositiveIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "min_storage_mib",
                    models.PositiveIntegerField(validators=[MinValueValidator(1)]),
                ),
                (
                    "max_storage_mib",
                    models.PositiveIntegerField(validators=[MinValueValidator(1)]),
                ),
                ("is_enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("name",)},
        )
    ]
