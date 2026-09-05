import calendar
import hashlib
from io import StringIO
from pathlib import Path
from django.conf import settings
from datetime import timedelta
import json
import logging
import re
import secrets
from decimal import Decimal, InvalidOperation
import unicodedata
import uuid
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Max, Q, Sum, Value, When
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.core import signing
from django.core.management import call_command
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import google_oauth
from .forms import MAX_PRODUCT_PHOTOS_PER_UPLOAD, validate_product_photo, CHECKOUT_PAYMENT_CREDIT, CartCheckoutForm, CheckoutCpfForm, ClientApprovalForm, CreditSaleForm, CreditSaleProductFormSet, DocesEMaisProductForm, InstallmentChoiceForm, ManualDebtForm, MeasurementsForm, PersonalDebtForm, PhoneVerificationForm, ProductCostForm, ProductForm, PartnerBagForm, ProfilePhotoForm, PromoEmailForm, RegisterForm, StoreSettingsForm, StoreOrderForm, SupplierCatalogSourceForm, SupplierForm, NewSupplierProductForm, StoreReelForm, SupplierProductEditForm, SupplierProductPhotoFormSet, SupplierProductVariantFormSet, UserPasswordChangeForm
from .models import StoreReel, StoreSettings, cashback_balance, ClientProfile, CreditSale, CreditSaleProduct, Debt, get_or_create_referral_code, Notification, PaymentAlert, PersonalDebt, points_balance_capped, points_discount_percent, credit_price_from_retail, retail_price_from_wholesale, Product, ProductCost, resolve_referrer, StoreOrder, Supplier, SupplierCatalogSource, SupplierProduct, SupplierProductPhoto, WELCOME_DISCOUNT_PERCENT, add_months, money
from .bucket_publico import copiar_vitrine, PREFIXOS_DA_VITRINE
from .espaco import atualizar_medicao, resumo_do_espaco, somar_arquivos
from .notifications import create_credit_limit_increased_notification, create_manual_debt_notification, create_registration_approved_notification, create_sale_available_notification, create_sale_confirmed_notifications, generate_due_notifications
from .payments import MercadoPagoNotConfigured, MercadoPagoRequestError, create_cart_checkout_preference, create_checkout_preference, create_credit_sale_card_preference, get_payment, payment_method_from_payment, verify_webhook_signature
from .store_shipping import SHIPPING_COSTS, shipping_cost_for
from .supplier_import import decode_catalog_content, import_supplier_catalog, import_supplier_catalog_content
from .utils import generate_phone_code

logger = logging.getLogger(__name__)
STORE_CHILD_SIZES = [str(size) for size in range(14, 33)]
STORE_ADULT_SIZES = [str(size) for size in range(33, 45)]
DOCES_E_MAIS_OWNER_EMAIL = "andrezamartinssantossilva@gmail.com"
DOCES_E_MAIS_SOURCE = "doces_e_mais"

# Navegacao da loja em dois niveis: grupo (nivel 1) -> categorias (nivel 2).
# As categorias sao os valores reais do campo SupplierProduct.category.
CATEGORY_GROUPS = [
    ("Calçados", [
        "Tênis", "Tênis Premium", "Saltos Anabelas Chinelos",
        "Rasteiras Papetes Flatforms", "Sapato Scarpin",
        "Ortopedicos Scarpin Mocassim Sapatilha", "Botas",
        "Botas Femininas", "Sandálias", "Anabela", "Meia Pata",
        "Sapatilhas", "Numeração Especial",
    ]),
    ("Infantil", ["Linha Infantil"]),
    ("Bolsas", ["Bolsas"]),
    ("Smartwatches", ["Smartwatches", "Fones de ouvido"]),
]
# Rotulos curtos para as abas de nivel 2.
CATEGORY_SHORT_LABELS = {
    "Saltos Anabelas Chinelos": "Saltos",
    "Rasteiras Papetes Flatforms": "Rasteiras",
    "Sapato Scarpin": "Scarpin",
    "Ortopedicos Scarpin Mocassim Sapatilha": "Ortopédicos",
    "Botas Femininas": "Botas Fem.",
    "Numeração Especial": "Num. especial",
}
# Grupos onde os filtros de numeracao/tamanho fazem sentido.
FOOTWEAR_GROUPS = {"Calçados", "Infantil"}

# Palavras que o cliente digita quando quer um smartwatch.
SEARCH_WATCH_ALIASES = ("relogio", "relogios", "smart watch", "smartwatch")


def _sem_acento(texto):
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())

    return "".join(ch for ch in normalizado if not unicodedata.combining(ch))

# Fotos de modelo usadas na faixa de inspiracao da loja. Ficam em
# accounts/static/accounts/img/modelos/<slug>.webp e ja vem com o topo
# esmaecido, entao o rosto praticamente nao aparece.
STORE_MODEL_PHOTOS = ["tenis", "sandalia", "rasteira", "bota", "bolsa", "bolsa2"]
CATEGORY_MODEL_PHOTOS = {
    "Tênis": ["tenis"],
    "Tênis Premium": ["tenis"],
    "Sandálias": ["sandalia"],
    "Anabela": ["sandalia"],
    "Meia Pata": ["sandalia"],
    "Saltos Anabelas Chinelos": ["sandalia", "rasteira"],
    "Rasteiras Papetes Flatforms": ["rasteira"],
    "Botas": ["bota"],
    "Botas Femininas": ["bota"],
    "Bolsas": ["bolsa", "bolsa2"],
    # Sem modelo propria de relogio ainda: usa os looks de trabalho, que
    # combinam com acessorio de pulso.
    "Bolsas e Relogios": ["bolsa", "bota"],
}
GROUP_MODEL_PHOTOS = {
    "Calçados": ["tenis", "sandalia", "rasteira", "bota"],
    "Bolsas": ["bolsa", "bolsa2"],
    "Relógios": ["bolsa", "bota"],
}


def pick_store_model_photos(category, group, limit=2):
    """Modelos das laterais da loja: a da categoria primeiro, depois as outras.

    A ordem das complementares gira a cada dia, entao a vitrine muda sozinha.
    """
    preferred = []
    if category or group:
        preferred = CATEGORY_MODEL_PHOTOS.get(category) or GROUP_MODEL_PHOTOS.get(group) or []
        if not preferred:
            return []
    others = [p for p in STORE_MODEL_PHOTOS if p not in preferred]
    if others:
        start = timezone.localdate().toordinal() % len(others)
        others = others[start:] + others[:start]
    return (preferred + others)[:limit]

PARTNER_SALES_STATUSES = (
    StoreOrder.PAID,
    StoreOrder.SUPPLIER_ORDERED,
    StoreOrder.SHIPPED,
)

DEFAULT_WHATSAPP_NOTICE = "Em breve vamos entrar em contato para confirmar disponibilidade e finalizar pelo WhatsApp."


def shipping_rates_payload():
    return {key: f"{value:.2f}" for key, value in SHIPPING_COSTS.items()}


def normalize_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")

    return ascii_value.lower()


def ensure_supplier_catalog_sources():
    defaults = [
        {
            "source": SupplierProduct.SOURCE_REVENDA_CALCADOS,
            "display_name": "Revenda de Calcados",
            "catalog_format": getattr(settings, "SHOE_SUPPLIER_CATALOG_FORMAT", SupplierCatalogSource.FORMAT_CSV),
            "supplier_panel_note": "Cole aqui a URL atual do catalogo da Revenda. Se preferir, voce ainda pode enviar o arquivo baixado do dia.",
            "customer_notice": "",
            "purchase_flow": SupplierCatalogSource.FLOW_STORE_CHECKOUT,
            "is_active": True,
        },
        {
            "source": SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            "display_name": "Parceiro sob consulta",
            "catalog_format": SupplierCatalogSource.FORMAT_CSV,
            "supplier_panel_note": "Sugestao de nome: Parceiro sob consulta. Use esta fonte para catalogos com disponibilidade mais instavel.",
            "customer_notice": DEFAULT_WHATSAPP_NOTICE,
            "purchase_flow": SupplierCatalogSource.FLOW_WHATSAPP_CONFIRMATION,
            "is_active": True,
        },
    ]

    sources = []
    for payload in defaults:
        source, _ = SupplierCatalogSource.objects.get_or_create(
            source=payload["source"],
            defaults=payload,
        )
        sources.append(source)

    return sources


def store_whatsapp_url(request, product):
    """Link do WhatsApp da loja com mensagem pronta sobre o produto.

    Inclui o link do produto para o vendedor identificar o item exato antes de
    responder. O codigo interno (faixa) nao aparece para o cliente.
    """
    number = getattr(settings, "STORE_WHATSAPP_NUMBER", "")
    if not number:
        return ""

    product_url = request.build_absolute_uri(reverse("store_product_detail", args=[product.id]))
    message = f"Olá, gostaria de saber mais sobre esse produto: {product.name}\n{product_url}"
    return f"https://wa.me/{number}?text={quote(message)}"


def source_notice_for_customer(product):
    if not product.requires_availability_confirmation():
        return ""

    source_config = SupplierCatalogSource.objects.filter(source=product.source, is_active=True).first()

    if source_config and source_config.customer_notice:
        return source_config.customer_notice

    return DEFAULT_WHATSAPP_NOTICE


def partner_sales_config(user):
    profile = getattr(user, "profile", None)

    if not profile:
        return {}

    extra_data = profile.extra_data or {}
    keyword = (extra_data.get("sales_report_brand_keyword") or "").strip()
    aliases = [alias.strip() for alias in extra_data.get("sales_report_brand_aliases", []) if str(alias).strip()]
    aliases = [keyword, *aliases] if keyword else aliases

    return {
        "keyword": keyword,
        "aliases": aliases,
        "title": (extra_data.get("sales_report_title") or "Relatorio de vendas").strip(),
    }


def user_can_view_partner_sales(user):
    return bool(partner_sales_config(user).get("keyword"))


def partner_profile_config(user):
    """Dados do papel de parceira (Ramose/Selma), guardados no extra_data."""
    profile = getattr(user, "profile", None)
    extra = (profile.extra_data if profile else None) or {}
    return {
        "is_partner": bool(extra.get("is_partner")),
        "name": (extra.get("partner_name") or "").strip(),
        "commission_percent": Decimal(str(extra.get("partner_commission_percent") or 0)),
        "notify_email": (extra.get("partner_notify_email") or "").strip(),
    }


def is_partner_user(user):
    return user.is_authenticated and not user.is_staff and partner_profile_config(user)["is_partner"]


def build_partner_sales_brand_query(aliases):
    query = Q()

    for alias in aliases:
        query |= Q(product_name__icontains=alias)

    return query


def percentage_growth(current_value, previous_value):
    current_decimal = Decimal(current_value or 0)
    previous_decimal = Decimal(previous_value or 0)

    if previous_decimal <= 0:
        return None if current_decimal <= 0 else Decimal("100.0")

    return ((current_decimal - previous_decimal) / previous_decimal * Decimal("100")).quantize(Decimal("0.1"))


def summarize_partner_sales_orders(orders):
    total_orders = len(orders)
    total_units = sum(order.quantity for order in orders)
    total_revenue = sum((order.total_amount for order in orders), Decimal("0.00"))
    total_profit = sum((order.estimated_profit for order in orders), Decimal("0.00"))
    average_ticket = (total_revenue / total_orders).quantize(Decimal("0.01")) if total_orders else Decimal("0.00")
    product_map = {}

    for order in orders:
        entry = product_map.setdefault(
            order.product_name,
            {
                "name": order.product_name,
                "units": 0,
                "orders": 0,
                "revenue": Decimal("0.00"),
                "profit": Decimal("0.00"),
                "last_sale_at": order.paid_at or order.created_at,
            },
        )
        entry["units"] += order.quantity
        entry["orders"] += 1
        entry["revenue"] += order.total_amount
        entry["profit"] += order.estimated_profit
        entry["last_sale_at"] = max(entry["last_sale_at"], order.paid_at or order.created_at)

    top_products = list(product_map.values())

    return {
        "total_orders": total_orders,
        "total_units": total_units,
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "average_ticket": average_ticket,
        "top_products": top_products,
    }


def sort_partner_sales_products(products, ranking):
    ranking = ranking or "units"

    if ranking == "revenue":
        return sorted(products, key=lambda item: (item["revenue"], item["units"]), reverse=True)

    if ranking == "profit":
        return sorted(products, key=lambda item: (item["profit"], item["units"]), reverse=True)

    if ranking == "recent":
        return sorted(products, key=lambda item: item["last_sale_at"], reverse=True)

    return sorted(products, key=lambda item: (item["units"], item["revenue"]), reverse=True)


def redirect_to_supplier_products():
    try:
        return redirect("supplier_products")
    except Exception:
        logger.exception("Falha ao resolver rota supplier_products")
        return redirect("/gestao/fornecedor/produtos/")


def safe_next_url(request, value):
    if value and url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return value

    return ""


def should_redirect_customer_to_store(user):
    if not user.is_authenticated or user.is_staff:
        return False

    profile = getattr(user, "profile", None)

    if not profile:
        return False

    if not profile.phone_verified or profile.registration_status != ClientProfile.APPROVED:
        return False

    return user.credit_sales.filter(status=CreditSale.PENDING).exists()


def authenticated_home_route(user):
    if user.is_staff:
        return "management_dashboard"

    if should_redirect_customer_to_store(user):
        return "store_front"

    return "dashboard"


def build_sale_payment_link(request, sale):
    return request.build_absolute_uri(reverse("public_choose_installments", args=[sale.public_token]))


def build_finalize_whatsapp_link(sale, payment_link):
    """Monta o link de WhatsApp do cliente com a mensagem e o link de finalizacao."""
    digits = re.sub(r"\D", "", sale.customer_phone() or "")
    if digits and not digits.startswith("55"):
        digits = f"55{digits}"
    if not digits:
        return ""
    message = f"Ola! Para finalizar sua compra na Lindice, acesse: {payment_link}"
    return f"https://wa.me/{digits}?text={quote(message)}"


