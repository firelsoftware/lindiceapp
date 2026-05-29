from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from .models import CreditSale, CreditSaleProduct, ClientProfile, Product, ProductCost, StoreOrder, User
from .utils import clean_digits, cpf_hash, cpf_last_digits, is_valid_cpf


class RegisterForm(UserCreationForm):
    full_name = forms.CharField(label="Nome completo *", max_length=150)
    preferred_name = forms.CharField(label="Como prefere ser chamado(a) *", max_length=80)
    email = forms.EmailField(label="Email *")
    cpf = forms.CharField(label="CPF *", max_length=14)
    phone = forms.CharField(label="Telefone *", max_length=20)
    address = forms.CharField(label="Endereco *", widget=forms.Textarea)
    residence_proof = forms.FileField(
        label="Comprovante de residencia no nome do cliente *"
    )

    class Meta:
        model = User
        fields = (
            "full_name",
            "preferred_name",
            "email",
            "password1",
            "password2",
            "cpf",
            "phone",
            "address",
            "residence_proof",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Senha *"
        self.fields["password2"].label = "Confirmacao de senha *"

    def clean_email(self):
        email = self.cleaned_data["email"].lower()

        if User.objects.filter(email=email).exists():
            raise ValidationError("Ja existe um cadastro com este email.")

        return email

    def clean_cpf(self):
        cpf = self.cleaned_data["cpf"]
        cpf_digits = clean_digits(cpf)

        if len(cpf_digits) != 11:
            raise ValidationError("Informe um CPF com 11 numeros.")

        if not is_valid_cpf(cpf_digits):
            raise ValidationError("Informe um CPF valido.")

        if ClientProfile.objects.filter(cpf_hash=cpf_hash(cpf_digits)).exists():
            raise ValidationError("Ja existe um cadastro com este CPF.")

        return cpf_digits

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]

        if commit:
            user.save()

            ClientProfile.objects.create(
                user=user,
                cpf_hash=cpf_hash(self.cleaned_data["cpf"]),
                cpf_last_digits=cpf_last_digits(self.cleaned_data["cpf"]),
                phone=self.cleaned_data["phone"],
                address=self.cleaned_data["address"],
                residence_proof=self.cleaned_data["residence_proof"],
            )

        return user


class PhoneVerificationForm(forms.Form):
    code = forms.CharField(max_length=6, min_length=6)


class MeasurementsForm(forms.Form):
    shoe_size = forms.DecimalField(
        label="Tamanho do pe",
        max_digits=4,
        decimal_places=1,
        required=False,
    )
    right_thumb = forms.CharField(label="Mao direita - polegar", required=False)
    right_index = forms.CharField(label="Mao direita - indicador", required=False)
    right_middle = forms.CharField(label="Mao direita - medio", required=False)
    right_ring = forms.CharField(label="Mao direita - anelar", required=False)
    right_little = forms.CharField(label="Mao direita - mindinho", required=False)
    left_thumb = forms.CharField(label="Mao esquerda - polegar", required=False)
    left_index = forms.CharField(label="Mao esquerda - indicador", required=False)
    left_middle = forms.CharField(label="Mao esquerda - medio", required=False)
    left_ring = forms.CharField(label="Mao esquerda - anelar", required=False)
    left_little = forms.CharField(label="Mao esquerda - mindinho", required=False)

    def save(self, profile):
        profile.shoe_size = self.cleaned_data["shoe_size"]
        profile.finger_sizes = {
            "mao_direita": {
                "polegar": self.cleaned_data["right_thumb"],
                "indicador": self.cleaned_data["right_index"],
                "medio": self.cleaned_data["right_middle"],
                "anelar": self.cleaned_data["right_ring"],
                "mindinho": self.cleaned_data["right_little"],
            },
            "mao_esquerda": {
                "polegar": self.cleaned_data["left_thumb"],
                "indicador": self.cleaned_data["left_index"],
                "medio": self.cleaned_data["left_middle"],
                "anelar": self.cleaned_data["left_ring"],
                "mindinho": self.cleaned_data["left_little"],
            },
        }
        profile.save(update_fields=["shoe_size", "finger_sizes"])


class ProfilePhotoForm(forms.ModelForm):
    class Meta:
        model = ClientProfile
        fields = ("profile_photo",)
        labels = {
            "profile_photo": "Foto do cliente",
        }
        help_texts = {
            "profile_photo": "Envie uma foto se quiser facilitar sua identificacao no atendimento.",
        }

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")

        if photo and hasattr(photo, "content_type") and not photo.content_type.startswith("image/"):
            raise ValidationError("Envie um arquivo de imagem.")

        return photo


