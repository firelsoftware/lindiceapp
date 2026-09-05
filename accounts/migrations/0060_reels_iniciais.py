"""Publica os primeiros videos da loja.

O dono nao tem terminal no plano da Render, e a senha do banco fica so nas
variaveis de ambiente. Entao os videos entram por aqui, no mesmo passo em que o
deploy aplica as migracoes.

Video que ja estiver cadastrado nao entra de novo, e desfazer a migracao nao
apaga nada: quem manda no que fica na loja e a tela de gestao.
"""

from django.db import migrations

LINKS = [
    "https://youtube.com/shorts/W25K2PUVI5s?feature=share",
    "https://youtube.com/shorts/J54HEdKbxCs?feature=share",
    "https://youtube.com/shorts/UcGh-VHJzyM?feature=share",
    "https://youtube.com/shorts/dbhT1RMK8jY?feature=share",
    "https://youtube.com/shorts/vEaIA1r5B-c?feature=share",
]


def codigo_do_video(link):
    for marcador in ("youtu.be/", "watch?v=", "/shorts/", "/embed/"):
        if marcador in link:
            resto = link.split(marcador, 1)[1]

            for separador in ("&", "?", "/", "#"):
                resto = resto.split(separador, 1)[0]

            return resto

    return ""


def publicar(apps, schema_editor):
    StoreReel = apps.get_model("accounts", "StoreReel")
    posicao = StoreReel.objects.count()

    for link in LINKS:
        codigo = codigo_do_video(link)

        if not codigo or StoreReel.objects.filter(video_url__contains=codigo).exists():
            continue

        StoreReel.objects.create(video_url=link, position=posicao, is_visible=True)
        posicao += 1


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0059_reel_do_youtube"),
    ]

    operations = [
        migrations.RunPython(publicar, noop),
    ]