def sale_checkout_context(sale, form, return_route):
    available_points = sale.available_points()

    return {
        "form": form,
        "sale": sale,
        "pix_option": sale.pix_option(),
        # Previa de quanto ficaria usando os pontos, para o cliente comparar.
        "pix_option_with_points": sale.pix_option(available_points) if available_points else None,
        "available_points": available_points,
        "card_payment_enabled": settings.CARD_PAYMENT_ENABLED,
        "card_options": sale.card_options(),
        "credit_options": sale.credit_options() if sale.can_use_credit() else [],
        "card_installments": [option["installments"] for option in sale.card_options()],
        "credit_installments": [option["installments"] for option in sale.credit_options()] if sale.can_use_credit() else [],
        "welcome_discount_available": sale.available_welcome_discount_amount() > 0,
        "welcome_discount_percent": WELCOME_DISCOUNT_PERCENT,
        "welcome_discount_preview": sale.available_welcome_discount_amount(),
        "credit_financed_amount": sale.credit_financed_amount(),
        "credit_remainder_amount": sale.credit_remainder_amount(),
        "credit_late_fee_percent": Debt._meta.get_field("late_fee_percent").default,
        "credit_monthly_interest_percent": Debt._meta.get_field("monthly_interest_percent").default,
        "credit_requires_registration": not sale.can_use_credit(),
        "return_route": return_route,
        "is_public_sale": return_route != "dashboard",
    }


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.get_user()
        # Se a conta estava marcada para exclusao, voltar a logar cancela.
        if getattr(user, "deletion_requested_at", None):
            user.cancel_deletion()
            messages.success(self.request, "Bem-vindo de volta! A exclusao da sua conta foi cancelada.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["google_login_enabled"] = google_oauth.is_enabled()
        return context

    def get_success_url(self):
        redirect_to = self.get_redirect_url()

        if redirect_to:
            return redirect_to

        return resolve_url(authenticated_home_route(self.request.user))


GOOGLE_STATE_SESSION_KEY = "google_oauth_state"
GOOGLE_NEXT_SESSION_KEY = "google_oauth_next"
GOOGLE_REF_SESSION_KEY = "google_oauth_ref"
GOOGLE_EMAIL_SESSION_KEY = "google_verified_email"
GOOGLE_NAME_SESSION_KEY = "google_verified_name"
GOOGLE_FIRST_NAME_SESSION_KEY = "google_verified_first_name"


def google_redirect_uri(request):
    return request.build_absolute_uri(reverse("google_login_callback"))


def google_login_start(request):
    """Manda o cliente para o Google, guardando o estado que valida a volta."""
    if not google_oauth.is_enabled():
        messages.error(request, "A entrada pelo Google nao esta disponivel no momento.")

        return redirect("login")

    state = google_oauth.new_state()
    request.session[GOOGLE_STATE_SESSION_KEY] = state
    request.session[GOOGLE_NEXT_SESSION_KEY] = safe_next_url(request, request.GET.get("next"))
    request.session[GOOGLE_REF_SESSION_KEY] = (request.GET.get("ref") or "").strip()

    return redirect(google_oauth.build_authorization_url(google_redirect_uri(request), state))


def google_login_callback(request):
    """Recebe a volta do Google, confere o estado e entra na conta."""
    expected_state = request.session.pop(GOOGLE_STATE_SESSION_KEY, "")
    next_url = safe_next_url(request, request.session.pop(GOOGLE_NEXT_SESSION_KEY, ""))
    ref_code = request.session.pop(GOOGLE_REF_SESSION_KEY, "")

    if request.GET.get("error"):
        messages.info(request, "Entrada pelo Google cancelada.")

        return redirect("login")

    code = request.GET.get("code", "")
    state = request.GET.get("state", "")

    if not code or not expected_state or not secrets.compare_digest(state, expected_state):
        messages.error(request, "Nao conseguimos confirmar a entrada pelo Google. Tente novamente.")

        return redirect("login")

    try:
        profile_data = google_oauth.get_profile(code, google_redirect_uri(request))
    except google_oauth.GoogleAuthError:
        logger.exception("Falha na entrada pelo Google")
        messages.error(request, "Nao conseguimos falar com o Google agora. Tente novamente em instantes.")

        return redirect("login")

    if not profile_data["email_verified"]:
        messages.error(request, "Seu email ainda nao foi confirmado no Google.")

        return redirect("login")

    email = profile_data["email"]
    user = get_user_model().objects.filter(email__iexact=email).first()

    if user is None:
        # Conta nova: o cadastro continua sendo o do Lindice, ja com o email
        # confirmado e o nome preenchidos.
        request.session[GOOGLE_EMAIL_SESSION_KEY] = email
        request.session[GOOGLE_NAME_SESSION_KEY] = profile_data["full_name"]
        request.session[GOOGLE_FIRST_NAME_SESSION_KEY] = profile_data["given_name"]
        messages.info(request, "Falta pouco: confirme seus dados para criar a conta.")
        destination = f"{reverse('register')}?google=1"

        if next_url:
            destination = f"{destination}&next={quote(next_url)}"

        if ref_code:
            destination = f"{destination}&ref={quote(ref_code)}"

        return redirect(destination)

    if not user.is_active:
        messages.error(request, "Esta conta esta desativada. Fale com a loja.")

        return redirect("login")

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    if getattr(user, "deletion_requested_at", None):
        user.cancel_deletion()
        messages.success(request, "Bem-vindo de volta! A exclusao da sua conta foi cancelada.")

    if next_url:
        return redirect(next_url)

    return redirect(authenticated_home_route(user))


def csrf_failure(request, reason=""):
    logger.warning("Falha de CSRF: %s", reason)
    messages.warning(request, "Sua sessao expirou. Entre novamente para continuar.")

    if request.user.is_authenticated:
        return redirect("dashboard")

    return redirect("login")


def legacy_installment_total(description):
    marker = " de "

    if marker not in description:
        return None

    try:
        return int(description.rsplit(marker, 1)[1])
    except ValueError:
        return None


def build_purchase_groups(user):
    debts = list(user.debts.filter(canceled=False).order_by("due_date", "id"))
    used_debt_ids = set()
    groups = []

    accepted_sales = user.credit_sales.filter(status=CreditSale.ACCEPTED).order_by("-accepted_at", "-created_at")

    for sale in accepted_sales:
        linked_debts = [debt for debt in debts if debt.credit_sale_id == sale.id]

        if not linked_debts:
            linked_debts = [
                debt
                for debt in debts
                if debt.id not in used_debt_ids
                and debt.description.startswith(f"{sale.description} - Parcela ")
                and legacy_installment_total(debt.description) == sale.selected_installments
            ]

        if linked_debts:
            used_debt_ids.update(debt.id for debt in linked_debts)
            groups.append(
                {
                    "title": sale.description,
                    "code": sale.sale_code,
                    "debts": linked_debts,
                    "total": sale.selected_total_with_interest or sum(debt.amount for debt in linked_debts),
                    "installments": sale.selected_installments,
                    "payment_method": sale.get_selected_payment_method_display() if sale.selected_payment_method else "",
                    "sale_id": sale.id,
                    "payment_status": sale.get_payment_status_display(),
                    "remainder_amount": sale.remainder_amount,
                    "remainder_payment_method": sale.get_remainder_payment_method_display() if sale.remainder_payment_method else "",
                    "mercado_pago_init_point": sale.mercado_pago_init_point,
                    "created_at": sale.created_at,
                }
            )
        elif sale.selected_payment_method in {CreditSale.PIX, CreditSale.CARD}:
            groups.append(
                {
                    "title": sale.description,
                    "code": sale.sale_code,
                    "debts": [],
                    "total": sale.selected_total_with_interest or sale.total_amount,
                    "installments": sale.selected_installments,
                    "payment_method": sale.get_selected_payment_method_display(),
                    "sale_id": sale.id,
                    "payment_status": sale.get_payment_status_display(),
                    "remainder_amount": sale.remainder_amount,
                    "remainder_payment_method": sale.get_remainder_payment_method_display() if sale.remainder_payment_method else "",
                    "mercado_pago_init_point": sale.mercado_pago_init_point,
                    "created_at": sale.created_at,
                }
            )

    standalone_debts = [debt for debt in debts if debt.id not in used_debt_ids]

    if standalone_debts:
        groups.append(
            {
                "title": "Debitos avulsos",
                "code": "",
                "debts": standalone_debts,
                "total": sum(debt.amount for debt in standalone_debts),
                "installments": None,
                "created_at": None,
            }
        )

    return groups


def build_client_financial_summary(profile):
    debts = list(profile.user.debts.order_by("due_date", "id"))
    active_debts = [debt for debt in debts if not debt.canceled]
    unpaid_debts = [debt for debt in active_debts if not debt.paid]
    overdue_debts = [debt for debt in unpaid_debts if debt.days_late() > 0]
    paid_debts = [debt for debt in active_debts if debt.paid]
    overdue_days = max((debt.days_late() for debt in overdue_debts), default=0)
    open_total = sum((debt.total_amount() for debt in unpaid_debts), Decimal("0.00"))
    overdue_total = sum((debt.total_amount() for debt in overdue_debts), Decimal("0.00"))
    paid_total = sum((debt.amount for debt in paid_debts), Decimal("0.00"))
    accepted_sales_count = profile.user.credit_sales.filter(status=CreditSale.ACCEPTED).count()

    if overdue_debts:
        relationship_label = "Inadimplente"
        relationship_badge = "badge-warning"
    elif unpaid_debts:
        relationship_label = "Em acompanhamento"
        relationship_badge = "badge-info"
    elif len(paid_debts) >= 3:
        relationship_label = "Cliente fiel"
        relationship_badge = "badge-success"
    elif paid_debts:
        relationship_label = "Bom historico"
        relationship_badge = "badge-success"
    else:
        relationship_label = "Novo cliente"
        relationship_badge = "badge-info"

    return {
        "profile": profile,
        "debts": debts,
        "next_unpaid_debt": unpaid_debts[0] if unpaid_debts else None,
        "open_debts_count": len(unpaid_debts),
        "open_total": open_total,
        "overdue_total": overdue_total,
        "overdue_days": overdue_days,
        "paid_debts_count": len(paid_debts),
        "paid_total": paid_total,
        "accepted_sales_count": accepted_sales_count,
        "relationship_label": relationship_label,
        "relationship_badge": relationship_badge,
    }


def build_finance_calendar(debts, reference_date):
    month_names = [
        "",
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    month_start = reference_date.replace(day=1)
    month_dates = calendar.Calendar(firstweekday=0).monthdatescalendar(month_start.year, month_start.month)
    debts_by_day = {}

    for debt in debts:
        debts_by_day.setdefault(debt["due_date"], []).append(debt)

    weeks = []
    for week in month_dates:
        cells = []
        for day in week:
            day_debts = debts_by_day.get(day, [])
            has_overdue = any(debt["days_late"] > 0 for debt in day_debts)
            is_today = day == reference_date
            if has_overdue:
                tone = "overdue"
            elif day_debts and is_today:
                tone = "today"
            elif day_debts:
                tone = "scheduled"
            else:
                tone = "empty"

            cells.append(
                {
                    "date": day,
                    "in_month": day.month == month_start.month,
                    "debts": day_debts,
                    "count": len(day_debts),
                    "total": sum((debt["amount"] for debt in day_debts), Decimal("0.00")),
                    "is_today": is_today,
                    "tone": tone,
                }
            )
        weeks.append(cells)

    return {
        "label": f"{month_names[month_start.month]} de {month_start.year}",
        "weeks": weeks,
    }


def hex_to_rgb(hex_value):
    normalized = (hex_value or PersonalDebt.DEFAULT_COLOR).lstrip("#")

    if len(normalized) != 6:
        normalized = PersonalDebt.DEFAULT_COLOR.lstrip("#")

    return tuple(int(normalized[index:index + 2], 16) for index in (0, 2, 4))


def personal_debt_color_style(hex_value):
    red, green, blue = hex_to_rgb(hex_value)
    brightness = ((red * 299) + (green * 587) + (blue * 114)) / 1000
    text_color = "#182230" if brightness >= 168 else "#ffffff"

    return {"background": hex_value or PersonalDebt.DEFAULT_COLOR, "text": text_color}


def build_store_commitment_entry(debt):
    return {
        "title": debt.description,
        "due_date": debt.due_date,
        "amount": debt.total_amount(),
        "signed_amount": -debt.total_amount(),
        "days_late": debt.days_late(),
        "kind": "store",
        "kind_label": "Lindice",
        "entry_type": PersonalDebt.TYPE_DEBT,
        "entry_type_label": "Divida",
        "category_label": "Compra no app",
        "chip_style": {"background": "#e7ecf2", "text": "#475467"},
        "notes": "",
    }


def build_personal_commitment_entry(debt):
    signed_amount = debt.total_amount() if debt.entry_type == PersonalDebt.TYPE_RECEIVABLE else -debt.total_amount()

    return {
        "title": debt.title,
        "due_date": debt.due_date,
        "amount": debt.total_amount(),
        "signed_amount": signed_amount,
        "days_late": debt.days_late(),
        "kind": "personal",
        "kind_label": "Pessoal",
        "entry_type": debt.entry_type,
        "entry_type_label": debt.get_entry_type_display(),
        "category_label": debt.get_category_display(),
        "chip_style": personal_debt_color_style(debt.color),
        "notes": debt.notes,
    }


def build_customer_finance_context(user, scope=None, include_store=True):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    next_month = add_months(month_start, 1)
    month_end = next_month - timedelta(days=1)
    if include_store:
        store_debts = list(user.debts.filter(paid=False, canceled=False).order_by("due_date", "id"))
    else:
        store_debts = []
    personal_qs = user.personal_debts.filter(paid=False)
    if scope:
        personal_qs = personal_qs.filter(scope=scope)
    personal_debts = list(personal_qs.order_by("due_date", "id"))
    commitments = [build_store_commitment_entry(debt) for debt in store_debts] + [
        build_personal_commitment_entry(debt) for debt in personal_debts
    ]
    commitments.sort(key=lambda item: (item["due_date"], item["title"]))
    overdue_debts = [debt for debt in commitments if debt["days_late"] > 0]
    due_this_month = [debt for debt in commitments if month_start <= debt["due_date"] <= month_end]
    future_debts = [debt for debt in commitments if debt["due_date"] > month_end]
    next_debt = commitments[0] if commitments else None
    personal_due_this_month = [debt for debt in due_this_month if debt["kind"] == "personal" and debt["entry_type"] == PersonalDebt.TYPE_DEBT]
    personal_future_debts = [debt for debt in future_debts if debt["kind"] == "personal" and debt["entry_type"] == PersonalDebt.TYPE_DEBT]
    receivables_this_month = [debt for debt in due_this_month if debt["kind"] == "personal" and debt["entry_type"] == PersonalDebt.TYPE_RECEIVABLE]
    future_receivables = [debt for debt in future_debts if debt["kind"] == "personal" and debt["entry_type"] == PersonalDebt.TYPE_RECEIVABLE]
    debt_total = sum((-debt["signed_amount"] for debt in commitments if debt["signed_amount"] < 0), Decimal("0.00"))
    receivable_total = sum((debt["signed_amount"] for debt in commitments if debt["signed_amount"] > 0), Decimal("0.00"))
    net_balance = receivable_total - debt_total

    return {
        "today": today,
        "calendar": build_finance_calendar(commitments, today),
        "due_this_month": due_this_month,
        "future_debts": future_debts,
        "personal_due_this_month": personal_due_this_month,
        "personal_future_debts": personal_future_debts,
        "receivables_this_month": receivables_this_month,
        "future_receivables": future_receivables,
        "overdue_debts": overdue_debts,
        "next_debt": next_debt,
        "open_total": sum((debt["amount"] for debt in commitments), Decimal("0.00")),
        "due_this_month_total": sum((debt["amount"] for debt in due_this_month), Decimal("0.00")),
        "future_total": sum((debt["amount"] for debt in future_debts), Decimal("0.00")),
        "overdue_total": sum((debt["amount"] for debt in overdue_debts), Decimal("0.00")),
        "debt_total": debt_total,
        "receivable_total": receivable_total,
        "net_balance": net_balance,
        "open_count": len(commitments),
        "personal_debt_form": PersonalDebtForm(),
    }


def finance_scope_totals(user, target_scope):
    entries = user.personal_debts.filter(paid=False, scope=target_scope)
    debts = entries.filter(entry_type=PersonalDebt.TYPE_DEBT).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    receivables = entries.filter(entry_type=PersonalDebt.TYPE_RECEIVABLE).aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    return {"debt": money(debts), "receivable": money(receivables), "net": money(receivables - debts)}


def apply_doces_e_mais_finance_labels(form):
    form.fields["entry_type"].choices = (
        (PersonalDebt.TYPE_RECEIVABLE, "Entrada"),
        (PersonalDebt.TYPE_DEBT, "Saída"),
    )
    form.fields["title"].label = "Descrição"
    form.fields["title"].widget.attrs["placeholder"] = "Ex.: Venda de cones, compra de chocolate, embalagem"
    form.fields["amount"].label = "Valor"
    form.fields["due_date"].label = "Data"
    form.fields["notes"].label = "Observação"
    form.fields["notes"].widget.attrs["placeholder"] = "Opcional: forma de pagamento, cliente, fornecedor ou detalhe do pedido"
    return form


def doces_e_mais_finance_ui_context(scope):
    return {
        "finance_staff_mode": True,
        "finance_doces_mode": True,
        "finance_scope": scope,
        "finance_scope_label": "Doces e Mais" if scope == PersonalDebt.SCOPE_BUSINESS else "Pessoal",
        "finance_personal_tab_label": "Minhas finanças",
        "finance_business_tab_label": "Finanças Doces e Mais",
        "finance_business_url": reverse("doces_e_mais_finances"),
        "finance_personal_url": reverse("customer_finances"),
        "finance_page_title": "Finanças Doces e Mais" if scope == PersonalDebt.SCOPE_BUSINESS else "Minhas finanças",
        "finance_create_title": "Adicionar entrada ou saída",
        "finance_create_help": "Registre vendas, encomendas a receber, compras de ingredientes, embalagens, entregas e qualquer movimento da Doces e Mais.",
        "finance_submit_label": "Salvar lançamento",
        "finance_total_label": "Total em lançamentos",
        "finance_debt_label": "Saídas",
        "finance_debt_help": "Valores a pagar registrados",
        "finance_receivable_label": "Entradas",
        "finance_receivable_help": "Valores a receber registrados",
        "finance_net_label": "Diferença entre entradas e saídas",
        "finance_net_positive": "Entradas acima das saídas",
        "finance_net_negative": "Saídas acima das entradas",
        "finance_calendar_title": "Calendário de entradas e saídas",
        "finance_debts_this_month_title": "Saídas deste mês",
        "finance_debts_this_month_empty": "Nenhuma saída prevista neste mês.",
        "finance_future_debts_title": "Saídas futuras",
        "finance_future_debts_empty": "Nenhuma saída futura registrada.",
        "finance_receivables_this_month_title": "Entradas deste mês",
        "finance_receivables_this_month_empty": "Nenhuma entrada prevista neste mês.",
        "finance_future_receivables_title": "Entradas futuras",
        "finance_future_receivables_empty": "Nenhuma entrada futura registrada.",
    }


def get_welcome_discount_profile(request):
    if not request.user.is_authenticated or request.user.is_staff:
        return None

    profile = request.user.profile

    if (
        profile.registration_status != ClientProfile.APPROVED
        or profile.first_purchase_discount_used
        or not profile.welcome_discount_expires_at
        or profile.welcome_discount_expires_at < timezone.localdate()
    ):
        return None

    return profile


def welcome_discount_amount(amount):
    return money(amount * (WELCOME_DISCOUNT_PERCENT / Decimal("100")))


def profile_has_credit_documents(profile):
    return bool(
        profile.rg_number
        and profile.phone
        and profile.address
        and profile.identity_document
        and profile.residence_proof
    )


def send_profile_to_credit_analysis(profile):
    needs_analysis = (
        profile.registration_status != ClientProfile.APPROVED
        or not profile_has_credit_documents(profile)
    )

    if not needs_analysis:
        return False

    review_note = f"Solicitou crediario pelo checkout em {timezone.localtime():%d/%m/%Y %H:%M}."
    existing_notes = profile.admin_notes.strip()
    profile.admin_notes = f"{existing_notes}\n{review_note}".strip() if existing_notes else review_note
    profile.registration_status = ClientProfile.PENDING
    profile.approved_at = None
    profile.approved_by = None
    profile.save(update_fields=["registration_status", "approved_at", "approved_by", "admin_notes"])

    return True


def create_credit_sale_from_checkout(request, items, form, shipping_cost):
    profile = getattr(request.user, "profile", None)

    if not profile:
        raise ValueError("Somente clientes podem solicitar crediario pelo checkout.")

    cleaned_data = form.cleaned_data
    products_total = money(sum((item["total"] for item in items), Decimal("0.00")))
    total_amount = money(products_total + shipping_cost)
    first_product = items[0]["product"]
    description = first_product.name if len(items) == 1 else f"Pedido loja ({len(items)} itens)"
    needs_analysis = send_profile_to_credit_analysis(profile)

    sale = CreditSale.objects.create(
        client=request.user,
        description=description,
        total_amount=total_amount,
        first_due_date=timezone.localdate() + timedelta(days=30),
        max_installments_allowed=profile.default_max_installments,
    )

    for index, item in enumerate(items):
        product = item["product"]
        item_shipping = shipping_cost if index == 0 else Decimal("0.00")
        notes = [
            f"Solicitado pelo checkout da loja.",
            f"Codigo fornecedor: {product.supplier_code}",
            f"Quantidade: {item['quantity']}",
            f"Frete neste item: R$ {item_shipping:.2f}",
            f"UF/regiao: {cleaned_data['shipping_state']}",
            f"Endereco: {cleaned_data['shipping_address']}",
        ]

        if cleaned_data.get("notes"):
            notes.append(f"Observacoes do cliente: {cleaned_data['notes']}")

        CreditSaleProduct.objects.create(
            sale=sale,
            name=product.name,
            brand=product.brand,
            shoe_size=item["selected_size"],
            notes="\n".join(notes),
        )

    create_sale_available_notification(sale)

    return sale, needs_analysis


def current_month_sales_summary():
    today = timezone.localdate()
    month_start = today.replace(day=1)

    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)

    store_orders = StoreOrder.objects.filter(status__in=PARTNER_SALES_STATUSES).filter(
        Q(paid_at__date__gte=month_start, paid_at__date__lt=next_month_start)
        | Q(paid_at__isnull=True, created_at__date__gte=month_start, created_at__date__lt=next_month_start)
    )
    credit_sales = CreditSale.objects.filter(
        status=CreditSale.ACCEPTED,
        accepted_at__date__gte=month_start,
        accepted_at__date__lt=next_month_start,
    )
    store_revenue = store_orders.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    credit_revenue = credit_sales.aggregate(total=Sum("selected_total_with_interest"))["total"] or Decimal("0.00")
    store_items = store_orders.aggregate(total=Sum("quantity"))["total"] or 0
    credit_items = CreditSaleProduct.objects.filter(sale__in=credit_sales).count()
    target_items = 10
    sold_items = store_items + credit_items

    return {
        "month_label": f"{month_start:%m/%Y}",
        "revenue": money(store_revenue + credit_revenue),
        "sales_count": store_orders.count() + credit_sales.count(),
        "items_sold": sold_items,
        "goal_target": target_items,
        "goal_hit": sold_items >= target_items,
        "goal_remaining": max(target_items - sold_items, 0),
    }


def get_cart(request):
    return request.session.setdefault("store_cart", {})


def build_cart_items(request):
    cart = get_cart(request)
    product_ids = {item["product_id"] for item in cart.values()}
    products = {
        product.id: product
        for product in SupplierProduct.objects.filter(
            id__in=product_ids,
            is_active=True,
            is_visible=True,
            stock_quantity__gt=0,
        )
    }
    items = []

    for key, item in cart.items():
        product = products.get(item["product_id"])

        if not product:
            continue

        quantity = max(1, min(int(item.get("quantity", 1)), product.stock_quantity))
        items.append(
            {
                "key": key,
                "product": product,
                "selected_size": item["selected_size"],
                "quantity": quantity,
                "total": money(product.suggested_sale_price * quantity),
            }
        )

    return items


def home(request):
    if request.user.is_authenticated:
        return redirect(authenticated_home_route(request.user))

    return redirect("store_front")


def can_manage_doces_e_mais(user):
    return user.is_authenticated and (user.is_staff or user.email.lower() == DOCES_E_MAIS_OWNER_EMAIL)


def is_doces_e_mais_owner_email(email):
    return (email or "").strip().lower() == DOCES_E_MAIS_OWNER_EMAIL


def ensure_doces_e_mais_profile_access(user):
    profile = getattr(user, "profile", None)
    if not profile or not is_doces_e_mais_owner_email(user.email):
        return

    changed_fields = []
    if not profile.phone_verified:
        profile.phone_verified = True
        profile.phone_verification_code = ""
        profile.phone_verification_attempts = 0
        changed_fields.extend(["phone_verified", "phone_verification_code", "phone_verification_attempts"])
    if profile.registration_status != ClientProfile.APPROVED:
        profile.registration_status = ClientProfile.APPROVED
        profile.approved_at = profile.approved_at or timezone.now()
        changed_fields.extend(["registration_status", "approved_at"])

    extra = dict(profile.extra_data or {})
    if not extra.get("doces_e_mais_owner"):
        extra["doces_e_mais_owner"] = True
        profile.extra_data = extra
        changed_fields.append("extra_data")

    if changed_fields:
        profile.save(update_fields=sorted(set(changed_fields)))


def doces_e_mais_defaults():
    return [
        {
            "code": "doces-01",
            "name": "Pastel de leite ninho recheado com Nutella",
            "description": "Casquinha delicada, recheio cremoso e aquele encontro perfeito entre leite ninho e Nutella.",
            "image": "accounts/doces-e-mais/pastel-leite-ninho-nutella.jpeg",
            "badge": "Muito recheio",
        },
        {
            "code": "doces-02",
            "name": "Pão de mel tradicional",
            "description": "Massa macia, cobertura generosa de chocolate e sabor artesanal com cara de presente.",
            "image": "accounts/doces-e-mais/pao-de-mel-tradicional.jpeg",
            "badge": "Classico premium",
        },
        {
            "code": "doces-03",
            "name": "Cone trufado - Brigadeiro",
            "description": "Cone crocante com brigadeiro cremoso e finalizacao caprichada para matar a vontade de chocolate.",
            "image": "accounts/doces-e-mais/cone-trufado-brigadeiro.jpeg",
            "badge": "Queridinho",
        },
        {
            "code": "doces-04",
            "name": "Cone trufado - Paçoca",
            "description": "Camadas de sabor, textura crocante e cobertura de paçoca para quem ama doce brasileiro.",
            "image": "accounts/doces-e-mais/cone-trufado-pacoca.jpeg",
            "badge": "Artesanal",
        },
        {
            "code": "doces-05",
            "name": "Trufa recheada - Morango",
            "description": "Chocolate envolvente com recheio de morango, embalagem charmosa e sabor marcante.",
            "image": "accounts/doces-e-mais/trufa-recheada-morango.jpeg",
            "badge": "Frutada",
        },
        {
            "code": "doces-06",
            "name": "Trufa recheada - Uva",
            "description": "Trufa cremosa com toque de uva, feita para presentear ou deixar o dia mais gostoso.",
            "image": "accounts/doces-e-mais/trufa-recheada-uva.jpeg",
            "badge": "Especial",
        },
        {
            "code": "doces-07",
            "name": "Fatia de bolo - Chocolate com brigadeiro de maracuja",
            "description": "Chocolate intenso com recheio de brigadeiro de maracujá para equilibrar doçura e frescor.",
            "image": "accounts/doces-e-mais/fatia-bolo-chocolate-maracuja.jpeg",
            "badge": "Irresistível",
        },
        {
            "code": "doces-08",
            "name": "Fatia de bolo - Cacau Black",
            "description": "Fatia de bolo escura, elegante e chocolatuda, com visual premium e sabor profundo.",
            "image": "accounts/doces-e-mais/fatia-bolo-cacau-black.jpeg",
            "badge": "Chocolate intenso",
        },
        {
            "code": "doces-09",
            "name": "Morango do Amor",
            "description": "Morango envolvido em brilho, carinho e capricho: bonito para presentear, melhor ainda para comer.",
            "image": "accounts/doces-e-mais/morango-do-amor.jpeg",
            "badge": "Presente perfeito",
        },
    ]


def ensure_doces_e_mais_products():
    products = []
    for order, item in enumerate(doces_e_mais_defaults(), start=1):
        product, created = SupplierProduct.objects.get_or_create(
            source=DOCES_E_MAIS_SOURCE,
            supplier_code=item["code"],
            defaults={
                "name": item["name"],
                "description": item["description"],
                "image_url": item["image"],
                "suggested_sale_price": Decimal("0.00"),
                "stock_quantity": 1,
                "is_active": True,
                "is_visible": True,
                "raw_data": {
                    "badge": item["badge"],
                    "featured": order <= 3,
                    "promo_text": "",
                    "order": order,
                    "static_image": item["image"],
                },
            },
        )
        if not created:
            raw = dict(product.raw_data or {})
            changed = False
            for key, value in {"order": order, "static_image": item["image"], "badge": raw.get("badge") or item["badge"]}.items():
                if raw.get(key) != value:
                    raw[key] = value
                    changed = True
            if changed:
                product.raw_data = raw
                product.save(update_fields=["raw_data", "updated_at"])
        products.append(product)
    return products


def doces_e_mais_analytics_record():
    record, _ = SupplierProduct.objects.get_or_create(
        source=DOCES_E_MAIS_SOURCE,
        supplier_code="__analytics__",
        defaults={
            "name": "Relatório de visitas Doces e Mais",
            "description": "Registro interno de visitas da página Doces e Mais.",
            "suggested_sale_price": Decimal("0.00"),
            "stock_quantity": 0,
            "is_active": False,
            "is_visible": False,
            "raw_data": {},
        },
    )
    return record


def request_ip_hash(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = (forwarded.split(",")[0] if forwarded else request.META.get("REMOTE_ADDR", "")).strip()
    if not ip:
        return ""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()[:16]


def request_device_label(request):
    agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
    if "mobile" in agent or "android" in agent or "iphone" in agent:
        return "Celular"
    if "tablet" in agent or "ipad" in agent:
        return "Tablet"
    if agent:
        return "Computador"
    return "Desconhecido"


def record_doces_e_mais_visit(request, variant):
    if can_manage_doces_e_mais(request.user):
        return

    today = timezone.localdate().isoformat()
    session_key = f"doces_e_mais_seen_{variant}_{today}"
    unique_today = not request.session.get(session_key)
    request.session[session_key] = True
    request.session.modified = True

    record = doces_e_mais_analytics_record()
    raw = dict(record.raw_data or {})
    days = dict(raw.get("days") or {})
    day_data = dict(days.get(today) or {"views": 0, "unique": 0})
    day_data["views"] = int(day_data.get("views") or 0) + 1
    if unique_today:
        day_data["unique"] = int(day_data.get("unique") or 0) + 1
    days[today] = day_data

    variants = dict(raw.get("variants") or {})
    variant_data = dict(variants.get(variant) or {"views": 0})
    variant_data["views"] = int(variant_data.get("views") or 0) + 1
    variants[variant] = variant_data

    last_visits = list(raw.get("last_visits") or [])
    last_visits.insert(0, {
        "at": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        "variant": variant,
        "path": request.path,
        "device": request_device_label(request),
        "ip_hash": request_ip_hash(request),
    })

    raw.update({
        "total_views": int(raw.get("total_views") or 0) + 1,
        "days": days,
        "variants": variants,
        "last_visits": last_visits[:12],
        "updated_at": timezone.now().isoformat(),
    })
    record.raw_data = raw
    record.save(update_fields=["raw_data", "updated_at"])


def doces_e_mais_visit_report():
    raw = doces_e_mais_analytics_record().raw_data or {}
    today = timezone.localdate().isoformat()
    days = raw.get("days") or {}
    today_data = days.get(today) or {}
    last_7_days = []
    for offset in range(6, -1, -1):
        date = timezone.localdate() - timedelta(days=offset)
        date_key = date.isoformat()
        day_data = days.get(date_key) or {}
        last_7_days.append({
            "label": date.strftime("%d/%m"),
            "views": int(day_data.get("views") or 0),
            "unique": int(day_data.get("unique") or 0),
        })

    variants = raw.get("variants") or {}
    return {
        "total_views": int(raw.get("total_views") or 0),
        "today_views": int(today_data.get("views") or 0),
        "today_unique": int(today_data.get("unique") or 0),
        "versao1_views": int((variants.get("versao1") or {}).get("views") or 0),
        "last_7_days": last_7_days,
        "last_visits": raw.get("last_visits") or [],
    }


def doces_e_mais_context():
    whatsapp_number = "5561992655947"
    base_message = "Olá! Vim pela página da Doces e Mais e gostaria de iniciar um atendimento."

    products = []
    visible_products = [
        product for product in ensure_doces_e_mais_products()
        if product.is_visible and not (product.raw_data or {}).get("deleted")
    ]
    visible_products.sort(key=lambda product: (product.raw_data or {}).get("order", 99))
    for index, product in enumerate(visible_products, start=1):
        raw = product.raw_data or {}
        product_message = f"{base_message} Tenho interesse em: {product.name}."
        image_url = product.image_file.url if product.image_file else ""
        products.append({
            "name": product.name,
            "description": product.description,
            "image": image_url or raw.get("static_image") or product.image_url,
            "image_is_static": not bool(image_url),
            "badge": raw.get("promo_text") or raw.get("badge") or "Artesanal",
            "featured": bool(raw.get("featured")),
            "promo_text": raw.get("promo_text", ""),
            "number": f"{index:02d}",
            "whatsapp_url": f"https://wa.me/{whatsapp_number}?text={quote(product_message)}",
        })

    featured_products = [product for product in products if product["featured"]]
    if not featured_products:
        featured_products = products[:3]

    return {
        "products": products,
        "featured_products": featured_products,
        "hero_product": products[0] if products else None,
        "whatsapp_url": f"https://wa.me/{whatsapp_number}?text={quote(base_message)}",
        "instagram_url": "https://www.instagram.com/doces.e.mais",
        "phone_label": "(61) 9 9265-5947",
        "instagram_label": "@doces.e.mais",
    }


def doces_e_mais(request):
    record_doces_e_mais_visit(request, "versao1")
    return render(request, "accounts/doces_e_mais.html", doces_e_mais_context())


def doces_e_mais_cardapio(request):
    record_doces_e_mais_visit(request, "versao2")
    return render(request, "accounts/doces_e_mais_cardapio.html", doces_e_mais_context())


@login_required(login_url="login")
def doces_e_mais_painel(request):
    if not can_manage_doces_e_mais(request.user):
        return HttpResponseForbidden("Acesso restrito a proprietária da Doces e Mais.")
    ensure_doces_e_mais_profile_access(request.user)

    products = ensure_doces_e_mais_products()
    products.sort(key=lambda product: (product.raw_data or {}).get("order", 99))
    forms_by_id = {}

    if request.method == "POST":
        action = request.POST.get("action", "save").strip()
        product_id = request.POST.get("product_id", "").strip()
        product = get_object_or_404(SupplierProduct, id=product_id, source=DOCES_E_MAIS_SOURCE)

        if action == "delete":
            raw = dict(product.raw_data or {})
            raw["deleted"] = True
            raw["featured"] = False
            product.raw_data = raw
            product.is_visible = False
            product.save(update_fields=["raw_data", "is_visible", "updated_at"])
            messages.success(request, f"{product.name} excluído da página. Você pode restaurar depois.")
            return redirect("doces_e_mais_painel")

        if action == "restore":
            raw = dict(product.raw_data or {})
            raw["deleted"] = False
            product.raw_data = raw
            product.is_visible = True
            product.save(update_fields=["raw_data", "is_visible", "updated_at"])
            messages.success(request, f"{product.name} restaurado na página.")
            return redirect("doces_e_mais_painel")

        form = DocesEMaisProductForm(request.POST, request.FILES, instance=product)
        forms_by_id[product.id] = form
        if form.is_valid():
            form.save()
            messages.success(request, f"{product.name} atualizado.")
            return redirect("doces_e_mais_painel")
        messages.error(request, "Revise os dados do produto.")

    rows = []
    deleted_rows = []
    for product in products:
        row = {
            "product": product,
            "form": forms_by_id.get(product.id) or DocesEMaisProductForm(instance=product),
            "raw": product.raw_data or {},
            "preview_image": product.image_file.url if product.image_file else (product.raw_data or {}).get("static_image") or product.image_url,
            "preview_is_static": not bool(product.image_file),
        }
        if row["raw"].get("deleted"):
            deleted_rows.append(row)
        else:
            rows.append(row)

    return render(
        request,
        "accounts/doces_e_mais_painel.html",
        {
            "rows": rows,
            "deleted_rows": deleted_rows,
            "visit_report": doces_e_mais_visit_report(),
            "versao1_url": reverse("doces_e_mais"),
            "finances_url": reverse("doces_e_mais_finances"),
        },
    )


@login_required(login_url="login")
def doces_e_mais_finances(request):
    if not can_manage_doces_e_mais(request.user):
        return HttpResponseForbidden("Acesso restrito a proprietária da Doces e Mais.")
    ensure_doces_e_mais_profile_access(request.user)

    scope = PersonalDebt.SCOPE_BUSINESS

    if request.method == "POST":
        form = apply_doces_e_mais_finance_labels(PersonalDebtForm(request.POST))

        if form.is_valid():
            entry = form.save(commit=False)
            entry.client = request.user
            entry.scope = scope
            entry.save()
            messages.success(request, "Lançamento da Doces e Mais adicionado.")
            return redirect("doces_e_mais_finances")
    else:
        form = apply_doces_e_mais_finance_labels(PersonalDebtForm())

    context = build_customer_finance_context(request.user, scope=scope, include_store=False)
    context["personal_debt_form"] = form
    context["finance_comparison"] = {
        "personal": finance_scope_totals(request.user, PersonalDebt.SCOPE_PERSONAL),
        "business": finance_scope_totals(request.user, PersonalDebt.SCOPE_BUSINESS),
    }
    context.update(doces_e_mais_finance_ui_context(scope))
    return render(request, "accounts/customer_finances.html", context)


def brand_preview(request):
    return render(request, "accounts/brand_preview.html")


def assetlinks(request):
    payload = []

    if settings.ANDROID_APP_PACKAGE_ID and settings.ANDROID_SHA256_CERT_FINGERPRINTS:
        payload.append(
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": settings.ANDROID_APP_PACKAGE_ID,
                    "sha256_cert_fingerprints": settings.ANDROID_SHA256_CERT_FINGERPRINTS,
                },
            }
        )

    return JsonResponse(payload, safe=False)


