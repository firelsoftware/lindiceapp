from decimal import Decimal

from django.db import migrations


def seed_ramose_products(apps, schema_editor):
    SupplierProduct = apps.get_model("accounts", "SupplierProduct")

    products = [
        {
            "supplier_code": "RAMOSE-MELINA",
            "name": "Bolsa Ramos\u00ea Melina",
            "description": "Croch\u00ea",
            "category": "Bolsas",
            "brand": "Ramos\u00ea",
            "image_url": "/static/accounts/ramose_products/melina-1.jpg",
            "gallery_images": [
                "/static/accounts/ramose_products/melina-1.jpg",
                "/static/accounts/ramose_products/melina-2.jpg",
            ],
            "price": Decimal("109.90"),
            "material": "Croch\u00ea",
            "featured_order": 1,
        },
        {
            "supplier_code": "RAMOSE-LIS",
            "name": "Bolsa Ramos\u00ea Lis",
            "description": "Croch\u00ea",
            "category": "Bolsas",
            "brand": "Ramos\u00ea",
            "image_url": "/static/accounts/ramose_products/lis-1.jpg",
            "gallery_images": [
                "/static/accounts/ramose_products/lis-1.jpg",
                "/static/accounts/ramose_products/lis-2.jpg",
            ],
            "price": Decimal("149.90"),
            "material": "Croch\u00ea",
            "featured_order": 2,
        },
        {
            "supplier_code": "RAMOSE-IRIS",
            "name": "Bolsa Ramos\u00ea \u00cdris",
            "description": "Croch\u00ea",
            "category": "Bolsas",
            "brand": "Ramos\u00ea",
            "image_url": "/static/accounts/ramose_products/iris-1.jpg",
            "gallery_images": [
                "/static/accounts/ramose_products/iris-1.jpg",
                "/static/accounts/ramose_products/iris-2.jpg",
            ],
            "price": Decimal("159.90"),
            "material": "Croch\u00ea",
            "featured_order": 3,
        },
        {
            "supplier_code": "RAMOSE-FLORA",
            "name": "Bolsa Ramos\u00ea Flora",
            "description": "Croch\u00ea",
            "category": "Bolsas",
            "brand": "Ramos\u00ea",
            "image_url": "/static/accounts/ramose_products/flora-1.jpg",
            "gallery_images": [
                "/static/accounts/ramose_products/flora-1.jpg",
                "/static/accounts/ramose_products/flora-2.jpg",
            ],
            "price": Decimal("109.90"),
            "material": "Croch\u00ea",
            "featured_order": 4,
        },
        {
            "supplier_code": "RAMOSE-PEONIA",
            "name": "Bolsa Ramos\u00ea Pe\u00f4nia",
            "description": "Fio Premium",
            "category": "Bolsas",
            "brand": "Ramos\u00ea",
            "image_url": "/static/accounts/ramose_products/peonia-1.jpg",
            "gallery_images": [
                "/static/accounts/ramose_products/peonia-1.jpg",
                "/static/accounts/ramose_products/peonia-2.jpg",
            ],
            "price": Decimal("179.90"),
            "material": "Fio Premium",
            "featured_order": 5,
        },
    ]

    for payload in products:
        product, _ = SupplierProduct.objects.update_or_create(
            source="revenda_calcados",
            supplier_code=payload["supplier_code"],
            defaults={
                "name": payload["name"],
                "description": payload["description"],
                "category": payload["category"],
                "brand": payload["brand"],
                "image_url": payload["image_url"],
                "product_url": "",
                "wholesale_price": payload["price"],
                "dropshipping_cost": payload["price"],
                "suggested_sale_price": payload["price"],
                "stock_quantity": 10,
                "sizes": "\u00danico",
                "is_active": True,
                "is_visible": True,
                "raw_data": {
                    "gallery_images": payload["gallery_images"],
                    "material": payload["material"],
                    "partner_brand": "Ramos\u00ea",
                    "featured_order": payload["featured_order"],
                },
            },
        )
        product.status_note = ""
        product.save(update_fields=["status_note", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0027_fix_ramose_product_text"),
    ]

    operations = [
        migrations.RunPython(seed_ramose_products, migrations.RunPython.noop),
    ]
