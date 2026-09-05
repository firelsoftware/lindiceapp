"""Cadastra os videos curtos da loja (reels) a partir de uma pasta.

Ignora arquivos cujo nome termina em "(1)", que sao copias baixadas duas vezes,
e nao repete videos que ja estejam cadastrados.
"""

import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from accounts.models import StoreReel

COPIA = re.compile(r"\(\d+\)\s*$")


class Command(BaseCommand):
    help = "Importa videos de uma pasta como reels da loja."

    def add_arguments(self, parser):
        parser.add_argument("pasta", help="Pasta com os arquivos de video.")
        parser.add_argument("--padrao", default="*.mp4", help="Padrao dos arquivos (padrao: *.mp4).")
        parser.add_argument("--ensaio", action="store_true", help="Mostra sem gravar.")

    def handle(self, *args, **options):
        pasta = Path(options["pasta"])

        if not pasta.is_dir():
            raise CommandError(f"Pasta nao encontrada: {pasta}")

        arquivos = sorted(pasta.glob(options["padrao"]))
        ja_cadastrados = set(StoreReel.objects.values_list("title", flat=True))
        entraram = ignorados = repetidos = 0
        posicao = StoreReel.objects.count()

        for arquivo in arquivos:
            nome = arquivo.stem

            if COPIA.search(nome):
                self.stdout.write(f"  copia ignorada: {arquivo.name}")
                ignorados += 1
                continue

            if nome in ja_cadastrados:
                repetidos += 1
                continue

            tamanho = arquivo.stat().st_size / (1024 * 1024)
            self.stdout.write(f"  {arquivo.name}  ({tamanho:.1f} MB)")

            if options["ensaio"]:
                entraram += 1
                continue

            reel = StoreReel(title=nome, position=posicao)

            with arquivo.open("rb") as conteudo:
                reel.video.save(arquivo.name, File(conteudo), save=False)

            reel.save()
            entraram += 1
            posicao += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{entraram} reels cadastrados."))

        if ignorados:
            self.stdout.write(f"{ignorados} copias '(1)' descartadas.")

        if repetidos:
            self.stdout.write(f"{repetidos} ja estavam cadastrados.")

        if options["ensaio"]:
            self.stdout.write(self.style.WARNING("ENSAIO: nada foi gravado."))
