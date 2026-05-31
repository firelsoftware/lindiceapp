from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Debt, Notification


def format_brl(value):
    return f"{value:.2f}".replace(".", ",")


def create_manual_debt_notification(debt):
    return Notification.objects.get_or_create(
        unique_key=f"debt:{debt.id}:created:client:{debt.client_id}",
        defaults={
            "recipient": debt.client,
            "debt": debt,
            "kind": Notification.MANUAL_DEBT,
            "title": "Novo debito cadastrado",
            "message": (
                f"{debt.description}: R$ {format_brl(debt.amount)}, "
                f"com vencimento em {debt.due_date:%d/%m/%Y}."
            ),
        },
    )


def _notify_staff(debt, kind, key_suffix, title, message):
    user_model = get_user_model()

    for staff_user in user_model.objects.filter(is_active=True, is_staff=True):
        Notification.objects.get_or_create(
            unique_key=f"debt:{debt.id}:{key_suffix}:staff:{staff_user.id}",
            defaults={
                "recipient": staff_user,
                "debt": debt,
                "kind": kind,
                "title": title,
                "message": message,
            },
        )


def generate_due_notifications(now=None):
    local_now = timezone.localtime(now or timezone.now())
    today = local_now.date()

    for debt in Debt.objects.filter(paid=False).select_related("client"):
        if debt.due_date == today + timedelta(days=2):
            Notification.objects.get_or_create(
                unique_key=f"debt:{debt.id}:due-soon:{today}:client:{debt.client_id}",
                defaults={
                    "recipient": debt.client,
                    "debt": debt,
                    "kind": Notification.DUE_SOON,
                    "title": "Vencimento em 2 dias",
                    "message": (
                        f"{debt.description}: R$ {format_brl(debt.total_amount())}, "
                        f"com vencimento em {debt.due_date:%d/%m/%Y}."
                    ),
                },
            )
            _notify_staff(
                debt,
                Notification.DUE_SOON,
                f"due-soon:{today}",
                "Cliente com vencimento em 2 dias",
                (
                    f"{debt.client.full_name}: {debt.description}, "
                    f"R$ {format_brl(debt.total_amount())}, vence em {debt.due_date:%d/%m/%Y}."
                ),
            )

        if debt.due_date == today and local_now.hour >= 21:
            Notification.objects.get_or_create(
                unique_key=f"debt:{debt.id}:due-today-21:{today}:client:{debt.client_id}",
                defaults={
                    "recipient": debt.client,
                    "debt": debt,
                    "kind": Notification.DUE_TODAY,
                    "title": "Pagamento pendente",
                    "message": (
                        f"{debt.description}: o pagamento ainda nao foi identificado. "
                        "Evite multa e juros por atraso."
                    ),
                },
            )
            _notify_staff(
                debt,
                Notification.DUE_TODAY,
                f"due-today-21:{today}",
                "Pagamento nao identificado ate 21h",
                (
                    f"{debt.client.full_name}: {debt.description}, "
                    f"R$ {format_brl(debt.total_amount())}. Entre em contato com o cliente."
                ),
            )
