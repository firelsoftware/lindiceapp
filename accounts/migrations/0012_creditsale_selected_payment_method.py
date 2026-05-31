from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_storeorder_public_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditsale",
            name="selected_payment_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pix", "Pix"),
                    ("card", "Cartao"),
                    ("credit", "Crediario"),
                ],
                max_length=20,
            ),
        ),
    ]
