import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from catalog.models import ServiceDefinition

service_name_validator = RegexValidator(
    regex=r"^[\w][\w .-]{0,62}$",
    message="Use letters, numbers, spaces, dots, underscores or hyphens.",
)
environment_name_validator = RegexValidator(
    regex=r"^[A-Za-z_][A-Za-z0-9_]*$",
    message="Use a letter or underscore first, followed by letters, numbers or underscores.",
)


class ServiceInstance(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        INSTALLING = "INSTALLING", "Installing"
        RUNNING = "RUNNING", "Running"
        FAILED = "FAILED", "Failed"
        DELETING = "DELETING", "Deleting"
        DELETED = "DELETED", "Deleted"
        UNKNOWN = "UNKNOWN", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="service_instances",
    )
    service_definition = models.ForeignKey(
        ServiceDefinition,
        on_delete=models.PROTECT,
        related_name="instances",
    )
    display_name = models.CharField(
        max_length=63,
        validators=[service_name_validator],
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    cpu_units = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    memory_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    storage_mib = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    release_name = models.CharField(max_length=53, unique=True, null=True, blank=True)
    namespace = models.CharField(max_length=63, blank=True)
    public_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cpu_units__gt=0), name="workload_cpu_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(memory_mib__gt=0), name="workload_memory_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(storage_mib__gt=0), name="workload_storage_positive"
            ),
        ]

    def __str__(self):
        return self.display_name

    def clean(self):
        super().clean()
        if not self.service_definition_id:
            return

        errors = {}
        ranges = (
            (
                "cpu_units",
                self.service_definition.min_cpu_units,
                self.service_definition.max_cpu_units,
            ),
            (
                "memory_mib",
                self.service_definition.min_memory_mib,
                self.service_definition.max_memory_mib,
            ),
            (
                "storage_mib",
                self.service_definition.min_storage_mib,
                self.service_definition.max_storage_mib,
            ),
        )
        for field_name, minimum, maximum in ranges:
            if not minimum <= getattr(self, field_name) <= maximum:
                errors[field_name] = f"Value must be between {minimum} and {maximum}."
        if errors:
            raise ValidationError(errors)


class ServiceEnvironmentVariable(models.Model):
    service_instance = models.ForeignKey(
        ServiceInstance,
        on_delete=models.CASCADE,
        related_name="environment_variables",
    )
    name = models.CharField(max_length=253, validators=[environment_name_validator])
    value = models.TextField(blank=True)
    is_secret = models.BooleanField(default=False)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("service_instance", "name"),
                name="workload_environment_name_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(is_secret=False) | models.Q(value=""),
                name="workload_secret_value_not_stored",
            ),
        ]

    def __str__(self):
        return self.name
