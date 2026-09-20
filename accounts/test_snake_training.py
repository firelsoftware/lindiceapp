"""Verifica permissão no servidor sem criar usuários ou alterar o banco."""
from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse, resolve

from .snake_views import snake_training


class SnakeTrainingAccessTests(SimpleTestCase):
    def request(self, user, filename="index.html"):
        request = RequestFactory().get("/gestao/snake-training/" + filename)
        request.user = user
        return snake_training(request, filename)

    def test_anonymous_cannot_read_page_or_assets(self):
        for filename in ("index.html", "style.css", "game.js"):
            response = self.request(AnonymousUser(), filename)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response.url)
            self.assertIn("no-store", response["Cache-Control"])

    def test_customers_staff_and_inactive_admin_cannot_read_any_file(self):
        for staff, superuser, active in ((False, False, True), (True, False, True), (True, True, False)):
            user = SimpleNamespace(is_authenticated=True, is_staff=staff, is_superuser=superuser, is_active=active)
            for filename in ("index.html", "style.css", "game.js"):
                self.assertEqual(self.request(user, filename).status_code, 403)

    def test_active_superuser_reads_complete_game_without_cache(self):
        admin = SimpleNamespace(is_authenticated=True, is_superuser=True, is_active=True)
        for filename, content in (("index.html", b"SNAKE TRAINING"), ("style.css", b".board"), ("game.js", b"executarAtividade")):
            response = self.request(admin, filename)
            self.assertEqual(response.status_code, 200)
            self.assertIn(content, response.content)
            self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(resolve(reverse("snake_training")).func, snake_training)

    def test_unlisted_files_are_not_served(self):
        from django.http import Http404
        admin = SimpleNamespace(is_authenticated=True, is_superuser=True, is_active=True)
        for filename in ("../models.py", "README.md", "unknown.js"):
            with self.assertRaises(Http404):
                self.request(admin, filename)
