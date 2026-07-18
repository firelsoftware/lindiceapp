from datetime import timedelta
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import ClientProfile, CreditSale, CreditSaleProduct, Debt, PersonalDebt, Product, ProductCost, StoreOrder, StoreSettings, Supplier, SupplierCatalogSource, SupplierProduct, User
from .store_shipping import shipping_choices_with_prices
from .utils import clean_digits, cpf_hash, is_valid_cpf


MAX_DOCUMENT_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_DOCUMENT_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp", "application/pdf")


def validate_document_file(uploaded_file):
    if not uploaded_file:
        return uploaded_file

    if uploaded_file.size > MAX_DOCUMENT_UPLOAD_SIZE:
        raise ValidationError("O arquivo deve ter no maximo 10MB.")

    content_type = getattr(uploaded_file, "content_type", "")

    if content_type and content_type not in ALLOWED_DOCUMENT_CONTENT_TYPES:
        raise ValidationError("Envie uma imagem (JPEG, PNG, WEBP) ou um PDF.")

    return uploaded_file


SHOE_SIZE_CHOICES = [(str(size), str(size)) for size in range(33, 45)]
CHILD_SHOE_SIZE_CHOICES = [(str(size), str(size)) for size in range(14, 33)]
NOT_APPLICABLE_SHOE_SIZE = "Nao se aplica"
GENERAL_SHOE_SIZE_CHOICES = [("", "Nao se aplica")] + CHILD_SHOE_SIZE_CHOICES + SHOE_SIZE_CHOICES
CHECKOUT_PAYMENT_ONLINE = "online"
CHECKOUT_PAYMENT_CREDIT = "credit"
CHECKOUT_PAYMENT_METHOD_CHOICES = (
    (CHECKOUT_PAYMENT_ONLINE, "Pagar agora"),
    (CHECKOUT_PAYMENT_CREDIT, "Solicitar crediario para analise"),
)


def client_label(user):
    profile_id = getattr(getattr(user, "profile", None), "id", user.id)
    return f"ID {profile_id:04d} - {user.full_name}"