def offline_page(request):
    return render(request, "accounts/offline.html", status=200)


def service_worker(request):
    response = render(request, "accounts/service-worker.js", {
        "store_front_url": resolve_url("store_front"),
        "offline_url": resolve_url("offline_page"),
    }, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


def privacy_policy(request):
    return render(
        request,
        "accounts/privacy_policy.html",
        {
            "contact_email": settings.STORE_CONTACT_EMAIL,
            "responsible_name": settings.STORE_RESPONSIBLE_NAME,
        },
    )


def terms_of_use(request):
    return render(
        request,
        "accounts/terms_of_use.html",
        {
            "contact_email": settings.STORE_CONTACT_EMAIL,
            "responsible_name": settings.STORE_RESPONSIBLE_NAME,
        },
    )


def store_front(request):
    ensure_supplier_catalog_sources()
    tennis_priority = Case(
        When(
            Q(category__icontains="tenis")
            | Q(category__icontains="tênis")
            | Q(name__icontains="tenis")
            | Q(name__icontains="tênis"),
            then=Value(0),
        ),
        default=Value(1),
        output_field=IntegerField(),
    )
    products = (
        SupplierProduct.objects.filter(is_active=True, is_visible=True, stock_quantity__gt=0)
        # Sem o prefetch, montar a galeria de cada produto faz uma consulta a
        # mais por produto: 24 produtos na pagina viram 24 consultas so de foto.
        .prefetch_related("photos")
        .annotate(tennis_priority=tennis_priority)
        .order_by("tennis_priority", "name")
    )
    reserved_sales = CreditSale.objects.none()
    query = request.GET.get("q", "").strip()
    category = request.GET.get("categoria", "").strip()
    group = request.GET.get("grupo", "").strip()
    size_group = request.GET.get("grupo_tamanho", "").strip()
    size = request.GET.get("tamanho", "").strip()
    cart_product_ids = {
        item.get("product_id")
        for item in get_cart(request).values()
        if item.get("product_id")
    }

    if cart_product_ids:
        products = products.exclude(id__in=cart_product_ids)

    if request.user.is_authenticated and not request.user.is_staff:
        profile = request.user.profile

        if profile.phone_verified and profile.registration_status == ClientProfile.APPROVED:
            reserved_sales = (
                request.user.credit_sales.filter(status=CreditSale.PENDING)
                .prefetch_related("products")
                .order_by("-created_at")
            )

    if query:
        busca = (
            Q(name__icontains=query)
            | Q(category__icontains=query)
            | Q(brand__icontains=query)
            | Q(description__icontains=query)
        )

        # Quem procura "relogio" esta procurando smartwatch: a palavra some das
        # abas da loja, mas continua valendo como termo de busca.
        if any(termo in _sem_acento(query) for termo in SEARCH_WATCH_ALIASES):
            busca |= Q(category__iexact="Smartwatches")

        products = products.filter(busca)

    # Categorias existentes (com produtos visiveis em estoque).
    existing_categories = set(
        SupplierProduct.objects.filter(is_active=True, is_visible=True, stock_quantity__gt=0)
        .exclude(category="")
        .values_list("category", flat=True)
        .distinct()
    )

    # Mapeia cada categoria conhecida ao seu grupo.
    cat_to_group = {}
    for group_name, group_cats in CATEGORY_GROUPS:
        for cat_name in group_cats:
            cat_to_group[cat_name] = group_name

    # Subcategorias presentes por grupo, na ordem definida; extras (nao mapeadas)
    # caem em Calçados.
    group_subcats = {}
    for group_name, group_cats in CATEGORY_GROUPS:
        group_subcats[group_name] = [c for c in group_cats if c in existing_categories]
    extras = sorted(c for c in existing_categories if c not in cat_to_group)
    group_subcats["Calçados"] = group_subcats.get("Calçados", []) + extras

    # Nivel 1: grupos que tem ao menos uma categoria presente.
    group_order = [g for g, _ in CATEGORY_GROUPS]
    groups_present = [g for g in group_order if group_subcats.get(g)]

    # Valida categoria selecionada.
    if category and category not in existing_categories:
        category = ""

    # Grupo ativo: derivado da categoria, ou do parametro grupo.
    if category:
        active_group = cat_to_group.get(category, "Calçados")
    elif group in groups_present:
        active_group = group
    else:
        active_group = ""

    # Filtra os produtos.
    if category:
        products = products.filter(category__iexact=category)
    elif active_group:
        products = products.filter(category__in=group_subcats.get(active_group, []))

    # Nivel 2: subcategorias do grupo ativo (so quando ha mais de uma).
    subcategories = []
    if active_group:
        subs = group_subcats.get(active_group, [])
        if len(subs) > 1:
            subcategories = [
                {
                    "value": c,
                    "label": CATEGORY_SHORT_LABELS.get(c, c),
                    "active": c == category,
                }
                for c in subs
            ]

    groups = [{"name": g, "active": g == active_group} for g in groups_present]
    show_size_filters = active_group in FOOTWEAR_GROUPS

    if size:
        products = products.filter(sizes__icontains=size)

    size_options = (
        SupplierProduct.objects.filter(is_active=True, is_visible=True, stock_quantity__gt=0)
        .exclude(sizes="")
        .values_list("sizes", flat=True)
    )
    parsed_sizes = sorted(
        {
            item.strip()
            for value in size_options
            for item in value.replace("/", ",").replace(";", ",").split(",")
            if item.strip()
        }
    )
    child_size_options = [option for option in STORE_CHILD_SIZES if option in parsed_sizes]
    adult_size_options = [option for option in STORE_ADULT_SIZES if option in parsed_sizes]

    if size and size not in parsed_sizes:
        size = ""

    if size_group == "child" and size and size not in child_size_options:
        size = ""
    elif size_group == "adult" and size and size not in adult_size_options:
        size = ""

    # Carrosseis iniciais: imagens aleatorias de qualquer produto visivel do site.
    # Dois carrosseis lado a lado, com amostras aleatorias diferentes.
    featured_pool = (
        SupplierProduct.objects.filter(is_active=True, is_visible=True, stock_quantity__gt=0)
        .exclude(image_file="", image_url="")
        .prefetch_related("photos")
    )
    featured_products = list(featured_pool.order_by("?")[:24])

    def build_showcase_item(featured):
        featured_gallery = featured.gallery_images()
        featured_image = featured_gallery[0] if featured_gallery else (featured.image_url or "")
        if not featured_image:
            return None
        return {
            "product_id": featured.id,
            "title": featured.name,
            "subtitle": featured.category or featured.brand or "",
            "price": f"R$ {featured.suggested_sale_price:.2f}".replace(".", ","),
            "sizes_label": "Tamanhos" if featured.sizes and featured.sizes != "Único" else "Modelo",
            "sizes": featured.sizes or "Único",
            "image_url": featured_image,
            "link_url": resolve_url("store_product_detail", featured.id),
        }

    showcase_items = [item for item in (build_showcase_item(p) for p in featured_products) if item]
    # Faixa propria dos produtos marcados como destaque (os smartwatches), do
    # mais barato para o mais caro, todos visiveis na mesma rolagem.
    featured_strip = [
        item
        for item in (
            build_showcase_item(produto)
            for produto in featured_pool.filter(is_featured=True).order_by("suggested_sale_price")
        )
        if item
    ]
    half = (len(showcase_items) + 1) // 2
    showcase_sections = [
        {"title": "Destaques", "items": showcase_items[:half]},
        {"title": "Você também pode gostar", "items": showcase_items[half:]},
    ]
    showcase_sections = [section for section in showcase_sections if section["items"]]

    # Paginacao: a loja pode ter milhares de produtos. Sem paginar, a pagina
    # renderizava todos de uma vez (lenta o suficiente para estourar o timeout
    # do servidor em producao). Processamos apenas os itens da pagina atual.
    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get("page"))

    querystring = request.GET.copy()
    querystring.pop("page", None)
    base_querystring = querystring.urlencode()

    for product in page_obj:
        product.gallery = product.gallery_images()
        product.primary_image = product.gallery[0] if product.gallery else ""
        product.customer_notice = source_notice_for_customer(product)

    consultation_sources = SupplierCatalogSource.objects.filter(
        is_active=True,
        purchase_flow=SupplierCatalogSource.FLOW_WHATSAPP_CONFIRMATION,
    )

    return render(
        request,
        "accounts/store_front.html",
        {
            "products": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "base_querystring": base_querystring,
            "showcase_sections": showcase_sections,
            "featured_strip": featured_strip,
            "store_reels": StoreReel.objects.filter(is_visible=True).select_related("product"),
            "query": query,
            "groups": groups,
            "subcategories": subcategories,
            "active_group": active_group,
            "selected_category": category,
            "store_model_photos": pick_store_model_photos(category, active_group),
            "show_size_filters": show_size_filters,
            "size_group": size_group,
            "size": size,
            "child_size_options": child_size_options,
            "adult_size_options": adult_size_options,
            "child_size_options_json": json.dumps(child_size_options),
            "adult_size_options_json": json.dumps(adult_size_options),
            "reserved_sales": reserved_sales,
            "welcome_discount_available": bool(get_welcome_discount_profile(request)),
            "welcome_discount_percent": WELCOME_DISCOUNT_PERCENT,
            "boticario_store_url": settings.BOTICARIO_STORE_URL,
            "consultation_sources": consultation_sources,
        },
    )


def store_product_detail(request, product_id):
    ensure_supplier_catalog_sources()
    product = get_object_or_404(
        SupplierProduct,
        id=product_id,
        is_active=True,
        is_visible=True,
        stock_quantity__gt=0,
    )

    size_options = [
        size.strip()
        for size in (product.sizes or "").replace("/", ",").replace(";", ",").split(",")
        if size.strip()
    ] or ["Confirmar tamanho"]

    gallery = product.gallery_images()

    # Outros modelos da mesma categoria, para o cliente continuar olhando sem
    # ter que voltar para a vitrine.
    relacionados = []

    if product.category:
        relacionados = (
            SupplierProduct.objects.filter(
                is_active=True,
                is_visible=True,
                stock_quantity__gt=0,
                category=product.category,
            )
            .exclude(id=product.id)
            .exclude(image_file="", image_url="")
            .prefetch_related("photos")
            .order_by("suggested_sale_price")[:12]
        )

    return render(
        request,
        "accounts/store_product_detail.html",
        {
            "product": product,
            "size_options": size_options,
            "gallery_images": gallery,
            "customer_notice": source_notice_for_customer(product),
            "whatsapp_url": store_whatsapp_url(request, product),
            "relacionados": relacionados,
        },
    )


