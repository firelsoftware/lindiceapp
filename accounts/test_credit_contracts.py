from decimal import Decimal
from datetime import timedelta
from tempfile import TemporaryDirectory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import User, ClientProfile, CreditSale, Debt, CreditAgreement, CreditAgreementSettings
from .utils import cpf_hash
from .credit_views import pdf_bytes


class CreditRulesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='credit@example.com', password='example', full_name='Cliente Teste')
        self.profile = ClientProfile.objects.create(user=self.user, cpf_hash=cpf_hash('52998224725'), cpf_last_digits='4725',
            phone='61999999999', address='Endereço teste', phone_verified=True, registration_status='approved',
            pre_approved_credit_limit=Decimal('500.00'), credit_contract_required=False)
        self.admin = User.objects.create_user(email='staff@example.com', password='example', is_staff=True)
        # Sem os dados do vendedor o contrato nao e emitido, entao a loja
        # preenche uma vez, como faz na tela de configuracao.
        config = CreditAgreementSettings.load()
        config.seller_name = 'Loja Teste'
        config.seller_cpf = '52998224725'
        config.seller_phone = '61999999999'
        config.save()

    def sale(self, amount='300.00'):
        return CreditSale.objects.create(client=self.user, description='Compra teste', total_amount=Decimal(amount),
            first_due_date=timezone.localdate()+timedelta(days=20), max_installments_allowed=5)

    def test_first_entry_and_next_without_entry(self):
        sale=self.sale()
        self.assertEqual(sale.credit_entry_amount(), Decimal('20'))
        sale.choose_payment('credit', 2, remainder_payment_method='pix')
        self.assertEqual(self.profile.credit_available(), Decimal('220'))
        # A entrada e cobrada no fechamento, junto com o Pix: ela nao vira
        # divida, senao o cliente pagaria os mesmos R$ 20 duas vezes.
        self.assertFalse(sale.debts.filter(is_credit_entry=True).exists())
        self.assertEqual(sale.remainder_amount, Decimal('20'))
        second=self.sale('100')
        self.assertEqual(second.credit_entry_amount(), Decimal('0'))
        second.choose_payment('credit', 1)
        self.assertEqual(self.profile.credit_available(), Decimal('120'))
        debt=sale.debts.filter(is_credit_entry=False).first()
        debt.mark_paid()
        self.assertEqual(self.profile.credit_available(), Decimal('260'))
        debt.mark_paid()
        self.assertEqual(self.profile.credit_available(), Decimal('260'))
        debt.mark_unpaid()
        self.assertEqual(self.profile.credit_available(), Decimal('120'))

    def test_limite_zero_financia_tudo_e_acima_do_limite_financia_o_que_cabe(self):
        # Limite zero e "a loja ainda nao definiu limite", nao "sem crediario":
        # tratar como zero disponivel travaria todo aprovado que nunca teve
        # limite digitado.
        self.profile.pre_approved_credit_limit = Decimal('0.00')
        self.profile.save()
        sale = self.sale('300.00')
        self.assertEqual(sale.credit_financed_amount(), Decimal('280.00'))

        # Com limite definido, a compra maior que o saldo nao e recusada: vai
        # para o carne o que cabe e o resto sai no fechamento.
        self.profile.pre_approved_credit_limit = Decimal('150.00')
        self.profile.save()
        maior = self.sale('190.00')
        self.assertEqual(maior.credit_entry_amount(), Decimal('20.00'))
        self.assertEqual(maior.credit_financed_amount(), Decimal('150.00'))
        self.assertEqual(maior.credit_above_limit_amount(), Decimal('20.00'))
        self.assertEqual(maior.credit_remainder_amount(), Decimal('40.00'))

        maior.choose_payment('credit', 2, remainder_payment_method='pix')
        maior.refresh_from_db()
        pago_no_carne = sum(d.amount for d in maior.debts.all())
        self.assertEqual(maior.remainder_amount + pago_no_carne, Decimal('190.00'))

    def test_interest_not_released_and_rounding_exact(self):
        sale=self.sale('399.99')
        sale.entry_waived=True
        sale.save()
        sale.choose_payment('credit', 4)
        debts=list(sale.debts.all())
        self.assertEqual(sum(d.principal_amount for d in debts), Decimal('399.99'))
        self.assertEqual(sum(d.amount for d in debts), sale.financed_total_with_interest)
        debts[0].mark_paid()
        self.assertGreater(debts[0].amount, debts[0].principal_amount)
        self.assertEqual(self.profile.credit_available(), Decimal('100.01')+debts[0].principal_amount)

    def test_repeated_checkout_does_not_delete_payments(self):
        sale=self.sale()
        stale=CreditSale.objects.get(pk=sale.pk)
        sale.choose_payment('credit', 2, remainder_payment_method='pix')
        ids=list(sale.debts.values_list('pk',flat=True))
        with self.assertRaises(ValueError): stale.choose_payment('pix')
        self.assertEqual(ids,list(sale.debts.values_list('pk',flat=True)))

    def test_server_enforces_contract_and_approval(self):
        self.profile.credit_contract_required=True
        self.profile.save()
        with self.assertRaisesMessage(ValueError,'contrato'): self.sale().choose_payment('credit',1)
        CreditAgreement.objects.create(profile=self.profile,status='submitted')
        with self.assertRaisesMessage(ValueError,'contrato'): self.sale().choose_payment('credit',1)
        CreditAgreement.objects.create(profile=self.profile,status='verified')
        self.sale().choose_payment('credit',1,remainder_payment_method='pix')

    def test_waiver_is_staff_only_and_scoped_to_sale(self):
        sale=self.sale()
        url=reverse('credit_entry_waive',args=[sale.pk])
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url,{'waive':'yes'}).status_code,302)
        sale.refresh_from_db(); self.assertFalse(sale.entry_waived)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code,405)
        self.client.post(url,{'waive':'yes'})
        sale.refresh_from_db()
        self.assertEqual(sale.entry_waived_by,self.admin)
        self.assertEqual(sale.credit_entry_amount(),0)
        self.assertEqual(self.sale().credit_entry_amount(),20)
        sale.choose_payment('credit',2)
        self.assertEqual(sale.principal_financed,300)
        self.client.post(url,{'waive':'no'})
        sale.refresh_from_db(); self.assertTrue(sale.entry_waived)

    def test_contract_owner_only_and_snapshot_unchanged(self):
        self.client.force_login(self.user)
        self.client.post(reverse('credit_contract'),{'action':'issue','cpf':'52998224725'})
        agreement=CreditAgreement.objects.get()
        config=CreditAgreementSettings.load(); config.terms='Texto novo'; config.save()
        agreement.refresh_from_db(); self.assertNotEqual(agreement.snapshot['terms'],'Texto novo')
        pdf_url=reverse('credit_contract_pdf',args=[agreement.pk])
        self.assertEqual(self.client.get(pdf_url).status_code,200)
        other=User.objects.create_user(email='other@example.com',password='example')
        self.client.force_login(other)
        self.assertEqual(self.client.get(pdf_url).status_code,404)
        self.assertEqual(self.client.get(reverse('credit_contract_settings')).status_code,302)

    def test_upload_needs_manual_verification(self):
        self.client.force_login(self.user)
        self.client.post(reverse('credit_contract'),{'action':'issue','cpf':'52998224725'})
        agreement=CreditAgreement.objects.get()
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            file=SimpleUploadedFile('assinado.pdf',pdf_bytes(agreement),content_type='application/pdf')
            self.client.post(reverse('credit_contract'),{'action':'upload','agreement_id':agreement.pk,'document':file})
            agreement.refresh_from_db(); self.assertEqual(agreement.status,'submitted')
            url=reverse('credit_contract_review',args=[self.profile.pk])
            self.client.post(url,{'agreement_id':agreement.pk,'action':'verify','checked':'yes'})
            agreement.refresh_from_db(); self.assertEqual(agreement.status,'submitted')
            self.client.force_login(self.admin)
            self.client.post(url,{'agreement_id':agreement.pk,'action':'verify'})
            agreement.refresh_from_db(); self.assertEqual(agreement.status,'submitted')
            self.client.post(url,{'agreement_id':agreement.pk,'action':'verify','checked':'yes'})
            agreement.refresh_from_db(); self.assertEqual(agreement.status,'verified')

    def test_bad_cpf_and_bad_upload_rejected(self):
        self.client.force_login(self.user)
        self.client.post(reverse('credit_contract'),{'action':'issue','cpf':'11111111111'})
        self.assertFalse(CreditAgreement.objects.exists())
        self.client.post(reverse('credit_contract'),{'action':'issue','cpf':'52998224725'})
        agreement=CreditAgreement.objects.get()
        self.client.post(reverse('credit_contract'),{'action':'upload','agreement_id':agreement.pk,
            'document':SimpleUploadedFile('fake.pdf',b'<script>x</script>')})
        agreement.refresh_from_db(); self.assertEqual(agreement.status,'issued')

    def test_cancel_releases_principal(self):
        sale=self.sale(); sale.choose_payment('credit',2,remainder_payment_method='pix')
        debt=sale.debts.filter(is_credit_entry=False).first()
        debt.cancel('Devolução')
        self.assertEqual(self.profile.credit_available(),Decimal('360'))
