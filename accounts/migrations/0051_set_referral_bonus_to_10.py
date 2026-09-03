from decimal import Decimal

from django.db import migrations


def set_referral_bonus_to_10(apps, schema_editor):
    StoreSettings = apps.get_model("accounts", "StoreSettings")
    StoreSettings.objects.update_or_create(
        pk=1,
        defaults={"referral_bonus": Decimal("10.00")},
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0050_storesettings"),
    ]

    operations = [
        migrations.RunPython(set_referral_bonus_to_10, noop),
    ]
