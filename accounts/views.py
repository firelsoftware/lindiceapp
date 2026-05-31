from django.conf import settings
import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Sum
from django.db.models import Q
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .forms import ClientApprovalForm, CreditSaleForm, CreditSaleProductFormSet, InstallmentChoiceForm, MeasurementsForm, PhoneVerificationForm, ProductCostForm, ProductForm, ProfilePhotoForm, RegisterForm, StoreOrderForm, UserPasswordChangeForm
from .models import CreditSale, ClientProfile, Product, ProductCost, StoreOrder, SupplierProduct
from .payments import MercadoPagoNotConfigured, MercadoPagoRequestError, create_checkout_preference, get_payment
from .supplier_import import import_supplier_catalog
from .utils import generate_phone_code

logger = logging.getLogger(__name__)


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


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    return redirect("login")


def brand_preview(request):
    return render(request, "accounts/brand_preview.html")


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
    products = SupplierProduct.objects.filter(is_active=True, is_visible=True, stock_quantity__gt=0).order_by("name")
    reserved_sales = CreditSale.objects.none()
    query = request.GET.get("q", "").strip()
    size = request.GET.get("tamanho", "").strip()

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

    return render(
        request,
        "accounts/store_front.html",
        {
            "products": products,
            "query": query,
            "size": size,
            "size_options": parsed_sizes,
            "reserved_sales": reserved_sales,
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

    return render(request, "accounts/store_product_detail.html", {"product": product})


def store_checkout(request, product_id):
    product = get_object_or_404(
        SupplierProduct,
        id=product_id,
        is_active=True,
        is_visible=True,
        stock_quantity__gt=0,
    )

    if request.method == "POST":
        form = StoreOrderForm(request.POST, product=product)

        if form.is_valid():
            order = form.save(commit=False)
            order.product = product
            order.product_name = product.name
            order.supplier_code = product.supplier_code
            order.unit_price = product.suggested_sale_price
            order.supplier_cost = product.dropshipping_cost
            order.total_amount = product.suggested_sale_price
            order.estimated_profit = product.suggested_sale_price - product.dropshipping_cost
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

    return render(request, "accounts/store_checkout.html", {"form": form, "product": product})


def store_order_detail(request, public_token):
    order = get_object_or_404(StoreOrder, public_token=public_token)

    return render(request, "accounts/store_order_detail.html", {"order": order})


def payment_success(request):
    order_code = request.GET.get("external_reference", "")
    payment_id = request.GET.get("payment_id", "")

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

    if payment.get("status") == "approved" and order_code:
        try:
            order = StoreOrder.objects.get(order_code=order_code)
        except StoreOrder.DoesNotExist:
            return JsonResponse({"ok": False, "error": "order not found"}, status=404)

        order.mark_paid(str(payment.get("id", payment_id)))

    return JsonResponse({"ok": True})


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except Exception:
                logger.exception("Erro ao criar cadastro")
                form.add_error(
                    "residence_proof",
                    "Nao foi possivel enviar o comprovante agora. Tente novamente em instantes.",
                )

                return render(request, "accounts/register.html", {"form": form}, status=500)

            profile = user.profile
            if settings.PHONE_VERIFICATION_REQUIRED:
                profile.phone_verification_code = generate_phone_code()
                profile.phone_verification_sent_at = timezone.now()
                profile.save(update_fields=["phone_verification_code", "phone_verification_sent_at"])
            else:
                profile.phone_verified = True
                profile.save(update_fields=["phone_verified"])
            login(request, user)

            if settings.PHONE_VERIFICATION_REQUIRED:
                return redirect("verify_phone")

            return redirect("dashboard")
    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


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
def account(request):
    return render(request, "accounts/account.html")


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

    sale = get_object_or_404(CreditSale, id=sale_id, client=request.user, status=CreditSale.PENDING)
    profile = request.user.profile

    if not profile.phone_verified:
        return redirect("verify_phone")

    if profile.registration_status != ClientProfile.APPROVED:
        return render(request, "accounts/registration_pending.html", {"profile": profile})

    if request.method == "POST":
        form = InstallmentChoiceForm(request.POST, sale=sale)

        if form.is_valid():
            with transaction.atomic():
                sale.choose_payment(
                    form.cleaned_data["payment_method"],
                    form.cleaned_data["installments"],
                )

            messages.success(request, "Forma de pagamento escolhida com sucesso.")

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
            "card_options": sale.card_options(),
            "credit_options": sale.credit_options(),
        },
    )


