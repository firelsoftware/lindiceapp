from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone

from .models import CreditSale, CreditSaleProduct, ClientProfile, Debt, Product, ProductCost, SupplierProduct, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ("email", "full_name", "preferred_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active")
    ordering = ("email",)
    search_fields = ("email", "full_name", "preferred_name")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados pessoais", {"fields": ("full_name", "preferred_name")}),
        ("Permissoes", {"fields": ("is_staff", "is_active", "is_superuser", "groups", "user_permissions")}),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "preferred_name", "password1", "password2", "is_staff", "is_active"),
            },
        ),
    )


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "registration_status", "approved_at", "approved_by")
    list_filter = ("registration_status", "phone_verified")
    search_fields = ("user__email", "user__full_name", "user__preferred_name", "phone", "cpf_last_digits")
    readonly_fields = ("approved_at",)

    fieldsets = (
        ("Cliente", {"fields": ("user", "phone", "phone_verified", "phone_verification_code", "phone_verification_sent_at")}),
        ("Documentos", {"fields": ("cpf_hash", "cpf_last_digits", "address", "residence_proof")}),
        ("Medidas", {"fields": ("shoe_size", "finger_sizes")}),
        ("Credito", {"fields": ("default_max_installments",)}),
        ("Cadastro", {"fields": ("registration_status", "admin_notes", "approved_at", "approved_by")}),
        ("Dados extras", {"fields": ("extra_data",)}),
    )

    def save_model(self, request, obj, form, change):
        if obj.registration_status == ClientProfile.APPROVED and obj.approved_at is None:
            obj.approved_at = timezone.now()
            obj.approved_by = request.user

        super().save_model(request, obj, form, change)


@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ("client", "description", "amount", "due_date", "paid", "total_amount")
    list_filter = ("paid", "due_date")
    search_fields = ("client__email", "client__full_name", "description")


@admin.register(CreditSale)
class CreditSaleAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "sale_code",
        "description",
        "total_amount",
        "max_installments_allowed",
        "status",
        "selected_installments",
        "created_at",
    )
    list_filter = ("status", "max_installments_allowed")
    search_fields = ("client__email", "client__full_name", "description")
    readonly_fields = ("created_at", "accepted_at")


@admin.register(CreditSaleProduct)
class CreditSaleProductAdmin(admin.ModelAdmin):
    list_display = ("product_code", "sale", "product", "name", "shoe_size", "created_at")
    search_fields = ("product_code", "sale__sale_code", "name", "sale__client__full_name")
    readonly_fields = ("product_code", "created_at")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("product_code", "name", "shoe_size", "purchase_price", "sale_price", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("product_code", "name", "shoe_size")
    readonly_fields = ("product_code", "created_at")


@admin.register(ProductCost)
class ProductCostAdmin(admin.ModelAdmin):
    list_display = ("product", "amount", "created_at")
    search_fields = ("product__product_code", "product__name", "reason")


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    list_display = ("supplier_code", "name", "stock_quantity", "dropshipping_cost", "suggested_sale_price", "is_active", "is_visible", "last_seen_at")
    list_filter = ("source", "is_active", "is_visible", "last_seen_at")
    search_fields = ("supplier_code", "name", "category", "brand")
    readonly_fields = ("raw_data", "last_seen_at", "created_at", "updated_at")
