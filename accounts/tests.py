from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from .forms import RegisterForm
from .models import ClientProfile, StoreOrder, SupplierProduct, User
from .utils import cpf_hash, is_valid_cpf


class CPFValidationTests(TestCase):
    def test_valid_cpf_passes_check_digit_validation(self):
        self.assertTrue(is_valid_cpf("529.982.247-25"))

    def test_repeated_digits_are_invalid(self):
        self.assertFalse(is_valid_cpf("111.111.111-11"))

    def test_wrong_check_digits_are_invalid(self):
        self.assertFalse(is_valid_cpf("529.982.247-24"))

    def test_register_form_rejects_duplicate_cpf(self):
        cpf = "52998224725"
        user = User.objects.create_user(
            email="cliente@exemplo.com",
            password="Teste12345!",
            full_name="Cliente Exemplo",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash=cpf_hash(cpf),
            cpf_last_digits=cpf[-4:],
            phone="61999999999",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
        )

        form = RegisterForm(
            data={
                "full_name": "Outro Cliente",
                "preferred_name": "Outro",
                "email": "outro@exemplo.com",
                "password1": "Teste12345!",
                "password2": "Teste12345!",
                "cpf": "529.982.247-25",
                "phone": "61988888888",
                "address": "Outro endereco",
            },
            files={
                "residence_proof": SimpleUploadedFile("comprovante.pdf", b"pdf"),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Ja existe um cadastro com este CPF.", form.errors["cpf"])

    def test_register_form_rejects_invalid_cpf_digits(self):
        form = RegisterForm(
            data={
                "full_name": "Cliente Invalido",
                "preferred_name": "Cliente",
                "email": "invalido@exemplo.com",
                "password1": "Teste12345!",
                "password2": "Teste12345!",
                "cpf": "529.982.247-24",
                "phone": "61999999999",
                "address": "Endereco",
            },
            files={
                "residence_proof": SimpleUploadedFile("comprovante.pdf", b"pdf"),
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Informe um CPF valido.", form.errors["cpf"])


class RegistrationFlowTests(TestCase):
    def registration_payload(self, **overrides):
        data = {
            "full_name": "Cliente Teste",
            "preferred_name": "Cliente",
            "email": "cliente-teste@example.com",
            "password1": "Teste12345!",
            "password2": "Teste12345!",
            "cpf": "529.982.247-25",
            "phone": "61999999999",
            "address": "Rua Teste, 1",
        }
        data.update(overrides)

        return data

    @override_settings(PHONE_VERIFICATION_REQUIRED=False)
    def test_registration_can_continue_to_manual_review_without_phone_verification(self):
        data = self.registration_payload(
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
        )

        response = self.client.post(
            "/cadastro/",
            data=data,
        )
        user = User.objects.get(email="cliente-teste@example.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/painel/")
        self.assertTrue(user.profile.phone_verified)
        self.assertEqual(user.profile.phone_verification_code, "")

    @override_settings(DEBUG=False, PHONE_VERIFICATION_REQUIRED=True, ALLOWED_HOSTS=["testserver"])
    def test_phone_verification_code_is_hidden_outside_debug(self):
        user = User.objects.create_user(
            email="cliente-codigo@example.com",
            password="Teste12345!",
            full_name="Cliente Codigo",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash=cpf_hash("52998224725"),
            cpf_last_digits="4725",
            phone="61999999999",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            phone_verification_code="123456",
        )
        self.client.force_login(user)

        response = self.client.get("/verificar-telefone/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Codigo de desenvolvimento")
        self.assertNotContains(response, "123456")

    @patch("accounts.views.RegisterForm.save")
    def test_registration_storage_error_returns_form_message(self, mocked_save):
        mocked_save.side_effect = RuntimeError("storage unavailable")
        data = self.registration_payload(
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
        )

        response = self.client.post("/cadastro/", data=data)

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Nao foi possivel enviar o comprovante agora", status_code=500)
        self.assertEqual(User.objects.count(), 0)


class CsrfFailureTests(TestCase):
    def test_csrf_failure_redirects_to_login(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post("/login/", {"username": "cliente@example.com", "password": "senha"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/")


class StoreFlowTests(TestCase):
    def create_supplier_product(self, **overrides):
        data = {
            "supplier_code": "RC001",
            "name": "Sandalia Teste",
            "wholesale_price": Decimal("50.00"),
            "dropshipping_cost": Decimal("55.00"),
            "suggested_sale_price": Decimal("99.90"),
            "stock_quantity": 3,
            "sizes": "35,36",
            "is_active": True,
            "is_visible": True,
        }
        data.update(overrides)

        return SupplierProduct.objects.create(**data)

    def test_store_front_only_shows_visible_products_with_stock(self):
        visible_product = self.create_supplier_product(name="Produto Visivel")
        self.create_supplier_product(supplier_code="RC002", name="Produto Oculto", is_visible=False)
        self.create_supplier_product(supplier_code="RC003", name="Produto Sem Estoque", stock_quantity=0)

        response = self.client.get("/loja/")

        self.assertContains(response, visible_product.name)
        self.assertNotContains(response, "Produto Oculto")
        self.assertNotContains(response, "Produto Sem Estoque")

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="")
    def test_checkout_creates_pending_order_without_payment_token(self):
        product = self.create_supplier_product()

        response = self.client.post(
            f"/loja/produto/{product.id}/comprar/",
            {
                "selected_size": "35",
                "customer_name": "Cliente Teste",
                "customer_email": "cliente@example.com",
                "customer_phone": "61999999999",
                "shipping_address": "Rua Teste, 1",
                "notes": "",
                "accept_terms": "on",
            },
        )
        order = StoreOrder.objects.get()

        self.assertEqual(response.status_code, 302)
        self.assertIn(str(order.public_token), response["Location"])
        self.assertEqual(order.status, StoreOrder.PENDING_PAYMENT)
        self.assertEqual(order.total_amount, Decimal("99.90"))

    def test_public_order_page_does_not_use_sequential_order_code(self):
        product = self.create_supplier_product()
        order = StoreOrder.objects.create(
            product=product,
            product_name=product.name,
            supplier_code=product.supplier_code,
            selected_size="35",
            customer_name="Cliente Teste",
            customer_email="cliente@example.com",
            customer_phone="61999999999",
            shipping_address="Rua Teste, 1",
            unit_price=Decimal("99.90"),
            supplier_cost=Decimal("55.00"),
            total_amount=Decimal("99.90"),
            estimated_profit=Decimal("44.90"),
        )

        response = self.client.get(f"/loja/pedido/{order.order_code}/")

        self.assertEqual(response.status_code, 404)

    def test_supplier_panel_rejects_visible_product_below_cost(self):
        staff = User.objects.create_superuser(
            email="admin-loja@example.com",
            password="Teste12345!",
            full_name="Admin Loja",
            preferred_name="Admin",
        )
        product = self.create_supplier_product(is_visible=False)
        self.client.force_login(staff)

        response = self.client.post(
            "/gestao/fornecedor/produtos/",
            {
                "visible_products": [str(product.id)],
                f"price_{product.id}": "10.00",
            },
        )
        product.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(product.is_visible)

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="")
    def test_checkout_requires_terms_acceptance(self):
        product = self.create_supplier_product()

        response = self.client.post(
            f"/loja/produto/{product.id}/comprar/",
            {
                "selected_size": "35",
                "customer_name": "Cliente Teste",
                "customer_email": "cliente@example.com",
                "customer_phone": "61999999999",
                "shipping_address": "Rua Teste, 1",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(StoreOrder.objects.count(), 0)

    @patch("accounts.views.get_payment")
    def test_mercado_pago_webhook_marks_order_as_paid(self, mocked_get_payment):
        product = self.create_supplier_product()
        order = StoreOrder.objects.create(
            product=product,
            product_name=product.name,
            supplier_code=product.supplier_code,
            selected_size="35",
            customer_name="Cliente Teste",
            customer_email="cliente@example.com",
            customer_phone="61999999999",
            shipping_address="Rua Teste, 1",
            unit_price=Decimal("99.90"),
            supplier_cost=Decimal("55.00"),
            total_amount=Decimal("99.90"),
            estimated_profit=Decimal("44.90"),
        )
        mocked_get_payment.return_value = {
            "id": "123",
            "status": "approved",
            "external_reference": order.order_code,
        }

        response = self.client.post(
            "/loja/mercado-pago/webhook/",
            data={"data": {"id": "123"}},
            content_type="application/json",
        )
        order.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.status, StoreOrder.PAID)
        self.assertEqual(order.mercado_pago_payment_id, "123")
