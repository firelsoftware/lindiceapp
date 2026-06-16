"""
Management command: import_pdf_catalog

Processes visual PDF catalogs from the "parceiro sob consulta" supplier.
Each PDF page (starting page 3) contains:
  - Text: a price tier code (e.g. "19") mapping to the 1-44 price table
  - Images: 2 decorative PNGs + 2-3 JPEG product photos (only JPEGs are products)

Usage:
  python manage.py import_pdf_catalog --pdf "BOTAS FEMININAS.pdf" --category "Botas Femininas"
  python manage.py import_pdf_catalog --all   (processes all known PDFs in DOWNLOADS_DIR)
  python manage.py import_pdf_catalog --clear (deletes all parceiro_sob_consulta products first)
"""

import glob
import os
import re
import unicodedata

import fitz  # pymupdf
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from accounts.models import SupplierProduct

PRICE_TABLE = {
    1: Decimal("19.90"),   2: Decimal("24.90"),   3: Decimal("29.90"),
    4: Decimal("34.90"),   5: Decimal("39.90"),    6: Decimal("44.60"),
    7: Decimal("49.90"),   8: Decimal("54.90"),    9: Decimal("59.90"),
    10: Decimal("69.90"),  11: Decimal("79.90"),   12: Decimal("89.90"),
    13: Decimal("99.90"),  14: Decimal("109.90"),  15: Decimal("119.90"),
    16: Decimal("129.90"), 17: Decimal("139.90"),  18: Decimal("149.90"),
    19: Decimal("159.90"), 20: Decimal("169.90"),  21: Decimal("179.90"),
    22: Decimal("189.90"), 23: Decimal("199.90"),  24: Decimal("209.90"),
    25: Decimal("219.90"), 26: Decimal("229.90"),  27: Decimal("239.90"),
    28: Decimal("249.90"), 29: Decimal("259.90"),  30: Decimal("269.90"),
    31: Decimal("279.90"), 32: Decimal("289.90"),  33: Decimal("299.90"),
    34: Decimal("309.90"), 35: Decimal("319.90"),  36: Decimal("329.90"),
    37: Decimal("339.90"), 38: Decimal("349.90"),  39: Decimal("359.90"),
    40: Decimal("369.90"), 41: Decimal("379.90"),  42: Decimal("389.90"),
    43: Decimal("399.90"), 44: Decimal("409.90"),
}

STORE_MARGIN = Decimal("1.40")

DOWNLOADS_DIR = r"C:\Users\Programador\Downloads"

KNOWN_PDFS = [
    ("BOTAS FEMININAS.pdf", "Botas Femininas"),
    ("RASTEIRAS  PAPETES  FLATFORMS.pdf", "Rasteiras Papetes Flatforms"),
    ("TÊNIS PREMIUM E ORIGINAL.pdf", "Tenis Premium e Original"),
    ("SALTOS  ANABELAS  CHINELOS.pdf", "Saltos Anabelas Chinelos"),
    ("ORTOPÉDICOS  SCARPIN  MOCASSIM  SAPATILHA.pdf", "Ortopedicos Scarpin Mocassim Sapatilha"),
    ("BOLSAS  RELÓGIOS.pdf", "Bolsas e Relogios"),
    ("LINHA INFANTIL.pdf", "Linha Infantil"),
]


def extrapolate_price(tier: int) -> Decimal:
    """For tiers beyond 44, extrapolate at +R$10 per step."""
    if tier in PRICE_TABLE:
        return PRICE_TABLE[tier]
    if tier > 44:
        return PRICE_TABLE[44] + Decimal("10.00") * (tier - 44)
    return Decimal("0.00")


def resolve_path(path: str) -> str:
    """Return the actual filesystem path, handling NFC/NFD Unicode differences on Windows."""
    if os.path.exists(path):
        return path
    # Try scanning the directory for a matching filename using NFD comparison
    directory = os.path.dirname(path)
    target_name = unicodedata.normalize("NFD", os.path.basename(path))
    for entry in os.scandir(directory):
        if unicodedata.normalize("NFD", entry.name) == target_name:
            return entry.path
    return path  # return original; fitz will raise FileNotFoundError with a clear message


def slug_from_category(category: str) -> str:
    s = category.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