# Campos que a loja pode corrigir sem abrir o painel inteiro.
CAMPOS_RAPIDOS_PRODUTO = {
    "description": ("Descricao", "texto"),
    "highlights": ("Recursos", "texto"),
    "tech_specs": ("Ficha tecnica", "texto"),
    "name": ("Nome", "linha"),
    "suggested_sale_price": ("Preco", "dinheiro"),
    "stock_quantity": ("Estoque", "inteiro"),
}


@staff_member_required(login_url="login")
def salvar_campo_produto(request, product_id):
    """Salva um campo editado fora do painel: na ficha da loja ou na lista de videos."""
    produto = get_object_or_404(SupplierProduct, id=product_id)
    ficha = reverse("store_product_detail", args=[produto.id])
    destino = safe_next_url(request, request.POST.get("voltar")) or ficha

    if request.method != "POST":
        return redirect(ficha)

    campo = request.POST.get("campo", "")
    valor = (request.POST.get("valor") or "").strip()

    if campo not in CAMPOS_RAPIDOS_PRODUTO:
        messages.error(request, "Campo invalido.")

        return redirect(destino)

    rotulo, tipo = CAMPOS_RAPIDOS_PRODUTO[campo]

    if tipo == "linha":
        valor = " ".join(valor.split())

        if not valor:
            messages.error(request, f"{rotulo} nao pode ficar em branco.")

            return redirect(destino)
    elif tipo == "dinheiro":
        # Com virgula, o ponto e separador de milhar (1.234,56).
        # Sem virgula, o ponto e a propria casa decimal (220.00).
        if "," in valor:
            valor = valor.replace(".", "").replace(",", ".")

        try:
            valor = Decimal(valor)
        except (InvalidOperation, AttributeError):
            messages.error(request, f"{rotulo} precisa ser um valor como 220,00.")

            return redirect(destino)

        if valor <= 0:
            messages.error(request, f"{rotulo} precisa ser maior que zero.")

            return redirect(destino)
    elif tipo == "inteiro":
        try:
            valor = int(valor)
        except ValueError:
            messages.error(request, f"{rotulo} precisa ser um numero inteiro.")

            return redirect(destino)

        if valor < 0:
            messages.error(request, f"{rotulo} nao pode ser negativo.")

            return redirect(destino)

    setattr(produto, campo, valor)
    produto.save(update_fields=[campo, "updated_at"])
    messages.success(request, f"{rotulo} de {produto.name} atualizado.")

    return redirect(destino)


def cart_add(request, product_id):
    product = get_object_or_404(SupplierProduct, id=product_id, is_active=True, is_visible=True, stock_quantity__gt=0)

    if request.method == "POST":
        selected_size = request.POST.get("selected_size", "").strip()
        sizes = [size.strip() for size in (product.sizes or "").replace("/", ",").replace(";", ",").split(",") if size.strip()]

        if sizes and selected_size not in sizes:
            messages.error(request, "Escolha um tamanho disponivel.")
            return redirect("store_product_detail", product_id=product.id)

        selected_size = selected_size or "Confirmar tamanho"
        key = f"{product.id}:{selected_size}"
        cart = get_cart(request)
        cart[key] = {
            "product_id": product.id,
            "selected_size": selected_size,
            "quantity": min(cart.get(key, {}).get("quantity", 0) + 1, product.stock_quantity),
        }
        request.session.modified = True
        messages.success(request, "Produto adicionado ao carrinho.")

    return redirect("cart_detail")


def cart_remove(request, item_key):
    if request.method == "POST":
        cart = get_cart(request)
        cart.pop(item_key, None)
        request.session.modified = True

    return redirect("cart_detail")


def cart_detail(request):
    items = build_cart_items(request)
    subtotal = money(sum((item["total"] for item in items), Decimal("0.00")))
    welcome_profile = get_welcome_discount_profile(request)

    return render(
        request,
        "accounts/cart_detail.html",
        {
            "items": items,
            "subtotal": subtotal,
            "welcome_discount_available": bool(welcome_profile),
            "welcome_discount_percent": WELCOME_DISCOUNT_PERCENT,
            "welcome_discount_expires_at": welcome_profile.welcome_discount_expires_at if welcome_profile else None,
            "shipping_rates": shipping_rates_payload(),
            "shipping_rates_json": json.dumps(shipping_rates_payload()),
            "boticario_store_url": settings.BOTICARIO_STORE_URL,
        },
    )


def cart_boticario_redirect(request):
    items = build_cart_items(request)

    if not items:
        messages.warning(request, "Seu carrinho esta vazio.")
        return redirect("cart_detail")

    if not settings.BOTICARIO_STORE_URL:
        messages.warning(request, "A loja Boticario ainda nao foi configurada.")
        return redirect("cart_detail")

    return redirect(settings.BOTICARIO_STORE_URL)


def cart_checkout(request):
    if not request.user.is_authenticated:
        messages.info(request, "Entre ou cadastre-se para finalizar a compra.")
        return redirect(f"{resolve_url('login')}?next={request.path}")

    items = build_cart_items(request)

    if not items:
        messages.warning(request, "Seu carrinho esta vazio.")
        return redirect("cart_detail")

    welcome_profile = get_welcome_discount_profile(request)
    subtotal = money(sum((item["total"] for item in items), Decimal("0.00")))
    voucher_discount = welcome_discount_amount(subtotal) if welcome_profile else Decimal("0.00")

    is_client = request.user.is_authenticated and not request.user.is_staff
    cashback_available = cashback_balance(request.user) if is_client else Decimal("0.00")
    store_settings = StoreSettings.load()
    cashback_max_percent = store_settings.cashback_max_redeem_percent
    # Preview: no maximo o % configurado da compra (apos voucher), sem zerar.
    items_after_voucher_preview = max(subtotal - voucher_discount, Decimal("0.00"))
    cashback_cap = items_after_voucher_preview * (cashback_max_percent / Decimal("100"))
    cashback_redeem_preview = min(cashback_available, cashback_cap, max(items_after_voucher_preview - Decimal("0.50"), Decimal("0.00")))
    cashback_redeem_preview = money(max(cashback_redeem_preview, Decimal("0.00")))

    if request.method == "POST":
        form = CartCheckoutForm(request.POST)

        if not welcome_profile:
            form.fields.pop("use_welcome_discount")
        if cashback_available <= 0:
            form.fields.pop("use_cashback")

        if form.is_valid():
            use_voucher = bool(welcome_profile and form.cleaned_data.get("use_welcome_discount"))
            use_cashback = bool(cashback_available > 0 and form.cleaned_data.get("use_cashback"))
            checkout_reference = uuid.uuid4()
            shipping_state = form.cleaned_data["shipping_state"]
            shipping_cost = shipping_cost_for(shipping_state)
            orders = []

            if form.cleaned_data["payment_method"] == CHECKOUT_PAYMENT_CREDIT:
                consultation_item = next((item for item in items if item["product"].requires_availability_confirmation()), None)
                if consultation_item:
                    messages.info(request, source_notice_for_customer(consultation_item["product"]))
                    return redirect("store_product_detail", product_id=consultation_item["product"].id)

                try:
                    with transaction.atomic():
                        sale, needs_analysis = create_credit_sale_from_checkout(request, items, form, shipping_cost)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect("cart_detail")

                request.session["store_cart"] = {}

                if needs_analysis:
                    messages.success(request, "Compra enviada para analise de crediario. Assim que aprovarmos, voce podera finalizar as parcelas.")
                    return redirect("dashboard")

                messages.success(request, "Compra separada para crediario. Escolha as parcelas para concluir.")
                return redirect("choose_installments", sale_id=sale.id)

            with transaction.atomic():
                if use_voucher:
                    profile = ClientProfile.objects.select_for_update().get(id=welcome_profile.id)

                    if profile.first_purchase_discount_used or profile.welcome_discount_expires_at < timezone.localdate():
                        use_voucher = False
                    else:
                        profile.first_purchase_discount_used = True
                        profile.save(update_fields=["first_purchase_discount_used"])

                for index, item in enumerate(items):
                    product = item["product"]
                    unit_price = product.suggested_sale_price
                    item_discount = Decimal("0.00")

                    if use_voucher:
                        item_discount = welcome_discount_amount(product.suggested_sale_price * item["quantity"])
                        unit_price = money(product.suggested_sale_price * (Decimal("1.00") - WELCOME_DISCOUNT_PERCENT / Decimal("100")))

                    order = StoreOrder.objects.create(
                        product=product,
                        customer=request.user if request.user.is_authenticated and not request.user.is_staff else None,
                        product_name=product.name,
                        supplier_code=product.supplier_code,
                        selected_size=item["selected_size"],
                        quantity=item["quantity"],
                        customer_name=form.cleaned_data["customer_name"],
                        customer_email=form.cleaned_data["customer_email"],
                        customer_phone=form.cleaned_data["customer_phone"],
                        shipping_state=shipping_state,
                        shipping_address=form.cleaned_data["shipping_address"],
                        shipping_cost=shipping_cost if index == 0 else Decimal("0.00"),
                        notes=form.cleaned_data["notes"],
                        unit_price=unit_price,
                        supplier_cost=product.dropshipping_cost,
                        total_amount=money(unit_price * item["quantity"] + (shipping_cost if index == 0 else Decimal("0.00"))),
                        welcome_discount_amount=item_discount,
                        estimated_profit=money((unit_price - product.dropshipping_cost) * item["quantity"]),
                        checkout_reference=checkout_reference,
                    )
                    orders.append(order)

                if use_cashback and orders:
                    items_subtotal = sum((o.items_total_amount for o in orders), Decimal("0.00"))
                    available_now = cashback_balance(request.user)
                    max_by_percent = items_subtotal * (cashback_max_percent / Decimal("100"))
                    redeem = money(min(available_now, max_by_percent, max(items_subtotal - Decimal("0.50"), Decimal("0.00"))))
                    if redeem > 0 and items_subtotal > 0:
                        remaining = redeem
                        last_index = len(orders) - 1
                        for i, o in enumerate(orders):
                            if i == last_index:
                                share = remaining
                            else:
                                share = money(redeem * (o.items_total_amount / items_subtotal))
                            share = min(share, remaining, o.items_total_amount)
                            if share <= 0:
                                continue
                            o.cashback_discount_amount = share
                            o.total_amount = money(o.total_amount - share)
                            o.save(update_fields=["cashback_discount_amount", "total_amount", "updated_at"])
                            remaining = money(remaining - share)

            request.session["store_cart"] = {}

            try:
                preference = create_cart_checkout_preference(orders, request)
            except MercadoPagoNotConfigured:
                messages.warning(request, "Pedido criado. Configure o Mercado Pago para ativar o pagamento online.")
                return redirect("store_order_detail", public_token=orders[0].public_token)
            except MercadoPagoRequestError as exc:
                messages.error(request, f"Pedido criado, mas o pagamento nao foi iniciado: {exc}")
                return redirect("store_order_detail", public_token=orders[0].public_token)

            for order in orders:
                order.mercado_pago_preference_id = preference["id"]
                order.mercado_pago_init_point = preference["init_point"]
                order.save(update_fields=["mercado_pago_preference_id", "mercado_pago_init_point", "updated_at"])

            return redirect(preference["init_point"])
    else:
        initial = {}

        if request.user.is_authenticated and not request.user.is_staff:
            initial = {
                "customer_name": request.user.full_name,
                "customer_email": request.user.email,
                "customer_phone": request.user.profile.phone,
                "shipping_address": request.user.profile.address,
            }

        form = CartCheckoutForm(initial=initial)

        if not welcome_profile:
            form.fields.pop("use_welcome_discount")
        if cashback_available <= 0:
            form.fields.pop("use_cashback")

    return render(
        request,
        "accounts/cart_checkout.html",
        {
            "form": form,
            "items": items,
            "subtotal": subtotal,
            "voucher_discount": voucher_discount,
            "welcome_discount_available": bool(welcome_profile),
            "welcome_discount_percent": WELCOME_DISCOUNT_PERCENT,
            "welcome_discount_expires_at": welcome_profile.welcome_discount_expires_at if welcome_profile else None,
            "cashback_available": cashback_available,
            "cashback_redeem_preview": cashback_redeem_preview,
            "cashback_max_percent": cashback_max_percent,
            "shipping_rates": shipping_rates_payload(),
            "shipping_rates_json": json.dumps(shipping_rates_payload()),
        },
    )


def store_checkout(request, product_id):
    if not request.user.is_authenticated:
        messages.info(request, "Entre ou cadastre-se para finalizar a compra.")
        return redirect(f"{resolve_url('login')}?next={request.path}")

    product = get_object_or_404(
        SupplierProduct,
        id=product_id,
        is_active=True,
        is_visible=True,
        stock_quantity__gt=0,
    )

    welcome_profile = get_welcome_discount_profile(request)
    welcome_discount = welcome_discount_amount(product.suggested_sale_price) if welcome_profile else Decimal("0.00")
    welcome_total = money(product.suggested_sale_price - welcome_discount)

    if request.method == "POST":
        form = StoreOrderForm(request.POST, product=product)

        if not welcome_profile:
            form.fields.pop("use_welcome_discount")

        if form.is_valid():
            shipping_cost = shipping_cost_for(form.cleaned_data["shipping_state"])

            if form.cleaned_data["payment_method"] == CHECKOUT_PAYMENT_CREDIT:
                if product.requires_availability_confirmation():
                    messages.info(request, source_notice_for_customer(product))
                    return redirect("store_product_detail", product_id=product.id)

                credit_items = [
                    {
                        "product": product,
                        "selected_size": form.cleaned_data["selected_size"],
                        "quantity": 1,
                        "total": product.suggested_sale_price,
                    }
                ]

                try:
                    with transaction.atomic():
                        sale, needs_analysis = create_credit_sale_from_checkout(request, credit_items, form, shipping_cost)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect("store_product_detail", product_id=product.id)

                if needs_analysis:
                    messages.success(request, "Compra enviada para analise de crediario. Assim que aprovarmos, voce podera finalizar as parcelas.")
                    return redirect("dashboard")

                messages.success(request, "Compra separada para crediario. Escolha as parcelas para concluir.")
                return redirect("choose_installments", sale_id=sale.id)

            with transaction.atomic():
                order = form.save(commit=False)
                order.product = product
                order.product_name = product.name
                order.supplier_code = product.supplier_code
                order.unit_price = product.suggested_sale_price
                order.supplier_cost = product.dropshipping_cost
                order.shipping_cost = shipping_cost
                order.total_amount = money(product.suggested_sale_price + shipping_cost)
                order.estimated_profit = product.suggested_sale_price - product.dropshipping_cost

                if request.user.is_authenticated and not request.user.is_staff:
                    order.customer = request.user

                if welcome_profile and form.cleaned_data.get("use_welcome_discount"):
                    profile = ClientProfile.objects.select_for_update().get(id=welcome_profile.id)

                    if not profile.first_purchase_discount_used:
                        order.customer = request.user
                        order.welcome_discount_amount = welcome_discount_amount(product.suggested_sale_price)
                        order.unit_price = money(product.suggested_sale_price - order.welcome_discount_amount)
                        order.total_amount = money(order.unit_price + shipping_cost)
                        order.estimated_profit = order.unit_price - product.dropshipping_cost
                        profile.first_purchase_discount_used = True
                        profile.save(update_fields=["first_purchase_discount_used"])

                order.save()

            try:
                preference = create_checkout_preference(order, request)
            except MercadoPagoNotConfigured:
                messages.warning(request, "Pedido criado. Configure o Mercado Pago para ativar o pagamento online.")

                return redirect("store_order_detail", public_token=order.public_token)
            except MercadoPagoRequestError as exc:
                messages.error(request, f"Pedido criado, mas o pagamento nao foi iniciado: {exc}")

                return redirect("store_order_detail", public_token=order.public_token)

            order.mercado_pago_preference_id = preference["id"]
            order.mercado_pago_init_point = preference["init_point"]
            order.save(update_fields=["mercado_pago_preference_id", "mercado_pago_init_point", "updated_at"])

            return redirect(order.mercado_pago_init_point)
    else:
        form = StoreOrderForm(product=product)

        if not welcome_profile:
            form.fields.pop("use_welcome_discount")

    return render(
        request,
        "accounts/store_checkout.html",
        {
            "form": form,
            "product": product,
            "welcome_discount": welcome_discount,
            "welcome_discount_percent": WELCOME_DISCOUNT_PERCENT,
            "welcome_total": welcome_total,
            "shipping_rates": shipping_rates_payload(),
            "shipping_rates_json": json.dumps(shipping_rates_payload()),
        },
    )


def store_order_detail(request, public_token):
    order = get_object_or_404(StoreOrder, public_token=public_token)

    return render(request, "accounts/store_order_detail.html", {"order": order})


def payment_success(request):
    order_code = request.GET.get("external_reference", "")
    payment_id = request.GET.get("payment_id", "")

    if order_code.startswith("cart:"):
        checkout_reference = order_code.split(":", 1)[1]
        orders = StoreOrder.objects.filter(checkout_reference=checkout_reference)
        first_order = orders.first()

        if not first_order:
            return render(request, "accounts/store_payment_return.html", {"title": "Pedido nao encontrado", "message": "Nao foi possivel localizar os itens deste pagamento."}, status=404)

        if payment_id:
            try:
                payment = get_payment(payment_id)
            except (MercadoPagoNotConfigured, MercadoPagoRequestError):
                payment = {}

            if payment.get("status") == "approved":
                method = payment_method_from_payment(payment)

                for order in orders:
                    order.mark_paid(str(payment.get("id", payment_id)), method)

        return redirect("store_order_detail", public_token=first_order.public_token)

    if order_code:
        order = get_object_or_404(StoreOrder, order_code=order_code)

        if payment_id:
            try:
                payment = get_payment(payment_id)
            except (MercadoPagoNotConfigured, MercadoPagoRequestError):
                payment = {}

            if payment.get("status") == "approved":
                order.mark_paid(str(payment.get("id", payment_id)), payment_method_from_payment(payment))

        return redirect("store_order_detail", public_token=order.public_token)

    return render(request, "accounts/store_payment_return.html", {"title": "Pagamento recebido", "message": "Obrigado. Seu pagamento esta em processamento."})


def payment_failure(request):
    return render(request, "accounts/store_payment_return.html", {"title": "Pagamento nao concluido", "message": "O pagamento nao foi concluido. Voce pode tentar novamente."})


def payment_pending(request):
    return render(request, "accounts/store_payment_return.html", {"title": "Pagamento pendente", "message": "Seu pagamento ainda esta pendente. Assim que confirmar, o pedido sera atualizado."})


@csrf_exempt
def mercado_pago_webhook(request):
    payment_id = request.GET.get("data.id") or request.GET.get("id")

    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}

        payment_id = payment_id or str(payload.get("data", {}).get("id", "") or payload.get("id", ""))

    if not payment_id:
        return JsonResponse({"ok": True, "ignored": "missing payment id"})

    if not verify_webhook_signature(request, payment_id.lower()):
        return JsonResponse({"ok": False, "error": "invalid signature"}, status=401)

    try:
        payment = get_payment(payment_id)
    except (MercadoPagoNotConfigured, MercadoPagoRequestError):
        return JsonResponse({"ok": False}, status=503)

    order_code = payment.get("external_reference", "")

    payment_status = payment.get("status")
    payment_reference = str(payment.get("id", payment_id))

    if order_code.startswith("cart:"):
        orders = StoreOrder.objects.filter(checkout_reference=order_code.split(":", 1)[1])

        if not orders.exists():
            return JsonResponse({"ok": False, "error": "cart not found"}, status=404)

        payment_method = payment_method_from_payment(payment)

        for order in orders:
            if payment_status == "approved":
                order.mark_paid(payment_reference, payment_method)
            elif payment_status == "rejected":
                order.mark_payment_failed(payment_reference)

        if payment_status == "rejected":
            PaymentAlert.objects.get_or_create(
                payment_id=payment_reference,
                defaults={
                    "store_order": orders.first(),
                    "status_detail": payment.get("status_detail", ""),
                },
            )

        return JsonResponse({"ok": True})

    if order_code.startswith("credit-sale:"):
        try:
            sale_id = int(order_code.split(":", 1)[1])
            sale = CreditSale.objects.get(id=sale_id)
        except (ValueError, CreditSale.DoesNotExist):
            return JsonResponse({"ok": False, "error": "sale not found"}, status=404)

        if payment_status == "approved":
            sale.mark_paid(payment_reference)
        elif payment_status == "rejected":
            sale.mark_payment_failed(payment_reference)
            PaymentAlert.objects.get_or_create(
                payment_id=payment_reference,
                defaults={
                    "credit_sale": sale,
                    "status_detail": payment.get("status_detail", ""),
                },
            )

        return JsonResponse({"ok": True})

    if order_code:
        try:
            order = StoreOrder.objects.get(order_code=order_code)
        except StoreOrder.DoesNotExist:
            return JsonResponse({"ok": False, "error": "order not found"}, status=404)

        if payment_status == "approved":
            order.mark_paid(payment_reference, payment_method_from_payment(payment))
        elif payment_status == "rejected":
            order.mark_payment_failed(payment_reference)
            PaymentAlert.objects.get_or_create(
                payment_id=payment_reference,
                defaults={
                    "store_order": order,
                    "status_detail": payment.get("status_detail", ""),
                },
            )

    return JsonResponse({"ok": True})


