"""Protótipo privado: reaproveita a autenticação do Lindice, sem novo login."""
from pathlib import Path

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


GAME_DIR = Path(__file__).resolve().parent / "private" / "snake_training"
FILES = {"index.html": "text/html", "style.css": "text/css", "game.js": "text/javascript"}


@never_cache
@require_safe
def snake_training(request, filename="index.html"):
    # A checagem protege inclusive CSS e JS; os arquivos ficam fora de static.
    user = request.user
    if not user.is_authenticated:
        return redirect_to_login(request.get_full_path(), reverse("login"))
    if not (user.is_active and user.is_superuser):
        return HttpResponseForbidden("Acesso exclusivo do administrador.")
    if filename not in FILES:
        raise Http404
    response = HttpResponse(
        (GAME_DIR / filename).read_bytes(),
        content_type=f"{FILES[filename]}; charset=utf-8",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
    return response
