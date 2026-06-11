from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0028_seed_ramose_products"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonalDebt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("category", models.CharField(choices=[("rent", "Aluguel"), ("utilities", "Contas da casa"), ("card", "Cartao"), ("market", "Mercado"), ("transport", "Transporte"), ("health", "Saude"), ("education", "Educacao"), ("other", "Outro")], default="other", max_length=20)),
                ("color", models.CharField(choices=[("plum", "Ameixa"), ("blue", "Azul"), ("green", "Verde"), ("gold", "Dourado"), ("coral", "Coral"), ("slate", "Cinza")], default="plum", max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("due_date", models.DateField()),
                ("notes", models.TextField(blank=True)),
                ("paid", models.BooleanField(default=False)),
                ("paid_at", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="personal_debts", to="accounts.user")),
            ],
            options={
                "ordering": ("due_date", "id"),
            },
        ),
    ]