def register(request):
    credit_mode = (request.POST.get("intent") or request.GET.get("intent") or "").strip() == "credit"
    next_url = safe_next_url(request, request.POST.get("next") or request.GET.get("next"))
    ref_code = (request.POST.get("ref") or request.GET.get("ref") or "").strip()
    # Quem chegou pelo Google ja tem email confirmado guardado na sessao.
    google_email = request.session.get(GOOGLE_EMAIL_SESSION_KEY, "")

    if request.method == "POST":
        form = RegisterForm(request.POST, request.FILES, credit_mode=credit_mode, google_email=google_email)

        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except Exception:
                logger.exception("Erro ao criar cadastro")
                form.add_error(
                    None,
                    "Nao foi possivel concluir seu cadastro agora. Tente novamente em instantes.",
                )

                return render(
                    request,
                    "accounts/register.html",
                    {
                        "form": form,
                        "credit_mode": credit_mode,
                        "next_url": next_url,
                        "ref_code": ref_code,
                        "google_email": google_email,
                    },
                    status=500,
                )

            profile = user.profile
            referrer = resolve_referrer(ref_code)
            if referrer and referrer.pk != user.pk:
                profile.referred_by = referrer
                profile.save(update_fields=["referred_by"])
            if is_doces_e_mais_owner_email(user.email):
                ensure_doces_e_mais_profile_access(user)
            elif credit_mode and settings.PHONE_VERIFICATION_REQUIRED and profile.phone:
                profile.phone_verification_code = generate_phone_code()
                profile.phone_verification_sent_at = timezone.now()
                profile.save(update_fields=["phone_verification_code", "phone_verification_sent_at"])
            else:
                profile.phone_verified = True
                profile.save(update_fields=["phone_verified"])
            login(request, user)

            for session_key in (GOOGLE_EMAIL_SESSION_KEY, GOOGLE_NAME_SESSION_KEY, GOOGLE_FIRST_NAME_SESSION_KEY):
                request.session.pop(session_key, None)

            if not is_doces_e_mais_owner_email(user.email) and credit_mode and settings.PHONE_VERIFICATION_REQUIRED and profile.phone:
                return redirect("verify_phone")

            if next_url:
                return redirect(next_url)

            return redirect("dashboard")
    else:
        initial = {}

        if google_email:
            initial = {
                "email": google_email,
                "full_name": request.session.get(GOOGLE_NAME_SESSION_KEY, ""),
                "preferred_name": request.session.get(GOOGLE_FIRST_NAME_SESSION_KEY, ""),
            }

        form = RegisterForm(credit_mode=credit_mode, google_email=google_email, initial=initial)

    return render(
        request,
        "accounts/register.html",
        {
            "form": form,
            "credit_mode": credit_mode,
            "next_url": next_url,
            "ref_code": ref_code,
            "google_email": google_email,
        },
    )


@login_required
def verify_phone(request):
    profile = request.user.profile

    if not settings.PHONE_VERIFICATION_REQUIRED:
        return redirect("dashboard")

    if profile.phone_verified:
        return redirect("dashboard")

    locked = profile.phone_verification_attempts >= ClientProfile.MAX_PHONE_VERIFICATION_ATTEMPTS

    if request.method == "POST" and locked:
        messages.error(
            request,
            f"Numero maximo de tentativas excedido. Entre em contato pelo email {settings.STORE_CONTACT_EMAIL} para receber um novo codigo.",
        )
        form = PhoneVerificationForm()
    elif request.method == "POST":
        form = PhoneVerificationForm(request.POST)

        if form.is_valid():
            if form.cleaned_data["code"] == profile.phone_verification_code:
                profile.phone_verified = True
                profile.phone_verification_code = ""
                profile.phone_verification_attempts = 0
                profile.save(update_fields=["phone_verified", "phone_verification_code", "phone_verification_attempts"])

                return redirect("dashboard")

            profile.phone_verification_attempts += 1
            profile.save(update_fields=["phone_verification_attempts"])
            locked = profile.phone_verification_attempts >= ClientProfile.MAX_PHONE_VERIFICATION_ATTEMPTS

            if locked:
                messages.error(
                    request,
                    f"Numero maximo de tentativas excedido. Entre em contato pelo email {settings.STORE_CONTACT_EMAIL} para receber um novo codigo.",
                )
            else:
                remaining = ClientProfile.MAX_PHONE_VERIFICATION_ATTEMPTS - profile.phone_verification_attempts
                messages.error(request, f"Codigo invalido. Tentativas restantes: {remaining}.")
    else:
        form = PhoneVerificationForm()

    return render(
        request,
        "accounts/verify_phone.html",
        {
            "form": form,
            "locked": locked,
            "development_code": profile.phone_verification_code if settings.DEBUG else "",
        },
    )


@login_required
def dashboard(request):
    if request.user.is_staff:
        return redirect("management_dashboard")

    if is_partner_user(request.user):
        return redirect("partner_home")

    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if profile.registration_status != ClientProfile.APPROVED:
        return render(request, "accounts/registration_pending.html", {"profile": profile})

    purchase_groups = build_purchase_groups(request.user)
    referral_code = get_or_create_referral_code(request.user)
    referral_link = request.build_absolute_uri(f"{resolve_url('register')}?ref={referral_code}") if referral_code else ""
    store_settings = StoreSettings.load()
    return render(
        request,
        "accounts/dashboard.html",
        {
            "purchase_groups": purchase_groups,
            "cashback_balance": cashback_balance(request.user),
            "cashback_percent": store_settings.cashback_percent,
            "cashback_history": request.user.cashback_transactions.all()[:10],
            "points_active": store_settings.points_active,
            "points_balance": points_balance_capped(request.user),
            "points_cap": store_settings.points_cap,
            "points_pix": store_settings.points_pix,
            "points_discount": points_discount_percent(points_balance_capped(request.user), store_settings),
            "points_history": request.user.points_transactions.all()[:10],
            "referral_points": store_settings.referral_points,
            "referral_code": referral_code,
            "referral_link": referral_link,
            "referral_count": request.user.referrals.count(),
            "referral_bonus": store_settings.referral_bonus,
        },
    )


@login_required
def partner_home(request):
    if not is_partner_user(request.user):
        return redirect("dashboard")

    config = partner_profile_config(request.user)
    return render(
        request,
        "accounts/partner_home.html",
        {
            "partner_name": config["name"] or "parceira",
            "commission_percent": config["commission_percent"],
        },
    )


PARTNER_BRAND = "Ramosê"


@login_required
def partner_add_bag(request):
    if not is_partner_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        form = PartnerBagForm(request.POST, request.FILES)
        if form.is_valid():
            bag = form.save(commit=False)
            # Trava categoria e marca: parceira so lanca bolsas da Ramose.
            bag.category = "Bolsas"
            bag.brand = PARTNER_BRAND
            # Garante que o nome carrega a marca (o relatorio filtra por nome).
            if "ramos" not in (bag.name or "").lower():
                bag.name = f"{PARTNER_BRAND} {bag.name}".strip()
            bag.sizes = bag.sizes or "Único"
            bag.source = SupplierProduct.SOURCE_REVENDA_CALCADOS
            bag.supplier_code = f"RAMOSE-{uuid.uuid4().hex[:8].upper()}"
            bag.is_visible = True
            bag.is_active = True
            bag.save()
            messages.success(request, "Bolsa lançada com sucesso e já disponível na loja.")
            return redirect("partner_add_bag")
    else:
        form = PartnerBagForm()

    my_bags = SupplierProduct.objects.filter(brand__iexact=PARTNER_BRAND).order_by("-created_at")[:50]
    return render(request, "accounts/partner_add_bag.html", {"form": form, "my_bags": my_bags})


@login_required
def partner_sales_detail(request):
    if not is_partner_user(request.user):
        return redirect("dashboard")

    aliases = partner_sales_config(request.user).get("aliases") or [PARTNER_BRAND]
    brand_q = build_partner_sales_brand_query(aliases)

    entries = []

    # Vendas na loja (cartao/Pix) - o parcelamento do cartao nao fica salvo.
    orders = StoreOrder.objects.filter(status__in=PARTNER_SALES_STATUSES).filter(brand_q)
    for order in orders:
        discount = money((order.welcome_discount_amount or Decimal("0.00")) + (order.cashback_discount_amount or Decimal("0.00")))
        entries.append({
            "date": order.paid_at or order.created_at,
            "product": order.product_name,
            "quantity": order.quantity,
            "total": order.total_amount,
            "discount": discount,
            "installments": None,
            "method": "Cartão/Pix",
            "payment_date": order.paid_at,
        })

    # Vendas no crediario que incluem bolsas da marca dela.
    sale_ids = set(
        CreditSaleProduct.objects.filter(
            Q(brand__icontains=PARTNER_BRAND) | Q(name__icontains="Ramos")
        ).values_list("sale_id", flat=True)
    )
    credit_sales = CreditSale.objects.filter(id__in=sale_ids, status=CreditSale.ACCEPTED).prefetch_related("products")
    for sale in credit_sales:
        her_names = [
            p.name for p in sale.products.all()
            if "ramos" in ((p.brand or "") + " " + (p.name or "")).lower()
        ]
        entries.append({
            "date": sale.created_at,
            "product": ", ".join(her_names) or "Bolsa Ramosê",
            "quantity": len(her_names) or 1,
            "total": sale.total_amount,
            "discount": sale.welcome_discount_amount,
            "installments": sale.selected_installments,
            "method": sale.get_selected_payment_method_display() if sale.selected_payment_method else "Crediário",
            "payment_date": sale.first_due_date,
        })

    entries.sort(key=lambda item: item["date"] or timezone.now(), reverse=True)

    return render(request, "accounts/partner_sales_detail.html", {"entries": entries})


@login_required
def partner_sales_report(request):
    if not user_can_view_partner_sales(request.user):
        return HttpResponseForbidden("Voce nao tem acesso a este relatorio.")

    config = partner_sales_config(request.user)
    scope = request.GET.get("scope", "combined").strip()
    ranking = request.GET.get("ranking", "units").strip()
    start_date = parse_date(request.GET.get("inicio", ""))
    end_date = parse_date(request.GET.get("fim", ""))
    today = timezone.localdate()

    if not end_date:
        end_date = today

    if not start_date:
        start_date = end_date - timedelta(days=29)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    base_queryset = (
        StoreOrder.objects.select_related("customer", "product")
        .filter(status__in=PARTNER_SALES_STATUSES)
        .filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
    )
    brand_query = build_partner_sales_brand_query(config["aliases"])

    if scope == "my_purchases":
        filtered_queryset = base_queryset.filter(customer=request.user)
    elif scope == "brand_only":
        filtered_queryset = base_queryset.filter(brand_query)
    else:
        scope = "combined"
        filtered_queryset = base_queryset.filter(brand_query | Q(customer=request.user))

    orders = list(filtered_queryset.order_by("-paid_at", "-created_at"))
    summary = summarize_partner_sales_orders(orders)

    period_days = max((end_date - start_date).days + 1, 1)
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)
    previous_queryset = (
        StoreOrder.objects.filter(status__in=PARTNER_SALES_STATUSES)
        .filter(created_at__date__gte=previous_start, created_at__date__lte=previous_end)
    )

    if scope == "my_purchases":
        previous_queryset = previous_queryset.filter(customer=request.user)
    elif scope == "brand_only":
        previous_queryset = previous_queryset.filter(brand_query)
    else:
        previous_queryset = previous_queryset.filter(brand_query | Q(customer=request.user))

    previous_summary = summarize_partner_sales_orders(list(previous_queryset))
    ranking_products = sort_partner_sales_products(summary["top_products"], ranking)

    return render(
        request,
        "accounts/partner_sales_report.html",
        {
            "report_title": config["title"],
            "brand_keyword": config["keyword"],
            "orders": orders,
            "summary": summary,
            "ranking_products": ranking_products[:10],
            "scope": scope,
            "ranking": ranking,
            "start_date": start_date,
            "end_date": end_date,
            "previous_start": previous_start,
            "previous_end": previous_end,
            "revenue_growth": percentage_growth(summary["total_revenue"], previous_summary["total_revenue"]),
            "order_growth": percentage_growth(summary["total_orders"], previous_summary["total_orders"]),
            "units_growth": percentage_growth(summary["total_units"], previous_summary["total_units"]),
            "profit_growth": percentage_growth(summary["total_profit"], previous_summary["total_profit"]),
            "scope_options": [
                {"value": "combined", "label": "Ramosê + minhas compras"},
                {"value": "brand_only", "label": "Somente Ramosê"},
                {"value": "my_purchases", "label": "Somente minhas compras"},
            ],
            "ranking_options": [
                {"value": "units", "label": "Mais vendidos"},
                {"value": "revenue", "label": "Maior faturamento"},
                {"value": "profit", "label": "Maior lucro"},
                {"value": "recent", "label": "Venda mais recente"},
            ],
        },
    )


@login_required
def account(request):
    return render(request, "accounts/account.html")


@login_required
def account_delete(request):
    if request.user.is_staff:
        return HttpResponseForbidden("Contas de gestao nao podem ser excluidas por aqui.")

    if request.method == "POST":
        password = request.POST.get("password", "")

        if not request.POST.get("confirm"):
            messages.error(request, "Confirme que entende o que acontece com sua conta antes de continuar.")
            return redirect("account_delete")

        if not request.user.check_password(password):
            messages.error(request, "Senha incorreta. Sua conta nao foi excluida.")
            return redirect("account_delete")

        user = request.user
        user.request_deletion()
        logout(request)
        messages.success(
            request,
            "Sua conta sera excluida totalmente em ate 7 dias. Se quiser voltar antes disso, "
            "basta entrar novamente com seu e-mail e senha que a exclusao e cancelada.",
        )

        return redirect("store_front")

    return render(request, "accounts/account_delete.html")


def data_deletion_info(request):
    return render(
        request,
        "accounts/data_deletion_info.html",
        {
            "contact_email": settings.STORE_CONTACT_EMAIL,
        },
    )


# Dicas diárias de educação financeira mostradas em "Minhas finanças".
# A dica do dia é escolhida pela data (todas as clientes veem a mesma).
FINANCE_TIPS = [
    "Anote tudo o que você gasta durante uma semana. Só de enxergar para onde o dinheiro vai, você já começa a economizar.",
    "Antes de comprar, espere 24 horas. Se no dia seguinte ainda fizer sentido, compre com tranquilidade.",
    "Separe uma quantia fixa por mês para você, como se fosse uma conta a pagar. Poupar primeiro, gastar depois.",
    "Divida seus gastos em três grupos: necessidades, desejos e sonhos. O equilíbrio entre eles é o segredo.",
    "Parcelar não é vilão — o vilão é parcelar sem somar quanto já está comprometido nos próximos meses.",
    "Guarde o troco: transferir os centavos e valores quebrados para uma reserva no fim do dia rende mais do que parece.",
    "Tenha uma reserva para emergências, mesmo que pequena. Começar com R$ 20 por mês já é começar.",
    "Revise suas assinaturas e serviços mensais. O que você não usa há 2 meses pode ser cancelado sem dor.",
    "Compare preços em 3 lugares antes de compras maiores. Dez minutos de pesquisa podem valer um bom desconto.",
    "Promoção só é economia se você já ia comprar. Se não ia, é gasto novo.",
    "Combine limites de presente em datas comemorativas. Carinho não se mede pelo preço.",
    "Pague primeiro as dívidas com juros maiores. Elas crescem mais rápido que as outras.",
    "Negociar dívida não é vergonha: quem procura o credor primeiro consegue as melhores condições.",
    "Evite usar o limite do cheque especial: ele é um dos créditos mais caros que existem.",
    "Faça uma lista antes de ir às compras e siga a lista. O supermercado é desenhado para te fazer gastar mais.",
    "Comprar usado ou trocar com amigas também é inteligência financeira.",
    "Defina um valor mensal para 'gastos livres' sem culpa. Orçamento apertado demais ninguém sustenta.",
    "Ensine as crianças sobre dinheiro com o cofrinho: elas aprendem vendo você cuidar do seu.",
    "Um sonho grande fica possível quando vira meta com prazo e valor mensal definidos.",
    "Cuidado com compras por impulso à noite: cansaço e celular são uma dupla perigosa para o bolso.",
    "Registre suas contas com vencimento aqui no app: pagar em dia evita juros e multas desnecessárias.",
    "Quando receber um dinheiro extra, divida: uma parte para dívidas, uma para reserva e uma para você.",
    "Renegociar plano de celular, internet e energia de tempos em tempos quase sempre traz desconto.",
    "Se a parcela não cabe no mês junto com as outras contas, o problema não é o preço: é o momento.",
    "Ter objetivos escritos aumenta muito a chance de alcançá-los. Escreva os seus três maiores.",
    "Cartão de crédito é ferramenta, não renda extra. Use apenas o que você conseguiria pagar à vista.",
    "Pequenos gastos diários somam: R$ 8 por dia úteis são mais de R$ 160 no mês.",
    "Reserve um dia do mês para 'cuidar do dinheiro': revisar contas, dívidas e metas. Meia hora basta.",
    "Antes de assumir uma dívida nova, quite ou reduza uma antiga. Uma entra, uma sai.",
    "Celebre suas pequenas vitórias financeiras. Quitou uma conta? Reconheça seu progresso!",
]


def daily_finance_tip():
    index = timezone.localdate().toordinal() % len(FINANCE_TIPS)
    return FINANCE_TIPS[index]


def customer_finances(request):
    if not request.user.is_authenticated:
        messages.info(request, "Para organizar suas finanças, cadastre-se e aprenda sobre organização financeira.")
        return redirect(f"{resolve_url('login')}?next={resolve_url('customer_finances')}")

    if request.user.is_staff:
        return HttpResponseForbidden("Area exclusiva do cliente.")

    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if profile.registration_status != ClientProfile.APPROVED:
        return render(request, "accounts/registration_pending.html", {"profile": profile})

    owner_finance_mode = can_manage_doces_e_mais(request.user)
    finance_scope = PersonalDebt.SCOPE_PERSONAL if owner_finance_mode else None

    if request.method == "POST":
        form = PersonalDebtForm(request.POST)

        if form.is_valid():
            personal_debt = form.save(commit=False)
            personal_debt.client = request.user
            if owner_finance_mode:
                personal_debt.scope = PersonalDebt.SCOPE_PERSONAL
            personal_debt.save()
            messages.success(request, "Conta pessoal criada com sucesso.")
            return redirect("customer_finances")
    else:
        form = PersonalDebtForm()

    context = build_customer_finance_context(request.user, scope=finance_scope)
    context["personal_debt_form"] = form
    context["finance_tip"] = daily_finance_tip()
    if owner_finance_mode:
        context["finance_comparison"] = {
            "personal": finance_scope_totals(request.user, PersonalDebt.SCOPE_PERSONAL),
            "business": finance_scope_totals(request.user, PersonalDebt.SCOPE_BUSINESS),
        }
        context.update(doces_e_mais_finance_ui_context(PersonalDebt.SCOPE_PERSONAL))
    return render(request, "accounts/customer_finances.html", context)


@login_required
def staff_finances(request):
    if not request.user.is_staff:
        return redirect("customer_finances")

    scope = request.GET.get("tipo", "").strip()
    if scope != PersonalDebt.SCOPE_BUSINESS:
        scope = PersonalDebt.SCOPE_PERSONAL

    if request.method == "POST":
        form = PersonalDebtForm(request.POST)

        if form.is_valid():
            entry = form.save(commit=False)
            entry.client = request.user
            entry.scope = scope
            entry.save()
            messages.success(request, "Lançamento adicionado.")
            return redirect(f"{resolve_url('staff_finances')}?tipo={scope}")
    else:
        form = PersonalDebtForm()

    context = build_customer_finance_context(request.user, scope=scope, include_store=False)
    context["personal_debt_form"] = form
    context["finance_staff_mode"] = True
    context["finance_scope"] = scope
    context["finance_scope_label"] = "Empresarial" if scope == PersonalDebt.SCOPE_BUSINESS else "Pessoal"
    context["finance_comparison"] = {
        "personal": finance_scope_totals(request.user, PersonalDebt.SCOPE_PERSONAL),
        "business": finance_scope_totals(request.user, PersonalDebt.SCOPE_BUSINESS),
    }
    return render(request, "accounts/customer_finances.html", context)


def _unsubscribe_url(request, user):
    token = signing.dumps({"uid": user.pk}, salt="marketing-unsubscribe")
    return request.build_absolute_uri(resolve_url("marketing_unsubscribe", token=token))


