from decimal import Decimal, ROUND_HALF_UP
import uuid
import re

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("O email e obrigatorio.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    full_name = models.CharField(max_length=150)
    preferred_name = models.CharField(max_length=80)
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name", "preferred_name"]

    objects = UserManager()

    def __str__(self):
        return self.email


class ClientProfile(models.Model):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    REGISTRATION_STATUS_CHOICES = [
        (PENDING, "Pendente"),
        (APPROVED, "Aprovado"),
        (REJECTED, "Rejeitado"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    cpf_hash = models.CharField(max_length=64, unique=True)
    cpf_last_digits = models.CharField(max_length=4)
    phone = models.CharField(max_length=20)
    phone_verified = models.BooleanField(default=False)
    phone_verification_code = models.CharField(max_length=6, blank=True)
    phone_verification_sent_at = models.DateTimeField(null=True, blank=True)
    address = models.TextField()
    residence_proof = models.FileField(upload_to="residence_proofs/")
    profile_photo = models.FileField(upload_to="profile_photos/", blank=True)
    shoe_size = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    finger_sizes = models.JSONField(default=dict, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)
    pre_approved_credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    default_max_installments = models.PositiveSmallIntegerField(default=5)
    registration_status = models.CharField(
        max_length=20,
        choices=REGISTRATION_STATUS_CHOICES,
        default=PENDING,
    )
    admin_notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_clients",
    )

    def __str__(self):
        return f"Cadastro de {self.user.email}"


INSTALLMENT_INTEREST_RATES = {
    1: Decimal("0.00"),
    2: Decimal("0.00"),
    3: Decimal("0.00"),
    4: Decimal("2.50"),
    5: Decimal("3.00"),
    6: Decimal("3.50"),
    7: Decimal("4.00"),
    8: Decimal("4.50"),
    9: Decimal("5.00"),
    10: Decimal("5.50"),
}

CARD_INSTALLMENT_INTEREST_RATES = {
    1: Decimal("0.00"),
    2: Decimal("0.00"),
    3: Decimal("0.00"),
    4: Decimal("0.00"),
    5: Decimal("0.00"),
    6: Decimal("3.50"),
    7: Decimal("4.00"),
    8: Decimal("4.50"),
    9: Decimal("5.00"),
    10: Decimal("5.50"),
}

PIX_DISCOUNT_PERCENT = Decimal("10.00")


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def add_months(date_value, months):
    month = date_value.month - 1 + months
    year = date_value.year + month // 12
    month = month % 12 + 1
    month_days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(date_value.day, month_days[month - 1])

    return date_value.replace(year=year, month=month, day=day)


def build_sale_code(created_at):
    month_start = created_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_count = CreditSale.objects.filter(created_at__gte=month_start).exclude(sale_code="").count() + 1

    return f"{monthly_count}{created_at:%m%y}"


def build_product_code(created_at):
    month_start = created_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_count = Product.objects.filter(created_at__gte=month_start).exclude(product_code="").count() + 1

    return f"P{monthly_count}{created_at:%m%y}"


def build_store_order_code(created_at):
    month_start = created_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_count = StoreOrder.objects.filter(created_at__gte=month_start).exclude(order_code="").count() + 1

    return f"LJ{monthly_count:04d}{created_at:%m%y}"


class Product(models.Model):
    AVAILABLE = "available"
    SOLD = "sold"
    DAMAGED = "damaged"

    STATUS_CHOICES = [
        (AVAILABLE, "Disponivel"),
        (SOLD, "Vendido"),
        (DAMAGED, "Com problema"),
    ]

    product_code = models.CharField(max_length=30, unique=True, blank=True)
    name = models.CharField(max_length=120)
    image = models.FileField(upload_to="products/", blank=True)
    shoe_size = models.CharField(max_length=20, blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=AVAILABLE)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if not self.product_code:
            self.product_code = build_product_code(self.created_at)
            super().save(update_fields=["product_code"])

    def extra_cost_total(self):
        return sum(cost.amount for cost in self.costs.all())

    def profit(self):
        return self.sale_price - self.purchase_price - self.extra_cost_total()

    def __str__(self):
        return f"{self.product_code} - {self.name}"


class ProductCost(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="costs")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.product_code} - R$ {self.amount}"


class SupplierProduct(models.Model):
    SOURCE_REVENDA_CALCADOS = "revenda_calcados"

    SOURCE_CHOICES = [
        (SOURCE_REVENDA_CALCADOS, "Revenda de Calcados"),
    ]

    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default=SOURCE_REVENDA_CALCADOS)
    supplier_code = models.CharField(max_length=120)
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    image_url = models.URLField(blank=True)
    product_url = models.URLField(blank=True)
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    dropshipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    suggested_sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    stock_quantity = models.IntegerField(default=0)
    sizes = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)
    is_visible = models.BooleanField(default=False)
    raw_data = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "supplier_code"], name="unique_supplier_product_code"),
        ]
        ordering = ["name", "supplier_code"]

    def __str__(self):
        return f"{self.supplier_code} - {self.name}"

    def store_margin(self):
        return self.suggested_sale_price - self.dropshipping_cost


