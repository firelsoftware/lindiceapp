"""Extract a reviewable CSV catalog and product JPEGs from supplier PDFs."""

import argparse
import csv
import re
import zlib
from pathlib import Path


STREAM_PATTERN = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
IMAGE_PATTERN = re.compile(
    rb"<<(?P<header>.*?/Subtype\s*/Image.*?)>>\s*stream\r?\n"
    rb"(?P<data>.*?)\r?\nendstream",
    re.S,
)
PRODUCT_PATTERN = re.compile(
    r"(?P<body>.*?)(?:BT\s+[\d.]+\s+[\d.]+\s+Td\s+)?"
    r"/F1\s+11\.0\s+Tf\s+\[\(Ref\.: (?P<reference>[^)]+)\)\]\s+TJ\s+ET",
    re.S,
)
SIZE_PATTERN = re.compile(
    r"/(?P<font>F1|F2)\s+10\.0\s+Tf\s+\[\((?P<size>\d+)\)\]\s+TJ\s+ET"
)


def decoded_content_streams(pdf_bytes):
    streams = []

    for match in STREAM_PATTERN.finditer(pdf_bytes):
        try:
            streams.append(zlib.decompress(match.group(1)).decode("latin-1"))
        except zlib.error:
            continue

    return streams


def extract_products(pdf_path):
    pdf_bytes = pdf_path.read_bytes()
    content = "\n".join(decoded_content_streams(pdf_bytes))
    products = []

    for match in PRODUCT_PATTERN.finditer(content):
        sizes = [
            size_match.group("size")
            for size_match in SIZE_PATTERN.finditer(match.group("body"))
            if size_match.group("font") == "F2"
        ]
        products.append(
            {
                "supplier_code": match.group("reference"),
                "sizes": ",".join(sizes),
            }
        )

    images = []

    for match in IMAGE_PATTERN.finditer(pdf_bytes):
        if b"/Filter /DCTDecode" in match.group("header"):
            images.append(match.group("data"))

    if len(images) != len(products):
        raise ValueError(
            f"{pdf_path.name}: {len(products)} produtos e {len(images)} fotos encontrados."
        )

    return products, images


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--category", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    args = parser.parse_args()

    products, images = extract_products(args.pdf)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.csv.parent.mkdir(parents=True, exist_ok=True)

    with args.csv.open("w", newline="", encoding="utf-8-sig") as catalog:
        writer = csv.DictWriter(
            catalog,
            fieldnames=[
                "codigo",
                "produto",
                "categoria",
                "foto",
                "tamanhos",
                "estoque",
                "valor",
                "preco dropshipping",
            ],
            delimiter=";",
        )
        writer.writeheader()

        for product, image in zip(products, images):
            reference = product["supplier_code"]
            image_name = f"{reference.lower()}.jpg"
            image_path = args.output_dir / image_name
            image_path.write_bytes(image)
            sizes = product["sizes"]
            writer.writerow(
                {
                    "codigo": reference,
                    "produto": f"{args.category} {reference}",
                    "categoria": args.category,
                    "foto": f"/static/accounts/catalog-test/{args.category.lower()}/{image_name}",
                    "tamanhos": sizes,
                    "estoque": max(len(sizes.split(",")), 1) if sizes else 0,
                    "valor": "",
                    "preco dropshipping": "",
                }
            )

    print(f"{len(products)} produtos extraidos de {args.pdf.name}.")


if __name__ == "__main__":
    main()