class RegisterForm(UserCreationForm):
    full_name = forms.CharField(label="Nome completo *", max_length=150)
    preferred_name = forms.CharField(label="Como prefere ser chamado(a) *", max_length=80)
    email = forms.EmailField(label="Email *")
    cpf = forms.CharField(label="CPF", max_length=14, required=False)
    rg_number = forms.CharField(label="RG", max_length=20, required=False)
    phone = forms.CharField(label="Telefone", max_length=20, required=False)
    address = forms.CharField(label="Endereco", widget=forms.Textarea, required=False)
    identity_document = forms.FileField(
        label="Foto ou PDF do RG (frente)",
        required=False,
    )
    identity_document_back = forms.FileField(
        label="Foto ou PDF do RG (verso)",
        required=False,
    )
    residence_proof = forms.FileField(
        label="Comprovante de residencia no nome do cliente",
        required=False,
    )
    marketing_opt_in = forms.BooleanField(
        label="Quero receber promocoes e novidades por email",
        required=False,
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
            "rg_number",
            "phone",
            "address",
            "identity_document",
            "identity_document_back",
            "residence_proof",
        )

    def __init__(self, *args, **kwargs):
        self.credit_mode = kwargs.pop("credit_mode", False)
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Senha *"
        self.fields["password2"].label = "Confirmacao de senha *"
        if self.credit_mode:
            self.fields["cpf"].label = "CPF *"
            self.fields["cpf"].required = True
            self.fields["rg_number"].label = "RG *"
            self.fields["phone"].label = "Telefone *"
            self.fields["address"].label = "Endereco *"
            self.fields["identity_document"].label = "Foto ou PDF do RG (frente) *"
            self.fields["identity_document_back"].label = "Foto ou PDF do RG (verso) *"
            self.fields["residence_proof"].label = "Comprovante de residencia no nome do cliente *"
            for field_name in ("rg_number", "phone", "address", "identity_document", "identity_document_back", "residence_proof"):
                self.fields[field_name].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].lower()

        if User.objects.filter(email=email).exists():
            raise ValidationError("Ja existe um cadastro com este email.")

        return email

    def clean_identity_document(self):
        return validate_document_file(self.cleaned_data.get("identity_document"))

    def clean_identity_document_back(self):
        return validate_document_file(self.cleaned_data.get("identity_document_back"))

    def clean_residence_proof(self):
        return validate_document_file(self.cleaned_data.get("residence_proof"))

    def clean_cpf(self):
        cpf = self.cleaned_data.get("cpf", "")
        cpf_digits = clean_digits(cpf)

        if not cpf_digits and not self.credit_mode:
            return ""

        if len(cpf_digits) != 11:
            raise ValidationError("Informe um CPF com 11 numeros.")

        if not is_valid_cpf(cpf_digits):
            raise ValidationError("Informe um CPF valido.")

        if ClientProfile.objects.filter(cpf_hash=cpf_hash(cpf_digits)).exists():
            raise ValidationError("Ja existe um cadastro com este CPF.")

        return cpf_digits

    def clean_rg_number(self):
        rg_number = self.cleaned_data.get("rg_number", "").strip()

        if not rg_number:
            return ""

        if len(rg_number) < 5:
            raise ValidationError("Informe um RG valido.")

        return rg_number

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]

        if commit:
            user.save()

            profile = ClientProfile(
                user=user,
                rg_number=self.cleaned_data.get("rg_number", ""),
                phone=self.cleaned_data.get("phone", ""),
                address=self.cleaned_data.get("address", ""),
                identity_document=self.cleaned_data.get("identity_document") or "",
                identity_document_back=self.cleaned_data.get("identity_document_back") or "",
                residence_proof=self.cleaned_data.get("residence_proof") or "",
                marketing_opt_in=self.cleaned_data.get("marketing_opt_in", False),
                registration_status=ClientProfile.PENDING if self.credit_mode else ClientProfile.APPROVED,
            )
            if self.cleaned_data["cpf"]:
                profile.set_cpf(self.cleaned_data["cpf"])
            else:
                profile.cpf_hash = ClientProfile.generate_cpf_placeholder()
                profile.cpf_last_digits = ""

            profile.save()

        return user


