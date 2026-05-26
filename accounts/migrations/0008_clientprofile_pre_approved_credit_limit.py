from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_clientprofile_profile_photo"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientprofile",
            name="pre_approved_credit_limit",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
    ]
