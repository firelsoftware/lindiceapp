from django.db import migrations


def make_active_stock_products_visible(apps, schema_editor):
    SupplierProduct = apps.get_model("accounts", "SupplierProduct")
    SupplierProduct.objects.filter(
        is_active=True,
        is_visible=False,
        stock_quantity__gt=0,
    ).update(is_visible=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0034_clientprofile_phone_verification_attempts'),
    ]

    operations = [
        migrations.RunPython(make_active_stock_products_visible, noop),
    ]
