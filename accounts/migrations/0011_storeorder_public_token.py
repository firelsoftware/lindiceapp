import uuid

from django.db import migrations, models


def fill_public_tokens(apps, schema_editor):
    StoreOrder = apps.get_model("accounts", "StoreOrder")

    for order in StoreOrder.objects.filter(public_token__isnull=True):
        order.public_token = uuid.uuid4()
        order.save(update_fields=["public_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_storeorder"),
    ]

    operations = [
        migrations.AddField(
            model_name="storeorder",
            name="public_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.RunPython(fill_public_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="storeorder",
            name="public_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
