from django.db import migrations


def tenis_primeiro(apps, schema_editor):
    Capa = apps.get_model("accounts", "CapaDoSite")
    capas = list(Capa.objects.using(schema_editor.connection.alias).order_by("posicao", "id"))
    tenis = next((capa for capa in capas if capa.titulo == "O tênis certo para andar o dia inteiro"), None)
    if tenis is None:
        return
    capas.remove(tenis)
    capas.insert(0, tenis)
    for posicao, capa in enumerate(capas):
        capa.posicao = posicao
    Capa.objects.using(schema_editor.connection.alias).bulk_update(capas, ["posicao"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0077_cor_escolhida_no_pedido")]
    operations = [migrations.RunPython(tenis_primeiro, migrations.RunPython.noop)]
