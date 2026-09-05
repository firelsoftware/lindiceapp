"""Armazenamento de arquivos da loja no Supabase.

O padrao do django-storages pergunta ao bucket se o arquivo ja existe antes de
gravar (HeadObject). O Supabase responde 403 nessa consulta quando a chave nao
tem permissao de listagem, e a gravacao nem chega a acontecer.

Aqui cada arquivo recebe um sufixo unico no proprio nome, entao nao ha nada a
consultar: grava direto. De quebra, some uma ida e volta de rede por upload.
"""

import os
import uuid

from storages.backends.s3 import S3Storage


class SupabaseMediaStorage(S3Storage):
    # Sem consulta previa: o nome ja e unico.
    file_overwrite = True

    def get_available_name(self, name, max_length=None):
        pasta, arquivo = os.path.split(name)
        base, extensao = os.path.splitext(arquivo)
        unico = f"{base}-{uuid.uuid4().hex[:10]}{extensao}"

        if max_length and len(unico) > max_length:
            sobra = len(unico) - max_length
            base = base[: max(1, len(base) - sobra)]
            unico = f"{base}-{uuid.uuid4().hex[:10]}{extensao}"

        return os.path.join(pasta, unico).replace("\\", "/")