class StoreOrder(models.Model):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    SUPPLIER_ORDERED = "supplier_ordered"
    SHIPPED = "shipped"
    CANCELED = "canceled"

    STATUS_CHOICES = [
        (PENDING_PAYMENT, "Aguardando pagamento"),
        (PAID, "Pago - comprar no fornecedor"),
        (PAYMENT_FAILED, "Pagamento recusado"),
        (SUPPLIER_ORDERED, "Pedido feito no fornecedor"),
        (SHIPPED, "Enviado ao cliente"),
        (CANCELED, "Cancelado"),
    ]

    order_code = models.CharField(max_length=20, unique=True, blank=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    product = models.ForeignKey(SupplierProduct, on_delete=models.PROTECT, related_name="store_orders")
    product_name = models.CharField(max_length=180)
    supplier_code = models.CharField(max_length=120)
    selected_size = models.CharField(max_length=30)
    quantity = models.PositiveSmallIntegerField(default=1)
    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=30)
    shipping_address = models.TextField()
    notes = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    supplier_cost = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    estimated_profit = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=PENDING_PAYMENT)
    mercado_pago_preference_id = models.CharField(max_length=120, blank=True)
    mercado_pago_payment_id = models.CharField(max_length=120, blank=True)
    mercado_pago_init_point = models.URLField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    supplier_ordered_at = models.DateTimeField(null=True, blank=True)
    supplier_order_reference = models.CharField(max_length=120, blank=True)
    tracking_code = models.CharField(max_length=120, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if not self.order_code:
            self.order_code = build_store_order_code(self.created_at)
            super().save(update_fields=["order_code"])

    def mark_paid(self, payment_id=""):
        self.status = self.PAID
        self.mercado_pago_payment_id = payment_id or self.mercado_pago_payment_id
        self.paid_at = self.paid_at or timezone.now()
        self.save(update_fields=["status", "mercado_pago_payment_id", "paid_at", "updated_at"])

    def mark_payment_failed(self, payment_id=""):
        self.status = self.PAYMENT_FAILED
        self.mercado_pago_payment_id = payment_id or self.mercado_pago_payment_id
        self.save(update_fields=["status", "mercado_pago_payment_id", "updated_at"])

    def whatsapp_url(self):
        digits = re.sub(r"\D", "", self.customer_phone)

        if digits and not digits.startswith("55"):
            digits = f"55{digits}"

        return f"https://wa.me/{digits}" if digits else ""

    def __str__(self):
        return f"{self.order_code} - {self.customer_name} - {self.product_name}"


class CreditSale(models.Model):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CANCELED = "canceled"

    PIX = "pix"
    CARD = "card"
    CREDIT = "credit"

    STATUS_CHOICES = [
        (PENDING, "Aguardando escolha do cliente"),
        (ACCEPTED, "Parcelamento escolhido"),
        (CANCELED, "Cancelada"),
    ]

    PAYMENT_METHOD_CHOICES = [
        (PIX, "Pix"),
        (CARD, "Cartao"),
        (CREDIT, "Crediario"),
    ]

    PAYMENT_PENDING = "pending"
    PAYMENT_PAID = "paid"
    PAYMENT_FAILED = "failed"

    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PENDING, "Aguardando pagamento"),
        (PAYMENT_PAID, "Pago"),
        (PAYMENT_FAILED, "Pagamento recusado"),
    ]

    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name="credit_sales")
    sale_code = models.CharField(max_length=20, unique=True, blank=True)
    description = models.CharField(max_length=200)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    max_installments_allowed = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    first_due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    selected_installments = models.PositiveSmallIntegerField(null=True, blank=True)
    selected_payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True)
    selected_monthly_interest_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    selected_installment_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    selected_total_with_interest = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PENDING)
    mercado_pago_preference_id = models.CharField(max_length=120, blank=True)
    mercado_pago_payment_id = models.CharField(max_length=120, blank=True)
    mercado_pago_init_point = models.URLField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_credit_sales",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if not self.sale_code:
            self.sale_code = build_sale_code(self.created_at)
            super().save(update_fields=["sale_code"])

    def installment_options(self):
        return self.credit_options()

    def credit_options(self):
        options = []
        max_installments = min(self.max_installments_allowed, 10)

        for installments in range(1, max_installments + 1):
            monthly_rate = INSTALLMENT_INTEREST_RATES[installments]
            rate = monthly_rate / Decimal("100")
            total = self.total_amount if monthly_rate == 0 else self.total_amount * ((Decimal("1.00") + rate) ** installments)
            total = money(total)
            installment_amount = money(total / Decimal(installments))

            if installments == 1 or installment_amount >= Decimal("70.00"):
                options.append(
                    {
                        "installments": installments,
                        "monthly_rate": monthly_rate,
                        "installment_amount": installment_amount,
                        "total": total,
                    }
                )

        return options

    def card_options(self):
        options = []
        max_installments = min(self.max_installments_allowed, 10)

        for installments in range(1, max_installments + 1):
            monthly_rate = CARD_INSTALLMENT_INTEREST_RATES[installments]
            rate = monthly_rate / Decimal("100")
            total = self.total_amount if monthly_rate == 0 else self.total_amount * ((Decimal("1.00") + rate) ** installments)
            total = money(total)
            installment_amount = money(total / Decimal(installments))
            options.append(
                {
                    "installments": installments,
                    "monthly_rate": monthly_rate,
                    "installment_amount": installment_amount,
                    "total": total,
                }
            )

        return options

    def pix_option(self):
        discount = money(self.total_amount * (PIX_DISCOUNT_PERCENT / Decimal("100")))
        total = money(self.total_amount - discount)

        return {
            "discount": discount,
            "discount_percent": PIX_DISCOUNT_PERCENT,
            "total": total,
        }

    def choose_payment(self, payment_method, installments=None):
        if self.payment_status == self.PAYMENT_PAID:
            raise ValueError("Pagamento ja confirmado.")

        self.debts.all().delete()
        self.payment_status = self.PAYMENT_PENDING
        self.mercado_pago_preference_id = ""
        self.mercado_pago_payment_id = ""
        self.mercado_pago_init_point = ""

        if payment_method == self.PIX:
            option = self.pix_option()
            self.selected_payment_method = self.PIX
            self.selected_installments = 1
            self.selected_monthly_interest_percent = Decimal("0.00")
            self.selected_installment_amount = option["total"]
            self.selected_total_with_interest = option["total"]
            self.status = self.ACCEPTED
            self.accepted_at = timezone.now()
            self.save()

            return

        if installments is None:
            raise ValueError("Escolha a quantidade de parcelas.")

        options = self.card_options() if payment_method == self.CARD else self.credit_options()
        selected_option = None

        for option in options:
            if option["installments"] == installments:
                selected_option = option
                break

        if selected_option is None:
            raise ValueError("Opcao de pagamento invalida.")

        self.selected_payment_method = payment_method
        self.selected_installments = installments
        self.selected_monthly_interest_percent = selected_option["monthly_rate"]
        self.selected_installment_amount = selected_option["installment_amount"]
        self.selected_total_with_interest = selected_option["total"]
        self.status = self.ACCEPTED
        self.accepted_at = timezone.now()
        self.save()

        if payment_method != self.CREDIT:
            return

        for number in range(1, installments + 1):
            Debt.objects.create(
                client=self.client,
                credit_sale=self,
                description=f"{self.description} - Parcela {number} de {installments}",
                amount=selected_option["installment_amount"],
                due_date=add_months(self.first_due_date, number - 1),
            )

    def choose_installments(self, installments):
        self.choose_payment(self.CREDIT, installments)

    def mark_paid(self, payment_id=""):
        self.payment_status = self.PAYMENT_PAID
        self.mercado_pago_payment_id = payment_id or self.mercado_pago_payment_id
        self.save(update_fields=["payment_status", "mercado_pago_payment_id"])

    def mark_payment_failed(self, payment_id=""):
        self.payment_status = self.PAYMENT_FAILED
        self.mercado_pago_payment_id = payment_id or self.mercado_pago_payment_id
        self.save(update_fields=["payment_status", "mercado_pago_payment_id"])

    def __str__(self):
        return f"{self.sale_code} - {self.client.email} - {self.description}"


