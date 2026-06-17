"""
Management command: import_pdf_catalog

Processes visual PDF catalogs from the "parceiro sob consulta" supplier.
Each PDF page (starting page 3) contains:
  - Text: a price faixa code (e.g. "19") from the wholesale price table
  - Images: 2 decorative PNGs + 2-3 JPEG product photos (only JPEGs are products)

Pricing (tabela de precos do atacado):
  - suggested_sale_price = coluna VAREJO da faixa (valor final ao cliente)
    excecao: faixa cujo varejo e R$149,90 vira R$159,90
  - dropshipping_cost     = coluna 30% (= varejo * 0,70) -> o gasto do lojista

Usage:
  python manage.py import_pdf_catalog --pdf "BOTAS FEMININAS.pdf" --category "Botas Femininas"
  python manage.py import_pdf_catalog --all   (processes all known PDFs in DOWNLOADS_DIR)
  python manage.py import_pdf_catalog --clear (deletes all parceiro_sob_consulta products first)
"""

import os
import re
import unicodedata
from decimal import Decimal

import fitz  # pymupdf

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from accounts.models import SupplierProduct

# Coluna VAREJO da tabela de precos do atacado (faixa -> preco de varejo).
PRICE_RETAIL = {
    1: Decimal("9.90"),    2: Decimal("14.90"),   3: Decimal("19.90"),
    4: Decimal("24.90"),   5: Decimal("29.90"),   6: Decimal("34.60"),
    7: Decimal("39.90"),   8: Decimal("44.90"),   9: Decimal("49.90"),
    10: Decimal("59.90"),  11: Decimal("69.90"),  12: Decimal("79.90"),
    13: Decimal("89.90"),  14: Decimal("99.90"),  15: Decimal("109.90"),
    16: Decimal("119.90"), 17: Decimal("129.90"), 18: Decimal("139.90"),
    19: Decimal("149.90"), 20: Decimal("159.90"), 21: Decimal("169.90"),
    22: Decimal("179.90"), 23: Decimal("189.90"), 24: Decimal("199.90"),
    25: Decimal("209.90"), 26: Decimal("219.90"), 27: Decimal("229.90"),
    28: Decimal("239.90"), 29: Decimal("249.90"), 30: Decimal("259.90"),
    31: Decimal("269.90"), 32: Decimal("279.90"), 33: Decimal("289.90"),
    34: Decimal("299.90"), 35: Decimal("309.90"), 36: Decimal("319.90"),
    37: Decimal("329.90"), 38: Decimal("339.90"), 39: Decimal("349.90"),
    40: Decimal("359.90"), 41: Decimal("369.90"), 42: Decimal("379.90"),
    43: Decimal("389.90"), 44: Decimal("399.90"), 45: Decimal("409.90"),
    46: Decimal("419.90"), 47: Decimal("429.90"), 48: Decimal("439.90"),
    49: Decimal("449.90"), 50: Decimal("459.90"), 51: Decimal("469.90"),
    52: Decimal("479.90"), 53: Decimal("489.90"), 54: Decimal("499.90"),
}

# Desconto de atacado usado como custo do lojista (coluna 30%).
WHOLESALE_DISCOUNT = Decimal("0.70")

# Substituicao pedida pelo lojista: varejo 149,90 vira 159,90 no preco final.
SALE_PRICE_OVERRIDES = {Decimal("149.90"): Decimal("159.90")}

# Tamanhos por categoria (calcados dos PDFs).
SIZES_FEMININO = "35,36,37,38"
SIZES_UNISSEX = "35,36,37,38,39,40,41,42,43,44"
SIZES_MASCULINO = "38,39,40,41,42,43,44"
SIZES_INFANTIL = "21,22,23,24,25,26,27,28,29,30,31,32,33"
SIZES_UNICO = "Único"

SIZES_BY_SLUG = {
    "botas_femininas": SIZES_FEMININO,
    "rasteiras_papetes_flatforms": SIZES_FEMININO,
    "tenis_premium_e_original": SIZES_UNISSEX,
    "saltos_anabelas_chinelos": SIZES_FEMININO,
    "ortopedicos_scarpin_mocassim_sapatilha": SIZES_FEMININO,
    "bolsas_e_relogios": SIZES_UNICO,
    "linha_infantil": SIZES_INFANTIL,
}

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


