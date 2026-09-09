"""Poe os fones na vitrine da primeira tela, logo depois dos dois Horizon.

A loja escolheu quem abre a vitrine. Como o plano da Render nao da terminal, a
escolha entra por migracao; depois e so mudar o campo "ordem na primeira tela"
na ficha de cada produto.
"""

from django.db import migrations

# nome do produto -> lugar na vitrine
# So os dois mais caros: o Zone Buds fica de fora da vitrine de entrada.
ESCOLHIDOS = [
    ("Headset Wearzone WZ08", 3),
    ("Fone Wearzone WZ06", 4),
]


def escolher(apps, schema_editor):
    Produto = apps.get_model("accounts", "SupplierProduct")
    alias = schema_editor.connection.alias

    for nome, posicao in ESCOLHIDOS:
        # So mexe em quem ainda nao tem lugar escolhido, para nao atropelar
        # uma decisao que a loja tenha tomado pela tela.
        Produto.objects.using(alias).filter(name__icontains=nome, posicao_na_home=0).update(
            posicao_na_home=posicao
        )


def desfazer(apps, schema_editor):
    Produto = apps.get_model("accounts", "SupplierProduct")
    alias = schema_editor.connection.alias

    for nome, posicao in ESCOLHIDOS:
        Produto.objects.using(alias).filter(name__icontains=nome, posicao_na_home=posicao).update(
            posicao_na_home=0
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0073_alter_supplierproduct_posicao_na_home")]
    operations = [migrations.RunPython(escolher, desfazer)]
