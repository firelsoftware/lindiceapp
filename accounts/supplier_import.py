import csv
import hashlib
import io
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .models import SupplierProduct


ALIASES = {
    "supplier_code": {"codigo", "cod", "sku", "referencia", "ref", "id", "produtoid"},
    "name": {"produto", "nome", "nomeproduto", "titulo", "title", "descricao", "descrição"},
    "description": {"detalhes", "descricaocompleta", "descrição completa", "description"},
    "category": {"categoria", "linha", "departamento", "tipo"},
    "brand": {"marca", "fabricante"},
    "image_url": {"imagem", "foto", "urlimagem", "urlfoto", "imagem1", "foto1"},
    "product_url": {"link", "url", "urlproduto", "produtourl"},
    "wholesale_price": {"preco", "preço", "precoatacado", "preçoatacado", "valor", "valoratacado"},
    "stock_quantity": {"estoque", "quantidade", "qtde", "saldo", "disponivel", "disponível"},
    "sizes": {"tamanho", "tamanhos", "numeracao", "numeração", "numero", "número"},
}


def normalize_key(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")

    return re.sub(r"[^a-z0-9]", "", ascii_value.lower())


NORMALIZED_ALIASES = {
    field: {normalize_key(alias) for alias in aliases}
    for field, aliases in ALIASES.items()
}


def find_value(row, field):
    aliases = NORMALIZED_ALIASES[field]

    for key, value in row.items():
        if normalize_key(key) in aliases:
            return str(value or "").strip()

    return ""


def parse_money(value):
    text = str(value or "").strip()

    if not text:
        return Decimal("0.00")

    text = re.sub(r"[^0-9,.-]", "", text)

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return Decimal(text or "0.00")
    except InvalidOperation:
        return Decimal("0.00")


def parse_int(value):
    text = re.sub(r"[^0-9-]", "", str(value or ""))

    try:
        return int(text or "0")
    except ValueError:
        return 0


def build_fallback_code(row, row_number):
    base = "|".join(
        [
            find_value(row, "product_url"),
            find_value(row, "name"),
            find_value(row, "sizes"),
            str(row_number),
        ]
    )

    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def fetch_catalog(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Lindice/1.0"})

    with urllib.request.urlopen(request, timeout=40) as response:
        charset = response.headers.get_content_charset() or "utf-8-sig"
        return response.read().decode(charset, errors="replace")


def parse_csv(content):
    sample = content[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)

    return list(reader)


def parse_xml(content):
    root = ET.fromstring(content)
    item_nodes = [node for node in root.iter() if len(node) and node is not root]
    rows = []

    for node in item_nodes:
        children = list(node)

        if not children:
            continue

        row = {}

        for child in children:
            tag = child.tag.split("}", 1)[-1]
            row[tag] = (child.text or "").strip()

        if row:
            rows.append(row)

    return rows


def row_to_payload(row, row_number):
    supplier_code = find_value(row, "supplier_code") or build_fallback_code(row, row_number)
    wholesale_price = parse_money(find_value(row, "wholesale_price"))
    dropshipping_cost = wholesale_price * Decimal("1.10")

    return {
        "supplier_code": supplier_code[:120],
        "name": (find_value(row, "name") or f"Produto {supplier_code}")[:180],
        "description": find_value(row, "description"),
        "category": find_value(row, "category")[:120],
        "brand": find_value(row, "brand")[:120],
        "image_url": find_value(row, "image_url"),
        "product_url": find_value(row, "product_url"),
        "wholesale_price": wholesale_price,
        "dropshipping_cost": dropshipping_cost,
        "suggested_sale_price": dropshipping_cost,
        "stock_quantity": parse_int(find_value(row, "stock_quantity")),
        "sizes": find_value(row, "sizes")[:180],
        "raw_data": row,
        "is_active": True,
        "last_seen_at": timezone.now(),
    }


def import_supplier_catalog(url, catalog_format="csv"):
    content = fetch_catalog(url)
    catalog_format = (catalog_format or "csv").lower()

    if catalog_format == "xml":
        rows = parse_xml(content)
    else:
        rows = parse_csv(content)

    created = 0
    updated = 0
    seen_ids = []

    for row_number, row in enumerate(rows, start=1):
        payload = row_to_payload(row, row_number)
        supplier_code = payload.pop("supplier_code")
        product, was_created = SupplierProduct.objects.update_or_create(
            source=SupplierProduct.SOURCE_REVENDA_CALCADOS,
            supplier_code=supplier_code,
            defaults=payload,
        )
        seen_ids.append(product.id)

        if was_created:
            created += 1
        else:
            updated += 1

    if seen_ids:
        SupplierProduct.objects.filter(source=SupplierProduct.SOURCE_REVENDA_CALCADOS).exclude(id__in=seen_ids).update(is_active=False)

    return {
        "created": created,
        "updated": updated,
        "total": len(rows),
    }
