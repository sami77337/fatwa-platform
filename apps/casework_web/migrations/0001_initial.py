from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("intake_workflow", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="ThrottleBucket",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("window", models.BigIntegerField()),
                ("requests", models.PositiveIntegerField()),
            ],
        ),
    ]
