from django.core.management.base import BaseCommand

from accounts.notifications import generate_due_notifications


class Command(BaseCommand):
    help = "Gera notificacoes internas para debitos proximos do vencimento."

    def handle(self, *args, **options):
        generate_due_notifications()
        self.stdout.write(self.style.SUCCESS("Notificacoes de vencimento atualizadas."))
