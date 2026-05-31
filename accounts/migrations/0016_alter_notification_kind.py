from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_notification"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("due_soon", "Vencimento proximo"),
                    ("due_today", "Vencimento hoje"),
                    ("overdue", "Pagamento em atraso"),
                    ("manual_debt", "Debito lancado"),
                    ("registration_approved", "Cadastro aprovado"),
                ],
                max_length=30,
            ),
        ),
    ]
