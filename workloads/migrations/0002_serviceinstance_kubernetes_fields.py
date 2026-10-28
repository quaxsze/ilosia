from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workloads", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="serviceinstance",
            name="namespace",
            field=models.CharField(blank=True, max_length=63),
        ),
        migrations.AddField(
            model_name="serviceinstance",
            name="public_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="serviceinstance",
            name="release_name",
            field=models.CharField(blank=True, max_length=53, null=True, unique=True),
        ),
    ]
