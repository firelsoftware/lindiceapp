from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_alter_notification_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientprofile",
            name="first_purchase_discount_used",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="welcome_discount_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="storeorder",
            name="customer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="store_orders", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="storeorder",
            name="welcome_discount_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
    ]
