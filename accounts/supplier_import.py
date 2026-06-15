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


MIN_STOCK_PER_SIZE = 3
STORE_PRICE_MULTIPLIER = Decimal("1.40")


ALIASES = {
    "supplier_code": {"codigo", "cod", "sku", "referencia", "ref", "id", "produtoid"},
    "name": {"produto", "nome", "nomeproduto", "titulo", "title", "descricao", "descrição"},
    "description": {"detalhes", "descricaocompleta", "descrição completa", "description"},
    "category": {"categoria", "linha", "departamento", "tipo"},
    "brand": {"marca", "fabricante"},
    "image_url": {"imagem", "foto", "fotos", "urlimagem", "urlfoto", "imagem1", "foto1"},
    "product_url": {"link", "url", "urlproduto", "produtourl"},
    "wholesale_price": {"preco", "preço", "precoatacado", "preçoatacado", "valor", "valoratacado"},
    "dropshipping_cost": {"precodropshipping", "preçodropshipping", "custodropshipping", "dropshipping"},
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
        return decode_catalog_content(response.read(), response.headers.get_content_charset())


def decode_catalog_content(raw_content, charset=None):
    if charset:
        return raw_content.decode(charset, errors="replace")

    content = raw_content.decode("utf-8-sig", errors="replace")

    if "\ufffd" in content:
        return raw_content.decode("latin-1", errors="replace")

    return content


def parse_csv(content):
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel()
        dialect.delimiter = ";"

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


def parse_stock_and_sizes(stock_value, fallback_sizes="", min_stock_per_size=MIN_STOCK_PER_SIZE):
    stock_text = str(stock_value or "").strip()
    total_stock = 0
    sizes = []

    if "|" in stock_text or "," in stock_text:
        for item in stock_text.split("|"):
            parts = [part.strip() for part in item.split(",", 1)]

            if not parts or not parts[0]:
                continue

            size = parts[0]
            quantity = parse_int(parts[1]) if len(parts) > 1 else 0
            if quantity >= min_stock_per_size:
                sizes.append(size)
                total_stock += quantity

        if sizes:
            return total_stock, ",".join(sizes)

        return 0, ""

    return parse_int(stock_text), fallback_sizes[:180]


def first_image_url(value):
    return str(value or "").split(",", 1)[0].strip()


def row_to_payload(row, row_number):
    supplier_code = find_value(row, "supplier_code") or build_fallback_code(row, row_number)
    wholesale_price = parse_money(find_value(row, "wholesale_price"))
    dropshipping_cost = parse_money(find_value(row, "dropshipping_cost")) or wholesale_price * Decimal("1.10")
    stock_quantity, sizes = parse_stock_and_sizes(find_value(row, "stock_quantity"), find_value(row, "sizes"))

    return {
        "supplier_code": supplier_code[:120],
        "name": (find_value(row, "name") or f"Produto {supplier_code}")[:180],
        "description": find_value(row, "description"),
        "category": find_value(row, "category")[:120],
        "brand": find_value(row, "brand")[:120],
        "image_url": first_image_url(find_value(row, "image_url")),
        "product_url": find_value(row, "product_url"),
        "wholesale_price": wholesale_price,
        "dropshipping_cost": dropshipping_cost,
        "suggested_sale_price": (dropshipping_cost * STORE_PRICE_MULTIPLIER).quantize(Decimal("0.01")),
        "stock_quantity": stock_quantity,
        "sizes": sizes,
        "raw_data": row,
        "is_active": True,
        "last_seen_at": timezone.now(),
    }


def import_supplier_catalog_content(
    content,
    catalog_format="csv",
    deactivate_missing=True,
    source=SupplierProduct.SOURCE_REVENDA_CALCADOS,
):
    catalog_format = (catalog_format or "csv").lower()

    if catalog_format == "xml":
        rows = parse_xml(content)
    else:
        rows = parse_csv(content)

    if not rows:
        raise ValueError("O catalogo nao trouxe produtos para importar.")

    payloads = {}

    for row_number, row in enumerate(rows, start=1):
        payload = row_to_payload(row, row_number)
        supplier_code = payload.pop("supplier_code")
        payloads[supplier_code] = payload

    existing = {
        product.supplier_code: product
        for product in SupplierProduct.objects.filter(source=source, supplier_code__in=payloads.keys())
    }

    to_create = []
    to_update = []
    update_fields = set()

    for supplier_code, payload in payloads.items():
        product = existing.get(supplier_code)

        if product:
            for field, value in payload.items():
                setattr(product, field, value)
                update_fields.add(field)

            to_update.append(product)
        else:
            to_create.append(
                SupplierProduct(
                    source=source,
                    supplier_code=supplier_code,
                    is_visible=payload["stock_quantity"] > 0,
                    **payload,
                )
            )

    if to_create:
        SupplierProduct.objects.bulk_create(to_create, batch_size=500)

    if to_update:
        SupplierProduct.objects.bulk_update(to_update, list(update_fields), batch_size=500)

    if deactivate_missing:
        SupplierProduct.objects.filter(source=source).exclude(supplier_code__in=payloads.keys()).update(is_active=False)

    return {
        "created": len(to_create),
        "updated": len(to_update),
        "total": len(rows),
    }


def import_supplier_catalog(url, catalog_format="csv", source=SupplierProduct.SOURCE_REVENDA_CALCADOS):
    return import_supplier_catalog_content(fetch_catalog(url), catalog_format, source=source)
