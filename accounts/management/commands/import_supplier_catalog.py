from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.supplier_import import import_supplier_catalog


class Command(BaseCommand):
    help = "Importa catalogo CSV/XML do fornecedor de calcados."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=settings.SHOE_SUPPLIER_CATALOG_URL)
        parser.add_argument("--format", default=settings.SHOE_SUPPLIER_CATALOG_FORMAT)

    def handle(self, *args, **options):
        url = options["url"]

        if not url:
            raise CommandError("Informe --url ou configure SHOE_SUPPLIER_CATALOG_URL.")

        result = import_supplier_catalog(url, options["format"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Catalogo atualizado: {result['created']} novos, {result['updated']} atualizados, {result['total']} lidos."
            )
        )
