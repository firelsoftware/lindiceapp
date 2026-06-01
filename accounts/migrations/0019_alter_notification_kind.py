from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0018_alter_notification_kind"),
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
                    ("credit_limit_increased", "Limite aumentado"),
                    ("sale_available", "Venda disponivel"),
                    ("sale_confirmed", "Venda efetivada"),
                ],
                max_length=30,
            ),
        ),
    ]
