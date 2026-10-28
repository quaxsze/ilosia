from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workloads", "0003_serviceenvironmentvariable")]

    operations = [
        migrations.AlterField(
            model_name="serviceinstance",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("INSTALLING", "Installing"),
                    ("RUNNING", "Running"),
                    ("FAILED", "Failed"),
                    ("STOPPING", "Stopping"),
                    ("STOPPED", "Stopped"),
                    ("DELETING", "Deleting"),
                    ("DELETED", "Deleted"),
                    ("UNKNOWN", "Unknown"),
                ],
                default="PENDING",
                max_length=16,
            ),
        ),
    ]