def staff_promo_email(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Area exclusiva da loja.")

    recipients = ClientProfile.objects.filter(
        marketing_opt_in=True,
    ).exclude(user__email="").select_related("user")
    recipient_count = recipients.count()

    if request.method == "POST":
        form = PromoEmailForm(request.POST)

        # Ativa o opt-in para os clientes ja cadastrados (aprovados, com email).
        if request.POST.get("action") == "optin_existing":
            updated = ClientProfile.objects.filter(
                registration_status=ClientProfile.APPROVED,
                marketing_opt_in=False,
                user__is_staff=False,
            ).exclude(user__email="").update(marketing_opt_in=True)
            messages.success(request, f"{updated} cliente(s) ativados para receber promoções.")
            return redirect("staff_promo_email")

        # Teste: envia so para o proprio admin, ignorando a lista/opt-in.
        if request.POST.get("action") == "test":
            if request.user.email:
                try:
                    EmailMultiAlternatives(
                        "Teste de envio - Líndice",
                        "Este é um e-mail de teste. Se você recebeu, a configuração de envio está funcionando.",
                        settings.DEFAULT_FROM_EMAIL,
                        [request.user.email],
                    ).send(fail_silently=False)
                    messages.success(request, f"E-mail de teste enviado para {request.user.email}.")
                except Exception as exc:
                    logger.exception("Falha no e-mail de teste")
                    messages.error(request, f"Não foi possível enviar o teste: {exc}")
            else:
                messages.error(request, "Sua conta não tem e-mail cadastrado.")
            return redirect("staff_promo_email")

        if form.is_valid():
            subject = form.cleaned_data["subject"]
            body = form.cleaned_data["message"]
            sent = 0
            for profile in recipients:
                user = profile.user
                unsubscribe = _unsubscribe_url(request, user)
                greeting = user.preferred_name or user.full_name or "Ola"
                text = (
                    f"{greeting},\n\n{body}\n\n"
                    f"---\nVoce recebe este email porque aceitou receber promocoes da Lindice.\n"
                    f"Para nao receber mais, acesse: {unsubscribe}"
                )
                try:
                    email = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
                    email.send(fail_silently=False)
                    sent += 1
                except Exception:
                    logger.exception("Falha ao enviar promocao para %s", user.email)

            messages.success(request, f"Promoção enviada para {sent} de {recipient_count} contato(s).")
            return redirect("staff_promo_email")
    else:
        form = PromoEmailForm()

    return render(
        request,
        "accounts/staff_promo_email.html",
        {"form": form, "recipient_count": recipient_count},
    )


def staff_loyalty_settings(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Area exclusiva da loja.")

    settings_obj = StoreSettings.load()

    if request.method == "POST":
        form = StoreSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Configurações do cashback atualizadas.")
            return redirect("staff_loyalty_settings")
    else:
        form = StoreSettingsForm(instance=settings_obj)

    return render(request, "accounts/staff_loyalty_settings.html", {"form": form})


def marketing_unsubscribe(request, token):
    try:
        data = signing.loads(token, salt="marketing-unsubscribe", max_age=60 * 60 * 24 * 365)
    except signing.BadSignature:
        return render(request, "accounts/marketing_unsubscribe.html", {"ok": False})

    profile = ClientProfile.objects.filter(user_id=data.get("uid")).first()
    if profile:
        profile.marketing_opt_in = False
        profile.save(update_fields=["marketing_opt_in"])

    return render(request, "accounts/marketing_unsubscribe.html", {"ok": True})


@login_required
def measurements(request):
    if request.user.is_staff:
        return redirect("management_dashboard")

    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if profile.registration_status != ClientProfile.APPROVED:
        return render(request, "accounts/registration_pending.html", {"profile": profile})

    finger_sizes = profile.finger_sizes or {}
    right_hand = finger_sizes.get("mao_direita", {})
    left_hand = finger_sizes.get("mao_esquerda", {})
    initial = {
        "shoe_size": profile.shoe_size,
        "right_thumb": right_hand.get("polegar", ""),
        "right_index": right_hand.get("indicador", ""),
        "right_middle": right_hand.get("medio", ""),
        "right_ring": right_hand.get("anelar", ""),
        "right_little": right_hand.get("mindinho", ""),
        "left_thumb": left_hand.get("polegar", ""),
        "left_index": left_hand.get("indicador", ""),
        "left_middle": left_hand.get("medio", ""),
        "left_ring": left_hand.get("anelar", ""),
        "left_little": left_hand.get("mindinho", ""),
    }

    if request.method == "POST":
        form = MeasurementsForm(request.POST)

        if form.is_valid():
            form.save(profile)
            messages.success(request, "Medidas salvas com sucesso.")

            return redirect("measurements")
    else:
        form = MeasurementsForm(initial=initial)

    return render(request, "accounts/measurements.html", {"form": form})


@login_required
def profile(request):
    if request.user.is_staff:
        return redirect("management_dashboard")

    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if request.method == "POST" and request.POST.get("action") == "cpf":
        photo_form = ProfilePhotoForm(instance=profile)
        cpf_form = CheckoutCpfForm(request.POST, profile=profile)

        if cpf_form.is_valid():
            cpf_form.save()
            messages.success(request, "CPF vinculado a sua conta com sucesso.")

            return redirect("profile")
    elif request.method == "POST":
        photo_form = ProfilePhotoForm(request.POST, request.FILES, instance=profile)
        cpf_form = CheckoutCpfForm(profile=profile)

        if photo_form.is_valid():
            photo_form.save()
            messages.success(request, "Foto atualizada com sucesso.")

            return redirect("profile")
    else:
        photo_form = ProfilePhotoForm(instance=profile)
        cpf_form = CheckoutCpfForm(profile=profile)

    return render(request, "accounts/profile.html", {"form": photo_form, "cpf_form": cpf_form, "profile": profile})


@login_required
def change_password(request):
    if request.method == "POST":
        form = UserPasswordChangeForm(request.user, request.POST)

        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Senha alterada com sucesso.")

            return redirect("store_front")
    else:
        form = UserPasswordChangeForm(request.user)

    return render(request, "accounts/change_password.html", {"form": form})


@login_required
def choose_installments(request, sale_id):
    if request.user.is_staff:
        return redirect("management_dashboard")

    sale = get_object_or_404(
        CreditSale,
        id=sale_id,
        client=request.user,
        status__in=[CreditSale.PENDING, CreditSale.ACCEPTED],
        payment_status__in=[CreditSale.PAYMENT_PENDING, CreditSale.PAYMENT_FAILED],
    )
    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if profile.registration_status != ClientProfile.APPROVED:
        return render(request, "accounts/registration_pending.html", {"profile": profile})

    if request.method == "POST":
        form = InstallmentChoiceForm(request.POST, sale=sale)

        if form.is_valid():
            was_pending = sale.status == CreditSale.PENDING

            with transaction.atomic():
                if form.cleaned_data["first_due_date"]:
                    sale.first_due_date = form.cleaned_data["first_due_date"]
                sale.choose_payment(
                    form.cleaned_data["payment_method"],
                    form.cleaned_data["installments"],
                    form.cleaned_data["use_welcome_discount"],
                    form.cleaned_data["remainder_payment_method"],
                    form.cleaned_data.get("use_points", False),
                )

            if was_pending:
                create_sale_confirmed_notifications(sale)

            if sale.selected_payment_method == CreditSale.CREDIT:
                messages.success(
                    request,
                    "Compra no crediario confirmada. Lembre-se: atraso gera multa de 2% e juros de 1% ao mes.",
                )
            else:
                messages.success(request, "Forma de pagamento escolhida com sucesso.")

            if sale.selected_payment_method == CreditSale.PIX:
                return redirect("pix_payment_instructions", sale_id=sale.id)

            if sale.selected_payment_method == CreditSale.CARD:
                try:
                    preference = create_credit_sale_card_preference(sale, request)
                except MercadoPagoNotConfigured:
                    messages.warning(request, "Cartao ainda nao esta disponivel. Entre em contato com a loja.")

                    return redirect("dashboard")
                except MercadoPagoRequestError:
                    logger.exception("Erro ao iniciar pagamento com cartao")
                    messages.error(request, "Nao foi possivel abrir o pagamento com cartao agora. Tente novamente.")

                    return redirect("dashboard")

                sale.mercado_pago_preference_id = preference["id"]
                sale.mercado_pago_init_point = preference["init_point"]
                sale.save(update_fields=["mercado_pago_preference_id", "mercado_pago_init_point"])

                return redirect(sale.mercado_pago_init_point)

            return redirect("dashboard")
    else:
        form = InstallmentChoiceForm(sale=sale)

    return render(request, "accounts/choose_installments.html", sale_checkout_context(sale, form, "dashboard"))


@login_required
def pix_payment_instructions(request, sale_id):
    sale = get_object_or_404(
        CreditSale,
        id=sale_id,
        client=request.user,
        status=CreditSale.ACCEPTED,
        selected_payment_method=CreditSale.PIX,
    )

    return render(
        request,
        "accounts/pix_payment_instructions.html",
        {
            "sale": sale,
            "pix_key": settings.STORE_PIX_KEY,
            "responsible_name": settings.STORE_RESPONSIBLE_NAME,
            "is_public_sale": False,
        },
    )


def public_choose_installments(request, public_token):
    sale = get_object_or_404(
        CreditSale,
        public_token=public_token,
        status__in=[CreditSale.PENDING, CreditSale.ACCEPTED],
        payment_status__in=[CreditSale.PAYMENT_PENDING, CreditSale.PAYMENT_FAILED],
    )

    if request.method == "POST" and request.POST.get("payment_method") == CreditSale.CREDIT:
        if not request.user.is_authenticated or request.user.is_staff:
            messages.info(request, "Para seguir no crediario, faca seu cadastro com CPF e documentos.")
            next_url = reverse("claim_public_credit_sale", args=[sale.public_token])
            return redirect(f"{resolve_url('register')}?intent=credit&next={next_url}")

        return redirect("claim_public_credit_sale", public_token=sale.public_token)

    if request.method == "POST":
        form = InstallmentChoiceForm(request.POST, sale=sale)

        if form.is_valid():
            was_pending = sale.status == CreditSale.PENDING

            with transaction.atomic():
                if form.cleaned_data["first_due_date"]:
                    sale.first_due_date = form.cleaned_data["first_due_date"]
                sale.choose_payment(
                    form.cleaned_data["payment_method"],
                    form.cleaned_data["installments"],
                    form.cleaned_data["use_welcome_discount"],
                    form.cleaned_data["remainder_payment_method"],
                    form.cleaned_data.get("use_points", False),
                )

            if was_pending and sale.client_id:
                create_sale_confirmed_notifications(sale)

            if sale.selected_payment_method == CreditSale.PIX:
                return redirect("public_pix_payment_instructions", public_token=sale.public_token)

            if sale.selected_payment_method == CreditSale.CARD:
                try:
                    preference = create_credit_sale_card_preference(sale, request, public_flow=True)
                except MercadoPagoNotConfigured:
                    messages.warning(request, "Cartao ainda nao esta disponivel. Entre em contato com a loja.")
                    return redirect("public_choose_installments", public_token=sale.public_token)
                except MercadoPagoRequestError:
                    logger.exception("Erro ao iniciar pagamento com cartao")
                    messages.error(request, "Nao foi possivel abrir o pagamento com cartao agora. Tente novamente.")
                    return redirect("public_choose_installments", public_token=sale.public_token)

                sale.mercado_pago_preference_id = preference["id"]
                sale.mercado_pago_init_point = preference["init_point"]
                sale.save(update_fields=["mercado_pago_preference_id", "mercado_pago_init_point"])
                return redirect(sale.mercado_pago_init_point)
    else:
        form = InstallmentChoiceForm(sale=sale)

    return render(request, "accounts/choose_installments.html", sale_checkout_context(sale, form, "store_front"))


@login_required
def claim_public_credit_sale(request, public_token):
    if request.user.is_staff:
        return redirect("management_dashboard")

    sale = get_object_or_404(
        CreditSale,
        public_token=public_token,
        status__in=[CreditSale.PENDING, CreditSale.ACCEPTED],
        payment_status__in=[CreditSale.PAYMENT_PENDING, CreditSale.PAYMENT_FAILED],
    )
    profile = request.user.profile

    if not profile.has_cpf():
        messages.error(request, "Para seguir no crediario, complete seu cadastro com CPF.")
        return redirect("profile")

    if sale.client_id is None:
        sale.client = request.user
        sale.max_installments_allowed = request.user.profile.default_max_installments
        sale.save(update_fields=["client", "max_installments_allowed"])
    elif sale.client_id != request.user.id:
        messages.error(request, "Esta venda esta vinculada a outro cliente.")
        return redirect("dashboard")

    return redirect("choose_installments", sale_id=sale.id)


def public_pix_payment_instructions(request, public_token):
    sale = get_object_or_404(
        CreditSale,
        public_token=public_token,
        status=CreditSale.ACCEPTED,
        selected_payment_method=CreditSale.PIX,
    )

    return render(
        request,
        "accounts/pix_payment_instructions.html",
        {
            "sale": sale,
            "pix_key": settings.STORE_PIX_KEY,
            "responsible_name": settings.STORE_RESPONSIBLE_NAME,
            "is_public_sale": True,
        },
    )


def public_credit_sale_payment_success(request, public_token):
    sale = get_object_or_404(CreditSale, public_token=public_token)
    payment_id = request.GET.get("payment_id", "")

    if payment_id:
        try:
            payment = get_payment(payment_id)
        except (MercadoPagoNotConfigured, MercadoPagoRequestError):
            payment = {}

        if payment.get("status") == "approved" and payment.get("external_reference") == f"credit-sale:{sale.id}":
            sale.mark_paid(str(payment.get("id", payment_id)))

    messages.success(request, "Pagamento recebido. Aguarde a confirmacao da loja.")
    return redirect("public_choose_installments", public_token=sale.public_token)


def public_credit_sale_payment_failure(request, public_token):
    messages.error(request, "Pagamento nao concluido. Voce pode tentar novamente neste link.")
    return redirect("public_choose_installments", public_token=public_token)


def public_credit_sale_payment_pending(request, public_token):
    messages.warning(request, "Pagamento pendente. Atualizaremos a compra assim que houver confirmacao.")
    return redirect("public_choose_installments", public_token=public_token)

    return render(
        request,
        "accounts/pix_payment_instructions.html",
        {
            "sale": sale,
            "pix_key": settings.STORE_PIX_KEY,
            "responsible_name": settings.STORE_RESPONSIBLE_NAME,
        },
    )


@login_required
def credit_sale_payment_success(request):
    payment_id = request.GET.get("payment_id", "")

    if payment_id:
        try:
            payment = get_payment(payment_id)
        except (MercadoPagoNotConfigured, MercadoPagoRequestError):
            payment = {}

        external_reference = payment.get("external_reference", "")

        if payment.get("status") == "approved" and external_reference.startswith("credit-sale:"):
            try:
                sale_id = int(external_reference.split(":", 1)[1])
                sale = CreditSale.objects.get(id=sale_id, client=request.user)
            except (ValueError, CreditSale.DoesNotExist):
                sale = None

            if sale:
                sale.mark_paid(str(payment.get("id", payment_id)))

    messages.success(request, "Pagamento recebido. Aguarde a confirmacao da loja.")

    return redirect("dashboard")


@login_required
def credit_sale_payment_failure(request):
    messages.error(request, "Pagamento nao concluido. Voce pode tentar novamente em Minhas compras.")

    return redirect("dashboard")


@login_required
def credit_sale_payment_pending(request):
    messages.warning(request, "Pagamento pendente. Atualizaremos sua compra assim que houver confirmacao.")

    return redirect("dashboard")


@staff_member_required(login_url="login")
def management_dashboard(request):
    generate_due_notifications()
    pending_profiles = ClientProfile.objects.filter(registration_status=ClientProfile.PENDING).order_by("user__full_name")
    pending_sales = list(CreditSale.objects.filter(status=CreditSale.PENDING).order_by("-created_at"))
    accepted_sales = CreditSale.objects.filter(status=CreditSale.ACCEPTED).order_by("-accepted_at")[:10]
    available_products = Product.objects.filter(status=Product.AVAILABLE).order_by("-created_at")[:10]
    store_paid_count = StoreOrder.objects.filter(status=StoreOrder.PAID).count()
    store_pending_payment_count = StoreOrder.objects.filter(status=StoreOrder.PENDING_PAYMENT).count()
    payment_alerts = PaymentAlert.objects.select_related("credit_sale__client", "store_order")[:10]
    monthly_sales_summary = current_month_sales_summary()

    for sale in pending_sales:
        sale.payment_link = build_sale_payment_link(request, sale)

    return render(
        request,
        "accounts/management_dashboard.html",
        {
            "pending_profiles": pending_profiles,
            "pending_sales": pending_sales,
            "accepted_sales": accepted_sales,
            "available_products": available_products,
            "store_paid_count": store_paid_count,
            "store_pending_payment_count": store_pending_payment_count,
            "monthly_sales_summary": monthly_sales_summary,
            "payment_alerts": payment_alerts,
            "supplier_catalog_configured": bool(settings.SHOE_SUPPLIER_CATALOG_URL),
            "mercado_pago_configured": bool(settings.MERCADO_PAGO_ACCESS_TOKEN),
            "public_site_url_configured": bool(settings.PUBLIC_SITE_URL),
            "pix_key_configured": bool(settings.STORE_PIX_KEY),
            "phone_verification_required": settings.PHONE_VERIFICATION_REQUIRED,
        },
    )


@staff_member_required(login_url="login")
def linde_stats(request):
    """Numeros ao vivo para a Linde IA responder perguntas do tipo
    'quantos clientes aguardando' ou 'quantas vendas no mes'."""
    today = timezone.localdate()
    month_start = today.replace(day=1)

    pending_clients = ClientProfile.objects.filter(registration_status=ClientProfile.PENDING).count()
    approved_clients = ClientProfile.objects.filter(registration_status=ClientProfile.APPROVED).count()
    pending_sales = CreditSale.objects.filter(status=CreditSale.PENDING).count()
    accepted_sales_month = CreditSale.objects.filter(
        status=CreditSale.ACCEPTED, accepted_at__date__gte=month_start
    ).count()
    store_paid = StoreOrder.objects.filter(status=StoreOrder.PAID).count()
    store_awaiting_payment = StoreOrder.objects.filter(status=StoreOrder.PENDING_PAYMENT).count()
    visible_products = SupplierProduct.objects.filter(
        is_active=True, is_visible=True, stock_quantity__gt=0
    ).count()
    overdue_qs = Debt.objects.filter(paid=False, canceled=False, due_date__lt=today)
    overdue_count = overdue_qs.count()
    overdue_total = overdue_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    summary = current_month_sales_summary()

    return JsonResponse(
        {
            "month_label": summary["month_label"],
            "metrics": {
                "clientes_aguardando": {
                    "value": pending_clients,
                    "label": "clientes aguardando aprovacao",
                    "url": resolve_url("clients_list") + "?cadastro=pending",
                },
                "clientes_aprovados": {
                    "value": approved_clients,
                    "label": "clientes aprovados",
                    "url": resolve_url("clients_list") + "?cadastro=approved",
                },
                "vendas_crediario_pendentes": {
                    "value": pending_sales,
                    "label": "vendas no crediario aguardando",
                    "url": resolve_url("management_dashboard"),
                },
                "vendas_aceitas_mes": {
                    "value": accepted_sales_month,
                    "label": "vendas no crediario aceitas no mes",
                    "url": resolve_url("management_dashboard"),
                },
                "pedidos_pagar_fornecedor": {
                    "value": store_paid,
                    "label": "pedidos pagos para comprar no fornecedor",
                    "url": resolve_url("store_orders"),
                },
                "pedidos_aguardando_pagamento": {
                    "value": store_awaiting_payment,
                    "label": "pedidos aguardando pagamento",
                    "url": resolve_url("store_orders"),
                },
                "faturamento_mes": {
                    "value": f"R$ {summary['revenue']:.2f}".replace(".", ","),
                    "label": "faturamento do mes",
                    "url": resolve_url("profit_report"),
                },
                "itens_vendidos_mes": {
                    "value": summary["items_sold"],
                    "label": "itens vendidos no mes",
                    "url": resolve_url("profit_report"),
                },
                "debitos_vencidos": {
                    "value": overdue_count,
                    "label": "debitos vencidos",
                    "extra": f"R$ {overdue_total:.2f}".replace(".", ","),
                    "url": resolve_url("clients_list") + "?financeiro=overdue",
                },
                "produtos_na_loja": {
                    "value": visible_products,
                    "label": "produtos visiveis na loja",
                    "url": resolve_url("supplier_products"),
                },
            },
        }
    )


@staff_member_required(login_url="login")
def clients_list(request):
    profiles = ClientProfile.objects.select_related("user").order_by("user__full_name")
    query = request.GET.get("q", "").strip()
    registration_status = request.GET.get("cadastro", "").strip()
    financial_status = request.GET.get("financeiro", "").strip()

    if query:
        profiles = profiles.filter(
            Q(user__full_name__icontains=query)
            | Q(user__email__icontains=query)
            | Q(phone__icontains=query)
            | Q(cpf_last_digits__icontains=query)
        )

    if registration_status in {ClientProfile.PENDING, ClientProfile.APPROVED, ClientProfile.REJECTED}:
        profiles = profiles.filter(registration_status=registration_status)

    client_summaries = [build_client_financial_summary(profile) for profile in profiles]

    if financial_status == "overdue":
        client_summaries = [summary for summary in client_summaries if summary["overdue_total"] > 0]
    elif financial_status == "open":
        client_summaries = [summary for summary in client_summaries if summary["open_total"] > 0]
    elif financial_status == "loyal":
        client_summaries = [summary for summary in client_summaries if summary["relationship_label"] == "Cliente fiel"]

    all_profiles = ClientProfile.objects.select_related("user")
    all_summaries = [build_client_financial_summary(profile) for profile in all_profiles]

    return render(
        request,
        "accounts/clients_list.html",
        {
            "client_summaries": client_summaries,
            "query": query,
            "registration_status": registration_status,
            "financial_status": financial_status,
            "clients_total": len(all_summaries),
            "clients_approved": sum(
                summary["profile"].registration_status == ClientProfile.APPROVED for summary in all_summaries
            ),
            "clients_pending": sum(
                summary["profile"].registration_status == ClientProfile.PENDING for summary in all_summaries
            ),
            "clients_overdue": sum(summary["overdue_total"] > 0 for summary in all_summaries),
        },
    )


def run_account_purge(request):
    """Expurgo das contas com exclusao pedida ha mais de 7 dias.
    Protegido por token (cron externo gratuito chama esta URL 1x/dia)."""
    token = settings.MAINTENANCE_TOKEN
    if not token or request.GET.get("token") != token:
        return HttpResponseForbidden("Token invalido.")

    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=7)
    pendentes = get_user_model().objects.filter(
        deletion_requested_at__lt=cutoff, is_active=True
    )
    total = 0
    for user in pendentes:
        user.anonymize_personal_data()
        total += 1

    return JsonResponse({"purged": total})


@login_required
def push_subscribe(request):
    """Salva a inscricao de Web Push do aparelho do usuario."""
    if request.method != "POST":
        return JsonResponse({"error": "metodo"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
        endpoint = data["endpoint"]
        keys = data.get("keys", {})
    except (ValueError, KeyError):
        return JsonResponse({"error": "payload"}, status=400)

    from .models import PushSubscription

    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user,
            "p256dh": keys.get("p256dh", ""),
            "auth": keys.get("auth", ""),
        },
    )
    return JsonResponse({"ok": True})


@login_required
def notifications_unread_count(request):
    """Contagem de notificacoes nao lidas (usada pelo sino em tempo real)."""
    count = request.user.notifications.filter(read_at__isnull=True).count()
    return JsonResponse({"count": count})


@login_required
def notifications_list(request):
    generate_due_notifications()
    notifications = request.user.notifications.select_related("debt")[:100]

    return render(request, "accounts/notifications.html", {"notifications": notifications})


@login_required
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)

    if request.method == "POST":
        notification.mark_as_read()

    return redirect("notifications_list")


