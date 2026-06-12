import calendar
from django.conf import settings
from datetime import timedelta
import json
import logging
from decimal import Decimal, InvalidOperation
import unicodedata
import uuid

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseForbidden, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .forms import CHECKOUT_PAYMENT_CREDIT, CartCheckoutForm, ClientApprovalForm, CreditSaleForm, CreditSaleProductFormSet, InstallmentChoiceForm, ManualDebtForm, MeasurementsForm, PersonalDebtForm, PhoneVerificationForm, ProductCostForm, ProductForm, ProfilePhotoForm, RegisterForm, StoreOrderForm, UserPasswordChangeForm
from .models import ClientProfile, CreditSale, CreditSaleProduct, Debt, Notification, PaymentAlert, PersonalDebt, Product, ProductCost, StoreOrder, SupplierProduct, WELCOME_DISCOUNT_PERCENT, add_months, money
from .notifications import create_credit_limit_increased_notification, create_manual_debt_notification, create_registration_approved_notification, create_sale_available_notification, create_sale_confirmed_notifications, generate_due_notifications
from .payments import MercadoPagoNotConfigured, MercadoPagoRequestError, create_cart_checkout_preference, create_checkout_preference, create_credit_sale_card_preference, get_payment
from .store_shipping import SHIPPING_COSTS, shipping_cost_for
from .supplier_import import decode_catalog_content, import_supplier_catalog, import_supplier_catalog_content
from .utils import generate_phone_code

logger = logging.getLogger(__name__)
STORE_CHILD_SIZES = [str(size) for size in range(14, 33)]
STORE_ADULT_SIZES = [str(size) for size in range(33, 45)]
PARTNER_SALES_STATUSES = (
    StoreOrder.PAID,
    StoreOrder.SUPPLIER_ORDERED,
    StoreOrder.SHIPPED,
)


def shipping_rates_payload():
    return {key: f"{value:.2f}" for key, value in SHIPPING_COSTS.items()}


def normalize_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")

    return ascii_value.lower()


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
    return request.build_absolute_uri(reverse("choose_installments", args=[sale.id]))


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        redirect_to = self.get_redirect_url()

        if redirect_to:
            return redirect_to

        return resolve_url(authenticated_home_route(self.request.user))


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
    debts = list(user.debts.order_by("due_date", "id"))
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
    unpaid_debts = [debt for debt in debts if not debt.paid]
    overdue_debts = [debt for debt in unpaid_debts if debt.days_late() > 0]
    paid_debts = [debt for debt in debts if debt.paid]
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


