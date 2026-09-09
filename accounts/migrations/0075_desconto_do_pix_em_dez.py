"""Poe o desconto do Pix em 10%.

O padrao do codigo so vale para loja nova: a linha de configuracao ja existe
gravada com 15. Como o plano da Render nao da terminal, a mudanca entra por
migracao. Depois disso, a loja muda quando quiser em /gestao/cashback/.
"""

from decimal import Decimal

from django.db import migrations


def ajustar(apps, schema_editor):
    Configuracao = apps.get_model("accounts", "StoreSettings")
    alias = schema_editor.connection.alias

    Configuracao.objects.using(alias).filter(pix_discount_percent=Decimal("15.00")).update(
        pix_discount_percent=Decimal("10.00")
    )


def desfazer(apps, schema_editor):
    Configuracao = apps.get_model("accounts", "StoreSettings")
    alias = schema_editor.connection.alias

    Configuracao.objects.using(alias).filter(pix_discount_percent=Decimal("10.00")).update(
        pix_discount_percent=Decimal("15.00")
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0074_fones_na_vitrine")]
    operations = [migrations.RunPython(ajustar, desfazer)]
