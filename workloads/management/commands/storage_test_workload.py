import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from catalog.models import ServiceDefinition
from infrastructure.storage_client import GarageAdminClient, StorageClient, user_bucket
from workloads.models import ServiceInstance
from workloads.services import delete_service_and_data, launch_service


class Command(BaseCommand):
    help = "Create or clean up a temporary Jupyter used by the S3 isolation check."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("create", "cleanup"))
        parser.add_argument("--service-id")

    def handle(self, *args, **options):
        if options["action"] == "create":
            self._create()
            return
        if not options["service_id"]:
            raise CommandError("cleanup requires --service-id")
        self._cleanup(options["service_id"])

    def _create(self):
        definition = ServiceDefinition.objects.get(slug="jupyter", is_enabled=True)
        user = get_user_model().objects.create_user(
            username=f"ilosia-storage-test-{uuid.uuid4().hex}",
            password=None,
        )
        instance = launch_service(
            user=user,
            definition=definition,
            data={
                "display_name": "Storage isolation check",
                "cpu_units": definition.default_cpu_units,
                "memory_gib": definition.default_memory_mib // 1024,
                "storage_gib": definition.default_storage_mib // 1024,
                "environment_variables": {},
                "secret_variables": {},
            },
        )
        self.stdout.write(f"{instance.namespace} {instance.id} {instance.status}")

    def _cleanup(self, service_id):
        try:
            instance = ServiceInstance.objects.select_related("user").get(pk=service_id)
        except (ServiceInstance.DoesNotExist, ValueError) as error:
            raise CommandError("Temporary service not found") from error

        user = instance.user
        if not user.username.startswith("ilosia-storage-test-"):
            raise CommandError("Refusing to clean up a non-test user")
        bucket = user_bucket(user)
        failures = []

        def attempt(name, operation):
            try:
                operation()
            except Exception as error:  # Cleanup must continue after a partial failure.
                failures.append(f"{name}: {error}")

        attempt("service", lambda: delete_service_and_data(instance))
        attempt("bucket", lambda: StorageClient().delete_bucket(bucket))
        attempt(
            "access key",
            lambda: GarageAdminClient().delete_key(f"ilosia-user-{user.pk}"),
        )
        user.delete()
        if failures:
            raise CommandError("Cleanup incomplete: " + "; ".join(failures))