def build_customer_finance_context(user):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    next_month = add_months(month_start, 1)
    month_end = next_month - timedelta(days=1)
    store_debts = list(user.debts.filter(paid=False).order_by("due_date", "id"))
    personal_debts = list(user.personal_debts.filter(paid=False).order_by("due_date", "id"))
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
        .annotate(tennis_priority=tennis_priority)
        .order_by("tennis_priority", "name")
    )
    reserved_sales = CreditSale.objects.none()
    query = request.GET.get("q", "").strip()
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
        products = products.filter(
            Q(name__icontains=query)
            | Q(category__icontains=query)
            | Q(brand__icontains=query)
            | Q(description__icontains=query)
        )

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

    anabela_product = (
        SupplierProduct.objects.filter(
            is_active=True,
            is_visible=True,
            stock_quantity__gt=0,
            name__icontains="Sandalia Plataforma de Cunha Anabela",
            image_url__icontains="4066b",
        )
        .order_by("name")
        .first()
    )
    sandalia_product = (
        SupplierProduct.objects.filter(
            is_active=True,
            is_visible=True,
            stock_quantity__gt=0,
            category__icontains="Sand",
        )
        .order_by("name")
        .first()
    )
    ankle_boot_product = (
        SupplierProduct.objects.filter(
            is_active=True,
            is_visible=True,
            stock_quantity__gt=0,
            name__icontains="Bota Ankle Boot Capa Cano Curto",
            image_url__icontains="1.958-4a",
        )
        .order_by("name")
        .first()
    )
    ramose_products = list(
        SupplierProduct.objects.filter(
            is_active=True,
            is_visible=True,
            stock_quantity__gt=0,
        )
        .filter(Q(brand__icontains="Ramos") | Q(name__icontains="Ramos"))
        .order_by("raw_data__featured_order", "name")[:5]
    )
    for product in ramose_products:
        gallery = product.gallery_images()
        product.primary_image = gallery[0] if gallery else ""
    ramose_showcase_url = f"{resolve_url('store_front')}?q=Ramos"

    showcase_sections = [
        {
            "title": "Calçados",
            "items": [
                {
                    "title": ankle_boot_product.name if ankle_boot_product else "Bota Ankle Boot Capa Cano Curto",
                    "subtitle": ankle_boot_product.category if ankle_boot_product else "Botas",
                    "price": f"R$ {ankle_boot_product.suggested_sale_price:.2f}".replace(".", ",") if ankle_boot_product else "R$ 230,85",
                    "sizes": ankle_boot_product.sizes if ankle_boot_product else "34,35,36,37,38,39",
                    "image_url": ankle_boot_product.image_url if ankle_boot_product else "/static/accounts/catalog-test/botas/1.958-4a.jpg",
                    "link_url": resolve_url("store_product_detail", ankle_boot_product.id) if ankle_boot_product else "",
                },
                {
                    "title": "NikeZoom Invicible Flyknit",
                    "subtitle": "Linha Premium",
                    "price": "R$ 239,90",
                    "sizes": "34,35,36,37,38,39,40,41,42,43",
                    "image_url": "/static/accounts/showcase-nikezoom.jpeg",
                    "link_url": "",
                },
                {
                    "title": sandalia_product.name if sandalia_product else "Sandalia feminina",
                    "subtitle": "Do nosso catalogo",
                    "price": f"R$ {sandalia_product.suggested_sale_price:.2f}".replace(".", ",") if sandalia_product else "R$ 107,65",
                    "sizes": sandalia_product.sizes if sandalia_product else "34,35,36,37,38,39",
                    "image_url": sandalia_product.image_url if sandalia_product else "",
                    "link_url": resolve_url("store_product_detail", sandalia_product.id) if sandalia_product else "",
                },
                {
                    "title": anabela_product.name if anabela_product else "Sandalia Plataforma de Cunha Anabela",
                    "subtitle": anabela_product.category if anabela_product else "Anabela",
                    "price": f"R$ {anabela_product.suggested_sale_price:.2f}".replace(".", ",") if anabela_product else "R$ 92,25",
                    "sizes": anabela_product.sizes if anabela_product else "34,35,36,37,38,39",
                    "image_url": anabela_product.image_url if anabela_product else "/static/accounts/catalog-test/anabela/4066b.jpg",
                    "link_url": resolve_url("store_product_detail", anabela_product.id) if anabela_product else "",
                },
            ],
        },
        {
            "title": "Bolsas",
            "items": [
                {
                    "title": product.name,
                    "subtitle": (product.raw_data or {}).get("material", product.description or "Bolsa artesanal"),
                    "price": f"R$ {product.suggested_sale_price:.2f}".replace(".", ","),
                    "sizes_label": "Modelo",
                    "sizes": product.sizes or "Único",
                    "image_url": product.primary_image,
                    "link_url": resolve_url("store_product_detail", product.id),
                }
                for product in ramose_products
            ] or [
                {
                    "title": "Bolsa Romosê",
                    "subtitle": "Crochê. Lenço não incluso.",
                    "price": "R$ 179,90",
                    "sizes_label": "Modelo",
                    "sizes": "Único",
                    "image_url": "/static/accounts/showcase-bolsa-tamose-preta.jpeg",
                    "link_url": ramose_showcase_url,
                },
                {
                    "title": "Bolsa Romosê",
                    "subtitle": "Crochê",
                    "price": "R$ 129,90",
                    "sizes_label": "Modelo",
                    "sizes": "Único",
                    "image_url": "/static/accounts/showcase-bolsa-tamose-bege.jpeg",
                    "link_url": ramose_showcase_url,
                },
                {
                    "title": "Bolsa Romosê",
                    "subtitle": "Crochê",
                    "price": "R$ 129,90",
                    "sizes_label": "Modelo",
                    "sizes": "Único",
                    "image_url": "/static/accounts/showcase-bolsa-tamose-caramelo.jpeg",
                    "link_url": ramose_showcase_url,
                },
            ],
        },
    ]

    for product in products:
        product.gallery = product.gallery_images()
        product.primary_image = product.gallery[0] if product.gallery else ""

    return render(
        request,
        "accounts/store_front.html",
        {
            "products": products,
            "showcase_sections": showcase_sections,
            "query": query,
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
        },
    )