@staff_member_required(login_url="login")
def management_dashboard(request):
    pending_profiles = ClientProfile.objects.filter(registration_status=ClientProfile.PENDING).order_by("user__full_name")
    pending_sales = CreditSale.objects.filter(status=CreditSale.PENDING).order_by("-created_at")
    accepted_sales = CreditSale.objects.filter(status=CreditSale.ACCEPTED).order_by("-accepted_at")[:10]
    available_products = Product.objects.filter(status=Product.AVAILABLE).order_by("-created_at")[:10]
    store_paid_count = StoreOrder.objects.filter(status=StoreOrder.PAID).count()
    store_pending_payment_count = StoreOrder.objects.filter(status=StoreOrder.PENDING_PAYMENT).count()

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
            "supplier_catalog_configured": bool(settings.SHOE_SUPPLIER_CATALOG_URL),
            "mercado_pago_configured": bool(settings.MERCADO_PAGO_ACCESS_TOKEN),
            "public_site_url_configured": bool(settings.PUBLIC_SITE_URL),
            "phone_verification_required": settings.PHONE_VERIFICATION_REQUIRED,
        },
    )


@staff_member_required(login_url="login")
def review_client_profile(request, profile_id):
    profile = get_object_or_404(ClientProfile, id=profile_id)

    if request.method == "POST":
        form = ClientApprovalForm(request.POST, instance=profile)
        action = request.POST.get("action")

        if form.is_valid():
            profile = form.save(commit=False)

            if action == "approve":
                profile.registration_status = ClientProfile.APPROVED
                profile.approved_at = timezone.now()
                profile.approved_by = request.user
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
            messages.success(request, message)

            return redirect("management_dashboard")
    else:
        form = ClientApprovalForm(instance=profile)

    return render(request, "accounts/review_client_profile.html", {"form": form, "profile": profile})


@staff_member_required(login_url="login")
def create_credit_sale(request):
    if request.method == "POST":
        form = CreditSaleForm(request.POST)
        product_formset = CreditSaleProductFormSet(request.POST, request.FILES)

        if form.is_valid() and product_formset.is_valid():
            sale = form.save(commit=False)
            sale.created_by = request.user
            sale.save()
            product_formset.instance = sale
            product_formset.save()
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
        visible_ids = set(request.POST.getlist("visible_products"))
        edited_ids = request.POST.getlist("product_ids")
        edited_products = SupplierProduct.objects.filter(id__in=edited_ids)
        updated = 0

        for product in edited_products:
            product.is_visible = str(product.id) in visible_ids
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

            product.save(update_fields=["is_visible", "suggested_sale_price", "updated_at"])
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
            "query": query,
            "visibility": visibility,
              "total_products": SupplierProduct.objects.count(),
              "visible_products": SupplierProduct.objects.filter(is_visible=True).count(),
              "stock_products": SupplierProduct.objects.filter(is_active=True, stock_quantity__gt=0).count(),
          },
      )


@staff_member_required(login_url="login")
def import_supplier_products(request):
    if request.method != "POST":
        return redirect("supplier_products")

    if not settings.SHOE_SUPPLIER_CATALOG_URL:
        messages.error(request, "Configure SHOE_SUPPLIER_CATALOG_URL antes de importar o catalogo.")

        return redirect("supplier_products")

    try:
        result = import_supplier_catalog(
            settings.SHOE_SUPPLIER_CATALOG_URL,
            settings.SHOE_SUPPLIER_CATALOG_FORMAT,
        )
    except Exception as exc:
        messages.error(request, f"Nao foi possivel importar o catalogo: {exc}")

        return redirect("supplier_products")

    messages.success(
        request,
        f"Catalogo atualizado: {result['created']} novos, {result['updated']} atualizados, {result['total']} lidos.",
    )

    return redirect("supplier_products")


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
