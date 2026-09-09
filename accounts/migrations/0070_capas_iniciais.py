"""Publica as quatro fotos do carrossel da primeira tela.

O plano da Render nao da terminal, entao subir arquivo em producao so acontece
pela migracao. As imagens vao junto no repositorio, em accounts/seed/capa/, ja
reduzidas para a web: as oito somam menos de 500 KB.

Roda uma vez so. Se a loja ja tiver mexido nas capas, nao mexe em nada.
"""

import os

from django.core.files import File
from django.db import migrations

PASTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed", "capa")

CAPAS = [
    {
        "arquivo": "fitness",
        "titulo": "Moda fitness que acompanha o seu ritmo",
        "chamada": "Peças leves para treinar e seguir o dia.",
        "categoria": "",
        "posicao": 0,
    },
    {
        "arquivo": "lingerie",
        "titulo": "Lingerie para o seu dia a dia",
        "chamada": "Conforto e acabamento que você sente ao vestir.",
        "categoria": "",
        "posicao": 1,
    },
    {
        "arquivo": "tenis",
        "titulo": "O tênis certo para andar o dia inteiro",
        "chamada": "Do treino ao trabalho, sem trocar de sapato.",
        "categoria": "Tenis Premium e Original",
        "posicao": 2,
    },
    {
        "arquivo": "smartwatch",
        "titulo": "Smartwatch com tudo no seu pulso",
        "chamada": "Saúde, notificações e bateria que dura.",
        "categoria": "Smartwatches",
        "posicao": 3,
    },
]


def publicar(apps, schema_editor):
    Capa = apps.get_model("accounts", "CapaDoSite")
    alias = schema_editor.connection.alias

    # Ja existe capa cadastrada: a loja assumiu o comando, nao mexer.
    if Capa.objects.using(alias).exists():
        return

    for dados in CAPAS:
        larga = os.path.join(PASTA, f"{dados['arquivo']}.webp")
        em_pe = os.path.join(PASTA, f"{dados['arquivo']}-celular.webp")

        if not os.path.exists(larga):
            continue

        capa = Capa(
            titulo=dados["titulo"],
            chamada=dados["chamada"],
            categoria=dados["categoria"],
            posicao=dados["posicao"],
            visivel=True,
        )

        with open(larga, "rb") as arquivo:
            capa.imagem.save(f"{dados['arquivo']}.webp", File(arquivo), save=False)

        if os.path.exists(em_pe):
            with open(em_pe, "rb") as arquivo:
                capa.imagem_celular.save(
                    f"{dados['arquivo']}-celular.webp", File(arquivo), save=False
                )

        capa.save(using=alias)


def desfazer(apps, schema_editor):
    # Desfazer a migracao nao apaga capa: quem manda no que aparece no site e
    # a tela de gestao, nao o historico de migracoes.
    pass


class Migration(migrations.Migration):
    dependencies = [("accounts", "0069_capadosite_remove_storesettings_hero_image_and_more")]
    operations = [migrations.RunPython(publicar, desfazer)]
