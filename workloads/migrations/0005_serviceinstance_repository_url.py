from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workloads", "0004_alter_serviceinstance_status")]

    operations = [
        migrations.AddField(
            model_name="serviceinstance",
            name="repository_url",
            field=models.URLField(blank=True, max_length=2048),
        )
    ]