class CheckoutCpfForm(forms.Form):
    cpf = forms.CharField(label="CPF *", max_length=14)

    def __init__(self, *args, **kwargs):
        self.profile = kwargs.pop("profile")
        super().__init__(*args, **kwargs)

    def clean_cpf(self):
        cpf = self.cleaned_data["cpf"]
        cpf_digits = clean_digits(cpf)

        if len(cpf_digits) != 11:
            raise ValidationError("Informe um CPF com 11 numeros.")

        if not is_valid_cpf(cpf_digits):
            raise ValidationError("Informe um CPF valido.")

        existing = ClientProfile.objects.filter(cpf_hash=cpf_hash(cpf_digits)).exclude(pk=self.profile.pk)
        if existing.exists():
            raise ValidationError("Ja existe um cadastro com este CPF.")

        return cpf_digits

    def save(self):
        self.profile.set_cpf(self.cleaned_data["cpf"])
        self.profile.save(update_fields=["cpf_hash", "cpf_last_digits"])
        return self.profile


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

        if photo and photo.size > MAX_DOCUMENT_UPLOAD_SIZE:
            raise ValidationError("O arquivo deve ter no maximo 10MB.")

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
    guest_name = forms.CharField(label="Nome do cliente novo", max_length=150, required=False)
    guest_email = forms.EmailField(label="Email do cliente novo", required=False)
    guest_phone = forms.CharField(label="Telefone do cliente novo", max_length=20, required=False)

    class Meta:
        model = CreditSale
        fields = ("client", "guest_name", "guest_email", "guest_phone", "description", "total_amount")
        labels = {
            "client": "Cliente",
            "description": "Descricao da venda",
            "total_amount": "Valor total",
        }
        help_texts = {
            "client": "Use este campo para quem ja tem cadastro aprovado. Se ficar em branco, preencha os dados do cliente novo abaixo.",
            "guest_email": "Para cliente novo, o link publico pode seguir so com email para Pix ou cartao.",
            "description": "Monte a venda e deixe o cliente escolher o vencimento da primeira parcela em ate 30 dias.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = User.objects.filter(
            profile__registration_status=ClientProfile.APPROVED,
            is_staff=False,
        ).order_by("full_name")
        self.fields["client"].label_from_instance = client_label
        self.fields["client"].required = False
        self.fields["client"].empty_label = "Venda sem cliente"
        self.fields["description"].required = False

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get("client")
        guest_name = (cleaned_data.get("guest_name") or "").strip()
        guest_email = (cleaned_data.get("guest_email") or "").strip()
        guest_phone = (cleaned_data.get("guest_phone") or "").strip()

        if client:
            cleaned_data["guest_name"] = ""
            cleaned_data["guest_email"] = ""
            cleaned_data["guest_phone"] = ""
            return cleaned_data

        if not guest_name and not guest_email and not guest_phone:
            cleaned_data["guest_name"] = ""
            cleaned_data["guest_email"] = ""
            cleaned_data["guest_phone"] = ""
            return cleaned_data

        if not guest_name:
            self.add_error("guest_name", "Informe o nome do cliente novo ou selecione um cliente cadastrado.")

        if not guest_email:
            self.add_error("guest_email", "Informe o email do cliente novo para enviar o link.")

        cleaned_data["guest_name"] = guest_name
        cleaned_data["guest_email"] = guest_email
        cleaned_data["guest_phone"] = guest_phone
        return cleaned_data


class ManualDebtForm(forms.ModelForm):
    create_payment_link = forms.BooleanField(
        label="Gerar link para o cliente escolher pagamento e parcelas",
        required=False,
        help_text="Use para clientes aprovados. O vencimento sera a sugestao da primeira parcela.",
    )

    class Meta:
        model = Debt
        fields = ("client", "description", "amount", "due_date")
        labels = {
            "client": "Cliente",
            "description": "Descricao do debito",
            "amount": "Valor",
            "due_date": "Data de vencimento",
        }
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }
        help_texts = {
            "due_date": "Para link de pagamento, use uma data entre hoje e os proximos 30 dias.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = User.objects.filter(
            profile__registration_status__in=[ClientProfile.PENDING, ClientProfile.APPROVED],
            is_staff=False,
        ).order_by("full_name")
        self.fields["client"].label_from_instance = client_label

    def clean(self):
        cleaned_data = super().clean()

        if not cleaned_data.get("create_payment_link"):
            return cleaned_data

        client = cleaned_data.get("client")
        due_date = cleaned_data.get("due_date")

        if client and client.profile.registration_status != ClientProfile.APPROVED:
            self.add_error("client", "Apenas clientes aprovados podem receber link de pagamento.")

        if due_date:
            today = timezone.localdate()
            max_due_date = today + timedelta(days=30)

            if due_date < today or due_date > max_due_date:
                self.add_error("due_date", "Para gerar link, o primeiro vencimento deve ficar entre hoje e os proximos 30 dias.")

        return cleaned_data


