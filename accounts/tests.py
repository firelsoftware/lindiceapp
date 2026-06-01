from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from .forms import RegisterForm
from .models import ClientProfile, CreditSale, CreditSaleProduct, Debt, Notification, PaymentAlert, StoreOrder, SupplierProduct, User
from .notifications import generate_due_notifications
from .payments import create_credit_sale_card_preference
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


class CreditSalePaymentChoiceTests(TestCase):
    def create_client(self):
        user = User.objects.create_user(
            email="cliente-compra@example.com",
            password="Teste12345!",
            full_name="Cliente Compra",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash=cpf_hash("52998224725"),
            cpf_last_digits="4725",
            phone="61999999999",
            phone_verified=True,
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )

        return user

    def create_sale(self, user, **overrides):
        data = {
            "client": user,
            "description": "Bota teste",
            "total_amount": Decimal("200.00"),
            "max_installments_allowed": 10,
            "first_due_date": "2026-06-10",
        }
        data.update(overrides)

        return CreditSale.objects.create(**data)

    @override_settings(STORE_PIX_KEY="d92f4cae-454c-4f33-97b2-6a513b292b24")
    def test_pix_choice_applies_discount_without_debts(self):
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.PIX,
                "installments": "",
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertRedirects(response, f"/pagamento/pix/{sale.id}/")
        self.assertEqual(sale.status, CreditSale.ACCEPTED)
        self.assertEqual(sale.selected_payment_method, CreditSale.PIX)
        self.assertEqual(sale.selected_total_with_interest, Decimal("171.00"))
        self.assertEqual(sale.welcome_discount_amount, Decimal("10.00"))
        user.profile.refresh_from_db()
        self.assertTrue(user.profile.first_purchase_discount_used)
        self.assertEqual(Debt.objects.count(), 0)

    @override_settings(STORE_PIX_KEY="d92f4cae-454c-4f33-97b2-6a513b292b24")
    def test_pix_page_shows_discounted_total_and_key(self):
        user = self.create_client()
        sale = self.create_sale(user)
        sale.choose_payment(CreditSale.PIX)
        self.client.force_login(user)

        response = self.client.get(f"/pagamento/pix/{sale.id}/")

        self.assertContains(response, "R$ 171,00")
        self.assertContains(response, "d92f4cae-454c-4f33-97b2-6a513b292b24")

    def test_store_front_announces_available_welcome_discount(self):
        user = self.create_client()
        self.client.force_login(user)

        response = self.client.get("/loja/")

        self.assertContains(response, "Presente de boas-vindas")
        self.assertContains(response, "5% OFF")

    def test_pix_page_is_private_to_sale_owner(self):
        user = self.create_client()
        sale = self.create_sale(user)
        sale.choose_payment(CreditSale.PIX)
        other_user = User.objects.create_user(
            email="outro-cliente@example.com",
            password="Teste12345!",
            full_name="Outro Cliente",
            preferred_name="Outro",
        )
        self.client.force_login(other_user)

        response = self.client.get(f"/pagamento/pix/{sale.id}/")

        self.assertEqual(response.status_code, 404)

    def test_card_option_is_not_available_to_customer(self):
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CARD,
                "installments": "3",
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Opcao ainda nao disponivel")
        self.assertEqual(sale.status, CreditSale.PENDING)

    def test_card_choice_has_interest_only_from_six_installments(self):
        user = self.create_client()
        sale = self.create_sale(user)

        self.assertEqual(sale.card_options()[4]["monthly_rate"], Decimal("0.00"))
        self.assertGreater(sale.card_options()[5]["monthly_rate"], Decimal("0.00"))

    @override_settings(CARD_PAYMENT_ENABLED=True)
    @patch("accounts.views.create_credit_sale_card_preference")
    def test_enabled_card_choice_redirects_to_mercado_pago(self, mocked_preference):
        mocked_preference.return_value = {
            "id": "pref-123",
            "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-123",
        }
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CARD,
                "installments": "5",
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertRedirects(
            response,
            "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-123",
            fetch_redirect_response=False,
        )
        self.assertEqual(sale.mercado_pago_preference_id, "pref-123")
        self.assertEqual(sale.selected_payment_method, CreditSale.CARD)

    @patch("accounts.views.get_payment")
    def test_mercado_pago_webhook_marks_credit_sale_as_paid(self, mocked_get_payment):
        user = self.create_client()
        sale = self.create_sale(user)
        sale.choose_payment(CreditSale.CARD, 5)
        mocked_get_payment.return_value = {
            "id": "payment-123",
            "status": "approved",
            "external_reference": f"credit-sale:{sale.id}",
        }

        response = self.client.post(
            "/loja/mercado-pago/webhook/",
            data={"data": {"id": "payment-123"}},
            content_type="application/json",
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sale.payment_status, CreditSale.PAYMENT_PAID)
        self.assertEqual(sale.mercado_pago_payment_id, "payment-123")

    @patch("accounts.views.get_payment")
    def test_mercado_pago_webhook_records_rejected_credit_sale(self, mocked_get_payment):
        user = self.create_client()
        sale = self.create_sale(user)
        sale.choose_payment(CreditSale.CARD, 5)
        mocked_get_payment.return_value = {
            "id": "payment-rejected",
            "status": "rejected",
            "status_detail": "cc_rejected_other_reason",
            "external_reference": f"credit-sale:{sale.id}",
        }

        response = self.client.post(
            "/loja/mercado-pago/webhook/",
            data={"data": {"id": "payment-rejected"}},
            content_type="application/json",
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sale.payment_status, CreditSale.PAYMENT_FAILED)
        self.assertTrue(PaymentAlert.objects.filter(credit_sale=sale, payment_id="payment-rejected").exists())

        self.client.force_login(user)
        retry_response = self.client.get(f"/parcelamento/{sale.id}/")

        self.assertEqual(retry_response.status_code, 200)

    def test_credit_choice_creates_debts(self):
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CREDIT,
                "installments": "2",
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(sale.selected_payment_method, CreditSale.CREDIT)
        self.assertEqual(Debt.objects.filter(credit_sale=sale).count(), 2)

    def test_changing_credit_choice_replaces_existing_debts(self):
        user = self.create_client()
        sale = self.create_sale(user)
        sale.refresh_from_db()

        sale.choose_payment(CreditSale.CREDIT, 2)
        sale.choose_payment(CreditSale.CREDIT, 1)

        self.assertEqual(Debt.objects.filter(credit_sale=sale).count(), 1)

    def test_welcome_discount_is_used_once_and_does_not_change_previous_debt(self):
        user = self.create_client()
        previous_debt = Debt.objects.create(
            client=user,
            description="Debito anterior",
            amount=Decimal("80.00"),
            due_date="2026-06-05",
        )
        first_sale = self.create_sale(user, first_due_date=datetime(2026, 6, 10).date())
        second_sale = self.create_sale(user, description="Segunda compra", first_due_date=datetime(2026, 7, 10).date())

        first_sale.choose_payment(CreditSale.CREDIT, 1)
        second_sale.choose_payment(CreditSale.CREDIT, 1)
        previous_debt.refresh_from_db()
        first_sale.refresh_from_db()
        second_sale.refresh_from_db()

        self.assertEqual(previous_debt.amount, Decimal("80.00"))
        self.assertEqual(first_sale.welcome_discount_amount, Decimal("10.00"))
        self.assertEqual(first_sale.selected_total_with_interest, Decimal("190.00"))
        self.assertEqual(second_sale.welcome_discount_amount, Decimal("0.00"))
        self.assertEqual(second_sale.selected_total_with_interest, Decimal("200.00"))

    def test_credit_choice_rejects_installment_below_minimum(self):
        user = self.create_client()
        sale = self.create_sale(user, total_amount=Decimal("100.00"))
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CREDIT,
                "installments": "2",
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escolha uma opcao de parcela disponivel")
        self.assertEqual(sale.status, CreditSale.PENDING)

    def test_payment_choice_requires_terms_acceptance(self):
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.PIX,
                "installments": "",
            },
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sale.status, CreditSale.PENDING)

    def test_pending_sale_appears_in_store_but_not_completed_purchases(self):
        user = self.create_client()
        sale = self.create_sale(user)
        CreditSaleProduct.objects.create(
            sale=sale,
            name="Bota cano curto",
            shoe_size="36",
        )
        self.client.force_login(user)

        store_response = self.client.get("/loja/")
        dashboard_response = self.client.get("/painel/")

        self.assertContains(store_response, "Separado para voce")
        self.assertContains(store_response, "Bota cano curto")
        self.assertContains(store_response, "Finalizar compra")
        self.assertNotContains(dashboard_response, "Bota cano curto")


