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
    """O cliente S3 do bucket principal, que serve para os dois buckets.

    Nao usa o storage da vitrine de proposito: a copia precisa rodar antes de
    a loja passar a servir as fotos de la.
    """
    from django.core.files.storage import default_storage

    return default_storage.connection.meta.client


def conferir_se_e_publico():
    """Abre um arquivo pelo endereco publico, como um cliente faria.

    E a unica prova de que o bucket esta mesmo publico: existir e ter o nome
    certo nao basta, a chave "Public bucket" pode ter ficado desligada, e ai a
    loja fica sem foto sem ninguem entender por que.

    Devolve (deu_certo, recado).
    """
    import urllib.error
    import urllib.request

    if not getattr(settings, "PODE_COPIAR_PARA_PUBLICO", False):
        return False, "O bucket publico ainda nao esta configurado."

    cliente = _cliente()
    chaves = listar_da_vitrine()

    if not chaves:
        return False, "Nao ha nenhuma foto de vitrine para conferir."

    chave = chaves[0][0]

    if not ja_esta_no_publico(cliente, chave):
        return False, "As fotos ainda nao foram copiadas para o bucket publico."

    endereco = f"https://{settings.SUPABASE_PUBLIC_DOMAIN}/{chave}"

    try:
        with urllib.request.urlopen(endereco, timeout=15) as resposta:
            if resposta.status == 200:
                return True, f"O bucket responde: {endereco}"

            return False, f"O bucket respondeu {resposta.status} em vez de 200."
    except urllib.error.HTTPError as erro:
        if erro.code in (400, 404):
            return False, (
                "O arquivo esta la, mas o bucket nao responde publicamente. "
                "No Supabase, abra o bucket, va em Edit bucket e ligue a chave "
                "\"Public bucket\"."
            )

        return False, f"O bucket respondeu {erro.code}."
    except Exception as erro:
        return False, f"Nao consegui abrir o endereco publico: {type(erro).__name__}"


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


# Um dia de cache no navegador. O nome do arquivo ja carrega um sufixo unico,
# entao foto trocada vira endereco novo e ninguem fica vendo a antiga.
CACHE_DA_VITRINE = "public, max-age=86400"


def situacao_no_publico(cliente, chave):
    """Diz se o arquivo ja esta la e se o cache dele esta certo.

    Devolve (existe, cache_ok).
    """
    from botocore.exceptions import ClientError

    try:
        cabecalhos = cliente.head_object(Bucket=settings.SUPABASE_PUBLIC_BUCKET, Key=chave)
    except ClientError:
        return False, False

    cache = (cabecalhos.get("CacheControl") or "").lower()

    return True, "max-age" in cache and "no-cache" not in cache


def ja_esta_no_publico(cliente, chave):
    existe, _ = situacao_no_publico(cliente, chave)

    return existe


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
            # Sem REPLACE o Cache-Control nao vai junto e o Supabase responde
            # no-cache, tirando o unico motivo de existir deste bucket.
            MetadataDirective="REPLACE",
            CacheControl=CACHE_DA_VITRINE,
            ContentType=tipo_do_arquivo(chave),
        )

        return "copiado"
    except Exception:
        logger.info("Copia direta falhou em %s, baixando e subindo", chave)

    corpo = cliente.get_object(**origem)["Body"].read()
    cliente.put_object(
        Bucket=settings.SUPABASE_PUBLIC_BUCKET,
        Key=chave,
        Body=corpo,
        CacheControl=CACHE_DA_VITRINE,
        ContentType=tipo_do_arquivo(chave),
    )

    return "reenviado"


def tipo_do_arquivo(chave):
    """O content-type pela extensao, para a imagem nao chegar como binario."""
    import mimetypes

    return mimetypes.guess_type(chave)[0] or "application/octet-stream"


def copiar_vitrine(limite=None):
    """Leva para o bucket publico tudo que ainda nao esta la.

    Pode rodar quantas vezes quiser: o que ja foi nao vai de novo. Devolve um
    resumo para a tela mostrar.
    """
    if not getattr(settings, "PODE_COPIAR_PARA_PUBLICO", False):
        return {"pronto": False, "recado": "O bucket publico ainda nao esta configurado."}

    cliente = _cliente()
    chaves = listar_da_vitrine()
    copiadas = 0
    corrigidas = 0
    puladas = 0
    bytes_copiados = 0
    falhas = []

    for chave, tamanho in chaves:
        if limite is not None and copiadas >= limite:
            break

        existe, cache_ok = situacao_no_publico(cliente, chave)

        if existe and cache_ok:
            puladas += 1
            continue

        if existe:
            # Copia antiga, sem o cabecalho de cache: refaz por cima.
            corrigidas += 1

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
        "corrigidas": corrigidas,
        "puladas": puladas,
        "bytes_copiados": bytes_copiados,
        "faltam": max(len(chaves) - copiadas - puladas, 0),
        "falhas": falhas[:20],
        "recado": "",
    }