class StoreSettingsForm(forms.ModelForm):
    class Meta:
        model = StoreSettings
        fields = ("cashback_percent", "cashback_max_redeem_percent", "referral_bonus")
        labels = {
            "cashback_percent": "Cashback por compra (%)",
            "cashback_max_redeem_percent": "Máximo de resgate por compra (%)",
            "referral_bonus": "Bônus de indicação (R$)",
        }
        widgets = {
            "cashback_percent": forms.NumberInput(attrs={"min": "0", "max": "100", "step": "0.5"}),
            "cashback_max_redeem_percent": forms.NumberInput(attrs={"min": "0", "max": "100", "step": "1"}),
            "referral_bonus": forms.NumberInput(attrs={"min": "0", "step": "1"}),
        }

    def clean_cashback_percent(self):
        value = self.cleaned_data["cashback_percent"]
        if value < 0 or value > 100:
            raise ValidationError("Informe um percentual entre 0 e 100.")
        return value

    def clean_cashback_max_redeem_percent(self):
        value = self.cleaned_data["cashback_max_redeem_percent"]
        if value < 0 or value > 100:
            raise ValidationError("Informe um percentual entre 0 e 100.")
        return value


class PromoEmailForm(forms.Form):
    subject = forms.CharField(label="Assunto", max_length=150)
    message = forms.CharField(
        label="Mensagem",
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Escreva a promocao ou novidade..."}),
    )


