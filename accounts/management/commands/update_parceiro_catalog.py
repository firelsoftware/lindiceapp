"""
Management command: update_parceiro_catalog

Atualiza, em lote, os produtos ja existentes do parceiro sob consulta com a
nova tabela de precos, nomes limpos (sem codigo visivel ao cliente), tamanhos
por categoria e codigo interno com a faixa. NAO mexe nas imagens ja enviadas
(nao re-processa PDFs nem re-faz upload), entao roda rapido.

Regras especiais:
  - Tenis: acima de R$200 vira "Tênis Premium"; o resto fica so "Tênis"
    (remove o rotulo "Premium e Original"). Tamanhos unissex 35-44.

A faixa de cada produto vem de raw_data["faixa"] ou, na primeira vez, do nome
antigo no formato "Categoria (cód 19)".

Usage:
  python manage.py update_parceiro_catalog            # aplica as mudancas
  python manage.py update_parceiro_catalog --dry-run  # so mostra o que mudaria
"""

import re
import unicodedata
from decimal import Decimal

from django.core.management.base import BaseCommand

from accounts.models import SupplierProduct
from accounts.management.commands.import_pdf_catalog import (
    SIZES_UNISSEX,
    build_supplier_code,
    cost_for,
    sale_price_for,
    sizes_for_slug,
    slug_from_category,
)

CODE_PARTS_RE = re.compile(r"p(\d+)[-_]i(\d+)")
NAME_TIER_RE = re.compile(r"\(c[oó]d\s*(\d+)\)", re.IGNORECASE)
TENIS_CODE_SLUG = "tenis_premium_e_original"


def _norm(text):
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


class Command(BaseCommand):
    help = "Atualiza precos, nomes, tamanhos e codigos dos produtos do parceiro (sem mexer nas imagens)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="So mostra o que mudaria")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        products = SupplierProduct.objects.filter(
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA
        )

        updated = skipped = 0
        for product in products:
            tier = self._tier_for(product)
            if tier is None:
                self.stdout.write(
                    self.style.WARNING(f"  Sem faixa, pulando: {product.supplier_code} | {product.name}")
                )
                skipped += 1
                continue

            sale = sale_price_for(tier)
            cost = cost_for(tier)

            if "tenis" in _norm(product.category) or "tenis" in _norm(product.name):
                code_slug = TENIS_CODE_SLUG
                sizes = SIZES_UNISSEX
                display = "Tênis Premium" if sale > Decimal("200") else "Tênis"
                name = display
                category = display
            else:
                code_slug = slug_from_category(product.category or product.name)
                sizes = sizes_for_slug(code_slug)
                name = product.category or product.name
                category = product.category

            page, img = self._page_img(product.supplier_code)
            new_code = build_supplier_code(code_slug, tier, page, img)

            if dry_run:
                self.stdout.write(
                    f"  {product.supplier_code} -> {new_code} | faixa {tier} | "
                    f"venda R${sale} custo R${cost} | tam '{sizes}' | nome '{name}'"
                )
                updated += 1
                continue

            product.name = name
            product.category = category
            if sizes:
                product.sizes = sizes
            product.suggested_sale_price = sale
            product.dropshipping_cost = cost
            product.supplier_code = new_code
            product.raw_data = {**(product.raw_data or {}), "faixa": tier}
            product.save(
                update_fields=[
                    "name",
                    "category",
                    "sizes",
                    "suggested_sale_price",
                    "dropshipping_cost",
                    "supplier_code",
                    "raw_data",
                    "updated_at",
                ]
            )
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Concluido: {updated} atualizados, {skipped} sem faixa.")
        )

    def _tier_for(self, product):
        raw = product.raw_data or {}
        if isinstance(raw.get("faixa"), int):
            return raw["faixa"]
        match = NAME_TIER_RE.search(product.name or "")
        if match:
            return int(match.group(1))
        code_match = re.search(r"-f(\d+)-", product.supplier_code or "")
        if code_match:
            return int(code_match.group(1))
        return None

    def _page_img(self, supplier_code):
        match = CODE_PARTS_RE.search(supplier_code or "")
        if match:
            return int(match.group(1)), int(match.group(2))
        return 0, 0
