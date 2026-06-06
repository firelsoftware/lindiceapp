from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0025_storeorder_shipping_cost_storeorder_shipping_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clientprofile",
            name="residence_proof",
            field=models.FileField(blank=True, upload_to="residence_proofs/"),
        ),
    ]
