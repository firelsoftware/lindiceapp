from django.db import migrations

SUPPLIERS = [
    "Ramosê",
    "Revenda Calçados Dropshipping",
    "Santa Fiori",
    "Micheline Joias",
    "Boticário",
]


def seed_suppliers(apps, schema_editor):
    Supplier = apps.get_model("accounts", "Supplier")
    for name in SUPPLIERS:
        Supplier.objects.get_or_create(name=name)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0038_supplier_model"),
    ]

    operations = [
        migrations.RunPython(seed_suppliers, noop),
    ]
