"""Coloca os dois Horizon na frente da vitrine da primeira tela.

A ordem era so por preco, entao os smartwatches mais caros ocupavam as oito
vagas e nenhum calcado aparecia - numa loja em que calcado e quase todo o
catalogo. Agora a loja escolhe a dedo quem vai na frente, e estes dois abrem.

O plano da Render nao da terminal, entao a escolha entra por aqui. Depois e so
mudar o campo "ordem na primeira tela" na ficha de cada produto.
"""

from django.db import migrations

# nome do produto -> lugar na vitrine
ESCOLHIDOS = [
    ("Horizon Titan", 1),
    ("Horizon Lite+", 2),
]


def escolher(apps, schema_editor):
    Produto = apps.get_model("accounts", "SupplierProduct")
    alias = schema_editor.connection.alias

    # Se a loja ja escolheu alguem, respeita e nao mexe.
    if Produto.objects.using(alias).filter(posicao_na_home__gt=0).exists():
        return

    for nome, posicao in ESCOLHIDOS:
        Produto.objects.using(alias).filter(name__icontains=nome).update(posicao_na_home=posicao)


def desfazer(apps, schema_editor):
    Produto = apps.get_model("accounts", "SupplierProduct")
    alias = schema_editor.connection.alias

    for nome, _ in ESCOLHIDOS:
        Produto.objects.using(alias).filter(name__icontains=nome).update(posicao_na_home=0)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0071_supplierproduct_posicao_na_home")]
    operations = [migrations.RunPython(escolher, desfazer)]