@login_required
def notifications_mark_all_read(request):
    if request.method == "POST":
        request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())

    return redirect("notifications_list")


@staff_member_required(login_url="login")
def review_client_profile(request, profile_id):
    profile = get_object_or_404(ClientProfile, id=profile_id)
    financial_summary = build_client_financial_summary(profile)
    was_approved = profile.registration_status == ClientProfile.APPROVED
    previous_credit_limit = profile.pre_approved_credit_limit

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "make_partner":
            extra = profile.extra_data or {}
            extra.update({
                "is_partner": True,
                "partner_name": "Selma",
                "partner_commission_percent": 20,
                "partner_notify_email": "Sellmaramos.3012@gmail.com",
                "sales_report_brand_keyword": "Ramose",
                "sales_report_brand_aliases": ["Ramosê", "Ramose"],
                "sales_report_title": "Vendas Ramosê",
            })
            profile.extra_data = extra
            profile.save(update_fields=["extra_data"])
            messages.success(request, "Cliente definida como parceira Ramosê (Selma).")
            return redirect("review_client_profile", profile_id=profile.id)

        if action == "remove_partner":
            extra = profile.extra_data or {}
            for key in ("is_partner", "partner_name", "partner_commission_percent", "partner_notify_email"):
                extra.pop(key, None)
            profile.extra_data = extra
            profile.save(update_fields=["extra_data"])
            messages.success(request, "Papel de parceira removido.")
            return redirect("review_client_profile", profile_id=profile.id)

        form = ClientApprovalForm(request.POST, instance=profile)

        if form.is_valid():
            profile = form.save(commit=False)

            if action == "approve":
                profile.registration_status = ClientProfile.APPROVED
                profile.approved_at = timezone.now()
                profile.approved_by = request.user
                profile.welcome_discount_expires_at = profile.welcome_discount_expires_at or add_months(timezone.localdate(), 3)
                message = "Cadastro aprovado com sucesso."
            elif action == "reject":
                profile.registration_status = ClientProfile.REJECTED
                profile.approved_at = None
                profile.approved_by = None
                message = "Cadastro rejeitado."
            else:
                messages.error(request, "Acao invalida.")
                return redirect("review_client_profile", profile_id=profile.id)

            profile.save()

            if action == "approve" and not was_approved:
                create_registration_approved_notification(profile)
            elif action == "approve" and profile.pre_approved_credit_limit > previous_credit_limit:
                create_credit_limit_increased_notification(profile, previous_credit_limit)

            messages.success(request, message)

            return redirect("management_dashboard")
    else:
        form = ClientApprovalForm(instance=profile)

    # Vendas pendentes do cliente, com link pra ele finalizar (e enviar por WhatsApp)
    phone_digits = re.sub(r"\D", "", profile.phone or "")
    if phone_digits and not phone_digits.startswith("55"):
        phone_digits = f"55{phone_digits}"

    pending_sales = list(
        profile.user.credit_sales.filter(status=CreditSale.PENDING).order_by("-created_at")
    )
    for sale in pending_sales:
        sale.finalize_link = build_sale_payment_link(request, sale)
        if phone_digits:
            msg = (
                f"Ola! Para finalizar sua compra na Lindice, acesse: {sale.finalize_link}"
            )
            sale.whatsapp_link = f"https://wa.me/{phone_digits}?text={quote(msg)}"
        else:
            sale.whatsapp_link = ""

    return render(
        request,
        "accounts/review_client_profile.html",
        {
            "debts": financial_summary["debts"],
            "financial_summary": financial_summary,
            "pending_sales": pending_sales,
            "form": form,
            "profile": profile,
            "partner_config": partner_profile_config(profile.user),
        },
    )


@staff_member_required(login_url="login")
def create_manual_debt(request):
    initial = {}
    client_id = request.GET.get("cliente")
    return_profile_id = request.GET.get("voltar_cadastro") or request.POST.get("return_profile_id")

    if client_id:
        initial["client"] = client_id

    if request.method == "POST":
        form = ManualDebtForm(request.POST)

        if form.is_valid():
            if form.cleaned_data["create_payment_link"]:
                sale = CreditSale.objects.create(
                    client=form.cleaned_data["client"],
                    description=form.cleaned_data["description"],
                    total_amount=form.cleaned_data["amount"],
                    first_due_date=form.cleaned_data["due_date"],
                    max_installments_allowed=form.cleaned_data["client"].profile.default_max_installments,
                    created_by=request.user,
                )
                create_sale_available_notification(sale)
                payment_link = build_sale_payment_link(request, sale)
                messages.success(request, "Link de pagamento gerado e cliente notificado com sucesso.")

                return render(
                    request,
                    "accounts/payment_link_created.html",
                    {
                        "payment_link": payment_link,
                        "whatsapp_link": build_finalize_whatsapp_link(sale, payment_link),
                        "return_profile_id": return_profile_id,
                        "sale": sale,
                    },
                )

            debt = form.save()
            create_manual_debt_notification(debt)
            messages.success(request, "Debito lancado e cliente notificado com sucesso.")

            if return_profile_id:
                return redirect("review_client_profile", profile_id=return_profile_id)

            return redirect("management_dashboard")
    else:
        form = ManualDebtForm(initial=initial)

    return render(request, "accounts/create_manual_debt.html", {"form": form, "return_profile_id": return_profile_id})


@staff_member_required(login_url="login")
def update_debt_payment(request, debt_id):
    debt = get_object_or_404(Debt, id=debt_id)

    if request.method != "POST":
        return redirect("review_client_profile", profile_id=debt.client.profile.id)

    action = request.POST.get("action")

    if action == "mark_paid":
        if debt.paid:
            messages.info(request, "Este debito ja estava marcado como pago.")
        else:
            debt.mark_paid()
            messages.success(request, "Debito marcado como pago manualmente.")
    elif action == "mark_unpaid":
        if not debt.paid:
            messages.info(request, "Este debito ja estava em aberto.")
        else:
            debt.mark_unpaid()
            messages.success(request, "Baixa manual removida e debito reaberto.")
    elif action == "cancel":
        reason = request.POST.get("cancel_reason", "").strip()
        if not reason:
            messages.error(request, "Escolha uma justificativa para cancelar o debito.")
        else:
            debt.cancel(reason)
            messages.success(request, f"Debito cancelado ({reason}). Nao conta mais para o cliente.")
    elif action == "uncancel":
        debt.canceled = False
        debt.cancel_reason = ""
        debt.canceled_at = None
        debt.save(update_fields=["canceled", "cancel_reason", "canceled_at"])
        messages.success(request, "Cancelamento desfeito. O debito voltou a contar.")
    elif action == "delete":
        debt.delete()
        messages.success(request, "Debito excluido definitivamente.")
    else:
        messages.error(request, "Acao invalida para este debito.")

    next_url = safe_next_url(request, request.POST.get("next"))

    if next_url:
        return redirect(next_url)

    profile_id = request.POST.get("return_profile_id") or getattr(getattr(debt.client, "profile", None), "id", None)

    if profile_id:
        return redirect("review_client_profile", profile_id=profile_id)

    return redirect("clients_list")


@staff_member_required(login_url="login")
def create_credit_sale(request):
    available_products = list(Product.objects.filter(status=Product.AVAILABLE).select_related("supplier").order_by("product_code"))
    product_catalog = [
        {
            "id": product.id,
            "name": product.name,
            "brand": product.brand or "",
            "supplier_id": product.supplier_id or "",
            "sale_price": f"{product.sale_price:.2f}",
            "shoe_size": product.shoe_size or "",
        }
        for product in available_products
    ]

    if request.method == "POST":
        form = CreditSaleForm(request.POST)
        product_formset = CreditSaleProductFormSet(request.POST, request.FILES)

        if form.is_valid() and product_formset.is_valid():
            sale = form.save(commit=False)
            sale.created_by = request.user
            sale.first_due_date = timezone.localdate() + timedelta(days=30)
            sale.max_installments_allowed = sale.client.profile.default_max_installments if sale.client_id else 10
            if not sale.description:
                first_item = next(
                    (
                        item for item in product_formset.cleaned_data
                        if item and not item.get("DELETE") and (item.get("name") or item.get("product"))
                    ),
                    None,
                )
                product_name = ""
                if first_item:
                    product_name = first_item.get("name") or getattr(first_item.get("product"), "name", "")
                sale.description = product_name or f"Venda para {sale.customer_name()}"
            sale.save()
            product_formset.instance = sale
            product_formset.save()

            # Se os itens tiverem valor, o total da venda passa a ser a soma deles.
            itens_total = sum(
                (item.unit_price for item in sale.products.all() if item.unit_price),
                Decimal("0.00"),
            )
            if itens_total > 0 and itens_total != sale.total_amount:
                sale.total_amount = itens_total
                sale.save(update_fields=["total_amount"])

            create_sale_available_notification(sale)
            messages.success(request, "Venda lancada. Envie o link para o cliente finalizar.")

            payment_link = build_sale_payment_link(request, sale)
            return render(
                request,
                "accounts/payment_link_created.html",
                {
                    "payment_link": payment_link,
                    "whatsapp_link": build_finalize_whatsapp_link(sale, payment_link),
                    "sale": sale,
                    "return_profile_id": getattr(getattr(sale.client, "profile", None), "id", None),
                },
            )
    else:
        form = CreditSaleForm()
        product_formset = CreditSaleProductFormSet()

    return render(
        request,
        "accounts/create_credit_sale.html",
        {"form": form, "product_formset": product_formset, "product_catalog": product_catalog},
    )


@staff_member_required(login_url="login")
def product_list(request):
    supplier_filter = request.GET.get("fornecedor", "").strip()
    products = Product.objects.select_related("supplier").order_by("-created_at")

    if supplier_filter == "none":
        products = products.filter(supplier__isnull=True)
    elif supplier_filter:
        products = products.filter(supplier_id=supplier_filter)

    suppliers = Supplier.objects.filter(is_active=True)

    # Relatorio por fornecedor: vendidos, estoque, faturamento e lucro.
    def supplier_metrics(qs):
        sold = [p for p in qs if p.status == Product.SOLD]
        return {
            "total": len(qs),
            "vendidos": len(sold),
            "estoque": sum(1 for p in qs if p.status == Product.AVAILABLE),
            "faturamento": sum((p.sale_price for p in sold), Decimal("0.00")),
            "lucro": sum((p.profit() for p in sold), Decimal("0.00")),
        }

    all_products = list(Product.objects.select_related("supplier").prefetch_related("costs"))
    supplier_report = []
    for supplier in suppliers:
        group = [p for p in all_products if p.supplier_id == supplier.id]
        if group:
            supplier_report.append({"name": supplier.name, **supplier_metrics(group)})
    no_supplier = [p for p in all_products if p.supplier_id is None]
    if no_supplier:
        supplier_report.append({"name": "Sem fornecedor", **supplier_metrics(no_supplier)})

    return render(
        request,
        "accounts/product_list.html",
        {
            "products": products,
            "suppliers": suppliers,
            "supplier_filter": supplier_filter,
            "supplier_report": supplier_report,
        },
    )


def salvar_fotos_em_lote(request, produto, campo="fotos_novas"):
    """Grava de uma vez todas as fotos que vieram no campo de varios arquivos.

    Devolve (quantas entraram, lista de recusas). Uma foto ruim no meio do lote
    nao derruba as outras: ela e recusada com o motivo e o resto entra.
    """
    arquivos = request.FILES.getlist(campo)

    if not arquivos:
        return 0, []

    recusas = []
    aceitas = []

    for arquivo in arquivos[:MAX_PRODUCT_PHOTOS_PER_UPLOAD]:
        motivo = validate_product_photo(arquivo)

        if motivo:
            recusas.append(f"{arquivo.name} {motivo}")
            continue

        aceitas.append(arquivo)

    if len(arquivos) > MAX_PRODUCT_PHOTOS_PER_UPLOAD:
        sobra = len(arquivos) - MAX_PRODUCT_PHOTOS_PER_UPLOAD
        recusas.append(f"{sobra} foto(s) ficaram de fora: o limite e {MAX_PRODUCT_PHOTOS_PER_UPLOAD} por vez")

    if not aceitas:
        return 0, recusas

    proxima = (produto.photos.aggregate(maior=Max("position"))["maior"] or 0) + 1
    entraram = 0
    subiram = 0

    for arquivo in aceitas:
        try:
            SupplierProductPhoto.objects.create(product=produto, image=arquivo, position=proxima)
        except Exception as erro:
            logger.exception("Falha ao gravar foto do produto %s", produto.id)
            recusas.append(f"{arquivo.name} nao subiu ({type(erro).__name__})")
            continue

        proxima += 1
        entraram += 1
        subiram += arquivo.size

    somar_arquivos(subiram, entraram)

    return entraram, recusas


def avisar_sobre_fotos(request, entraram, recusas):
    """Conta para a loja o que entrou e o que ficou de fora."""
    if entraram == 1:
        messages.success(request, "1 foto adicionada.")
    elif entraram > 1:
        messages.success(request, f"{entraram} fotos adicionadas.")

    for recusa in recusas:
        messages.warning(request, recusa)


@staff_member_required(login_url="login")
def edit_supplier_product(request, product_id):
    product = get_object_or_404(SupplierProduct, id=product_id)

    if request.method == "POST":
        form = SupplierProductEditForm(request.POST, request.FILES, instance=product)
        fotos = SupplierProductPhotoFormSet(request.POST, request.FILES, instance=product, prefix="fotos")
        cores = SupplierProductVariantFormSet(request.POST, request.FILES, instance=product, prefix="cores")

        if form.is_valid() and fotos.is_valid() and cores.is_valid():
            with transaction.atomic():
                form.save()
                fotos.save()
                cores.save()
                entraram, recusas = salvar_fotos_em_lote(request, product)

            messages.success(request, "Produto atualizado com sucesso.")
            avisar_sobre_fotos(request, entraram, recusas)

            return redirect("edit_supplier_product", product_id=product.id)

        messages.error(request, "Confira os campos destacados abaixo.")
    else:
        form = SupplierProductEditForm(instance=product)
        fotos = SupplierProductPhotoFormSet(instance=product, prefix="fotos")
        cores = SupplierProductVariantFormSet(instance=product, prefix="cores")

    return render(
        request,
        "accounts/edit_supplier_product.html",
        {
            "form": form,
            "fotos": fotos,
            "cores": cores,
            "product": product,
            # Sugestao de preco pelas regras da loja, so como referencia.
            "preco_sugerido": retail_price_from_wholesale(product.wholesale_price) if product.wholesale_price else None,
            "preco_crediario": credit_price_from_retail(product.suggested_sale_price),
        },
    )


@staff_member_required(login_url="login")
def fotos_publicas(request):
    """Leva as fotos que ja existem para o bucket publico.

    Serve uma vez so, depois que o bucket publico e criado no Supabase. Pode
    rodar de novo sem medo: o que ja foi copiado nao vai duas vezes.
    """
    resultado = None

    if request.method == "POST":
        resultado = copiar_vitrine()

        if not resultado["pronto"]:
            messages.error(request, resultado["recado"])
        elif resultado["copiadas"]:
            messages.success(
                request,
                f"{resultado['copiadas']} arquivo(s) copiados. "
                f"{resultado['puladas']} ja estavam la.",
            )
        else:
            messages.success(request, "Nada a copiar: tudo ja esta no bucket publico.")

        for falha in resultado["falhas"]:
            messages.warning(request, falha)

    return render(
        request,
        "accounts/fotos_publicas.html",
        {
            "resultado": resultado,
            "ligado": getattr(settings, "USE_SUPABASE_PUBLIC", False),
            "bucket_publico": getattr(settings, "SUPABASE_PUBLIC_BUCKET", ""),
            "bucket_privado": getattr(settings, "SUPABASE_STORAGE_BUCKET", ""),
            "endereco_publico": getattr(settings, "SUPABASE_PUBLIC_DOMAIN", ""),
            "prefixos": PREFIXOS_DA_VITRINE,
        },
    )


@staff_member_required(login_url="login")
def espaco_usado(request):
    """Mostra quanto da cota do Supabase ja foi gasto e deixa medir de novo.

    Existe porque o plano gratuito nao avisa: quando a cota estoura, o upload
    simplesmente falha. Aqui da para ver antes e decidir o que apagar.
    """
    if request.method == "POST":
        uso = atualizar_medicao()

        if uso.erro:
            messages.error(request, uso.erro)
        else:
            messages.success(request, "Medicao atualizada.")

        return redirect("espaco_usado")

    return render(request, "accounts/espaco_usado.html", resumo_do_espaco())


@staff_member_required(login_url="login")
def storage_check(request):
    """Testa o armazenamento de arquivos e diz exatamente o que falhou.

    Escreve um arquivo minusculo, le de volta e apaga. Sem isso, um erro de
    permissao aparece so no meio de uma importacao, sem dizer a causa.
    """
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    etapas = []
    caminho = ""

    def anota(passo, ok, detalhe=""):
        etapas.append({"passo": passo, "ok": ok, "detalhe": detalhe})

    usando_s3 = getattr(settings, "USE_SUPABASE_STORAGE", False)
    anota(
        "Backend em uso",
        True,
        "Supabase Storage (S3)" if usando_s3 else "Disco do servidor (as variaveis do Supabase nao estao todas preenchidas)",
    )

    if usando_s3:
        anota("Bucket", True, settings.SUPABASE_STORAGE_BUCKET)
        anota("Endpoint", True, settings.SUPABASE_STORAGE_ENDPOINT_URL)
        anota("Regiao", True, settings.SUPABASE_STORAGE_REGION)
        chave = settings.SUPABASE_S3_ACCESS_KEY_ID
        anota("Access key", True, f"{chave[:4]}...{chave[-4:]} ({len(chave)} caracteres)" if chave else "vazia")

    try:
        caminho = default_storage.save("teste-conexao/ping.txt", ContentFile(b"ping"))
        anota("Gravar arquivo", True, caminho)
    except Exception as erro:
        anota("Gravar arquivo", False, f"{type(erro).__name__}: {erro}")

        return render(request, "accounts/storage_check.html", {"etapas": etapas})

    try:
        with default_storage.open(caminho) as arquivo:
            conteudo = arquivo.read()
        anota("Ler de volta", conteudo == b"ping", f"{len(conteudo)} bytes")
    except Exception as erro:
        anota("Ler de volta", False, f"{type(erro).__name__}: {erro}")

    try:
        anota("Gerar link", True, default_storage.url(caminho)[:90] + "...")
    except Exception as erro:
        anota("Gerar link", False, f"{type(erro).__name__}: {erro}")

    try:
        default_storage.delete(caminho)
        anota("Apagar arquivo", True, "removido")
    except Exception as erro:
        anota("Apagar arquivo", False, f"{type(erro).__name__}: {erro}")

    return render(request, "accounts/storage_check.html", {"etapas": etapas})


