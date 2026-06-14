import json
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from .forms import RegisterForm
from .models import ClientProfile, CreditSale, CreditSaleProduct, Debt, Notification, PaymentAlert, PersonalDebt, Product, StoreOrder, SupplierCatalogSource, SupplierProduct, User, add_months
from .notifications import create_sale_available_notification, create_sale_confirmed_notifications, generate_due_notifications
from .payments import create_credit_sale_card_preference
from .store_shipping import shipping_cost_for
from .supplier_import import parse_csv, row_to_payload
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
                "rg_number": "1234567",
                "phone": "61988888888",
                "address": "Outro endereco",
            },
            files={
                "identity_document": SimpleUploadedFile("rg.pdf", b"pdf"),
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
                "rg_number": "1234567",
                "phone": "61999999999",
                "address": "Endereco",
            },
            files={
                "identity_document": SimpleUploadedFile("rg.pdf", b"pdf"),
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
            "intent": "shop",
        }
        data.update(overrides)

        return data

    @override_settings(PHONE_VERIFICATION_REQUIRED=False)
    def test_basic_registration_creates_account_without_credit_documents(self):
        data = self.registration_payload()

        response = self.client.post(
            "/cadastro/",
            data=data,
        )
        user = User.objects.get(email="cliente-teste@example.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/painel/")
        self.assertTrue(user.profile.phone_verified)
        self.assertEqual(user.profile.phone_verification_code, "")
        self.assertEqual(user.profile.registration_status, ClientProfile.APPROVED)
        self.assertEqual(user.profile.rg_number, "")
        self.assertFalse(bool(user.profile.identity_document))
        self.assertFalse(bool(user.profile.residence_proof))

    def test_credit_registration_requires_rg_document_for_credit_application(self):
        data = self.registration_payload(
            intent="credit",
            rg_number="1234567",
            phone="61999999999",
            address="Rua Teste, 1",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
        )

        response = self.client.post("/cadastro/", data=data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Foto ou PDF do RG")
        self.assertEqual(User.objects.count(), 0)

    @override_settings(PHONE_VERIFICATION_REQUIRED=False)
    def test_credit_registration_stays_pending_for_manual_review(self):
        data = self.registration_payload(
            intent="credit",
            rg_number="1234567",
            phone="61999999999",
            address="Rua Teste, 1",
            identity_document=SimpleUploadedFile("rg.pdf", b"pdf", content_type="application/pdf"),
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf", content_type="application/pdf"),
        )

        response = self.client.post("/cadastro/?intent=credit", data=data)
        user = User.objects.get(email="cliente-teste@example.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/painel/")
        self.assertEqual(user.profile.registration_status, ClientProfile.PENDING)
        self.assertEqual(user.profile.rg_number, "1234567")
        self.assertTrue(bool(user.profile.identity_document))

    @override_settings(PHONE_VERIFICATION_REQUIRED=False)
    def test_basic_registration_with_next_returns_user_to_checkout(self):
        data = self.registration_payload(next="/loja/carrinho/finalizar/")

        response = self.client.post("/cadastro/?next=/loja/carrinho/finalizar/", data=data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/loja/carrinho/finalizar/")

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
        data = self.registration_payload()

        response = self.client.post("/cadastro/", data=data)

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Nao foi possivel concluir seu cadastro agora", status_code=500)
        self.assertEqual(User.objects.count(), 0)


class CsrfFailureTests(TestCase):
    def test_csrf_failure_redirects_to_login(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post("/login/", {"username": "cliente@example.com", "password": "senha"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/")


class CreditSalePaymentChoiceTests(TestCase):
    def credit_due_date_input(self, days=10):
        return (timezone.localdate() + timedelta(days=days)).isoformat()

    def create_client(self, **profile_overrides):
        user = User.objects.create_user(
            email="cliente-compra@example.com",
            password="Teste12345!",
            full_name="Cliente Compra",
            preferred_name="Cliente",
        )
        profile_data = {
            "user": user,
            "cpf_hash": cpf_hash("52998224725"),
            "cpf_last_digits": "4725",
            "phone": "61999999999",
            "phone_verified": True,
            "address": "Endereco",
            "residence_proof": SimpleUploadedFile("comprovante.pdf", b"pdf"),
            "registration_status": ClientProfile.APPROVED,
            "welcome_discount_expires_at": timezone.localdate() + timedelta(days=90),
        }
        profile_data.update(profile_overrides)
        ClientProfile.objects.create(
            **profile_data,
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
                "use_welcome_discount": "on",
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
        sale.choose_payment(CreditSale.PIX, use_welcome_discount=True)
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

    def test_credit_payment_page_explains_late_fee_rules(self):
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.get(f"/parcelamento/{sale.id}/")

        self.assertContains(response, "Credi&aacute;rio*")
        self.assertContains(response, "atraso gera multa de 2% e juros de 1%")
        self.assertContains(response, "Regras do crediario")
        self.assertContains(response, "Se escolher crediario, revise juros e multa por atraso antes de concluir.")
        self.assertContains(response, 'data-payment-panel="credit" hidden')
        self.assertNotContains(response, "calculados proporcionalmente")

    def test_credit_choice_success_message_reminds_about_late_fee_and_interest(self):
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CREDIT,
                "installments": "2",
                "first_due_date": self.credit_due_date_input(),
                "accept_terms": "on",
            },
            follow=True,
        )

        self.assertContains(response, "Compra no crediario confirmada. Lembre-se: atraso gera multa de 2% e juros de 1% ao mes.")

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

    @override_settings(CARD_PAYMENT_ENABLED=False)
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
        self.assertContains(response, "Op&ccedil;&atilde;o ainda n&atilde;o dispon&iacute;vel.")
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
                "first_due_date": self.credit_due_date_input(),
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

        first_sale.choose_payment(CreditSale.CREDIT, 1, use_welcome_discount=True)
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
                "first_due_date": self.credit_due_date_input(),
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escolha uma opcao de parcela disponivel")
        self.assertEqual(sale.status, CreditSale.PENDING)

    def test_credit_choice_rejects_due_date_beyond_thirty_days(self):
        user = self.create_client()
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CREDIT,
                "installments": "1",
                "first_due_date": self.credit_due_date_input(days=31),
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "O primeiro vencimento deve ficar entre hoje e os proximos 30 dias.")
        self.assertEqual(sale.status, CreditSale.PENDING)

    def test_credit_choice_requires_remainder_payment_method_above_credit_limit(self):
        user = self.create_client(pre_approved_credit_limit=Decimal("150.00"))
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CREDIT,
                "installments": "2",
                "first_due_date": self.credit_due_date_input(),
                "accept_terms": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escolha como pagar o restante fora do crediario.")

    def test_credit_choice_records_remainder_above_credit_limit(self):
        user = self.create_client(pre_approved_credit_limit=Decimal("150.00"))
        sale = self.create_sale(user)
        self.client.force_login(user)

        response = self.client.post(
            f"/parcelamento/{sale.id}/",
            {
                "payment_method": CreditSale.CREDIT,
                "installments": "2",
                "first_due_date": self.credit_due_date_input(),
                "remainder_payment_method": CreditSale.REMAINDER_PIX,
                "accept_terms": "on",
            },
        )
        sale.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(sale.remainder_amount, Decimal("40.00"))
        self.assertEqual(sale.remainder_payment_method, CreditSale.REMAINDER_PIX)
        self.assertEqual(sale.financed_total_with_interest, Decimal("150.00"))
        self.assertEqual(sale.selected_total_with_interest, Decimal("190.00"))
        self.assertEqual(Debt.objects.filter(credit_sale=sale).count(), 2)

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
            welcome_discount_expires_at=timezone.localdate() + timedelta(days=90),
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
        self.assertNotContains(response, "Loja publica")
        self.assertNotContains(response, "Produtos prontos para navegar")
        self.assertNotContains(response, "Pagamento acompanhado")
        self.assertNotContains(response, "exibidos nesta busca")

    def test_store_front_prioritizes_tenis_products_first(self):
        self.create_supplier_product(name="Sandalia Azul", category="Sandalia")
        self.create_supplier_product(
            supplier_code="RC002",
            name="Tenis Branco",
            category="Tenis",
        )

        response = self.client.get("/loja/")
        content = response.content.decode()
        grid_content = content[content.index("Buscar produto"):]

        self.assertLess(grid_content.index("Tenis Branco"), grid_content.index("Sandalia Azul"))

    def test_store_front_shows_showcase_carousels_before_filters(self):
        self.create_supplier_product(name="Sandalia Azul", category="Sandalia")
        self.create_supplier_product(
            supplier_code="RC002",
            name="Tenis Branco",
            category="Tenis",
        )
        self.create_supplier_product(
            supplier_code="RC003",
            name="Bota Ankle Boot Capa Cano Curto",
            category="Botas",
            suggested_sale_price=Decimal("230.85"),
            sizes="34,35,36,37,38,39",
            image_url="/static/accounts/catalog-test/botas/1.958-4a.jpg",
        )
        self.create_supplier_product(
            supplier_code="RC004",
            name="Sandalia Plataforma de Cunha Anabela",
            category="Anabela",
            suggested_sale_price=Decimal("92.25"),
            sizes="34,35,36,37,38,39",
            image_url="/static/accounts/catalog-test/anabela/4066b.jpg",
        )

        response = self.client.get("/loja/")
        content = response.content.decode()

        self.assertContains(response, "Calçados")
        self.assertContains(response, "Bolsas")
        self.assertContains(response, "Bota Ankle Boot Capa Cano Curto")
        self.assertContains(response, "R$ 230,85")
        self.assertContains(response, "Sandalia Plataforma de Cunha Anabela")
        self.assertContains(response, "R$ 92,25")
        self.assertContains(response, "NikeZoom Invicible Flyknit")
        self.assertContains(response, "Bolsa Ramosê Melina")
        self.assertContains(response, "R$ 179,90")
        self.assertContains(response, "R$ 109,90")
        self.assertContains(response, "Crochê")
        self.assertLess(content.index("Sandalia Azul"), content.index("Sandalia Plataforma de Cunha Anabela"))
        self.assertLess(content.index("NikeZoom Invicible Flyknit"), content.index("Buscar produto"))

    def test_store_front_uses_live_search_with_size_group_selector(self):
        self.create_supplier_product()

        response = self.client.get("/loja/")

        self.assertContains(response, "Numeracao")
        self.assertContains(response, ">Adulto<", html=False)
        self.assertContains(response, ">Infantil<", html=False)
        self.assertNotContains(response, ">Filtrar<", html=False)

    def test_store_product_detail_shows_gallery_carousel_when_product_has_two_images(self):
        product = self.create_supplier_product(
            image_url="/static/accounts/catalog-test/botas/1.958-4a.jpg",
            raw_data={"gallery_images": ["/static/accounts/catalog-test/botas/1.958-4b.jpg"]},
        )

        response = self.client.get(f"/loja/produto/{product.id}/")

        self.assertContains(response, 'class="product-gallery product-gallery-detail"', html=False)
        self.assertContains(response, "/static/accounts/catalog-test/botas/1.958-4a.jpg")
        self.assertContains(response, "/static/accounts/catalog-test/botas/1.958-4b.jpg")

    def test_store_product_detail_for_consultation_source_hides_cart_flow(self):
        SupplierCatalogSource.objects.update_or_create(
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            defaults={
                "display_name": "Parceiro sob consulta",
                "customer_notice": "Em breve vamos entrar em contato para confirmar disponibilidade e finalizar pelo WhatsApp.",
                "purchase_flow": SupplierCatalogSource.FLOW_WHATSAPP_CONFIRMATION,
            },
        )
        product = self.create_supplier_product(
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            supplier_code="SC001",
            name="Bota sob consulta",
        )

        response = self.client.get(f"/loja/produto/{product.id}/")

        self.assertContains(response, "Sob consulta")
        self.assertContains(response, "finalizar pelo WhatsApp")
        self.assertNotContains(response, "Adicionar ao carrinho")

    def test_cart_add_blocks_consultation_source_product(self):
        SupplierCatalogSource.objects.update_or_create(
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            defaults={
                "display_name": "Parceiro sob consulta",
                "customer_notice": "Em breve vamos entrar em contato para confirmar disponibilidade e finalizar pelo WhatsApp.",
                "purchase_flow": SupplierCatalogSource.FLOW_WHATSAPP_CONFIRMATION,
            },
        )
        product = self.create_supplier_product(
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            supplier_code="SC002",
        )

        response = self.client.post(f"/loja/carrinho/adicionar/{product.id}/", {"selected_size": "35"}, follow=True)

        self.assertRedirects(response, f"/loja/produto/{product.id}/")
        self.assertContains(response, "finalizar pelo WhatsApp")
        self.assertEqual(self.client.session.get("store_cart", {}), {})

    def test_guest_header_exposes_login_and_register_paths(self):
        response = self.client.get("/loja/")

        self.assertContains(response, 'Abrir minha conta')
        self.assertContains(response, 'class="guest-account-toggle"', html=False)
        self.assertContains(response, '>Minha conta</h2>', html=False)
        self.assertContains(response, '>Cadastro para crediario</a>', html=False)
        self.assertContains(response, 'href="/login/"')
        self.assertContains(response, 'href="/cadastro/?intent=credit"')
        self.assertNotContains(response, "Painel de gestao")
        self.assertNotContains(response, "Abrir notificacoes")
        self.assertNotContains(response, '>Crediario</a>', html=False)

    def test_offline_page_and_service_worker_are_available(self):
        offline_response = self.client.get("/offline/")
        service_worker_response = self.client.get("/service-worker.js")

        self.assertEqual(offline_response.status_code, 200)
        self.assertContains(offline_response, "Sem conexao")
        self.assertEqual(service_worker_response.status_code, 200)
        self.assertEqual(service_worker_response["Service-Worker-Allowed"], "/")
        self.assertIn("/loja/", service_worker_response.content.decode())
        self.assertIn("/offline/", service_worker_response.content.decode())

    def test_webmanifest_has_standalone_mode_and_shortcuts(self):
        manifest_path = Path("accounts/static/accounts/site.webmanifest")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["display"], "standalone")
        self.assertIn("shortcuts", payload)
        self.assertEqual(payload["shortcuts"][0]["url"], "/loja/")

    def test_store_front_hides_products_already_in_cart(self):
        product_in_cart = self.create_supplier_product(name="Produto No Carrinho")
        visible_product = self.create_supplier_product(supplier_code="RC002", name="Produto Fora Do Carrinho")

        self.client.post(f"/loja/carrinho/adicionar/{product_in_cart.id}/", {"selected_size": "35"})
        response = self.client.get("/loja/")

        self.assertNotContains(response, product_in_cart.name)
        self.assertContains(response, visible_product.name)

    def test_cart_still_lists_product_hidden_from_store_front(self):
        product_in_cart = self.create_supplier_product(name="Produto Reservado No Carrinho")

        self.client.post(f"/loja/carrinho/adicionar/{product_in_cart.id}/", {"selected_size": "35"})
        response = self.client.get("/loja/carrinho/")

        self.assertContains(response, product_in_cart.name)

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="")
    def test_checkout_creates_pending_order_without_payment_token(self):
        product = self.create_supplier_product()
        user = User.objects.create_user(
            email="checkout@example.com",
            password="Teste12345!",
            full_name="Cliente Checkout",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-hash-checkout",
            cpf_last_digits="1212",
            phone="61999999999",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            f"/loja/produto/{product.id}/comprar/",
            {
                "selected_size": "35",
                "customer_name": "Cliente Teste",
                "customer_email": "cliente@example.com",
                "customer_phone": "61999999999",
                "shipping_state": "DF",
                "shipping_address": "Rua Teste, 1",
                "notes": "",
                "accept_terms": "on",
            },
        )
        order = StoreOrder.objects.get()

        self.assertEqual(response.status_code, 302)
        self.assertIn(str(order.public_token), response["Location"])
        self.assertEqual(order.status, StoreOrder.PENDING_PAYMENT)
        self.assertEqual(order.shipping_state, "DF")
        self.assertEqual(order.shipping_cost, Decimal("20.00"))
        self.assertEqual(order.total_amount, Decimal("119.90"))

    def test_checkout_credit_request_sends_basic_profile_to_analysis(self):
        product = self.create_supplier_product()
        user = User.objects.create_user(
            email="checkout-credit@example.com",
            password="Teste12345!",
            full_name="Cliente Credito",
            preferred_name="Cliente",
        )
        profile = ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-hash-checkout-credit",
            cpf_last_digits="5656",
            phone="61999999999",
            address="Endereco",
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            f"/loja/produto/{product.id}/comprar/",
            {
                "selected_size": "35",
                "customer_name": "Cliente Credito",
                "customer_email": "cliente-credito@example.com",
                "customer_phone": "61999999999",
                "shipping_state": "DF",
                "shipping_address": "Rua Teste, 1",
                "notes": "Pode entregar a tarde.",
                "payment_method": "credit",
                "accept_terms": "on",
            },
            follow=True,
        )
        sale = CreditSale.objects.get()
        sale_product = sale.products.get()
        profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(profile.registration_status, ClientProfile.PENDING)
        self.assertContains(response, "Cadastro em analise")
        self.assertContains(response, "Solicitou crediario pelo checkout")
        self.assertEqual(StoreOrder.objects.count(), 0)
        self.assertEqual(sale.client, user)
        self.assertEqual(sale.status, CreditSale.PENDING)
        self.assertEqual(sale.total_amount, Decimal("119.90"))
        self.assertEqual(sale_product.name, product.name)
        self.assertIn("Codigo fornecedor: RC001", sale_product.notes)
        self.assertIn("Rua Teste, 1", sale_product.notes)

    def test_checkout_credit_request_for_approved_credit_profile_goes_to_installments(self):
        product = self.create_supplier_product()
        user = User.objects.create_user(
            email="checkout-credit-approved@example.com",
            password="Teste12345!",
            full_name="Cliente Credito Aprovado",
            preferred_name="Cliente",
        )
        profile = ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-hash-checkout-credit-approved",
            cpf_last_digits="7878",
            rg_number="1234567",
            phone="61999999999",
            address="Endereco",
            identity_document=SimpleUploadedFile("rg.pdf", b"pdf"),
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            f"/loja/produto/{product.id}/comprar/",
            {
                "selected_size": "35",
                "customer_name": "Cliente Credito Aprovado",
                "customer_email": "cliente-credito-aprovado@example.com",
                "customer_phone": "61999999999",
                "shipping_state": "DF",
                "shipping_address": "Rua Teste, 1",
                "notes": "",
                "payment_method": "credit",
                "accept_terms": "on",
            },
        )
        sale = CreditSale.objects.get()
        profile.refresh_from_db()

        self.assertRedirects(response, f"/parcelamento/{sale.id}/")
        self.assertEqual(profile.registration_status, ClientProfile.APPROVED)
        self.assertEqual(sale.total_amount, Decimal("119.90"))

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
            welcome_discount_expires_at=timezone.localdate() + timedelta(days=90),
        )
        self.client.force_login(user)
        payload = {
            "selected_size": "35",
            "customer_name": "Cliente Loja",
            "customer_email": "cliente-loja@example.com",
            "customer_phone": "61999999999",
            "shipping_state": "DF",
            "shipping_address": "Rua Teste, 1",
            "notes": "",
            "use_welcome_discount": "on",
            "accept_terms": "on",
        }

        self.client.post(f"/loja/produto/{product.id}/comprar/", payload)
        self.client.post(f"/loja/produto/{product.id}/comprar/", payload)
        first_order, second_order = StoreOrder.objects.order_by("created_at", "id")

        self.assertEqual(first_order.welcome_discount_amount, Decimal("5.00"))
        self.assertEqual(first_order.total_amount, Decimal("114.90"))
        self.assertEqual(second_order.welcome_discount_amount, Decimal("0.00"))
        self.assertEqual(second_order.total_amount, Decimal("119.90"))

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="")
    def test_cart_keeps_voucher_for_later_when_customer_does_not_select_it(self):
        product = self.create_supplier_product()
        user = User.objects.create_user(
            email="cliente-carrinho@example.com",
            password="Teste12345!",
            full_name="Cliente Carrinho",
            preferred_name="Cliente",
        )
        profile = ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-hash-cliente-carrinho",
            cpf_last_digits="4444",
            phone="61999999999",
            phone_verified=True,
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            welcome_discount_expires_at=timezone.localdate() + timedelta(days=90),
        )
        self.client.force_login(user)
        self.client.post(f"/loja/carrinho/adicionar/{product.id}/", {"selected_size": "35"})

        response = self.client.post(
            "/loja/carrinho/finalizar/",
            {
                "customer_name": "Cliente Carrinho",
                "customer_email": "cliente-carrinho@example.com",
                "customer_phone": "61999999999",
                "shipping_state": "DF",
                "shipping_address": "Rua Teste, 1",
                "notes": "",
                "accept_terms": "on",
            },
        )
        order = StoreOrder.objects.get()
        profile.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(order.shipping_cost, Decimal("20.00"))
        self.assertEqual(order.total_amount, Decimal("119.90"))
        self.assertEqual(order.welcome_discount_amount, Decimal("0.00"))
        self.assertFalse(profile.first_purchase_discount_used)

    @override_settings(BOTICARIO_STORE_URL="https://minhaloja.grupoboticario.com.br/loja-teste")
    def test_cart_can_redirect_to_boticario_store(self):
        product = self.create_supplier_product()
        self.client.post(f"/loja/carrinho/adicionar/{product.id}/", {"selected_size": "35"})

        cart_response = self.client.get("/loja/carrinho/")
        redirect_response = self.client.get("/loja/carrinho/boticario/")

        self.assertNotContains(cart_response, "Finalizar no Boticario")
        self.assertRedirects(
            redirect_response,
            "https://minhaloja.grupoboticario.com.br/loja-teste",
            fetch_redirect_response=False,
        )

    def test_shipping_table_covers_df_entorno_default_and_ac(self):
        self.assertEqual(shipping_cost_for("DF"), Decimal("20.00"))
        self.assertEqual(shipping_cost_for("ENTORNO_DF"), Decimal("20.00"))
        self.assertEqual(shipping_cost_for("GO"), Decimal("25.00"))
        self.assertEqual(shipping_cost_for("SP"), Decimal("25.00"))
        self.assertEqual(shipping_cost_for("RJ"), Decimal("40.00"))
        self.assertEqual(shipping_cost_for("AC"), Decimal("45.00"))

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="")
    def test_cart_applies_selected_voucher_to_grouped_orders(self):
        first_product = self.create_supplier_product()
        second_product = self.create_supplier_product(supplier_code="RC002", name="Outro Produto", suggested_sale_price=Decimal("200.00"))
        user = User.objects.create_user(
            email="cliente-voucher@example.com",
            password="Teste12345!",
            full_name="Cliente Voucher",
            preferred_name="Cliente",
        )
        profile = ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-hash-cliente-voucher",
            cpf_last_digits="5555",
            phone="61999999999",
            phone_verified=True,
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            welcome_discount_expires_at=timezone.localdate() + timedelta(days=90),
        )
        self.client.force_login(user)
        self.client.post(f"/loja/carrinho/adicionar/{first_product.id}/", {"selected_size": "35"})
        self.client.post(f"/loja/carrinho/adicionar/{second_product.id}/", {"selected_size": "36"})

        self.client.post(
            "/loja/carrinho/finalizar/",
            {
                "customer_name": "Cliente Voucher",
                "customer_email": "cliente-voucher@example.com",
                "customer_phone": "61999999999",
                "shipping_state": "DF",
                "shipping_address": "Rua Teste, 1",
                "notes": "",
                "use_welcome_discount": "on",
                "accept_terms": "on",
            },
        )
        orders = list(StoreOrder.objects.order_by("id"))
        profile.refresh_from_db()

        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].checkout_reference, orders[1].checkout_reference)
        self.assertEqual(orders[0].shipping_cost, Decimal("20.00"))
        self.assertEqual(orders[1].shipping_cost, Decimal("0.00"))
        self.assertEqual(sum(order.total_amount for order in orders), Decimal("304.91"))
        self.assertTrue(profile.first_purchase_discount_used)

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

    def test_supplier_panel_requires_note_to_hide_product(self):
        staff = User.objects.create_superuser(
            email="admin-hide@example.com",
            password="Teste12345!",
            full_name="Admin Hide",
            preferred_name="Admin",
        )
        product = self.create_supplier_product(is_visible=True)
        self.client.force_login(staff)

        response = self.client.post(
            f"/gestao/fornecedor/produtos/{product.id}/status/",
            {"action": "hide", "status_note": ""},
        )
        product.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(product.is_visible)

    def test_supplier_panel_inactivates_product_with_required_note(self):
        staff = User.objects.create_superuser(
            email="admin-inactive@example.com",
            password="Teste12345!",
            full_name="Admin Inactive",
            preferred_name="Admin",
        )
        product = self.create_supplier_product(is_visible=True)
        self.client.force_login(staff)

        response = self.client.post(
            f"/gestao/fornecedor/produtos/{product.id}/status/",
            {"action": "deactivate", "status_note": "Produto de teste removido da operacao."},
        )
        product.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(product.is_active)
        self.assertFalse(product.is_visible)
        self.assertEqual(product.status_note, "Produto de teste removido da operacao.")

    def test_staff_can_delete_local_test_product_without_sales(self):
        staff = User.objects.create_superuser(
            email="admin-delete-product@example.com",
            password="Teste12345!",
            full_name="Admin Delete Product",
            preferred_name="Admin",
        )
        product = Product.objects.create(
            name="Produto Teste",
            purchase_price=Decimal("30.00"),
            sale_price=Decimal("80.00"),
        )
        self.client.force_login(staff)

        response = self.client.post(f"/gestao/produtos/{product.id}/excluir/", follow=True)

        self.assertRedirects(response, "/gestao/produtos/")
        self.assertFalse(Product.objects.filter(id=product.id).exists())
        self.assertContains(response, "foi excluido")

    def test_supplier_product_delete_is_blocked_when_order_exists(self):
        staff = User.objects.create_superuser(
            email="admin-delete-supplier@example.com",
            password="Teste12345!",
            full_name="Admin Delete Supplier",
            preferred_name="Admin",
        )
        product = self.create_supplier_product()
        StoreOrder.objects.create(
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
        self.client.force_login(staff)

        response = self.client.post(f"/gestao/fornecedor/produtos/{product.id}/excluir/", follow=True)

        self.assertRedirects(response, "/gestao/fornecedor/produtos/")
        self.assertTrue(SupplierProduct.objects.filter(id=product.id).exists())
        self.assertContains(response, "ja tem pedido vinculado")

    def test_management_dashboard_shows_monthly_revenue_sales_and_goal(self):
        staff = User.objects.create_superuser(
            email="admin-monthly@example.com",
            password="Teste12345!",
            full_name="Admin Monthly",
            preferred_name="Admin",
        )
        user = User.objects.create_user(
            email="cliente-monthly@example.com",
            password="Teste12345!",
            full_name="Cliente Monthly",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-monthly",
            cpf_last_digits="9090",
            phone="61999999999",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        supplier_product = self.create_supplier_product()
        StoreOrder.objects.create(
            product=supplier_product,
            product_name=supplier_product.name,
            supplier_code=supplier_product.supplier_code,
            selected_size="35",
            quantity=2,
            customer_name="Cliente Monthly",
            customer_email="cliente-monthly@example.com",
            customer_phone="61999999999",
            shipping_address="Rua Teste, 1",
            unit_price=Decimal("75.00"),
            supplier_cost=Decimal("40.00"),
            total_amount=Decimal("150.00"),
            estimated_profit=Decimal("70.00"),
            status=StoreOrder.PAID,
            paid_at=timezone.now(),
        )
        sale = CreditSale.objects.create(
            client=user,
            description="Venda mensal",
            total_amount=Decimal("200.00"),
            first_due_date=timezone.localdate() + timedelta(days=30),
            status=CreditSale.ACCEPTED,
            selected_total_with_interest=Decimal("200.00"),
            accepted_at=timezone.now(),
        )
        CreditSaleProduct.objects.create(sale=sale, name="Sapato Mensal", brand="Marca", shoe_size="35")
        self.client.force_login(staff)

        response = self.client.get("/gestao/")

        self.assertContains(response, "Faturamento do mes")
        self.assertContains(response, "R$ 350,00")
        self.assertContains(response, "Vendas no mes")
        self.assertContains(response, "3/10")
        self.assertContains(response, "Faltam 7")

    @override_settings(SHOE_SUPPLIER_DROPSHIPPING_URL="https://example.com/dropshipping")
    def test_supplier_panel_links_to_dropshipping_area(self):
        staff = User.objects.create_superuser(
            email="admin-dropshipping@example.com",
            password="Teste12345!",
            full_name="Admin Dropshipping",
            preferred_name="Admin",
        )
        self.client.force_login(staff)

        response = self.client.get("/gestao/fornecedor/produtos/")

        self.assertContains(response, "Dropshipping Revenda de Calcados")
        self.assertContains(response, "https://example.com/dropshipping")

    def test_create_credit_sale_form_shows_brand_and_size_fields_without_due_date(self):
        staff = User.objects.create_superuser(
            email="admin-venda@example.com",
            password="Teste12345!",
            full_name="Admin Venda",
            preferred_name="Admin",
        )
        self.client.force_login(staff)

        response = self.client.get("/gestao/vendas/nova/")

        self.assertContains(response, "Marca")
        self.assertContains(response, "Tamanho")
        self.assertNotContains(response, 'name="first_due_date"', html=False)
        self.assertNotContains(response, 'name="max_installments_allowed"', html=False)

    def test_create_credit_sale_form_uses_client_id_and_name_labels(self):
        staff = User.objects.create_superuser(
            email="admin-venda-id@example.com",
            password="Teste12345!",
            full_name="Admin Venda",
            preferred_name="Admin",
        )
        user = User.objects.create_user(
            email="cliente-id@example.com",
            password="Teste12345!",
            full_name="Maria Cliente",
            preferred_name="Maria",
        )
        profile = ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-id-cliente",
            cpf_last_digits="8888",
            phone="61999997777",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        self.client.force_login(staff)

        response = self.client.get("/gestao/vendas/nova/")

        self.assertContains(response, f"ID {profile.id:04d} - Maria Cliente")

    def test_create_credit_sale_uses_client_default_installments_and_optional_description(self):
        staff = User.objects.create_superuser(
            email="admin-venda-post@example.com",
            password="Teste12345!",
            full_name="Admin Venda",
            preferred_name="Admin",
        )
        user = User.objects.create_user(
            email="cliente-venda@example.com",
            password="Teste12345!",
            full_name="Cliente Venda",
            preferred_name="Cliente",
        )
        profile = ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-venda-cliente",
            cpf_last_digits="7777",
            phone="61999996666",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
            default_max_installments=7,
        )
        self.client.force_login(staff)

        response = self.client.post(
            "/gestao/vendas/nova/",
            {
                "client": user.id,
                "description": "",
                "total_amount": "240.00",
                "products-TOTAL_FORMS": "1",
                "products-INITIAL_FORMS": "0",
                "products-MIN_NUM_FORMS": "0",
                "products-MAX_NUM_FORMS": "20",
                "products-0-product": "",
                "products-0-name": "Sapato Teste",
                "products-0-brand": "Marca Teste",
                "products-0-shoe_size": "34",
                "products-0-size_group": "adult",
                "products-0-notes": "",
            },
        )
        sale = CreditSale.objects.get(client=user)

        self.assertEqual(profile.default_max_installments, 7)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sale.max_installments_allowed, 7)
        self.assertEqual(sale.description, "Sapato Teste")

    def test_staff_menu_shows_store_link(self):
        staff = User.objects.create_superuser(
            email="admin-menu@example.com",
            password="Teste12345!",
            full_name="Admin Menu",
            preferred_name="Admin",
        )
        self.client.force_login(staff)

        response = self.client.get("/gestao/fornecedor/produtos/")

        self.assertContains(response, '>Loja</a>', html=False)
        self.assertNotContains(response, '>Minhas financas</a>', html=False)
        self.assertContains(response, "Línde IA")

    def test_client_menu_shows_customer_finances_link(self):
        user = User.objects.create_user(
            email="cliente-financas-menu@example.com",
            password="Teste12345!",
            full_name="Cliente Financas",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-financas-menu",
            cpf_last_digits="6611",
            phone="61999995555",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        self.client.force_login(user)

        response = self.client.get("/painel/")

        self.assertContains(response, '>Minhas financas</a>', html=False)
        self.assertNotContains(response, "Línde IA")

    def test_customer_finances_page_is_visible_only_for_client(self):
        user = User.objects.create_user(
            email="cliente-financas@example.com",
            password="Teste12345!",
            full_name="Cliente Financas",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-financas",
            cpf_last_digits="6622",
            phone="61999994444",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        Debt.objects.create(
            client=user,
            description="Parcela junho",
            amount=Decimal("120.00"),
            due_date=timezone.localdate() + timedelta(days=3),
        )
        Debt.objects.create(
            client=user,
            description="Parcela julho",
            amount=Decimal("140.00"),
            due_date=add_months(timezone.localdate().replace(day=1), 1) + timedelta(days=4),
        )
        self.client.force_login(user)

        response = self.client.get("/painel/financas/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Somente voce ve esta area no aplicativo.")
        self.assertContains(response, "Criar")
        self.assertContains(response, "Contas pessoais do mes")
        self.assertContains(response, "Contas pessoais futuras")

    def test_customer_can_create_personal_debt_with_category_and_color(self):
        user = User.objects.create_user(
            email="cliente-financas-form@example.com",
            password="Teste12345!",
            full_name="Cliente Formulario",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-financas-form",
            cpf_last_digits="6633",
            phone="61999993333",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            "/painel/financas/",
            {
                "title": "Aluguel apartamento",
                "entry_type": PersonalDebt.TYPE_DEBT,
                "category": PersonalDebt.CATEGORY_RENT,
                "color": "#ff6b57",
                "amount": "1200.00",
                "due_date": (timezone.localdate() + timedelta(days=5)).isoformat(),
                "notes": "Pagar antes do quinto dia util",
            },
        )

        debt = PersonalDebt.objects.get(client=user, title="Aluguel apartamento")
        self.assertRedirects(response, "/painel/financas/")
        self.assertEqual(debt.entry_type, PersonalDebt.TYPE_DEBT)
        self.assertEqual(debt.category, PersonalDebt.CATEGORY_RENT)
        self.assertEqual(debt.color, "#ff6b57")

    def test_customer_finances_shows_receivables_and_balance(self):
        user = User.objects.create_user(
            email="cliente-financas-recebiveis@example.com",
            password="Teste12345!",
            full_name="Cliente Recebiveis",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-financas-recebiveis",
            cpf_last_digits="6644",
            phone="61999992222",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        PersonalDebt.objects.create(
            client=user,
            title="Aluguel",
            entry_type=PersonalDebt.TYPE_DEBT,
            category=PersonalDebt.CATEGORY_RENT,
            color="#ff6b57",
            amount=Decimal("1200.00"),
            due_date=timezone.localdate() + timedelta(days=3),
        )
        PersonalDebt.objects.create(
            client=user,
            title="Freela",
            entry_type=PersonalDebt.TYPE_RECEIVABLE,
            category=PersonalDebt.CATEGORY_OTHER,
            color="#16a34a",
            amount=Decimal("1500.00"),
            due_date=timezone.localdate() + timedelta(days=6),
        )
        self.client.force_login(user)

        response = self.client.get("/painel/financas/")

        self.assertContains(response, "Recebiveis")
        self.assertContains(response, "Recebiveis deste mes")
        self.assertContains(response, "Diferenca entre recebiveis e dividas")
        self.assertContains(response, "+R$ 300,00")

    def test_customer_finances_page_forbids_staff_access(self):
        staff = User.objects.create_superuser(
            email="admin-financas@example.com",
            password="Teste12345!",
            full_name="Admin Financas",
            preferred_name="Admin",
        )
        self.client.force_login(staff)

        response = self.client.get("/painel/financas/")

        self.assertEqual(response.status_code, 403)

    def revenda_csv_content(self, stock="34,5|35,4|36,10"):
        content = (
            "REFERENCIA;NOMEPRODUTO;CATEGORIA;ESTOQUE;PRECOATACADO;PRECODROPSHIPPING;MARCA;DESCRICAO;URLPRODUTO;FOTOS;COR;GRUPO;\n"
            f"67096B;Bota Bico Fino Cano Longo;Botas;{stock};179.90;197.89;Torricella;Material Napa;"
            "https://www.revendadecalcados.com.br/produto-8775.html;"
            "https://www.revendadecalcados.com.br/foto1.jpg,https://www.revendadecalcados.com.br/foto2.jpg;Caramelo;Botas;\n"
        )

        return content

    def test_revenda_csv_payload_maps_stock_sizes_cost_and_first_image(self):
        content = self.revenda_csv_content()

        rows = parse_csv(content)
        payload = row_to_payload(rows[0], 1)

        self.assertEqual(payload["supplier_code"], "67096B")
        self.assertEqual(payload["name"], "Bota Bico Fino Cano Longo")
        self.assertEqual(payload["category"], "Botas")
        self.assertEqual(payload["brand"], "Torricella")
        self.assertEqual(payload["wholesale_price"], Decimal("179.90"))
        self.assertEqual(payload["dropshipping_cost"], Decimal("197.89"))
        self.assertEqual(payload["suggested_sale_price"], Decimal("277.05"))
        self.assertEqual(payload["stock_quantity"], 19)
        self.assertEqual(payload["sizes"], "34,35,36")
        self.assertEqual(payload["image_url"], "https://www.revendadecalcados.com.br/foto1.jpg")

    def test_revenda_csv_payload_keeps_only_sizes_with_safe_stock(self):
        rows = parse_csv(self.revenda_csv_content(stock="34,2|35,3|36,1|37,8"))
        payload = row_to_payload(rows[0], 1)

        self.assertEqual(payload["stock_quantity"], 11)
        self.assertEqual(payload["sizes"], "35,37")

    def test_supplier_panel_imports_uploaded_revenda_csv(self):
        staff = User.objects.create_superuser(
            email="admin-upload-csv@example.com",
            password="Teste12345!",
            full_name="Admin Upload CSV",
            preferred_name="Admin",
        )
        self.client.force_login(staff)

        response = self.client.post(
            "/gestao/fornecedor/importar/",
            {
                "catalog_file": SimpleUploadedFile(
                    "produtos.csv",
                    self.revenda_csv_content(stock="34,2|35,3|36,5").encode("latin-1"),
                    content_type="text/csv",
                ),
            },
        )
        product = SupplierProduct.objects.get(supplier_code="67096B")

        self.assertRedirects(response, "/gestao/fornecedor/produtos/")
        self.assertEqual(product.stock_quantity, 8)
        self.assertEqual(product.sizes, "35,36")
        self.assertEqual(product.image_url, "https://www.revendadecalcados.com.br/foto1.jpg")

    @patch("accounts.views.import_supplier_catalog")
    def test_supplier_panel_imports_from_saved_source_url(self, mocked_import):
        staff = User.objects.create_superuser(
            email="admin-import-url@example.com",
            password="Teste12345!",
            full_name="Admin Import URL",
            preferred_name="Admin",
        )
        self.client.force_login(staff)
        SupplierCatalogSource.objects.update_or_create(
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            defaults={
                "display_name": "Parceiro sob consulta",
                "catalog_url": "https://example.com/catalogo.xml",
                "catalog_format": SupplierCatalogSource.FORMAT_XML,
                "purchase_flow": SupplierCatalogSource.FLOW_WHATSAPP_CONFIRMATION,
            },
        )
        mocked_import.return_value = {"created": 2, "updated": 3, "total": 5}

        response = self.client.post(
            "/gestao/fornecedor/importar/",
            {
                "source": SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            },
            follow=True,
        )

        self.assertRedirects(response, "/gestao/fornecedor/produtos/")
        mocked_import.assert_called_once_with(
            "https://example.com/catalogo.xml",
            SupplierCatalogSource.FORMAT_XML,
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
        )
        self.assertContains(response, "Catalogo atualizado: 2 novos, 3 atualizados, 5 lidos.")

    def test_supplier_panel_updates_saved_source_settings(self):
        staff = User.objects.create_superuser(
            email="admin-source-settings@example.com",
            password="Teste12345!",
            full_name="Admin Source Settings",
            preferred_name="Admin",
        )
        self.client.force_login(staff)
        source, _ = SupplierCatalogSource.objects.update_or_create(
            source=SupplierProduct.SOURCE_PARCEIRO_SOB_CONSULTA,
            defaults={
                "display_name": "Parceiro sob consulta",
                "purchase_flow": SupplierCatalogSource.FLOW_WHATSAPP_CONFIRMATION,
            },
        )

        response = self.client.post(
            f"/gestao/fornecedor/fontes/{source.source}/",
            {
                "display_name": "Catalogo sob consulta",
                "catalog_url": "https://example.com/catalogo.csv",
                "catalog_format": SupplierCatalogSource.FORMAT_CSV,
                "purchase_flow": SupplierCatalogSource.FLOW_WHATSAPP_CONFIRMATION,
                "supplier_panel_note": "Atualizo essa URL manualmente.",
                "customer_notice": "Em breve vamos entrar em contato para confirmar disponibilidade e finalizar pelo WhatsApp.",
                "is_active": "on",
            },
            follow=True,
        )
        source.refresh_from_db()

        self.assertRedirects(response, "/gestao/fornecedor/produtos/")
        self.assertEqual(source.display_name, "Catalogo sob consulta")
        self.assertEqual(source.catalog_url, "https://example.com/catalogo.csv")
        self.assertContains(response, "Catalogo sob consulta foi atualizado.")

    def test_supplier_import_route_redirects_get_to_supplier_products(self):
        staff = User.objects.create_superuser(
            email="admin-import-get@example.com",
            password="Teste12345!",
            full_name="Admin Import GET",
            preferred_name="Admin",
        )
        self.client.force_login(staff)

        response = self.client.get("/gestao/fornecedor/importar/")

        self.assertRedirects(response, "/gestao/fornecedor/produtos/")

    @override_settings(MERCADO_PAGO_ACCESS_TOKEN="")
    def test_checkout_requires_terms_acceptance(self):
        product = self.create_supplier_product()
        user = User.objects.create_user(
            email="checkout-termos@example.com",
            password="Teste12345!",
            full_name="Cliente Termos",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash="cpf-hash-termos",
            cpf_last_digits="3434",
            phone="61999999999",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            f"/loja/produto/{product.id}/comprar/",
            {
                "selected_size": "35",
                "customer_name": "Cliente Teste",
                "customer_email": "cliente@example.com",
                "customer_phone": "61999999999",
                "shipping_state": "DF",
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
    def test_mercado_pago_webhook_marks_all_cart_orders_as_paid(self, mocked_get_payment):
        product = self.create_supplier_product()
        checkout_reference = "f77cbe39-14d8-4954-8f4c-da82908267e6"
        orders = [
            StoreOrder.objects.create(
                product=product,
                product_name=f"{product.name} {number}",
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
                checkout_reference=checkout_reference,
            )
            for number in range(2)
        ]
        mocked_get_payment.return_value = {
            "id": "cart-payment",
            "status": "approved",
            "external_reference": f"cart:{checkout_reference}",
        }

        response = self.client.post(
            "/loja/mercado-pago/webhook/",
            data={"data": {"id": "cart-payment"}},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        for order in orders:
            order.refresh_from_db()
            self.assertEqual(order.status, StoreOrder.PAID)
            self.assertEqual(order.mercado_pago_payment_id, "cart-payment")

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

    def test_staff_can_generate_payment_link_from_manual_debt_form(self):
        self.client.force_login(self.staff)
        due_date = timezone.localdate() + timedelta(days=7)

        response = self.client.post(
            "/gestao/debitos/novo/",
            {
                "client": self.client_user.id,
                "description": "Acerto combinado",
                "amount": "220.00",
                "due_date": due_date.isoformat(),
                "create_payment_link": "on",
            },
        )

        sale = CreditSale.objects.get(client=self.client_user, description="Acerto combinado")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sale.total_amount, Decimal("220.00"))
        self.assertEqual(sale.first_due_date, due_date)
        self.assertEqual(sale.max_installments_allowed, self.client_user.profile.default_max_installments)
        self.assertFalse(Debt.objects.filter(client=self.client_user, description="Acerto combinado").exists())
        self.assertContains(response, "Link de pagamento gerado")
        self.assertContains(response, f"/parcelamento/{sale.id}/")
        self.assertTrue(
            self.client_user.notifications.filter(
                kind=Notification.SALE_AVAILABLE,
                title="Pagamento disponivel para finalizar",
            ).exists()
        )

        dashboard_response = self.client.get("/gestao/")

        self.assertContains(dashboard_response, f"/parcelamento/{sale.id}/")

        self.client_user.profile.phone_verified = True
        self.client_user.profile.save(update_fields=["phone_verified"])
        self.client.force_login(self.client_user)
        client_response = self.client.get(f"/parcelamento/{sale.id}/")

        self.assertContains(client_response, "Acerto combinado")
        self.assertContains(client_response, "Op&ccedil;&otilde;es de pagamento", html=False)

    def test_payment_link_requires_approved_client(self):
        self.client_user.profile.registration_status = ClientProfile.PENDING
        self.client_user.profile.save(update_fields=["registration_status"])
        self.client.force_login(self.staff)

        response = self.client.post(
            "/gestao/debitos/novo/",
            {
                "client": self.client_user.id,
                "description": "Link para pendente",
                "amount": "220.00",
                "due_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "create_payment_link": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apenas clientes aprovados podem receber link de pagamento.")
        self.assertFalse(CreditSale.objects.filter(client=self.client_user, description="Link para pendente").exists())
        self.assertFalse(Debt.objects.filter(client=self.client_user, description="Link para pendente").exists())

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
        notification = self.client_user.notifications.get(kind=Notification.REGISTRATION_APPROVED)
        self.assertIn("Seu limite liberado e de R$ 500,00.", notification.message)

    def test_staff_credit_limit_increase_notifies_client_only_when_value_increases(self):
        profile = self.client_user.profile
        profile.pre_approved_credit_limit = Decimal("500.00")
        profile.save(update_fields=["pre_approved_credit_limit"])
        self.client.force_login(self.staff)

        payload = {
            "pre_approved_credit_limit": "750.00",
            "default_max_installments": "5",
            "admin_notes": "",
            "action": "approve",
        }
        response = self.client.post(f"/gestao/cadastros/{profile.id}/", payload)

        self.assertRedirects(response, "/gestao/")
        notification = self.client_user.notifications.get(kind=Notification.CREDIT_LIMIT_INCREASED)
        self.assertEqual(notification.title, "Seu limite aumentou")
        self.assertIn("de R$ 500,00 para R$ 750,00", notification.message)

        response = self.client.post(f"/gestao/cadastros/{profile.id}/", payload)

        self.assertRedirects(response, "/gestao/")
        self.assertEqual(self.client_user.notifications.filter(kind=Notification.CREDIT_LIMIT_INCREASED).count(), 1)

    def test_sale_available_notification_invites_client_to_choose_payment_only_once(self):
        sale = CreditSale.objects.create(
            client=self.client_user,
            description="Sandalia reservada",
            total_amount=Decimal("180.00"),
            first_due_date="2026-06-10",
        )

        create_sale_available_notification(sale)
        create_sale_available_notification(sale)

        notification = self.client_user.notifications.get(kind=Notification.SALE_AVAILABLE)
        self.assertIn("escolher a forma de pagamento", notification.message)
        self.assertEqual(self.client_user.notifications.filter(kind=Notification.SALE_AVAILABLE).count(), 1)

    def test_sale_confirmation_notifies_client_and_staff_only_once(self):
        sale = CreditSale.objects.create(
            client=self.client_user,
            description="Sandalia efetivada",
            total_amount=Decimal("180.00"),
            first_due_date="2026-06-10",
        )
        sale.choose_payment(CreditSale.PIX)

        create_sale_confirmed_notifications(sale)
        create_sale_confirmed_notifications(sale)

        client_notification = self.client_user.notifications.get(kind=Notification.SALE_CONFIRMED)
        staff_notification = self.staff.notifications.get(kind=Notification.SALE_CONFIRMED)
        self.assertEqual(client_notification.title, "Compra efetivada")
        self.assertIn("Forma de pagamento: Pix", staff_notification.message)
        self.assertEqual(Notification.objects.filter(kind=Notification.SALE_CONFIRMED).count(), 2)

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

    def test_staff_can_mark_debt_paid_manually_from_profile(self):
        debt = Debt.objects.create(
            client=self.client_user,
            description="Parcela paga fora do app",
            amount=Decimal("80.00"),
            due_date=timezone.localdate() - timedelta(days=2),
        )

        response = self.client.post(
            f"/gestao/debitos/{debt.id}/pagamento/",
            {
                "action": "mark_paid",
                "return_profile_id": self.profile.id,
            },
            follow=True,
        )
        debt.refresh_from_db()

        self.assertRedirects(response, f"/gestao/cadastros/{self.profile.id}/")
        self.assertTrue(debt.paid)
        self.assertEqual(debt.paid_at, timezone.localdate())
        self.assertContains(response, "Debito marcado como pago manualmente.")
        self.assertContains(response, "Pago em")

    def test_staff_can_quick_mark_debt_paid_from_clients_list(self):
        debt = Debt.objects.create(
            client=self.client_user,
            description="Parcela para baixa rapida",
            amount=Decimal("80.00"),
            due_date=timezone.localdate() - timedelta(days=2),
        )

        list_response = self.client.get("/gestao/clientes/?financeiro=open")

        self.assertContains(list_response, "Dar baixa")
        self.assertContains(list_response, "Parcela para baixa rapida")

        response = self.client.post(
            f"/gestao/debitos/{debt.id}/pagamento/",
            {
                "action": "mark_paid",
                "next": "/gestao/clientes/?financeiro=open",
            },
            follow=True,
        )
        debt.refresh_from_db()

        self.assertRedirects(response, "/gestao/clientes/?financeiro=open")
        self.assertTrue(debt.paid)
        self.assertEqual(debt.paid_at, timezone.localdate())
        self.assertContains(response, "Debito marcado como pago manualmente.")
        self.assertNotContains(response, "Parcela para baixa rapida")

    def test_staff_can_reopen_debt_after_manual_payment(self):
        debt = Debt.objects.create(
            client=self.client_user,
            description="Parcela baixada por engano",
            amount=Decimal("95.00"),
            due_date=timezone.localdate(),
            paid=True,
            paid_at=timezone.localdate(),
        )

        response = self.client.post(
            f"/gestao/debitos/{debt.id}/pagamento/",
            {
                "action": "mark_unpaid",
                "return_profile_id": self.profile.id,
            },
            follow=True,
        )
        debt.refresh_from_db()

        self.assertRedirects(response, f"/gestao/cadastros/{self.profile.id}/")
        self.assertFalse(debt.paid)
        self.assertIsNone(debt.paid_at)
        self.assertContains(response, "Baixa manual removida e debito reaberto.")
        self.assertContains(response, "Pendente")


class PartnerSalesReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="sellmaramos.3012@gmail.com",
            password="123456",
            full_name="Ramose Parceira",
            preferred_name="Ramose",
        )
        self.profile = ClientProfile.objects.create(
            user=self.user,
            cpf_hash="cpf-hash-ramose",
            cpf_last_digits="3012",
            phone="61988887766",
            phone_verified=True,
            address="Endereco Ramose",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            extra_data={
                "sales_report_brand_keyword": "Ramose",
                "sales_report_brand_aliases": ["Ramosê"],
                "sales_report_title": "Relatorio Ramose",
                "brand_theme": {
                    "accent": "#6f5139",
                    "ink": "#4e3b2d",
                    "soft": "#8a9065",
                    "surface": "#fffaf4",
                    "page": "#f6efe7",
                    "line": "#ddd1c5",
                },
            },
        )
        self.other_user = User.objects.create_user(
            email="outra-cliente@example.com",
            password="Teste12345!",
            full_name="Outra Cliente",
            preferred_name="Outra",
        )
        ClientProfile.objects.create(
            user=self.other_user,
            cpf_hash="cpf-hash-outra",
            cpf_last_digits="2020",
            phone="61988887700",
            phone_verified=True,
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )
        self.client.force_login(self.user)

    def create_supplier_product(self, code, name):
        return SupplierProduct.objects.create(
            source=SupplierProduct.SOURCE_REVENDA_CALCADOS,
            supplier_code=code,
            name=name,
            wholesale_price=Decimal("80.00"),
            dropshipping_cost=Decimal("90.00"),
            suggested_sale_price=Decimal("150.00"),
            stock_quantity=10,
            is_active=True,
            is_visible=True,
        )

    def create_store_order(self, product, customer, product_name, total_amount, estimated_profit, quantity=1, days_ago=0):
        order = StoreOrder.objects.create(
            product=product,
            customer=customer,
            product_name=product_name,
            supplier_code=product.supplier_code,
            selected_size="U",
            quantity=quantity,
            customer_name=customer.full_name,
            customer_email=customer.email,
            customer_phone="61999999999",
            shipping_address="Rua Teste, 1",
            unit_price=Decimal("150.00"),
            supplier_cost=Decimal("90.00"),
            total_amount=Decimal(total_amount),
            estimated_profit=Decimal(estimated_profit),
            status=StoreOrder.PAID,
        )
        sale_time = timezone.now() - timedelta(days=days_ago)
        StoreOrder.objects.filter(id=order.id).update(created_at=sale_time, paid_at=sale_time)

        return StoreOrder.objects.get(id=order.id)

    def test_partner_sales_report_forbidden_without_brand_access(self):
        no_access_user = User.objects.create_user(
            email="sem-relatorio@example.com",
            password="Teste12345!",
            full_name="Sem Relatorio",
            preferred_name="Sem",
        )
        ClientProfile.objects.create(
            user=no_access_user,
            cpf_hash="cpf-hash-sem-relatorio",
            cpf_last_digits="9090",
            phone="61988889999",
            phone_verified=True,
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
        )
        self.client.force_login(no_access_user)

        response = self.client.get("/painel/relatorio-vendas/")

        self.assertEqual(response.status_code, 403)

    def test_partner_sales_report_combines_brand_sales_with_own_purchases(self):
        brand_product = self.create_supplier_product("RAM001", "Bolsa Ramosê Premium")
        own_product = self.create_supplier_product("OWN001", "Sandalia Nude")
        other_product = self.create_supplier_product("OUT001", "Produto Generico")

        self.create_store_order(brand_product, self.other_user, "Bolsa Ramosê Premium", "300.00", "120.00", quantity=2, days_ago=3)
        self.create_store_order(own_product, self.user, "Sandalia Nude", "150.00", "60.00", quantity=1, days_ago=2)
        self.create_store_order(other_product, self.other_user, "Produto Generico", "199.00", "40.00", quantity=1, days_ago=1)
        self.create_store_order(brand_product, self.other_user, "Bolsa Ramosê Premium", "100.00", "35.00", quantity=1, days_ago=40)

        response = self.client.get("/painel/relatorio-vendas/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["total_orders"], 2)
        self.assertEqual(response.context["summary"]["total_units"], 3)
        self.assertEqual(response.context["summary"]["total_revenue"], Decimal("450.00"))
        self.assertEqual(response.context["summary"]["total_profit"], Decimal("180.00"))
        self.assertContains(response, "Relatorio Ramose")
        self.assertContains(response, "R$ 450,00")
        self.assertNotContains(response, "Produto Generico")

    def test_partner_sales_report_brand_only_scope_and_ranking(self):
        first_brand_product = self.create_supplier_product("RAM010", "Bolsa Ramosê Mini")
        second_brand_product = self.create_supplier_product("RAM020", "Bolsa Ramose Maxi")

        self.create_store_order(first_brand_product, self.other_user, "Bolsa Ramosê Mini", "180.00", "70.00", quantity=1, days_ago=5)
        self.create_store_order(second_brand_product, self.other_user, "Bolsa Ramose Maxi", "400.00", "160.00", quantity=3, days_ago=4)

        response = self.client.get("/painel/relatorio-vendas/?scope=brand_only&ranking=revenue")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scope"], "brand_only")
        self.assertEqual(response.context["ranking_products"][0]["name"], "Bolsa Ramose Maxi")
        self.assertEqual(response.context["summary"]["total_orders"], 2)
        self.assertContains(response, "Somente Ramosê")


class CustomerEntryRoutingTests(TestCase):
    def create_client(self, email="cliente-fluxo@example.com"):
        user = User.objects.create_user(
            email=email,
            password="Teste12345!",
            full_name="Cliente Fluxo",
            preferred_name="Cliente",
        )
        ClientProfile.objects.create(
            user=user,
            cpf_hash=f"cpf-hash-{email}",
            cpf_last_digits="3333",
            phone="61999998888",
            address="Endereco",
            residence_proof=SimpleUploadedFile("comprovante.pdf", b"pdf"),
            registration_status=ClientProfile.APPROVED,
            phone_verified=True,
        )

        return user

    def test_home_redirects_guest_to_public_store(self):
        response = self.client.get("/")

        self.assertRedirects(response, "/loja/")

    def test_home_redirects_client_with_pending_sale_to_store(self):
        user = self.create_client()
        CreditSale.objects.create(
            client=user,
            description="Compra separada",
            total_amount=Decimal("180.00"),
            first_due_date="2026-06-10",
        )
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(response, "/loja/")

    def test_login_page_redirects_authenticated_client_with_pending_sale_to_store(self):
        user = self.create_client(email="cliente-login@example.com")
        CreditSale.objects.create(
            client=user,
            description="Compra separada",
            total_amount=Decimal("180.00"),
            first_due_date="2026-06-10",
        )
        self.client.force_login(user)

        response = self.client.get("/login/")

        self.assertRedirects(response, "/loja/")

    def test_home_keeps_client_without_pending_sale_on_dashboard(self):
        user = self.create_client(email="cliente-dashboard@example.com")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(response, "/painel/")

    def test_login_route_opens_for_guest_without_next(self):
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continuar sem login")
        self.assertContains(response, "Crie sua conta com CPF, email e nome")
        self.assertNotContains(response, "Abrir minha conta")

    def test_login_page_still_opens_when_purchase_redirect_includes_next(self):
        response = self.client.get("/login/?next=/loja/carrinho/finalizar/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continuar sem login")
        self.assertContains(response, "Finalizar seu carrinho")
        self.assertContains(response, "Faca seu cadastro")
        self.assertContains(response, 'href="/cadastro/?next=/loja/carrinho/finalizar/"')


class StoreCheckoutAccessTests(TestCase):
    def create_supplier_product(self):
        return SupplierProduct.objects.create(
            supplier_code="SKU-001",
            name="Sandalia teste",
            brand="Marca teste",
            category="Sandalias",
            image_url="https://example.com/sandalia.jpg",
            product_url="https://example.com/sandalia",
            dropshipping_cost=Decimal("55.00"),
            suggested_sale_price=Decimal("99.90"),
            stock_quantity=5,
            sizes="34,35,36",
            is_visible=True,
            is_active=True,
        )

    def test_guest_is_redirected_to_login_when_trying_cart_checkout(self):
        response = self.client.get("/loja/carrinho/finalizar/")

        self.assertRedirects(response, "/login/?next=/loja/carrinho/finalizar/")

    def test_guest_is_redirected_to_login_when_trying_direct_product_checkout(self):
        product = self.create_supplier_product()

        response = self.client.get(f"/loja/produto/{product.id}/comprar/")

        self.assertRedirects(response, f"/login/?next=/loja/produto/{product.id}/comprar/")


class PlayStorePreparationTests(TestCase):
    def test_assetlinks_returns_android_app_binding_when_configured(self):
        with self.settings(
            ANDROID_APP_PACKAGE_ID="com.lindice.app",
            ANDROID_SHA256_CERT_FINGERPRINTS=[
                "AA:BB:CC:DD:EE:FF",
                "11:22:33:44:55:66",
            ],
        ):
            response = self.client.get("/.well-known/assetlinks.json")

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            [
                {
                    "relation": ["delegate_permission/common.handle_all_urls"],
                    "target": {
                        "namespace": "android_app",
                        "package_name": "com.lindice.app",
                        "sha256_cert_fingerprints": [
                            "AA:BB:CC:DD:EE:FF",
                            "11:22:33:44:55:66",
                        ],
                    },
                }
            ],
        )

    def test_assetlinks_returns_empty_list_when_not_configured(self):
        with self.settings(
            ANDROID_APP_PACKAGE_ID="",
            ANDROID_SHA256_CERT_FINGERPRINTS=[],
        ):
            response = self.client.get("/.well-known/assetlinks.json")

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, [])