def store_product_detail(request, product_id):
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

    return render(
        request,
        "accounts/store_product_detail.html",
        {
            "product": product,
            "size_options": size_options,
            "gallery_images": gallery,
        },
    )


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

    if request.method == "POST":
        form = CartCheckoutForm(request.POST)

        if not welcome_profile:
            form.fields.pop("use_welcome_discount")

        if form.is_valid():
            use_voucher = bool(welcome_profile and form.cleaned_data.get("use_welcome_discount"))
            checkout_reference = uuid.uuid4()
            shipping_state = form.cleaned_data["shipping_state"]
            shipping_cost = shipping_cost_for(shipping_state)
            orders = []

            if form.cleaned_data["payment_method"] == CHECKOUT_PAYMENT_CREDIT:
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
                for order in orders:
                    order.mark_paid(str(payment.get("id", payment_id)))

        return redirect("store_order_detail", public_token=first_order.public_token)

    if order_code:
        order = get_object_or_404(StoreOrder, order_code=order_code)

        if payment_id:
            try:
                payment = get_payment(payment_id)
            except (MercadoPagoNotConfigured, MercadoPagoRequestError):
                payment = {}

            if payment.get("status") == "approved":
                order.mark_paid(str(payment.get("id", payment_id)))

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

        for order in orders:
            if payment_status == "approved":
                order.mark_paid(payment_reference)
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
            order.mark_paid(payment_reference)
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

    if request.method == "POST":
        form = RegisterForm(request.POST, request.FILES, credit_mode=credit_mode)

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
                    {"form": form, "credit_mode": credit_mode, "next_url": next_url},
                    status=500,
                )

            profile = user.profile
            if credit_mode and settings.PHONE_VERIFICATION_REQUIRED and profile.phone:
                profile.phone_verification_code = generate_phone_code()
                profile.phone_verification_sent_at = timezone.now()
                profile.save(update_fields=["phone_verification_code", "phone_verification_sent_at"])
            else:
                profile.phone_verified = True
                profile.save(update_fields=["phone_verified"])
            login(request, user)

            if credit_mode and settings.PHONE_VERIFICATION_REQUIRED and profile.phone:
                return redirect("verify_phone")

            if next_url:
                return redirect(next_url)

            return redirect("dashboard")
    else:
        form = RegisterForm(credit_mode=credit_mode)

    return render(
        request,
        "accounts/register.html",
        {"form": form, "credit_mode": credit_mode, "next_url": next_url},
    )


@login_required
def verify_phone(request):
    profile = request.user.profile

    if not settings.PHONE_VERIFICATION_REQUIRED:
        return redirect("dashboard")

    if profile.phone_verified:
        return redirect("dashboard")

    if request.method == "POST":
        form = PhoneVerificationForm(request.POST)

        if form.is_valid():
            if form.cleaned_data["code"] == profile.phone_verification_code:
                profile.phone_verified = True
                profile.phone_verification_code = ""
                profile.save(update_fields=["phone_verified", "phone_verification_code"])

                return redirect("dashboard")

            messages.error(request, "Codigo invalido.")
    else:
        form = PhoneVerificationForm()

    return render(
        request,
        "accounts/verify_phone.html",
        {
            "form": form,
            "development_code": profile.phone_verification_code if settings.DEBUG else "",
        },
    )