@staff_member_required(login_url="login")
def new_supplier_product(request):
    """Cria um produto do zero e leva direto para a ficha completa."""
    if request.method == "POST":
        form = NewSupplierProductForm(request.POST, request.FILES)

        if form.is_valid():
            produto = form.save()
            entraram, recusas = salvar_fotos_em_lote(request, produto)
            messages.success(
                request,
                f"{produto.name} criado. Agora confira as cores e a descricao, "
                "e marque 'Mostrar na loja' quando estiver pronto.",
            )
            avisar_sobre_fotos(request, entraram, recusas)

            return redirect("edit_supplier_product", product_id=produto.id)

        messages.error(request, "Confira os campos destacados.")
    else:
        form = NewSupplierProductForm()

    return render(request, "accounts/new_supplier_product.html", {"form": form})


@staff_member_required(login_url="login")
def import_wearzone_catalog(request):
    """Cadastra (ou atualiza) os smartwatches e fones com um clique.

    Existe porque o plano da Render nao da terminal: sem isso, nao haveria como
    rodar o comando em producao.
    """
    if request.method != "POST":
        return redirect("supplier_products")

    saida = StringIO()
    refazer = request.POST.get("refazer") == "sim"

    try:
        if refazer:
            call_command("importar_wearzone", "--refazer", stdout=saida, stderr=saida)
        else:
            call_command("importar_wearzone", stdout=saida, stderr=saida)
    except Exception as erro:
        logger.exception("Falha ao importar o catalogo Wearzone")
        # Mostrar o motivo de verdade: sem isso a loja fica adivinhando o que houve.
        messages.error(request, f"A importacao parou: {type(erro).__name__} - {erro}")

        return redirect("supplier_products")

    relatorio = saida.getvalue()
    resumo = [linha for linha in relatorio.splitlines() if "cadastrados" in linha]
    messages.success(request, resumo[-1] if resumo else "Catalogo importado.")

    for linha in relatorio.splitlines():
        if "FALHOU" in linha or linha.strip().startswith("- "):
            messages.warning(request, linha.strip())

    return redirect(f"{reverse('supplier_products')}?origem={SupplierProduct.SOURCE_WEARZONE}")


@staff_member_required(login_url="login")
def staff_reels(request):
    """Lista os reels e permite cadastrar um novo."""
    if request.method == "POST":
        form = StoreReelForm(request.POST, request.FILES)

        if form.is_valid():
            form.save()
            messages.success(request, "Video publicado na loja.")

            return redirect("staff_reels")

        messages.error(request, "Confira os campos destacados.")
    else:
        form = StoreReelForm()

    return render(
        request,
        "accounts/staff_reels.html",
        {
            "form": form,
            "reels": StoreReel.objects.select_related("product"),
            "produtos": SupplierProduct.objects.filter(is_active=True).order_by("name"),
        },
    )


@staff_member_required(login_url="login")
def ligar_reel_produto(request, reel_id):
    """Liga (ou desliga) o video a um produto, direto pela lista."""
    reel = get_object_or_404(StoreReel, id=reel_id)

    if request.method != "POST":
        return redirect("staff_reels")

    escolhido = (request.POST.get("product") or "").strip()

    if escolhido:
        produto = SupplierProduct.objects.filter(id=escolhido, is_active=True).first()

        if not produto:
            messages.error(request, "Produto nao encontrado.")

            return redirect("staff_reels")

        reel.product = produto
        reel.save(update_fields=["product"])
        messages.success(request, f"Video ligado a {produto.name}.")
    else:
        reel.product = None
        reel.save(update_fields=["product"])
        messages.success(request, "Video desligado do produto.")

    return redirect("staff_reels")


@staff_member_required(login_url="login")
def add_reels_em_lote(request):
    """Cadastra varios videos do YouTube de uma vez, um link por linha."""
    if request.method != "POST":
        return redirect("staff_reels")

    linhas = [linha.strip() for linha in (request.POST.get("links") or "").splitlines() if linha.strip()]

    if not linhas:
        messages.error(request, "Cole ao menos um link.")

        return redirect("staff_reels")

    posicao = StoreReel.objects.count()
    criados = repetidos = recusados = 0

    for linha in linhas:
        codigo = StoreReel(video_url=linha).youtube_id()

        if not codigo:
            recusados += 1
            messages.warning(request, f"Nao reconheci como YouTube: {linha[:60]}")
            continue

        if StoreReel.objects.filter(video_url__contains=codigo).exists():
            repetidos += 1
            continue

        StoreReel.objects.create(video_url=linha, position=posicao, is_visible=True)
        posicao += 1
        criados += 1

    partes = [f"{criados} video(s) publicado(s)"]

    if repetidos:
        partes.append(f"{repetidos} ja estavam na loja")

    if recusados:
        partes.append(f"{recusados} link(s) nao reconhecido(s)")

    messages.success(request, ", ".join(partes) + ".")

    return redirect("staff_reels")


@staff_member_required(login_url="login")
def edit_reel(request, reel_id):
    reel = get_object_or_404(StoreReel, id=reel_id)

    if request.method == "POST":
        if request.POST.get("acao") == "excluir":
            titulo = reel.display_title()
            reel.delete()
            messages.success(request, f"Video removido: {titulo}.")

            # Excluir a partir da vitrine devolve para a vitrine.
            volta = safe_next_url(request, request.POST.get("voltar"))

            return redirect(volta or "staff_reels")

        form = StoreReelForm(request.POST, request.FILES, instance=reel)

        if form.is_valid():
            form.save()
            messages.success(request, "Video atualizado.")

            return redirect("staff_reels")

        messages.error(request, "Confira os campos destacados.")
    else:
        form = StoreReelForm(instance=reel)

    return render(
        request,
        "accounts/staff_reels.html",
        {
            "form": form,
            "reel": reel,
            "reels": StoreReel.objects.select_related("product"),
            "produtos": SupplierProduct.objects.filter(is_active=True).order_by("name"),
        },
    )


@staff_member_required(login_url="login")
def download_reel(request, reel_id):
    """Baixa o video do reel. So a loja enxerga esse link."""
    reel = get_object_or_404(StoreReel, id=reel_id)

    if not reel.video:
        raise Http404("Video nao encontrado.")

    nome = Path(reel.video.name).name
    resposta = FileResponse(reel.video.open("rb"), as_attachment=True, filename=nome)

    return resposta


@staff_member_required(login_url="login")
def suppliers_list(request):
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Fornecedor cadastrado com sucesso.")
            return redirect("suppliers_list")
    else:
        form = SupplierForm()

    suppliers = Supplier.objects.all()
    return render(
        request,
        "accounts/suppliers_list.html",
        {
            "suppliers": suppliers,
            "form": form,
            "catalog_url_configured": bool(settings.SHOE_SUPPLIER_CATALOG_URL),
            "supplier_dropshipping_url": settings.SHOE_SUPPLIER_DROPSHIPPING_URL,
            "catalog_sources": [
                {"instance": source, "form": SupplierCatalogSourceForm(instance=source)}
                for source in SupplierCatalogSource.objects.all()
            ],
            "source_choices": SupplierProduct.SOURCE_CHOICES,
        },
    )


@staff_member_required(login_url="login")
def supplier_detail(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id)

    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, "Fornecedor atualizado.")
            return redirect("supplier_detail", supplier_id=supplier.id)
    else:
        form = SupplierForm(instance=supplier)

    products = supplier.products.order_by("-created_at")
    return render(
        request,
        "accounts/supplier_detail.html",
        {"supplier": supplier, "form": form, "products": products},
    )


@staff_member_required(login_url="login")
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method != "POST":
        return redirect("product_detail", product_id=product.id)

    product_label = str(product)

    if product.sale_items.exists():
        messages.error(request, f"{product_label} ja esta vinculado a uma venda. Marque como com problema em vez de excluir.")
        return redirect("product_detail", product_id=product.id)

    product.delete()
    messages.success(request, f"{product_label} foi excluido.")

    return redirect("product_list")


@staff_member_required(login_url="login")
def supplier_products(request):
    ensure_supplier_catalog_sources()
    products = SupplierProduct.objects.order_by("-last_seen_at", "name")
    query = request.GET.get("q", "").strip()
    visibility = request.GET.get("visibilidade", "")
    source_filter = request.GET.get("fonte", "").strip()

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(supplier_code__icontains=query)
            | Q(category__icontains=query)
            | Q(brand__icontains=query)
            | Q(sizes__icontains=query)
        )

    if visibility == "visible":
        products = products.filter(is_visible=True)
    elif visibility == "hidden":
        products = products.filter(is_visible=False)
    elif visibility == "stock":
        products = products.filter(is_active=True, stock_quantity__gt=0)
    elif visibility == "inactive":
        products = products.filter(is_active=False)

    if source_filter:
        products = products.filter(source=source_filter)

    if request.method == "POST":
        edited_ids = request.POST.getlist("product_ids")
        edited_products = SupplierProduct.objects.filter(id__in=edited_ids)
        updated = 0

        for product in edited_products:
            price_value = request.POST.get(f"price_{product.id}", "").strip().replace(",", ".")

            if price_value:
                try:
                    product.suggested_sale_price = Decimal(price_value)
                except InvalidOperation:
                    messages.error(request, f"Preco invalido para {product.name}.")

                    return redirect("supplier_products")

            if product.suggested_sale_price < 0:
                messages.error(request, f"Preco invalido para {product.name}.")

                return redirect("supplier_products")

            if product.is_visible and product.suggested_sale_price < product.dropshipping_cost:
                messages.error(request, f"O preco de {product.name} esta menor que o custo dropshipping.")

                return redirect("supplier_products")

            product.save(update_fields=["suggested_sale_price", "updated_at"])
            updated += 1

        messages.success(request, f"Loja atualizada: {updated} produtos revisados.")

        return redirect("supplier_products")

    paginator = Paginator(products, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "accounts/supplier_products.html",
        {
            "products": page_obj,
            "catalog_url_configured": bool(settings.SHOE_SUPPLIER_CATALOG_URL),
            "supplier_dropshipping_url": settings.SHOE_SUPPLIER_DROPSHIPPING_URL,
            "catalog_sources": [
                {
                    "instance": source,
                    "form": SupplierCatalogSourceForm(instance=source),
                }
                for source in SupplierCatalogSource.objects.all()
            ],
            "query": query,
            "visibility": visibility,
            "source_filter": source_filter,
            "source_choices": SupplierProduct.SOURCE_CHOICES,
            "total_products": SupplierProduct.objects.count(),
            "visible_products": SupplierProduct.objects.filter(is_visible=True).count(),
            "stock_products": SupplierProduct.objects.filter(is_active=True, stock_quantity__gt=0).count(),
        },
    )


@staff_member_required(login_url="login")
def update_supplier_catalog_source(request, source_key):
    ensure_supplier_catalog_sources()

    if request.method != "POST":
        return redirect("supplier_products")

    source = get_object_or_404(SupplierCatalogSource, source=source_key)
    form = SupplierCatalogSourceForm(request.POST, instance=source)

    if not form.is_valid():
        messages.error(request, f"Revise os dados de {source.display_name}.")
        return redirect("supplier_products")

    form.save()
    messages.success(request, f"{source.display_name} foi atualizado.")
    return redirect("supplier_products")


@staff_member_required(login_url="login")
def update_supplier_product_status(request, product_id):
    if request.method != "POST":
        return redirect("supplier_products")

    product = get_object_or_404(SupplierProduct, id=product_id)
    action = request.POST.get("action", "").strip()
    note = request.POST.get("status_note", "").strip()

    if action in {"hide", "deactivate"} and not note:
        messages.error(request, f"Informe uma observacao para {product.name} antes de ocultar ou inativar.")
        return redirect("supplier_products")

    if action == "hide":
        product.is_visible = False
        product.status_note = note
        product.save(update_fields=["is_visible", "status_note", "updated_at"])
        messages.success(request, f"{product.name} foi ocultado da loja.")
    elif action == "show":
        if product.suggested_sale_price < product.dropshipping_cost:
            messages.error(request, f"O preco de {product.name} esta menor que o custo dropshipping.")
            return redirect("supplier_products")
        product.is_visible = True
        product.save(update_fields=["is_visible", "updated_at"])
        messages.success(request, f"{product.name} voltou a aparecer na loja.")
    elif action == "deactivate":
        product.is_active = False
        product.is_visible = False
        product.status_note = note
        product.save(update_fields=["is_active", "is_visible", "status_note", "updated_at"])
        messages.success(request, f"{product.name} foi inativado.")
    elif action == "reactivate":
        product.is_active = True
        product.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"{product.name} foi reativado.")
    else:
        messages.error(request, "Acao invalida para o produto do fornecedor.")

    return redirect("supplier_products")


@staff_member_required(login_url="login")
def delete_supplier_product(request, product_id):
    if request.method != "POST":
        return redirect("supplier_products")

    product = get_object_or_404(SupplierProduct, id=product_id)
    product_label = f"{product.supplier_code} - {product.name}"
    # Excluindo pelo cartao da loja, volta para a loja; pelo painel, volta ao painel.
    destino = safe_next_url(request, request.POST.get("voltar")) or "supplier_products"

    try:
        product.delete()
    except ProtectedError:
        messages.error(request, f"{product_label} ja tem pedido vinculado. Inative ou oculte para manter o historico.")
        return redirect(destino)

    messages.success(request, f"{product_label} foi excluido do catalogo.")

    return redirect(destino)


@staff_member_required(login_url="login")
def import_supplier_products(request):
    if request.method != "POST":
        return redirect_to_supplier_products()

    ensure_supplier_catalog_sources()
    uploaded_catalog = request.FILES.get("catalog_file")
    source_key = request.POST.get("source", SupplierProduct.SOURCE_REVENDA_CALCADOS).strip() or SupplierProduct.SOURCE_REVENDA_CALCADOS
    source_config = SupplierCatalogSource.objects.filter(source=source_key).first()
    catalog_url = ""
    catalog_format = getattr(settings, "SHOE_SUPPLIER_CATALOG_FORMAT", SupplierCatalogSource.FORMAT_CSV)

    if source_config:
        catalog_url = (source_config.catalog_url or "").strip()
        catalog_format = source_config.catalog_format or catalog_format

    if source_key == SupplierProduct.SOURCE_REVENDA_CALCADOS and not catalog_url:
        catalog_url = settings.SHOE_SUPPLIER_CATALOG_URL
        catalog_format = settings.SHOE_SUPPLIER_CATALOG_FORMAT

    if not uploaded_catalog and not catalog_url:
        messages.error(request, "Envie um CSV/XML ou salve uma URL de catalogo antes de importar.")

        return redirect_to_supplier_products()

    try:
        if uploaded_catalog:
            raw_content = uploaded_catalog.read()
            result = import_supplier_catalog_content(
                decode_catalog_content(raw_content),
                "xml" if uploaded_catalog.name.lower().endswith(".xml") else "csv",
                source=source_key,
            )
        else:
            result = import_supplier_catalog(
                catalog_url,
                catalog_format,
                source=source_key,
            )
    except Exception as exc:
        logger.exception("Erro ao importar catalogo do fornecedor")
        messages.error(request, f"Nao foi possivel importar o catalogo: {exc}")

        return redirect_to_supplier_products()

    messages.success(
        request,
        f"Catalogo atualizado: {result['created']} novos, {result['updated']} atualizados, {result['total']} lidos.",
    )

    return redirect_to_supplier_products()


@staff_member_required(login_url="login")
def store_orders(request):
    orders = StoreOrder.objects.order_by("-created_at")
    status = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()

    if status:
        orders = orders.filter(status=status)

    if query:
        orders = orders.filter(
            Q(order_code__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(customer_email__icontains=query)
            | Q(customer_phone__icontains=query)
            | Q(product_name__icontains=query)
        )

    return render(
        request,
        "accounts/store_orders.html",
        {
            "orders": orders,
            "status": status,
            "query": query,
            "status_choices": StoreOrder.STATUS_CHOICES,
            "pending_supplier_count": StoreOrder.objects.filter(status=StoreOrder.PAID).count(),
            "pending_payment_count": StoreOrder.objects.filter(status=StoreOrder.PENDING_PAYMENT).count(),
            "shipped_count": StoreOrder.objects.filter(status=StoreOrder.SHIPPED).count(),
        },
    )


@staff_member_required(login_url="login")
def store_order_admin(request, order_code):
    order = get_object_or_404(StoreOrder, order_code=order_code)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "mark_supplier_ordered":
            order.status = StoreOrder.SUPPLIER_ORDERED
            order.supplier_ordered_at = timezone.now()
            order.supplier_order_reference = request.POST.get("supplier_order_reference", "").strip()
            order.save(update_fields=["status", "supplier_ordered_at", "supplier_order_reference", "updated_at"])
            messages.success(request, "Pedido marcado como feito no fornecedor.")
        elif action == "mark_shipped":
            order.status = StoreOrder.SHIPPED
            order.tracking_code = request.POST.get("tracking_code", "").strip()
            order.shipped_at = timezone.now()
            order.save(update_fields=["status", "tracking_code", "shipped_at", "updated_at"])
            messages.success(request, "Pedido marcado como enviado.")
        elif action == "mark_paid":
            manual_method = request.POST.get("payment_method", "").strip()
            order.mark_paid(payment_method=manual_method if manual_method in {"pix", "card"} else "")
            messages.success(request, "Pedido marcado como pago manualmente.")
        elif action == "cancel":
            order.status = StoreOrder.CANCELED
            order.save(update_fields=["status", "updated_at"])
            messages.success(request, "Pedido cancelado.")

        return redirect("store_order_admin", order_code=order.order_code)

    return render(request, "accounts/store_order_admin.html", {"order": order})


@staff_member_required(login_url="login")
def create_product(request):
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                product = form.save()
            except Exception:
                logger.exception("Erro ao cadastrar produto")
                messages.error(request, "Nao foi possivel salvar o produto agora. Confira a foto enviada e tente novamente.")

                return render(request, "accounts/create_product.html", {"form": form}, status=500)

            messages.success(request, f"Produto {product.product_code} cadastrado com sucesso.")

            return redirect("product_detail", product_id=product.id)
    else:
        initial = {}
        supplier_id = request.GET.get("fornecedor")
        if supplier_id:
            initial["supplier"] = supplier_id
        form = ProductForm(initial=initial)

    return render(request, "accounts/create_product.html", {"form": form})


@staff_member_required(login_url="login")
def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    costs = product.costs.order_by("-created_at")

    return render(request, "accounts/product_detail.html", {"product": product, "costs": costs})


@staff_member_required(login_url="login")
def add_product_cost(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method == "POST":
        form = ProductCostForm(request.POST)

        if form.is_valid():
            cost = form.save(commit=False)
            cost.product = product
            cost.save()
            messages.success(request, "Custo extra lancado com sucesso.")

            return redirect("product_detail", product_id=product.id)
    else:
        form = ProductCostForm()

    return render(request, "accounts/add_product_cost.html", {"form": form, "product": product})


@staff_member_required(login_url="login")
def profit_report(request):
    products = Product.objects.order_by("-created_at")
    total_purchase = products.aggregate(total=Sum("purchase_price"))["total"] or 0
    total_sale = products.aggregate(total=Sum("sale_price"))["total"] or 0
    total_extra_costs = ProductCost.objects.aggregate(total=Sum("amount"))["total"] or 0
    gross_profit = total_sale - total_purchase - total_extra_costs
    sold_products = products.filter(status=Product.SOLD).count()
    available_products = products.filter(status=Product.AVAILABLE).count()
    start_date = parse_date(request.GET.get("inicio", ""))
    end_date = parse_date(request.GET.get("fim", ""))
    real_products = Product.objects.filter(status=Product.SOLD, sale_items__sale__status=CreditSale.ACCEPTED).distinct()

    if start_date:
        real_products = real_products.filter(sale_items__sale__accepted_at__date__gte=start_date)

    if end_date:
        real_products = real_products.filter(sale_items__sale__accepted_at__date__lte=end_date)

    real_purchase = sum(product.purchase_price for product in real_products)
    real_sale = sum(product.sale_price for product in real_products)
    real_extra_costs = sum(product.extra_cost_total() for product in real_products)
    real_profit = real_sale - real_purchase - real_extra_costs

    def margin_percent(profit, sale):
        sale = Decimal(sale or 0)
        if sale <= 0:
            return None
        return (Decimal(profit or 0) / sale * Decimal("100")).quantize(Decimal("0.1"))

    gross_margin = margin_percent(gross_profit, total_sale)
    real_margin = margin_percent(real_profit, real_sale)

    return render(
        request,
        "accounts/profit_report.html",
        {
            "products": products,
            "total_purchase": total_purchase,
            "total_sale": total_sale,
            "total_extra_costs": total_extra_costs,
            "gross_profit": gross_profit,
            "gross_margin": gross_margin,
            "sold_products": sold_products,
            "available_products": available_products,
            "start_date": start_date,
            "end_date": end_date,
            "real_products": real_products,
            "real_purchase": real_purchase,
            "real_sale": real_sale,
            "real_extra_costs": real_extra_costs,
            "real_profit": real_profit,
            "real_margin": real_margin,
        },
    )
