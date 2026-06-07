from django.db import migrations


def fix_ramose_product_text(apps, schema_editor):
    SupplierProduct = apps.get_model("accounts", "SupplierProduct")

    updates = {
        "RAMOSE-MELINA": {
            "name": "Bolsa Ramos\u00ea Melina",
            "description": "Croch\u00ea",
            "sizes": "\u00danico",
            "material": "Croch\u00ea",
            "partner_brand": "Ramos\u00ea",
        },
        "RAMOSE-LIS": {
            "name": "Bolsa Ramos\u00ea Lis",
            "description": "Croch\u00ea",
            "sizes": "\u00danico",
            "material": "Croch\u00ea",
            "partner_brand": "Ramos\u00ea",
        },
        "RAMOSE-IRIS": {
            "name": "Bolsa Ramos\u00ea \u00cdris",
            "description": "Croch\u00ea",
            "sizes": "\u00danico",
            "material": "Croch\u00ea",
            "partner_brand": "Ramos\u00ea",
        },
        "RAMOSE-FLORA": {
            "name": "Bolsa Ramos\u00ea Flora",
            "description": "Croch\u00ea",
            "sizes": "\u00danico",
            "material": "Croch\u00ea",
            "partner_brand": "Ramos\u00ea",
        },
        "RAMOSE-PEONIA": {
            "name": "Bolsa Ramos\u00ea Pe\u00f4nia",
            "description": "Fio Premium",
            "sizes": "\u00danico",
            "material": "Fio Premium",
            "partner_brand": "Ramos\u00ea",
        },
    }

    for supplier_code, payload in updates.items():
        product = SupplierProduct.objects.filter(supplier_code=supplier_code).first()
        if not product:
            continue

        raw_data = dict(product.raw_data or {})
        raw_data["material"] = payload["material"]
        raw_data["partner_brand"] = payload["partner_brand"]

        product.name = payload["name"]
        product.description = payload["description"]
        product.sizes = payload["sizes"]
        product.raw_data = raw_data
        product.save(update_fields=["name", "description", "sizes", "raw_data", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0026_alter_clientprofile_residence_proof"),
    ]

    operations = [
        migrations.RunPython(fix_ramose_product_text, migrations.RunPython.noop),
    ]
