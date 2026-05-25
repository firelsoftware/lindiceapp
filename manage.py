#!/usr/bin/env python
"""Arquivo usado para executar comandos administrativos do Django."""
import os
import sys


def main():
    """Executa comandos administrativos do projeto."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Nao foi possivel importar o Django. Verifique se ele esta "
            "instalado e se o ambiente virtual esta ativo."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
