from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0021_supplierproduct_status_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditsaleproduct",
            name="brand",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
