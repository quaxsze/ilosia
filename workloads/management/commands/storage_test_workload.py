import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from catalog.models import ServiceDefinition
from infrastructure.storage_client import GarageAdminClient, user_bucket
from workloads.models import ServiceInstance
from workloads.services import delete_service_and_data, launch_service


class Command(BaseCommand):
    help = "Create or clean up a temporary Jupyter used by the S3 isolation check."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("create", "cleanup"))
        parser.add_argument("--services", type=int, choices=(1, 2), default=1)
        parser.add_argument("--user-id")

    def handle(self, *args, **options):
        if options["action"] == "create":
            self._create(options["services"])
            return
        if not options["user_id"]:
            raise CommandError("cleanup requires --user-id")
        self._cleanup(options["user_id"])

    def _create(self, service_count):
        definition = ServiceDefinition.objects.get(slug="jupyter", is_enabled=True)
        user = get_user_model().objects.create_user(
            username=f"ilosia-storage-test-{uuid.uuid4().hex}",
            password=None,
        )
        instances = []
        for number in range(1, service_count + 1):
            instance = launch_service(
                user=user,
                definition=definition,
                data={
                    "display_name": f"Storage isolation check {number}",
                    "cpu_units": definition.default_cpu_units,
                    "memory_gib": definition.default_memory_mib // 1024,
                    "storage_gib": definition.default_storage_mib // 1024,
                    "environment_variables": {},
                    "secret_variables": {},
                },
            )
            instances.append(instance)
            if instance.status != ServiceInstance.Status.RUNNING:
                break
        status = (
            ServiceInstance.Status.RUNNING
            if len(instances) == service_count
            and all(
                instance.status == ServiceInstance.Status.RUNNING
                for instance in instances
            )
            else ServiceInstance.Status.FAILED
        )
        self.stdout.write(f"user-{user.pk} {user.pk} {status}")

    def _cleanup(self, user_id):
        try:
            user = get_user_model().objects.get(pk=user_id)
        except (get_user_model().DoesNotExist, ValueError) as error:
            raise CommandError("Temporary user not found") from error
        if not user.username.startswith("ilosia-storage-test-"):
            raise CommandError("Refusing to clean up a non-test user")
        bucket = user_bucket(user)
        failures = []

        def attempt(name, operation):
            try:
                operation()
            except Exception as error:  # Cleanup must continue after a partial failure.
                failures.append(f"{name}: {error}")

        for instance in user.service_instances.all():
            attempt(
                f"service {instance.id}",
                lambda instance=instance: delete_service_and_data(instance),
            )
        garage = GarageAdminClient()
        attempt(
            "access key",
            lambda: garage.delete_key(f"ilosia-user-{user.pk}"),
        )
        attempt("bucket", lambda: garage.delete_bucket(bucket))
        user.delete()
        if failures:
            raise CommandError("Cleanup incomplete: " + "; ".join(failures))