class CreditSaleProduct(models.Model):
    sale = models.ForeignKey(CreditSale, on_delete=models.CASCADE, related_name="products")
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sale_items",
    )
    product_code = models.CharField(max_length=30, unique=True, blank=True)
    name = models.CharField(max_length=120, blank=True)
    image = models.FileField(upload_to="sale_products/", blank=True)
    shoe_size = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.product:
            self.name = self.name or self.product.name
            self.shoe_size = self.shoe_size or self.product.shoe_size
            self.notes = self.notes or self.product.notes

            if not self.image and self.product.image:
                self.image = self.product.image

        super().save(*args, **kwargs)

        if not self.product_code:
            self.product_code = f"{self.sale.sale_code}-{self.sale.products.count():02d}"
            super().save(update_fields=["product_code"])

        if self.product and self.product.status != Product.SOLD:
            self.product.status = Product.SOLD
            self.product.save(update_fields=["status"])

    def __str__(self):
        return f"{self.product_code} - {self.name}"


class PaymentAlert(models.Model):
    payment_id = models.CharField(max_length=120, unique=True)
    credit_sale = models.ForeignKey(
        CreditSale,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payment_alerts",
    )
    store_order = models.ForeignKey(
        StoreOrder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payment_alerts",
    )
    status_detail = models.CharField(max_length=180, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pagamento recusado: {self.payment_id}"


class Debt(models.Model):
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name="debts")
    credit_sale = models.ForeignKey(
        CreditSale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="debts",
    )
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    paid = models.BooleanField(default=False)
    paid_at = models.DateField(null=True, blank=True)
    late_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.00"))
    monthly_interest_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    def days_late(self):
        if self.paid:
            return 0

        today = timezone.localdate()

        if today <= self.due_date:
            return 0

        return (today - self.due_date).days

    def late_fee_amount(self):
        if self.days_late() == 0:
            return Decimal("0.00")

        return self.amount * (self.late_fee_percent / Decimal("100"))

    def interest_amount(self):
        days = self.days_late()

        if days == 0:
            return Decimal("0.00")

        daily_interest = self.monthly_interest_percent / Decimal("100") / Decimal("30")
        return self.amount * daily_interest * days

    def total_amount(self):
        return self.amount + self.late_fee_amount() + self.interest_amount()

    def __str__(self):
        return f"{self.client.email} - R$ {self.total_amount():.2f}"


class Notification(models.Model):
    DUE_SOON = "due_soon"
    DUE_TODAY = "due_today"
    MANUAL_DEBT = "manual_debt"
    KIND_CHOICES = (
        (DUE_SOON, "Vencimento proximo"),
        (DUE_TODAY, "Vencimento hoje"),
        (MANUAL_DEBT, "Debito lancado"),
    )

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    debt = models.ForeignKey(Debt, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    title = models.CharField(max_length=160)
    message = models.TextField()
    unique_key = models.CharField(max_length=220, unique=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_as_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])

    def __str__(self):
        return f"{self.recipient.email} - {self.title}"