@login_required
def dashboard(request):
    if request.user.is_staff:
        return redirect("management_dashboard")

    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if profile.registration_status != ClientProfile.APPROVED:
        return render(request, "accounts/registration_pending.html", {"profile": profile})

    purchase_groups = build_purchase_groups(request.user)
    return render(request, "accounts/dashboard.html", {"purchase_groups": purchase_groups})


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
def customer_finances(request):
    if request.user.is_staff:
        return HttpResponseForbidden("Area exclusiva do cliente.")

    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if profile.registration_status != ClientProfile.APPROVED:
        return render(request, "accounts/registration_pending.html", {"profile": profile})

    if request.method == "POST":
        form = PersonalDebtForm(request.POST)

        if form.is_valid():
            personal_debt = form.save(commit=False)
            personal_debt.client = request.user
            personal_debt.save()
            messages.success(request, "Conta pessoal criada com sucesso.")
            return redirect("customer_finances")
    else:
        form = PersonalDebtForm()

    context = build_customer_finance_context(request.user)
    context["personal_debt_form"] = form
    return render(request, "accounts/customer_finances.html", context)


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

    if request.method == "POST":
        form = ProfilePhotoForm(request.POST, request.FILES, instance=profile)

        if form.is_valid():
            form.save()
            messages.success(request, "Foto atualizada com sucesso.")

            return redirect("profile")
    else:
        form = ProfilePhotoForm(instance=profile)

    return render(request, "accounts/profile.html", {"form": form, "profile": profile})


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

    return render(
        request,
        "accounts/choose_installments.html",
        {
            "form": form,
            "sale": sale,
            "pix_option": sale.pix_option(),
            "card_payment_enabled": settings.CARD_PAYMENT_ENABLED,
            "card_options": sale.card_options(),
            "credit_options": sale.credit_options(),
            "card_installments": [option["installments"] for option in sale.card_options()],
            "credit_installments": [option["installments"] for option in sale.credit_options()],
            "welcome_discount_available": sale.available_welcome_discount_amount() > 0,
            "welcome_discount_percent": WELCOME_DISCOUNT_PERCENT,
            "welcome_discount_preview": sale.available_welcome_discount_amount(),
            "credit_financed_amount": sale.credit_financed_amount(),
            "credit_remainder_amount": sale.credit_remainder_amount(),
            "credit_late_fee_percent": Debt._meta.get_field("late_fee_percent").default,
            "credit_monthly_interest_percent": Debt._meta.get_field("monthly_interest_percent").default,
        },
    )


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
        form = ClientApprovalForm(request.POST, instance=profile)
        action = request.POST.get("action")

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

    return render(
        request,
        "accounts/review_client_profile.html",
        {
            "debts": financial_summary["debts"],
            "financial_summary": financial_summary,
            "form": form,
            "profile": profile,
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
    if request.method == "POST":
        form = CreditSaleForm(request.POST)
        product_formset = CreditSaleProductFormSet(request.POST, request.FILES)

        if form.is_valid() and product_formset.is_valid():
            sale = form.save(commit=False)
            sale.created_by = request.user
            sale.first_due_date = timezone.localdate() + timedelta(days=30)
            sale.max_installments_allowed = sale.client.profile.default_max_installments
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
                sale.description = product_name or f"Venda para {sale.client.full_name}"
            sale.save()
            product_formset.instance = sale
            product_formset.save()
            create_sale_available_notification(sale)
            messages.success(request, "Venda lancada para o cliente escolher o parcelamento.")

            return redirect("management_dashboard")
    else:
        form = CreditSaleForm()
        product_formset = CreditSaleProductFormSet()

    return render(request, "accounts/create_credit_sale.html", {"form": form, "product_formset": product_formset})


@staff_member_required(login_url="login")
def product_list(request):
    products = Product.objects.order_by("-created_at")

    return render(request, "accounts/product_list.html", {"products": products})


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
    products = SupplierProduct.objects.order_by("-last_seen_at", "name")
    query = request.GET.get("q", "").strip()
    visibility = request.GET.get("visibilidade", "")

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
            "query": query,
            "visibility": visibility,
              "total_products": SupplierProduct.objects.count(),
              "visible_products": SupplierProduct.objects.filter(is_visible=True).count(),
              "stock_products": SupplierProduct.objects.filter(is_active=True, stock_quantity__gt=0).count(),
          },
      )


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

    try:
        product.delete()
    except ProtectedError:
        messages.error(request, f"{product_label} ja tem pedido vinculado. Inative ou oculte para manter o historico.")
        return redirect("supplier_products")

    messages.success(request, f"{product_label} foi excluido do catalogo.")

    return redirect("supplier_products")


@staff_member_required(login_url="login")
def import_supplier_products(request):
    if request.method != "POST":
        return redirect_to_supplier_products()

    uploaded_catalog = request.FILES.get("catalog_file")

    if not uploaded_catalog and not settings.SHOE_SUPPLIER_CATALOG_URL:
        messages.error(request, "Envie um CSV/XML ou configure SHOE_SUPPLIER_CATALOG_URL antes de importar o catalogo.")

        return redirect_to_supplier_products()

    try:
        if uploaded_catalog:
            raw_content = uploaded_catalog.read()
            result = import_supplier_catalog_content(
                decode_catalog_content(raw_content),
                "xml" if uploaded_catalog.name.lower().endswith(".xml") else "csv",
            )
        else:
            result = import_supplier_catalog(
                settings.SHOE_SUPPLIER_CATALOG_URL,
                settings.SHOE_SUPPLIER_CATALOG_FORMAT,
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
            order.mark_paid()
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
        form = ProductForm()

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

    return render(
        request,
        "accounts/profit_report.html",
        {
            "products": products,
            "total_purchase": total_purchase,
            "total_sale": total_sale,
            "total_extra_costs": total_extra_costs,
            "gross_profit": gross_profit,
            "sold_products": sold_products,
            "available_products": available_products,
            "start_date": start_date,
            "end_date": end_date,
            "real_products": real_products,
            "real_purchase": real_purchase,
            "real_sale": real_sale,
            "real_extra_costs": real_extra_costs,
            "real_profit": real_profit,
        },
    )
