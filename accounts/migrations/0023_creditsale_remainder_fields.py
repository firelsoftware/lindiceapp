from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0022_creditsaleproduct_brand"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditsale",
            name="financed_total_with_interest",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="remainder_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="remainder_payment_method",
            field=models.CharField(blank=True, choices=[("pix", "Pix"), ("card", "Cartao")], max_length=20),
        ),
    ]
