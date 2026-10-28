from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class ServiceDefinition(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon_name = models.CharField(max_length=50, blank=True)

    default_cpu_units = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)]
    )
    min_cpu_units = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    max_cpu_units = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])

    default_memory_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    min_memory_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    max_memory_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    default_storage_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    min_storage_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    max_storage_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        errors = {}
        ranges = (
            (
                "cpu_units",
                self.min_cpu_units,
                self.default_cpu_units,
                self.max_cpu_units,
            ),
            (
                "memory_mib",
                self.min_memory_mib,
                self.default_memory_mib,
                self.max_memory_mib,
            ),
            (
                "storage_mib",
                self.min_storage_mib,
                self.default_storage_mib,
                self.max_storage_mib,
            ),
        )
        for name, minimum, default, maximum in ranges:
            if not minimum <= default <= maximum:
                errors[f"default_{name}"] = (
                    f"Default {name} must be between its minimum and maximum."
                )
        for field_name in (
            "default_memory_mib",
            "min_memory_mib",
            "max_memory_mib",
            "default_storage_mib",
            "min_storage_mib",
            "max_storage_mib",
        ):
            if getattr(self, field_name) % 1024:
                errors[field_name] = "Use whole GiB values expressed in MiB."
        if errors:
            raise ValidationError(errors)