class Command(BaseCommand):
    help = "Import parceiro-sob-consulta products from PDF visual catalogs"

    def add_arguments(self, parser):
        parser.add_argument("--pdf", type=str, help="Path to a single PDF file")
        parser.add_argument("--category", type=str, help="Category name for the --pdf file")
        parser.add_argument("--all", action="store_true", help="Process all known PDFs in Downloads")
        parser.add_argument("--clear", action="store_true", help="Delete existing parceiro_sob_consulta products first")
        parser.add_argument("--dry-run", action="store_true", help="Don't save to DB, just print summary")

    def handle(self, *args, **options):
        if options["clear"]:
            count, _ = SupplierProduct.objects.filter(
                source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA
            ).delete()
            self.stdout.write(self.style.WARNING(f"Deleted {count} existing parceiro products."))

        if options["pdf"]:
            pdf_path = resolve_path(options["pdf"])
            category = options.get("category") or os.path.splitext(os.path.basename(pdf_path))[0].title()
            self._process_pdf(pdf_path, category, dry_run=options["dry_run"])
        elif options["all"]:
            for filename, category in KNOWN_PDFS:
                pdf_path = resolve_path(os.path.join(DOWNLOADS_DIR, filename))
                if os.path.exists(pdf_path):
                    self.stdout.write(f"\nProcessing: {filename}")
                    self._process_pdf(pdf_path, category, dry_run=options["dry_run"])
                else:
                    self.stdout.write(self.style.WARNING(f"Not found, skipping: {pdf_path}"))
        else:
            self.stderr.write("Provide --pdf <path> or --all")

    def _process_pdf(self, pdf_path: str, category: str, dry_run: bool = False):
        cat_slug = slug_from_category(category)
        pdf_path = resolve_path(pdf_path)
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        created = updated = skipped = 0

        for page_num in range(2, total_pages):  # skip pages 0 and 1 (cover/intro)
            page = doc[page_num]

            # --- Extract price tier from page text ---
            text = page.get_text("text").strip()
            # Find first integer in text (the price tier code)
            tier_match = re.search(r"\b(\d{1,3})\b", text)
            if not tier_match:
                self.stdout.write(f"  Page {page_num + 1}: no price code found, skipping")
                continue
            tier = int(tier_match.group(1))
            cost = extrapolate_price(tier)
            sale_price = (cost * STORE_MARGIN).quantize(Decimal("0.01"))

            # --- Extract JPEG images only (product photos) ---
            image_list = page.get_images(full=True)
            jpeg_images = []
            for img_info in image_list:
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                if base_image["ext"].lower() in ("jpg", "jpeg"):
                    jpeg_images.append(base_image)

            if not jpeg_images:
                self.stdout.write(f"  Page {page_num + 1}: no JPEG images, skipping")
                continue

            for img_idx, base_image in enumerate(jpeg_images):
                supplier_code = f"{cat_slug}_p{page_num + 1}_i{img_idx + 1}"
                name = f"{category} (cód {tier})"

                if dry_run:
                    self.stdout.write(
                        f"  [DRY] Page {page_num+1} img {img_idx+1}: code={supplier_code} tier={tier} cost=R${cost} sale=R${sale_price}"
                    )
                    skipped += 1
                    continue

                img_bytes = base_image["image"]
                img_content = ContentFile(img_bytes, name=f"{supplier_code}.jpg")

                existing = SupplierProduct.objects.filter(
                    source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
                    supplier_code=supplier_code,
                ).first()

                if existing:
                    existing.name = name
                    existing.category = category
                    existing.dropshipping_cost = cost
                    existing.suggested_sale_price = sale_price
                    existing.stock_quantity = 999
                    existing.is_active = True
                    existing.is_visible = True
                    # Replace image file
                    if existing.image_file:
                        existing.image_file.delete(save=False)
                    existing.image_file.save(f"{supplier_code}.jpg", img_content, save=False)
                    existing.save()
                    updated += 1
                else:
                    product = SupplierProduct(
                        source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
                        supplier_code=supplier_code,
                        name=name,
                        category=category,
                        dropshipping_cost=cost,
                        suggested_sale_price=sale_price,
                        stock_quantity=999,
                        is_active=True,
                        is_visible=True,
                    )
                    product.image_file.save(f"{supplier_code}.jpg", img_content, save=False)
                    product.save()
                    created += 1

        doc.close()
        self.stdout.write(
            self.style.SUCCESS(
                f"  Done: {created} created, {updated} updated, {skipped} skipped — {category}"
            )
        )
