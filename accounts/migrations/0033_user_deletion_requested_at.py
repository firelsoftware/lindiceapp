from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0032_suppliercatalogsource_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="deletion_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
