from datetime import timedelta
from uuid import uuid4

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


def create_registration_approved_notification(profile):
    return Notification.objects.get_or_create(
        unique_key=f"profile:{profile.id}:approved:client:{profile.user_id}",
        defaults={
            "recipient": profile.user,
            "kind": Notification.REGISTRATION_APPROVED,
            "title": "Cadastro aprovado",
            "message": (
                "Seu cadastro foi aprovado. "
                f"Seu limite liberado e de R$ {format_brl(profile.pre_approved_credit_limit)}. "
                f"Voce tambem recebeu um voucher de 5% valido ate {profile.welcome_discount_expires_at:%d/%m/%Y}. "
                "Voce ja pode acessar a loja e usar os recursos liberados para sua conta."
            ),
        },
    )


def create_credit_limit_increased_notification(profile, previous_limit):
    return Notification.objects.create(
        unique_key=f"profile:{profile.id}:credit-limit-increased:{uuid4().hex}:client:{profile.user_id}",
        recipient=profile.user,
        kind=Notification.CREDIT_LIMIT_INCREASED,
        title="Seu limite aumentou",
        message=(
            f"Seu limite aumentou de R$ {format_brl(previous_limit)} "
            f"para R$ {format_brl(profile.pre_approved_credit_limit)}."
        ),
    )


def create_sale_available_notification(sale):
    has_products = sale.products.exists()
    title = "Produto disponivel para finalizar" if has_products else "Pagamento disponivel para finalizar"
    message = (
        f"{sale.description}: acesse a loja para conferir os produtos separados "
        "e escolher a forma de pagamento."
    )

    if not has_products:
        message = f"{sale.description}: acesse o link enviado pela loja para escolher a forma de pagamento."

    return Notification.objects.get_or_create(
        unique_key=f"sale:{sale.id}:available:client:{sale.client_id}",
        defaults={
            "recipient": sale.client,
            "kind": Notification.SALE_AVAILABLE,
            "title": title,
            "message": message,
        },
    )


def create_sale_confirmed_notifications(sale):
    Notification.objects.get_or_create(
        unique_key=f"sale:{sale.id}:confirmed:client:{sale.client_id}",
        defaults={
            "recipient": sale.client,
            "kind": Notification.SALE_CONFIRMED,
            "title": "Compra efetivada",
            "message": (
                f"{sale.description}: sua forma de pagamento foi confirmada. "
                "Acompanhe os proximos passos em Minhas compras."
            ),
        },
    )

    user_model = get_user_model()

    for staff_user in user_model.objects.filter(is_active=True, is_staff=True):
        Notification.objects.get_or_create(
            unique_key=f"sale:{sale.id}:confirmed:staff:{staff_user.id}",
            defaults={
                "recipient": staff_user,
                "kind": Notification.SALE_CONFIRMED,
                "title": "Cliente efetivou a compra",
                "message": (
                    f"{sale.client.full_name}: {sale.description}. "
                    f"Forma de pagamento: {sale.get_selected_payment_method_display()}."
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

        days_late = (today - debt.due_date).days

        if days_late >= 1 and (days_late - 1) % 3 == 0:
            Notification.objects.get_or_create(
                unique_key=f"debt:{debt.id}:overdue:{today}:client:{debt.client_id}",
                defaults={
                    "recipient": debt.client,
                    "debt": debt,
                    "kind": Notification.OVERDUE,
                    "title": "Pagamento em atraso",
                    "message": (
                        f"{debt.description}: pagamento em atraso ha {days_late} dia(s). "
                        f"Total atualizado: R$ {format_brl(debt.total_amount())}. "
                        "Regularize o pagamento para evitar novos juros."
                    ),
                },
            )
            _notify_staff(
                debt,
                Notification.OVERDUE,
                f"overdue:{today}",
                "Cliente com pagamento em atraso",
                (
                    f"{debt.client.full_name}: {debt.description}, atraso de {days_late} dia(s), "
                    f"total atualizado R$ {format_brl(debt.total_amount())}."
                ),
            )
