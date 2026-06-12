from django.db import migrations, models


def seed_supplier_catalog_sources(apps, schema_editor):
    SupplierCatalogSource = apps.get_model("accounts", "SupplierCatalogSource")

    SupplierCatalogSource.objects.update_or_create(
        source="revenda_calcados",
        defaults={
            "display_name": "Revenda de Calcados",
            "catalog_format": "csv",
            "supplier_panel_note": "Cole aqui a URL atual do catalogo da Revenda. Se preferir, voce ainda pode enviar o arquivo baixado do dia.",
            "customer_notice": "",
            "purchase_flow": "store_checkout",
            "is_active": True,
        },
    )
    SupplierCatalogSource.objects.update_or_create(
        source="parceiro_sob_consulta",
        defaults={
            "display_name": "Parceiro sob consulta",
            "catalog_format": "csv",
            "supplier_panel_note": "Sugestao de nome: Parceiro sob consulta. Use esta fonte para catalogos com disponibilidade mais instavel.",
            "customer_notice": "Em breve vamos entrar em contato para confirmar disponibilidade e finalizar pelo WhatsApp.",
            "purchase_flow": "whatsapp_confirmation",
            "is_active": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0031_personaldebt_entry_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierCatalogSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("revenda_calcados", "Revenda de Calcados"), ("parceiro_sob_consulta", "Parceiro sob consulta")], max_length=50, unique=True)),
                ("display_name", models.CharField(max_length=80)),
                ("catalog_url", models.URLField(blank=True)),
                ("catalog_format", models.CharField(choices=[("csv", "CSV"), ("xml", "XML")], default="csv", max_length=10)),
                ("supplier_panel_note", models.TextField(blank=True)),
                ("customer_notice", models.TextField(blank=True)),
                ("purchase_flow", models.CharField(choices=[("store_checkout", "Checkout normal da loja"), ("whatsapp_confirmation", "Confirmar disponibilidade e finalizar no WhatsApp")], default="store_checkout", max_length=30)),
                ("is_active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["display_name"],
            },
        ),
        migrations.AlterField(
            model_name="supplierproduct",
            name="source",
            field=models.CharField(choices=[("revenda_calcados", "Revenda de Calcados"), ("parceiro_sob_consulta", "Parceiro sob consulta")], default="revenda_calcados", max_length=50),
        ),
        migrations.RunPython(seed_supplier_catalog_sources, migrations.RunPython.noop),
    ]
