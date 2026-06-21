from django.db import migrations, models
import uuid


def populate_credit_sale_tokens(apps, schema_editor):
    CreditSale = apps.get_model("accounts", "CreditSale")

    for sale in CreditSale.objects.filter(public_token__isnull=True):
        sale.public_token = uuid.uuid4()
        sale.save(update_fields=["public_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0042_push_subscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditsale",
            name="guest_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="guest_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="guest_phone",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="public_token",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name="creditsale",
            name="client",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="credit_sales", to="accounts.user"),
        ),
        migrations.RunPython(populate_credit_sale_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="creditsale",
            name="public_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
