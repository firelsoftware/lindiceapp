"""Deixa a Revenda de Calcados ja em 1,60 de margem.

A loja decidiu subir a margem desse fornecedor: com 1,40 e o desconto de 15% do
Pix, sobrava pouco (bota de custo R$ 197,89 saia por R$ 240,00 no Pix, com
R$ 42,11 de lucro). Em 1,60 o mesmo par sai por R$ 270,00 e deixa R$ 72,11.

So esta fonte muda. As outras seguem em 1,40, e a margem so vale da proxima
importacao em diante - o preco do que ja esta na loja nao se mexe aqui.

Como o plano da Render nao da terminal, esta e a unica forma de deixar o numero
pronto sem depender de alguem abrir a tela.
"""

from decimal import Decimal

from django.db import migrations

FONTE = "revenda_calcados"
MARGEM_NOVA = Decimal("1.60")
MARGEM_ANTIGA = Decimal("1.40")


def subir_margem(apps, schema_editor):
    Fonte = apps.get_model("accounts", "SupplierCatalogSource")
    alias = schema_editor.connection.alias
    fonte = Fonte.objects.using(alias).filter(source=FONTE).first()

    if fonte is None:
        # A fonte e criada quando alguem abre o painel de fornecedores. Se ainda
        # nao existe, ja nasce com a margem certa.
        Fonte.objects.using(alias).create(
            source=FONTE,
            display_name="Revenda de Calcados",
            price_multiplier=MARGEM_NOVA,
        )

        return

    # Se a loja ja tiver mexido na margem, respeita a escolha dela.
    if fonte.price_multiplier == MARGEM_ANTIGA:
        fonte.price_multiplier = MARGEM_NOVA
        fonte.save(update_fields=["price_multiplier"])


def voltar(apps, schema_editor):
    Fonte = apps.get_model("accounts", "SupplierCatalogSource")
    alias = schema_editor.connection.alias
    Fonte.objects.using(alias).filter(source=FONTE, price_multiplier=MARGEM_NOVA).update(
        price_multiplier=MARGEM_ANTIGA
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0066_suppliercatalogsource_price_multiplier")]
    operations = [migrations.RunPython(subir_margem, voltar)]
