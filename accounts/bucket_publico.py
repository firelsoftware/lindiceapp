"""Copia as fotos da vitrine para o bucket publico.

O bucket principal e privado porque guarda documento de cliente (CPF, RG,
comprovante de residencia). Isso obriga todo link a vir assinado e a vencer em
uma hora, o que atrapalha justo a foto de produto: o navegador nao consegue
guardar em cache, e nenhum site de fora abre a imagem.

A saida e um segundo bucket, publico, so com a midia que ja aparece na loja.
As fotos novas ja nascem la; as antigas precisam ser copiadas uma vez, e e isso
que este modulo faz.

A chave do arquivo continua a mesma nos dois buckets, entao nada muda no banco:
o endereco passa a sair do bucket publico so porque o campo aponta para ele.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Somente o que aparece na loja. Documento de cliente mora em outros prefixos
# (identity_documents/, residence_proofs/, profile_photos/) e nao entra aqui
# de jeito nenhum.
PREFIXOS_DA_VITRINE = ("supplier_products/", "product_videos/", "reels/")


def _cliente():
    from django.core.files.storage import storages

    return storages["vitrine"].connection.meta.client


def listar_da_vitrine():
    """Todas as chaves de midia de vitrine que estao no bucket privado."""
    cliente = _cliente()
    paginador = cliente.get_paginator("list_objects_v2")
    chaves = []

    for prefixo in PREFIXOS_DA_VITRINE:
        for pagina in paginador.paginate(Bucket=settings.SUPABASE_STORAGE_BUCKET, Prefix=prefixo):
            for objeto in pagina.get("Contents", []):
                chaves.append((objeto["Key"], objeto.get("Size", 0)))

    return chaves


def ja_esta_no_publico(cliente, chave):
    from botocore.exceptions import ClientError

    try:
        cliente.head_object(Bucket=settings.SUPABASE_PUBLIC_BUCKET, Key=chave)

        return True
    except ClientError:
        return False


def copiar_uma(cliente, chave):
    """Copia um arquivo do bucket privado para o publico.

    Tenta a copia direta primeiro; se o Supabase recusar, baixa e sobe de novo.
    """
    origem = {"Bucket": settings.SUPABASE_STORAGE_BUCKET, "Key": chave}

    try:
        cliente.copy_object(
            Bucket=settings.SUPABASE_PUBLIC_BUCKET,
            Key=chave,
            CopySource=origem,
        )

        return "copiado"
    except Exception:
        logger.info("Copia direta falhou em %s, baixando e subindo", chave)

    corpo = cliente.get_object(**origem)["Body"].read()
    cliente.put_object(Bucket=settings.SUPABASE_PUBLIC_BUCKET, Key=chave, Body=corpo)

    return "reenviado"


def copiar_vitrine(limite=None):
    """Leva para o bucket publico tudo que ainda nao esta la.

    Pode rodar quantas vezes quiser: o que ja foi nao vai de novo. Devolve um
    resumo para a tela mostrar.
    """
    if not getattr(settings, "USE_SUPABASE_PUBLIC", False):
        return {"pronto": False, "recado": "O bucket publico ainda nao esta configurado."}

    cliente = _cliente()
    chaves = listar_da_vitrine()
    copiadas = 0
    puladas = 0
    bytes_copiados = 0
    falhas = []

    for chave, tamanho in chaves:
        if limite is not None and copiadas >= limite:
            break

        if ja_esta_no_publico(cliente, chave):
            puladas += 1
            continue

        try:
            copiar_uma(cliente, chave)
        except Exception as erro:
            logger.exception("Falha ao copiar %s", chave)
            falhas.append(f"{chave}: {type(erro).__name__}")
            continue

        copiadas += 1
        bytes_copiados += tamanho

    return {
        "pronto": True,
        "total": len(chaves),
        "copiadas": copiadas,
        "puladas": puladas,
        "bytes_copiados": bytes_copiados,
        "faltam": max(len(chaves) - copiadas - puladas, 0),
        "falhas": falhas[:20],
        "recado": "",
    }
