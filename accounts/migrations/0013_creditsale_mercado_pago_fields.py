from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_creditsale_selected_payment_method"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditsale",
            name="mercado_pago_init_point",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="mercado_pago_payment_id",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="mercado_pago_preference_id",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("pending", "Aguardando pagamento"),
                    ("paid", "Pago"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
