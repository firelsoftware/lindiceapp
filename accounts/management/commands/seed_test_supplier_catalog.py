import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from accounts.models import SupplierProduct
from accounts.supplier_import import import_supplier_catalog_content


class Command(BaseCommand):
    help = "Publica a selecao de produtos usada para validar a vitrine."

    def handle(self, *args, **options):
        catalog_path = Path(__file__).resolve().parents[2] / "catalog_test_featured.csv"
        content = catalog_path.read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(content.splitlines(), delimiter=";"))
        result = import_supplier_catalog_content(content, deactivate_missing=False)
        codes = [row["codigo"] for row in rows]
        SupplierProduct.objects.filter(supplier_code__in=codes).update(is_visible=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Amostra publicada: {result['created']} novos, {result['updated']} atualizados, {result['total']} visiveis."
            )
        )