class ClientApprovalForm(forms.ModelForm):
    class Meta:
        model = ClientProfile
        fields = ("pre_approved_credit_limit", "default_max_installments", "admin_notes")
        labels = {
            "pre_approved_credit_limit": "Limite pre-aprovado",
            "admin_notes": "Observacoes internas",
            "default_max_installments": "Limite padrao de parcelas",
        }
        widgets = {
            "pre_approved_credit_limit": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "default_max_installments": forms.NumberInput(attrs={"min": 1, "max": 10}),
        }

    def clean_pre_approved_credit_limit(self):
        credit_limit = self.cleaned_data["pre_approved_credit_limit"]

        if credit_limit < 0:
            raise ValidationError("Informe um limite igual ou maior que zero.")

        return credit_limit

    def clean_default_max_installments(self):
        installments = self.cleaned_data["default_max_installments"]

        if installments < 1 or installments > 10:
            raise ValidationError("Informe um valor entre 1 e 10 parcelas.")

        return installments


class UserPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(label="Senha atual", widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="Nova senha", widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Confirmar nova senha", widget=forms.PasswordInput)


class CreditSaleForm(forms.ModelForm):
    class Meta:
        model = CreditSale
        fields = ("client", "description", "total_amount", "max_installments_allowed", "first_due_date")
        labels = {
            "client": "Cliente",
            "description": "Descricao da venda",
            "total_amount": "Valor total",
            "max_installments_allowed": "Maximo de parcelas permitido",
            "first_due_date": "Vencimento da primeira parcela",
        }
        help_texts = {
            "max_installments_allowed": "Clientes novos normalmente ficam ate 5x. Voce pode liberar ate 10x para clientes de confianca.",
        }
        widgets = {
            "first_due_date": forms.DateInput(attrs={"type": "date"}),
            "max_installments_allowed": forms.NumberInput(attrs={"min": 1, "max": 10}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = User.objects.filter(
            profile__registration_status=ClientProfile.APPROVED,
            is_staff=False,
        ).order_by("full_name")

    def clean_max_installments_allowed(self):
        max_installments = self.cleaned_data["max_installments_allowed"]

        if max_installments < 1 or max_installments > 10:
            raise ValidationError("Informe um valor entre 1 e 10 parcelas.")

        return max_installments


class InstallmentChoiceForm(forms.Form):
    installments = forms.ChoiceField(label="Escolha o parcelamento")

    def __init__(self, *args, sale, **kwargs):
        super().__init__(*args, **kwargs)
        self.sale = sale
        self.fields["installments"].choices = [
            (
                option["installments"],
                f"{option['installments']}x de R$ {option['installment_amount']} | juros {option['monthly_rate']}% a.m. | total R$ {option['total']}",
            )
            for option in sale.installment_options()
        ]

    def clean_installments(self):
        return int(self.cleaned_data["installments"])


class CreditSaleProductForm(forms.ModelForm):
    class Meta:
        model = CreditSaleProduct
        fields = ("product", "name", "image", "shoe_size", "notes")
        labels = {
            "product": "Produto ja cadastrado",
            "name": "Nome do produto",
            "image": "Foto do produto",
            "shoe_size": "Tamanho",
            "notes": "Observacoes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(status=Product.AVAILABLE).order_by("product_code")
        self.fields["product"].required = False
        self.fields["name"].required = False
        self.fields["image"].required = False


CreditSaleProductFormSet = inlineformset_factory(
    CreditSale,
    CreditSaleProduct,
    form=CreditSaleProductForm,
    extra=1,
    max_num=20,
    can_delete=False,
)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("name", "image", "shoe_size", "purchase_price", "sale_price", "notes", "status")
        labels = {
            "name": "Nome do produto",
            "image": "Foto do produto",
            "shoe_size": "Tamanho",
            "purchase_price": "Valor de compra",
            "sale_price": "Valor de venda",
            "notes": "Observacoes",
            "status": "Status",
        }


class ProductCostForm(forms.ModelForm):
    class Meta:
        model = ProductCost
        fields = ("amount", "reason")
        labels = {
            "amount": "Valor do custo",
            "reason": "Motivo/observacao",
        }


class StoreOrderForm(forms.ModelForm):
    selected_size = forms.ChoiceField(label="Tamanho")

    class Meta:
        model = StoreOrder
        fields = ("selected_size", "customer_name", "customer_email", "customer_phone", "shipping_address", "notes")
        labels = {
            "customer_name": "Nome completo",
            "customer_email": "Email",
            "customer_phone": "Telefone/WhatsApp",
            "shipping_address": "Endereco completo de entrega",
            "notes": "Observacoes",
        }
        widgets = {
            "shipping_address": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, product, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product
        sizes = [size.strip() for size in (product.sizes or "").replace("/", ",").replace(";", ",").split(",") if size.strip()]

        if not sizes:
            sizes = ["Confirmar tamanho"]

        self.fields["selected_size"].choices = [(size, size) for size in sizes]
