from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0020_clientprofile_welcome_discount_expires_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplierproduct",
            name="status_note",
            field=models.TextField(blank=True),
        ),
    ]
