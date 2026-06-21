"""Anonimiza definitivamente as contas cuja exclusao foi pedida ha 7+ dias.

Ate la, o cliente pode cancelar a exclusao apenas entrando novamente.
Rode periodicamente (ex.: cron diario):

    python manage.py purge_deleted_accounts
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User

GRACE_DAYS = 7


class Command(BaseCommand):
    help = "Anonimiza contas com exclusao solicitada ha mais de 7 dias"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="So mostra quantas seriam apagadas")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=GRACE_DAYS)
        pendentes = User.objects.filter(deletion_requested_at__lt=cutoff, is_active=True)

        if options["dry_run"]:
            self.stdout.write(f"{pendentes.count()} contas seriam anonimizadas.")
            return

        total = 0
        for user in pendentes:
            user.anonymize_personal_data()
            total += 1

        self.stdout.write(self.style.SUCCESS(f"{total} contas anonimizadas (exclusao apos {GRACE_DAYS} dias)."))
