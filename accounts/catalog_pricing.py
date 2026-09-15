"""Preços dos PDFs de calçados de setembro/2026, sem afetar outros fornecedores."""
from decimal import Decimal, ROUND_CEILING


def pdf_catalog_price(retail):
    base = Decimal(str(retail))
    if not base.is_finite() or base <= 0:
        raise ValueError('Preço de varejo deve ser positivo e finito.')
    multiplier = Decimal('1.05') if base > Decimal('200') else Decimal('1.10')
    adjusted = base * multiplier
    return (((adjusted + Decimal('.10')) / Decimal('10')).to_integral_value(
        rounding=ROUND_CEILING) * Decimal('10') - Decimal('.10')).quantize(Decimal('.01'))
