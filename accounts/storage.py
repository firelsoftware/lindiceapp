"""Armazenamento de arquivos da loja no Supabase.

O padrao do django-storages pergunta ao bucket se o arquivo ja existe antes de
gravar (HeadObject). O Supabase responde 403 nessa consulta quando a chave nao
tem permissao de listagem, e a gravacao nem chega a acontecer.

Aqui cada arquivo recebe um sufixo unico no proprio nome, entao nao ha nada a
consultar: grava direto. De quebra, some uma ida e volta de rede por upload.
"""

import os
import re
import uuid

from storages.backends.s3 import S3Storage


def safe_upload_name(name):
    """Return an object key that is friendly to S3/Supabase and browsers."""
    pasta, arquivo = os.path.split(name)
    base, extensao = os.path.splitext(arquivo)
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-_")
    extensao = re.sub(r"[^A-Za-z0-9.]+", "", extensao.lower())

    if not base:
        base = "arquivo"

    if not extensao:
        extensao = ".bin"

    return os.path.join(pasta, f"{base}{extensao}").replace("\\", "/")


class SupabaseMediaStorage(S3Storage):
    # Sem consulta previa: o nome ja e unico.
    file_overwrite = True

    def get_available_name(self, name, max_length=None):
        name = safe_upload_name(name)
        pasta, arquivo = os.path.split(name)
        base, extensao = os.path.splitext(arquivo)
        unico = f"{base}-{uuid.uuid4().hex[:10]}{extensao}"

        if max_length and len(unico) > max_length:
            sobra = len(unico) - max_length
            base = base[: max(1, len(base) - sobra)]
            unico = f"{base}-{uuid.uuid4().hex[:10]}{extensao}"

        return os.path.join(pasta, unico).replace("\\", "/")