class MercadoPagoPayloadTests(TestCase):
    def create_sale(self):
        user = User.objects.create_user(
            email="cliente-real@example.com",
            password="Teste12345!",
            full_name="Cliente Real",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash=cpf_hash("52998224725"),
            cpf_last_digits="4725",
            phone="61999999999",
            phone_verified=True,
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )
        sale = CreditSale.objects.create(
            client=user,
            description="Bota teste",
            total_amount=Decimal("200.00"),
            max_installments_allowed=10,
            first_due_date="2026-06-10",
        )
        sale.choose_payment(CreditSale.CARD, 5)

        return sale

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="TEST-token")
    @patch("accounts.payments.mercado_pago_request")
    def test_test_checkout_does_not_send_real_customer_data(self, mocked_request):
        mocked_request.return_value = {"id": "pref", "init_point": "https://example.com"}
        sale = self.create_sale()

        create_credit_sale_card_preference(sale, RequestFactory().get("/"))
        payload = mocked_request.call_args.args[1]

        self.assertNotIn("payer", payload)

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="APP_USR-token")
    @patch("accounts.payments.mercado_pago_request")
    def test_production_checkout_sends_customer_data(self, mocked_request):
        mocked_request.return_value = {"id": "pref", "init_point": "https://example.com"}
        sale = self.create_sale()

        create_credit_sale_card_preference(sale, RequestFactory().get("/"))
        payload = mocked_request.call_args.args[1]

        self.assertEqual(payload["payer"]["email"], "cliente-real@example.com")


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

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="")
    def test_logged_client_receives_welcome_discount_only_on_first_store_order(self):
        product = self.create_supplier_product()
        user = User.objects.create_user(
            email="cliente-loja@example.com",
            password="Teste12345!",
            full_name="Cliente Loja",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-hash-cliente-loja",
            cpf_last_digits="3333",
            phone="61999999999",
            phone_verified=True,
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )
        self.client.force_login(user)
        payload = {
            "selected_size": "35",
            "customer_name": "Cliente Loja",
            "customer_email": "cliente-loja@example.com",
            "customer_phone": "61999999999",
            "shipping_address": "Rua Teste, 1",
            "notes": "",
            "accept_terms": "on",
        }

        self.client.post(f"/loja/produto/{product.id}/comprar/", payload)
        self.client.post(f"/loja/produto/{product.id}/comprar/", payload)
        first_order, second_order = StoreOrder.objects.order_by("created_at", "id")

        self.assertEqual(first_order.welcome_discount_amount, Decimal("5.00"))
        self.assertEqual(first_order.total_amount, Decimal("94.90"))
        self.assertEqual(second_order.welcome_discount_amount, Decimal("0.00"))
        self.assertEqual(second_order.total_amount, Decimal("99.90"))

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

    @patch("accounts.views.get_payment")
    def test_mercado_pago_webhook_records_rejected_store_order(self, mocked_get_payment):
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
            "id": "order-payment-rejected",
            "status": "rejected",
            "status_detail": "cc_rejected_other_reason",
            "external_reference": order.order_code,
        }

        response = self.client.post(
            "/loja/mercado-pago/webhook/",
            data={"data": {"id": "order-payment-rejected"}},
            content_type="application/json",
        )
        order.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(order.status, StoreOrder.PAYMENT_FAILED)
        self.assertTrue(PaymentAlert.objects.filter(store_order=order, payment_id="order-payment-rejected").exists())


class NotificationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            email="gestao@example.com",
            password="Teste12345!",
            full_name="Gestao",
            preferred_name="Gestao",
            is_staff=True,
        )
        self.client_user = User.objects.create_user(
            email="cliente-notificacao@example.com",
            password="Teste12345!",
            full_name="Cliente Notificacao",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=self.client_user,
            phone="61999999999",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )

    def test_generates_due_soon_notifications_only_once_for_client_and_staff(self):
        now = timezone.make_aware(datetime(2026, 6, 1, 12, 0))
        Debt.objects.create(
            client=self.client_user,
            description="Parcela teste",
            amount=Decimal("100.00"),
            due_date=now.date() + timedelta(days=2),
        )

        generate_due_notifications(now)
        generate_due_notifications(now)

        self.assertEqual(Notification.objects.filter(kind=Notification.DUE_SOON).count(), 2)
        self.assertTrue(self.client_user.notifications.filter(kind=Notification.DUE_SOON).exists())
        self.assertTrue(self.staff.notifications.filter(kind=Notification.DUE_SOON).exists())

    def test_generates_due_today_notification_after_21_hours(self):
        debt = Debt.objects.create(
            client=self.client_user,
            description="Parcela teste",
            amount=Decimal("100.00"),
            due_date=datetime(2026, 6, 1).date(),
        )

        generate_due_notifications(timezone.make_aware(datetime(2026, 6, 1, 20, 59)))
        self.assertFalse(self.client_user.notifications.filter(kind=Notification.DUE_TODAY).exists())

        generate_due_notifications(timezone.make_aware(datetime(2026, 6, 1, 21, 0)))
        notification = self.client_user.notifications.get(kind=Notification.DUE_TODAY, debt=debt)
        self.assertIn("Evite multa e juros por atraso.", notification.message)

    def test_staff_can_launch_manual_debt_for_pending_registration(self):
        self.client_user.profile.registration_status = ClientProfile.PENDING
        self.client_user.profile.save(update_fields=["registration_status"])
        self.client.force_login(self.staff)

        response = self.client.post(
            "/gestao/debitos/novo/",
            {
                "client": self.client_user.id,
                "description": "Entrada solicitada",
                "amount": "75.90",
                "due_date": "2026-06-10",
            },
        )

        debt = Debt.objects.get(client=self.client_user, description="Entrada solicitada")
        self.assertRedirects(response, "/gestao/")
        self.assertTrue(self.client_user.notifications.filter(kind=Notification.MANUAL_DEBT, debt=debt).exists())

    def test_manual_debt_from_profile_returns_to_profile_and_is_visible(self):
        profile = self.client_user.profile
        profile.registration_status = ClientProfile.PENDING
        profile.save(update_fields=["registration_status"])
        self.client.force_login(self.staff)

        response = self.client.post(
            "/gestao/debitos/novo/",
            {
                "client": self.client_user.id,
                "description": "Saldo anterior",
                "amount": "125.50",
                "due_date": "2026-06-15",
                "return_profile_id": profile.id,
            },
            follow=True,
        )

        self.assertRedirects(response, f"/gestao/cadastros/{profile.id}/")
        self.assertContains(response, "Saldo anterior")
        self.assertContains(response, "R$ 125,50")

    def test_staff_approval_notifies_client(self):
        profile = self.client_user.profile
        profile.registration_status = ClientProfile.PENDING
        profile.save(update_fields=["registration_status"])
        self.client.force_login(self.staff)

        response = self.client.post(
            f"/gestao/cadastros/{profile.id}/",
            {
                "pre_approved_credit_limit": "500.00",
                "default_max_installments": "5",
                "admin_notes": "",
                "action": "approve",
            },
        )

        self.assertRedirects(response, "/gestao/")
        self.assertTrue(self.client_user.notifications.filter(kind=Notification.REGISTRATION_APPROVED).exists())

    def test_generates_overdue_notification_on_first_day_and_every_three_days_after(self):
        debt = Debt.objects.create(
            client=self.client_user,
            description="Parcela atrasada",
            amount=Decimal("100.00"),
            due_date=datetime(2026, 6, 1).date(),
        )

        generate_due_notifications(timezone.make_aware(datetime(2026, 6, 2, 10, 0)))
        generate_due_notifications(timezone.make_aware(datetime(2026, 6, 3, 10, 0)))
        generate_due_notifications(timezone.make_aware(datetime(2026, 6, 4, 10, 0)))
        generate_due_notifications(timezone.make_aware(datetime(2026, 6, 5, 10, 0)))

        client_notifications = self.client_user.notifications.filter(kind=Notification.OVERDUE, debt=debt)
        self.assertEqual(client_notifications.count(), 2)
        self.assertTrue(client_notifications.filter(message__contains="ha 1 dia(s)").exists())
        self.assertTrue(client_notifications.filter(message__contains="ha 4 dia(s)").exists())


class ClientPortfolioTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            email="carteira@example.com",
            password="Teste12345!",
            full_name="Gestao Carteira",
            preferred_name="Gestao",
            is_staff=True,
        )
        self.client_user = User.objects.create_user(
            email="maria@example.com",
            password="Teste12345!",
            full_name="Maria Cliente",
            preferred_name="Maria",
        )
        self.profile = ClientProfile.objects.create(
            user=self.client_user,
            cpf_hash="cpf-hash-maria",
            cpf_last_digits="1111",
            phone="61988887777",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )
        self.client.force_login(self.staff)

    def test_clients_list_shows_registration_and_overdue_analysis(self):
        Debt.objects.create(
            client=self.client_user,
            description="Parcela atrasada",
            amount=Decimal("100.00"),
            due_date=timezone.localdate() - timedelta(days=4),
        )

        response = self.client.get("/gestao/clientes/")

        self.assertContains(response, "Maria Cliente")
        self.assertContains(response, "Aprovado")
        self.assertContains(response, "Inadimplente")
        self.assertContains(response, "4 dias")

    def test_clients_list_filters_by_query_and_overdue_status(self):
        Debt.objects.create(
            client=self.client_user,
            description="Parcela atrasada",
            amount=Decimal("100.00"),
            due_date=timezone.localdate() - timedelta(days=1),
        )
        other_user = User.objects.create_user(
            email="joao@example.com",
            password="Teste12345!",
            full_name="Joao Regular",
            preferred_name="Joao",
        )
        ClientProfile.objects.create(
            user=other_user,
            cpf_hash="cpf-hash-joao",
            cpf_last_digits="2222",
            phone="61977776666",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )

        response = self.client.get("/gestao/clientes/?q=Maria&financeiro=overdue")

        self.assertContains(response, "Maria Cliente")
        self.assertNotContains(response, "Joao Regular")

    def test_client_profile_shows_financial_summary(self):
        Debt.objects.create(
            client=self.client_user,
            description="Parcela aberta",
            amount=Decimal("150.00"),
            due_date=timezone.localdate() + timedelta(days=10),
        )

        response = self.client.get(f"/gestao/cadastros/{self.profile.id}/")

        self.assertContains(response, "Analise financeira")
        self.assertContains(response, "Em acompanhamento")
        self.assertContains(response, "Saldo aberto")
        self.assertContains(response, "R$ 150,00")
