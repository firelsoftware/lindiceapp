from django.db import migrations, models
import uuid


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
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="creditsale",
            name="client",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="credit_sales", to="accounts.user"),
        ),
    ]