def retail_for(tier: int) -> Decimal:
    """Preco de varejo da faixa; extrapola +R$10 por faixa acima de 54."""
    if tier in PRICE_RETAIL:
        return PRICE_RETAIL[tier]
    if tier > 54:
        return PRICE_RETAIL[54] + Decimal("10.00") * (tier - 54)
    return Decimal("0.00")


def sale_price_for(tier: int) -> Decimal:
    """Preco final ao cliente = varejo, com a substituicao 149,90 -> 159,90."""
    retail = retail_for(tier)
    return SALE_PRICE_OVERRIDES.get(retail, retail)


def cost_for(tier: int) -> Decimal:
    """Custo do lojista = coluna 30% (varejo * 0,70), sobre o varejo real da faixa."""
    return (retail_for(tier) * WHOLESALE_DISCOUNT).quantize(Decimal("0.01"))


def sizes_for_slug(cat_slug: str) -> str:
    return SIZES_BY_SLUG.get(cat_slug, "")


def resolve_path(path: str) -> str:
    """Return the actual filesystem path, handling NFC/NFD Unicode differences on Windows."""
    if os.path.exists(path):
        return path
    directory = os.path.dirname(path)
    target_name = unicodedata.normalize("NFD", os.path.basename(path))
    for entry in os.scandir(directory):
        if unicodedata.normalize("NFD", entry.name) == target_name:
            return entry.path
    return path


def slug_from_category(category: str) -> str:
    s = category.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def build_supplier_code(cat_slug: str, tier: int, page: int, img_idx: int) -> str:
    """Codigo interno (visivel so ao admin). Inclui a faixa para auditoria."""
    return f"{cat_slug}-f{tier}-p{page}-i{img_idx}"


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
        sizes = sizes_for_slug(cat_slug)
        pdf_path = resolve_path(pdf_path)
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        created = updated = skipped = 0

        for page_num in range(2, total_pages):  # skip pages 0 and 1 (cover/intro)
            page = doc[page_num]

            text = page.get_text("text").strip()
            tier_match = re.search(r"\b(\d{1,3})\b", text)
            if not tier_match:
                self.stdout.write(f"  Page {page_num + 1}: no price code found, skipping")
                continue
            tier = int(tier_match.group(1))
            cost = cost_for(tier)
            sale_price = sale_price_for(tier)

            # Tenis: acima de R$200 e "Premium"; o resto fica so "Tênis".
            if cat_slug == "tenis_premium_e_original":
                display_category = "Tênis Premium" if sale_price > Decimal("200") else "Tênis"
            else:
                display_category = category

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
                supplier_code = build_supplier_code(cat_slug, tier, page_num + 1, img_idx + 1)
                name = display_category  # nome limpo, sem codigo visivel ao cliente

                if dry_run:
                    self.stdout.write(
                        f"  [DRY] {supplier_code}: faixa={tier} venda=R${sale_price} custo=R${cost} tam={sizes}"
                    )
                    skipped += 1
                    continue

                existing = SupplierProduct.objects.filter(
                    source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
                    supplier_code=supplier_code,
                ).first()

                if existing:
                    existing.name = name
                    existing.category = display_category
                    existing.sizes = sizes
                    existing.dropshipping_cost = cost
                    existing.suggested_sale_price = sale_price
                    existing.stock_quantity = 999
                    existing.is_active = True
                    existing.is_visible = True
                    existing.raw_data = {**(existing.raw_data or {}), "faixa": tier}
                    # Mantem a imagem ja enviada; so re-envia se nao houver.
                    if not existing.image_file:
                        existing.image_file.save(
                            f"{supplier_code}.jpg",
                            ContentFile(base_image["image"], name=f"{supplier_code}.jpg"),
                            save=False,
                        )
                    existing.save()
                    updated += 1
                else:
                    product = SupplierProduct(
                        source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
                        supplier_code=supplier_code,
                        name=name,
                        category=display_category,
                        sizes=sizes,
                        dropshipping_cost=cost,
                        suggested_sale_price=sale_price,
                        stock_quantity=999,
                        is_active=True,
                        is_visible=True,
                        raw_data={"faixa": tier},
                    )
                    product.image_file.save(
                        f"{supplier_code}.jpg",
                        ContentFile(base_image["image"], name=f"{supplier_code}.jpg"),
                        save=False,
                    )
                    product.save()
                    created += 1

        doc.close()
        self.stdout.write(
            self.style.SUCCESS(
                f"  Done: {created} created, {updated} updated, {skipped} skipped — {category}"
            )
        )
