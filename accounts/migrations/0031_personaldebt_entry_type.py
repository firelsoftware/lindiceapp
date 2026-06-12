from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0030_personaldebt_color_hex"),
    ]

    operations = [
        migrations.AddField(
            model_name="personaldebt",
            name="entry_type",
            field=models.CharField(choices=[("debt", "Divida"), ("receivable", "Recebivel")], default="debt", max_length=20),
        ),
    ]