class DocesEMaisProductForm(forms.ModelForm):
    featured = forms.BooleanField(label="Destacar produto", required=False)
    promo_text = forms.CharField(
        label="Promoção / chamada",
        required=False,
        max_length=80,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Especial da semana"}),
    )
    badge = forms.CharField(
        label="Etiqueta",
        required=False,
        max_length=40,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Muito recheio"}),
    )

    class Meta:
        model = SupplierProduct
        fields = ("name", "description", "image_file", "is_visible", "featured", "promo_text", "badge")
        labels = {
            "name": "Nome do doce",
            "description": "Descrição",
            "image_file": "Foto",
            "is_visible": "Mostrar na página",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        raw = getattr(self.instance, "raw_data", None) or {}
        if not self.is_bound:
            self.fields["featured"].initial = bool(raw.get("featured"))
            self.fields["promo_text"].initial = raw.get("promo_text", "")
            self.fields["badge"].initial = raw.get("badge", "")
        self.fields["image_file"].required = False
        self.fields["is_visible"].required = False

    def save(self, commit=True):
        product = super().save(commit=False)
        raw = dict(product.raw_data or {})
        raw["featured"] = bool(self.cleaned_data.get("featured"))
        raw["promo_text"] = (self.cleaned_data.get("promo_text") or "").strip()
        raw["badge"] = (self.cleaned_data.get("badge") or "").strip()
        product.raw_data = raw
        if commit:
            product.save()
        return product


class PersonalDebtForm(forms.ModelForm):
    class Meta:
        model = PersonalDebt
        fields = ("title", "entry_type", "category", "color", "amount", "due_date", "notes")
        labels = {
            "title": "Descricao complementar",
            "entry_type": "Tipo",
            "category": "Categoria",
            "color": "Cor da etiqueta",
            "amount": "Valor",
            "due_date": "Vencimento",
            "notes": "Observacao",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ex.: Apto centro, freela cliente Ana, parcela de julho"}),
            "color": forms.TextInput(attrs={"type": "color"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Opcional: detalhes para lembrar depois"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]

        if amount <= 0:
            raise ValidationError("Informe um valor maior que zero.")

        return amount


class SupplierCatalogSourceForm(forms.ModelForm):
    class Meta:
        model = SupplierCatalogSource
        fields = (
            "display_name",
            "catalog_url",
            "catalog_format",
            "purchase_flow",
            "supplier_panel_note",
            "customer_notice",
            "is_active",
        )
        labels = {
            "display_name": "Nome da fonte",
            "catalog_url": "URL do catalogo",
            "catalog_format": "Formato",
            "purchase_flow": "Como esse fornecedor fecha a venda",
            "supplier_panel_note": "Observacao interna",
            "customer_notice": "Mensagem para o cliente",
            "is_active": "Fonte ativa",
        }
        help_texts = {
            "catalog_url": "Cole aqui a URL atual do CSV ou XML. Voce pode trocar quando quiser.",
            "customer_notice": "Esse texto aparece para o cliente quando a compra depender de confirmacao manual.",
        }
        widgets = {
            "supplier_panel_note": forms.Textarea(attrs={"rows": 3}),
            "customer_notice": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_color(self):
        color = (self.cleaned_data["color"] or "").strip()

        if len(color) != 7 or not color.startswith("#"):
            raise ValidationError("Escolha uma cor valida.")

        hex_digits = color[1:]
        try:
            int(hex_digits, 16)
        except ValueError as exc:
            raise ValidationError("Escolha uma cor valida.") from exc

        return color.lower()


class InstallmentChoiceForm(forms.Form):
    first_due_date = forms.DateField(
        label="Vencimento da primeira parcela",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    payment_method = forms.ChoiceField(
        label="Forma de pagamento",
        choices=CreditSale.PAYMENT_METHOD_CHOICES,
        widget=forms.RadioSelect,
    )
    installments = forms.ChoiceField(label="Parcelas", required=False)
    remainder_payment_method = forms.ChoiceField(
        label="Como pagar o restante fora do crediario",
        required=False,
        choices=CreditSale.REMAINDER_PAYMENT_CHOICES,
    )
    accept_terms = forms.BooleanField(
        label="Li e aceito os termos de uso e a politica de privacidade",
        required=True,
    )
    use_welcome_discount = forms.BooleanField(label="Usar voucher de 5% nesta compra", required=False)

    def __init__(self, *args, sale, **kwargs):
        super().__init__(*args, **kwargs)
        self.sale = sale
        today = timezone.localdate()
        max_due_date = today + timedelta(days=30)
        self.fields["first_due_date"].initial = sale.first_due_date
        self.fields["first_due_date"].widget.attrs.update(
            {
                "min": today.isoformat(),
                "max": max_due_date.isoformat(),
            }
        )
        if not settings.CARD_PAYMENT_ENABLED:
            self.fields["payment_method"].choices = [
                choice for choice in CreditSale.PAYMENT_METHOD_CHOICES if choice[0] != CreditSale.CARD
            ]
            self.fields["remainder_payment_method"].choices = [
                choice for choice in CreditSale.REMAINDER_PAYMENT_CHOICES if choice[0] != CreditSale.REMAINDER_CARD
            ]
        self.fields["installments"].choices = [("", "Selecione")] + [
            (option["installments"], f"{option['installments']}x")
            for option in sale.card_options()
        ]

    def clean_installments(self):
        value = self.cleaned_data.get("installments")

        if not value:
            return None

        return int(value)

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get("payment_method")
        installments = cleaned_data.get("installments")
        first_due_date = cleaned_data.get("first_due_date")
        remainder_payment_method = cleaned_data.get("remainder_payment_method")
        today = timezone.localdate()
        max_due_date = today + timedelta(days=30)

        if payment_method in {CreditSale.CARD, CreditSale.CREDIT} and installments is None:
            raise ValidationError("Escolha a quantidade de parcelas.")

        if payment_method == CreditSale.CREDIT:
            if first_due_date is None:
                raise ValidationError("Escolha o vencimento da primeira parcela.")

            if first_due_date < today or first_due_date > max_due_date:
                raise ValidationError("O primeiro vencimento deve ficar entre hoje e os proximos 30 dias.")

            if self.sale.credit_remainder_amount() > Decimal("0.00") and not remainder_payment_method:
                raise ValidationError("Escolha como pagar o restante fora do crediario.")

        if installments is not None:
            options = self.sale.card_options() if payment_method == CreditSale.CARD else self.sale.credit_options()
            valid_installments = {option["installments"] for option in options}

            if installments not in valid_installments:
                raise ValidationError("Escolha uma opcao de parcela disponivel para esta forma de pagamento.")

        return cleaned_data


class CreditSaleProductForm(forms.ModelForm):
    SIZE_GROUP_NOT_APPLICABLE = "na"
    SIZE_GROUP_ADULT = "adult"
    SIZE_GROUP_CHILD = "child"

    class Meta:
        model = CreditSaleProduct
        fields = ("product", "name", "brand", "supplier", "unit_price", "image", "shoe_size", "notes")
        labels = {
            "product": "Produto ja cadastrado",
            "name": "Produto",
            "brand": "Marca",
            "supplier": "Fornecedor",
            "unit_price": "Valor",
            "image": "Foto do produto",
            "shoe_size": "Tamanho",
            "notes": "Observacoes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(status=Product.AVAILABLE).order_by("product_code")
        self.fields["product"].required = False
        self.fields["name"].required = False
        self.fields["brand"].required = False
        self.fields["image"].required = False
        self.fields["supplier"].required = False
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        self.fields["supplier"].empty_label = "Sem fornecedor"
        self.fields["unit_price"].required = False
        self.fields["size_group"] = forms.ChoiceField(
            label="Tipo de tamanho",
            choices=[
                (self.SIZE_GROUP_NOT_APPLICABLE, "Nao se aplica"),
                (self.SIZE_GROUP_ADULT, "Adulto"),
                (self.SIZE_GROUP_CHILD, "Crianca"),
            ],
        )
        initial_size = self.initial.get("shoe_size") or getattr(self.instance, "shoe_size", "")
        if initial_size in ("", NOT_APPLICABLE_SHOE_SIZE):
            initial_group = self.SIZE_GROUP_NOT_APPLICABLE
        else:
            initial_group = self.SIZE_GROUP_CHILD if str(initial_size).isdigit() and int(initial_size) <= 32 else self.SIZE_GROUP_ADULT
        self.fields["size_group"].initial = initial_group
        self.fields["shoe_size"].widget = forms.Select(
            choices=GENERAL_SHOE_SIZE_CHOICES
        )
        self.fields["notes"].required = False
        self.fields["notes"].widget = forms.Textarea(attrs={"rows": 1, "data-autosize": "true", "placeholder": "Observacoes opcionais"})
        self.order_fields(["product", "name", "brand", "supplier", "unit_price", "image", "size_group", "shoe_size", "notes"])

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        size_group = cleaned_data.get("size_group")
        shoe_size = cleaned_data.get("shoe_size")

        if product:
            cleaned_data["name"] = cleaned_data.get("name") or product.name
            cleaned_data["brand"] = cleaned_data.get("brand") or product.brand
            cleaned_data["supplier"] = cleaned_data.get("supplier") or product.supplier
            cleaned_data["unit_price"] = cleaned_data.get("unit_price") or product.sale_price
            cleaned_data["shoe_size"] = cleaned_data.get("shoe_size") or product.shoe_size or NOT_APPLICABLE_SHOE_SIZE
            shoe_size = cleaned_data["shoe_size"]
            if shoe_size in ("", NOT_APPLICABLE_SHOE_SIZE):
                cleaned_data["size_group"] = self.SIZE_GROUP_NOT_APPLICABLE
                size_group = self.SIZE_GROUP_NOT_APPLICABLE
            elif str(shoe_size).isdigit():
                cleaned_data["size_group"] = self.SIZE_GROUP_CHILD if int(shoe_size) <= 32 else self.SIZE_GROUP_ADULT
                size_group = cleaned_data["size_group"]

        if not product and not cleaned_data.get("name"):
            self.add_error("name", "Informe o produto da venda.")

        if size_group == self.SIZE_GROUP_NOT_APPLICABLE:
            cleaned_data["shoe_size"] = NOT_APPLICABLE_SHOE_SIZE
        elif not shoe_size:
            self.add_error("shoe_size", "Escolha o tamanho do calcado.")
        elif size_group == self.SIZE_GROUP_CHILD and shoe_size not in dict(CHILD_SHOE_SIZE_CHOICES):
            self.add_error("shoe_size", "Escolha um tamanho infantil entre 14 e 32.")
        elif size_group == self.SIZE_GROUP_ADULT and shoe_size not in dict(SHOE_SIZE_CHOICES):
            self.add_error("shoe_size", "Escolha um tamanho adulto entre 33 e 44.")

        return cleaned_data


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
        fields = ("name", "brand", "supplier", "image", "shoe_size", "purchase_price", "sale_price", "notes", "status")
        labels = {
            "name": "Nome do produto",
            "brand": "Marca",
            "supplier": "Fornecedor",
            "image": "Foto do produto",
            "shoe_size": "Tamanho",
            "purchase_price": "Valor de compra",
            "sale_price": "Valor de venda",
            "notes": "Observacoes",
            "status": "Status",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].required = False
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        self.fields["supplier"].empty_label = "Sem fornecedor"
        self.fields["shoe_size"] = forms.ChoiceField(label="Tamanho", required=False, choices=GENERAL_SHOE_SIZE_CHOICES)


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ("name", "whatsapp", "notes", "is_active")
        labels = {
            "name": "Nome do fornecedor",
            "whatsapp": "WhatsApp (opcional)",
            "notes": "Observacoes",
            "is_active": "Ativo",
        }


class PartnerBagForm(forms.ModelForm):
    class Meta:
        model = SupplierProduct
        fields = ("name", "suggested_sale_price", "compare_at_price", "stock_quantity", "sizes", "image_file")
        labels = {
            "name": "Nome da bolsa",
            "suggested_sale_price": "Preço de venda (R$)",
            "compare_at_price": "Preço 'de' / promoção (opcional)",
            "stock_quantity": "Quantidade em estoque",
            "sizes": "Medida/tamanho (opcional)",
            "image_file": "Foto da bolsa",
        }
        help_texts = {
            "compare_at_price": "Se maior que o preço de venda, aparece como promoção (de/por).",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex.: Bolsa tiracolo caramelo"}),
            "suggested_sale_price": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image_file"].required = True
        self.fields["suggested_sale_price"].required = True

    def clean(self):
        cleaned = super().clean()
        price = cleaned.get("suggested_sale_price")
        compare = cleaned.get("compare_at_price")
        if compare and price and compare <= price:
            self.add_error("compare_at_price", "O preço 'de' deve ser maior que o preço de venda.")
        return cleaned


class SupplierProductEditForm(forms.ModelForm):
    MATERIAL_CHOICES = [
        ("", "Nao se aplica"),
        ("Prata", "Prata"),
        ("Folheado prata", "Folheado prata"),
        ("Ouro", "Ouro"),
        ("Folheado ouro", "Folheado ouro"),
        ("Aco", "Aco"),
    ]

    # Campos extras guardados em raw_data (variam por tipo de produto)
    modelo = forms.CharField(label="Modelo", required=False)
    cor = forms.CharField(label="Cor", required=False)
    material = forms.ChoiceField(label="Material (joias)", required=False, choices=MATERIAL_CHOICES)
    medida_cm = forms.CharField(label="Medida em cm (colar/pulseira)", required=False)

    class Meta:
        model = SupplierProduct
        fields = (
            "name", "brand", "sizes", "suggested_sale_price", "compare_at_price",
            "stock_quantity", "is_visible", "is_active", "status_note",
        )
        labels = {
            "name": "Nome do produto",
            "brand": "Marca",
            "sizes": "Tamanhos (separados por virgula)",
            "suggested_sale_price": "Preco de venda (R$)",
            "compare_at_price": "Preco 'de' / promocao (opcional)",
            "stock_quantity": "Estoque",
            "is_visible": "Mostrar na loja",
            "is_active": "Ativo",
            "status_note": "Observacao interna",
        }
        help_texts = {
            "compare_at_price": "Se maior que o preco de venda, a loja mostra como promocao (de/por).",
            "is_visible": "Desmarque para suspender o produto (sai da loja).",
        }

    EXTRA_KEYS = ("modelo", "cor", "material", "medida_cm")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        raw = getattr(self.instance, "raw_data", None) or {}
        for key in self.EXTRA_KEYS:
            if not self.is_bound and raw.get(key):
                self.fields[key].initial = raw.get(key)

    def clean(self):
        cleaned = super().clean()
        price = cleaned.get("suggested_sale_price")
        compare = cleaned.get("compare_at_price")
        if compare and price and compare <= price:
            self.add_error("compare_at_price", "O preco 'de' deve ser maior que o preco de venda.")
        return cleaned

    def save(self, commit=True):
        product = super().save(commit=False)
        raw = dict(product.raw_data or {})
        for key in self.EXTRA_KEYS:
            value = (self.cleaned_data.get(key) or "").strip()
            if value:
                raw[key] = value
            else:
                raw.pop(key, None)
        product.raw_data = raw
        if commit:
            product.save()
        return product


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
    shipping_state = forms.ChoiceField(label="Estado / regiao de entrega")
    payment_method = forms.ChoiceField(
        label="Forma de pagamento",
        choices=CHECKOUT_PAYMENT_METHOD_CHOICES,
        initial=CHECKOUT_PAYMENT_ONLINE,
        required=False,
        widget=forms.RadioSelect,
    )
    use_welcome_discount = forms.BooleanField(label="Usar voucher de 5% nesta compra", required=False)
    accept_terms = forms.BooleanField(
        label="Li e aceito os termos de uso e a politica de privacidade",
        required=True,
    )

    class Meta:
        model = StoreOrder
        fields = ("selected_size", "customer_name", "customer_email", "customer_phone", "shipping_state", "shipping_address", "notes")
        labels = {
            "customer_name": "Nome completo",
            "customer_email": "Email",
            "customer_phone": "Telefone/WhatsApp",
            "shipping_state": "Estado / regiao para calcular o frete",
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
        self.fields["shipping_state"].choices = [("", "Selecione")] + shipping_choices_with_prices()

    def clean(self):
        cleaned_data = super().clean()

        if not self.product.is_active or not self.product.is_visible or self.product.stock_quantity <= 0:
            raise ValidationError("Este produto nao esta disponivel para compra no momento.")

        if self.product.suggested_sale_price <= 0:
            raise ValidationError("Este produto ainda nao tem preco definido para venda.")

        return cleaned_data

    def clean_payment_method(self):
        return self.cleaned_data.get("payment_method") or CHECKOUT_PAYMENT_ONLINE


class CartCheckoutForm(forms.Form):
    customer_name = forms.CharField(label="Nome completo", max_length=150)
    customer_email = forms.EmailField(label="Email")
    customer_phone = forms.CharField(label="Telefone/WhatsApp", max_length=30)
    shipping_state = forms.ChoiceField(label="Estado / regiao para calcular o frete")
    shipping_address = forms.CharField(label="Endereco completo de entrega", widget=forms.Textarea(attrs={"rows": 4}))
    notes = forms.CharField(label="Observacoes", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    payment_method = forms.ChoiceField(
        label="Forma de pagamento",
        choices=CHECKOUT_PAYMENT_METHOD_CHOICES,
        initial=CHECKOUT_PAYMENT_ONLINE,
        required=False,
        widget=forms.RadioSelect,
    )
    use_welcome_discount = forms.BooleanField(label="Usar voucher de 5% nesta compra", required=False)
    use_cashback = forms.BooleanField(label="Usar meu cashback nesta compra", required=False)
    accept_terms = forms.BooleanField(
        label="Li e aceito os termos de uso e a politica de privacidade",
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shipping_state"].choices = [("", "Selecione")] + shipping_choices_with_prices()

    def clean_payment_method(self):
        return self.cleaned_data.get("payment_method") or CHECKOUT_PAYMENT_ONLINE
