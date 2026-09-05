"""Quanto do Supabase a loja ja gastou.

O plano gratuito tem cota de arquivos e de banco. Estourar significa parar de
gravar foto e, no limite, perder o projeto - foi o que aconteceu antes. Aqui a
gente mede o que ja esta gravado e guarda o numero, para o site avisar antes de
bater no teto em vez de descobrir na hora que o upload falha.

A medicao completa varre o bucket, entao ela nao roda a cada pagina: fica
guardada numa linha unica e e refeita quando alguem da loja pede, ou somada de
pouquinho a cada foto nova.
"""

import logging
import os

from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

# Limites do plano. Ficam em variavel de ambiente porque mudam quando o plano
# muda, e ninguem quer subir codigo so por causa disso.
COTA_ARQUIVOS = int(os.environ.get("SUPABASE_STORAGE_QUOTA_BYTES", 1 * 1024 ** 3))
COTA_BANCO = int(os.environ.get("SUPABASE_DB_QUOTA_BYTES", 500 * 1024 ** 2))

# A partir daqui o site comeca a avisar.
NIVEL_ATENCAO = 75
NIVEL_PERIGO = 90


def formatar_bytes(quantidade):
    """1536 -> '1,5 KB'. Numero para gente ler, com virgula decimal."""
    quantidade = float(quantidade or 0)

    for unidade in ("bytes", "KB", "MB", "GB", "TB"):
        if quantidade < 1024 or unidade == "TB":
            if unidade == "bytes":
                return f"{int(quantidade)} bytes"

            return f"{quantidade:.1f} {unidade}".replace(".", ",")

        quantidade /= 1024

    return f"{quantidade:.1f} TB".replace(".", ",")


def medir_arquivos():
    """Soma o tamanho de tudo que esta gravado. Devolve (bytes, quantidade)."""
    if not getattr(settings, "USE_SUPABASE_STORAGE", False):
        # Em desenvolvimento os arquivos ficam em disco.
        raiz = getattr(settings, "MEDIA_ROOT", "")

        if not raiz or not os.path.isdir(raiz):
            return 0, 0

        total = 0
        quantos = 0

        for pasta, _, arquivos in os.walk(raiz):
            for nome in arquivos:
                try:
                    total += os.path.getsize(os.path.join(pasta, nome))
                    quantos += 1
                except OSError:
                    continue

        return total, quantos

    from django.core.files.storage import default_storage

    cliente = default_storage.connection.meta.client
    paginador = cliente.get_paginator("list_objects_v2")
    total = 0
    quantos = 0

    for pagina in paginador.paginate(Bucket=settings.SUPABASE_STORAGE_BUCKET):
        for objeto in pagina.get("Contents", []):
            total += objeto.get("Size", 0)
            quantos += 1

    return total, quantos


def medir_banco():
    """Tamanho do banco em bytes."""
    motor = connection.settings_dict.get("ENGINE", "")

    if "postgres" in motor:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_database_size(current_database())")

            return cursor.fetchone()[0] or 0

    caminho = connection.settings_dict.get("NAME", "")

    try:
        return os.path.getsize(caminho)
    except (OSError, TypeError):
        return 0


def atualizar_medicao():
    """Mede tudo de novo e guarda. Devolve a linha salva."""
    from .models import UsoDeEspaco

    uso = UsoDeEspaco.load()
    erro = ""

    try:
        arquivos_bytes, arquivos_quantidade = medir_arquivos()
    except Exception as falha:
        logger.exception("Falha ao medir o espaco de arquivos")
        arquivos_bytes, arquivos_quantidade = uso.arquivos_bytes, uso.arquivos_quantidade
        erro = f"Nao consegui ler o bucket: {type(falha).__name__}"

    try:
        banco_bytes = medir_banco()
    except Exception as falha:
        logger.exception("Falha ao medir o espaco do banco")
        banco_bytes = uso.banco_bytes
        erro = (erro + " | " if erro else "") + f"Nao consegui medir o banco: {type(falha).__name__}"

    uso.arquivos_bytes = arquivos_bytes
    uso.arquivos_quantidade = arquivos_quantidade
    uso.banco_bytes = banco_bytes
    uso.medido_em = timezone.now()
    uso.erro = erro[:200]
    uso.save()

    return uso


def somar_arquivos(bytes_novos, quantidade=1):
    """Soma o que acabou de subir, sem varrer o bucket de novo.

    Mantem o aviso proximo da realidade entre uma medicao completa e outra.
    """
    if not bytes_novos:
        return

    from .models import UsoDeEspaco

    uso = UsoDeEspaco.load()

    if not uso.medido_em:
        # Sem uma medicao de base, somar sozinho daria um numero mentiroso.
        return

    uso.arquivos_bytes += int(bytes_novos)
    uso.arquivos_quantidade += int(quantidade)
    uso.save(update_fields=["arquivos_bytes", "arquivos_quantidade"])


def _linha(rotulo, usado, cota):
    percentual = (usado / cota * 100) if cota else 0

    return {
        "rotulo": rotulo,
        "usado": usado,
        "usado_legivel": formatar_bytes(usado),
        "cota": cota,
        "cota_legivel": formatar_bytes(cota),
        "livre": max(cota - usado, 0),
        "livre_legivel": formatar_bytes(max(cota - usado, 0)),
        "percentual": round(percentual, 1),
        # A largura da barra vai separada, com ponto: em pt-BR o Django escreve
        # "59,3" no template e o CSS ignora a virgula, deixando a barra cheia.
        "largura_css": f"{min(percentual, 100):.1f}".replace(",", "."),
        "faltam": round(max(100 - percentual, 0), 1),
        "nivel": "perigo" if percentual >= NIVEL_PERIGO else ("atencao" if percentual >= NIVEL_ATENCAO else "ok"),
    }


def resumo_do_espaco():
    """O quadro pronto para a tela: cada cota, quanto falta e se e para avisar."""
    from .models import UsoDeEspaco

    uso = UsoDeEspaco.load()
    linhas = [
        _linha("Fotos e vídeos", uso.arquivos_bytes, COTA_ARQUIVOS),
        _linha("Banco de dados", uso.banco_bytes, COTA_BANCO),
    ]
    pior = max(linhas, key=lambda linha: linha["percentual"])

    return {
        "linhas": linhas,
        "pior": pior,
        "avisar": bool(uso.medido_em) and pior["nivel"] != "ok",
        "medido_em": uso.medido_em,
        "arquivos_quantidade": uso.arquivos_quantidade,
        "erro": uso.erro,
    }
