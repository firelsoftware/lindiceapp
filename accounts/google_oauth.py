"""Entrada pela conta Google usando OAuth 2.0 (fluxo de codigo de autorizacao).

Sem dependencia nova: a troca do codigo pelo token e a leitura do perfil sao
chamadas HTTPS feitas pelo proprio servidor, com urllib. O navegador do cliente
nunca carrega o segredo, e o perfil vem direto do Google.
"""

import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = "openid email profile"
REQUEST_TIMEOUT = 10


class GoogleAuthError(Exception):
    """Falha em qualquer etapa da conversa com o Google."""


def is_enabled():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def new_state():
    """Valor unico que amarra o retorno do Google a esta sessao."""
    return secrets.token_urlsafe(32)


def build_authorization_url(redirect_uri, state):
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }

    return f"{AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _request_json(url, data=None, headers=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    request = urllib.request.Request(url, data=body, headers=headers or {})

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:500]
        logger.warning("Google respondeu %s em %s: %s", error.code, url, detail)
        raise GoogleAuthError("O Google recusou a solicitacao.") from error
    except (urllib.error.URLError, TimeoutError) as error:
        logger.warning("Falha de conexao com o Google em %s: %s", url, error)
        raise GoogleAuthError("Nao foi possivel falar com o Google.") from error
    except json.JSONDecodeError as error:
        logger.warning("Resposta ilegivel do Google em %s", url)
        raise GoogleAuthError("Resposta inesperada do Google.") from error


def exchange_code(code, redirect_uri):
    """Troca o codigo de uso unico pelo token de acesso."""
    payload = _request_json(
        TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    access_token = payload.get("access_token")

    if not access_token:
        raise GoogleAuthError("O Google nao devolveu o token de acesso.")

    return access_token


def fetch_profile(access_token):
    """Le nome e email da conta. A resposta vem do Google, nao do navegador."""
    payload = _request_json(
        USERINFO_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    email = (payload.get("email") or "").strip().lower()

    if not email:
        raise GoogleAuthError("A conta Google nao informou um email.")

    return {
        "sub": payload.get("sub", ""),
        "email": email,
        "email_verified": bool(payload.get("email_verified")),
        "full_name": (payload.get("name") or "").strip(),
        "given_name": (payload.get("given_name") or "").strip(),
    }


def get_profile(code, redirect_uri):
    return fetch_profile(exchange_code(code, redirect_uri))
