from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0023_creditsale_remainder_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientprofile",
            name="identity_document",
            field=models.FileField(blank=True, upload_to="identity_documents/"),
        ),
        migrations.AddField(
            model_name="clientprofile",
            name="rg_number",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
