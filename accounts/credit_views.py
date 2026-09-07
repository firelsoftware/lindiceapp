from decimal import Decimal
from io import BytesIO

from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import ClientProfile, CreditSale, CreditAgreement, CreditAgreementSettings
from .utils import clean_digits, cpf_hash, is_valid_cpf


class SettingsForm(forms.ModelForm):
    class Meta:
        model = CreditAgreementSettings
        fields = ('seller_name', 'seller_cpf', 'seller_phone', 'terms')
        labels = {'seller_name': 'Nome do vendedor', 'seller_cpf': 'CPF do vendedor',
                  'seller_phone': 'Telefone do vendedor', 'terms': 'Texto do contrato'}
        widgets = {'terms': forms.Textarea(attrs={'rows': 28})}

    def clean_seller_cpf(self):
        value = clean_digits(self.cleaned_data['seller_cpf'])
        if not is_valid_cpf(value):
            raise forms.ValidationError('Informe um CPF válido.')
        return value


class IdentityForm(forms.Form):
    cpf = forms.CharField(label='Confirme seu CPF para preencher o contrato', max_length=14)

    def __init__(self, *args, profile, **kwargs):
        self.profile = profile
        super().__init__(*args, **kwargs)

    def clean_cpf(self):
        value = clean_digits(self.cleaned_data['cpf'])
        if not is_valid_cpf(value) or cpf_hash(value) != self.profile.cpf_hash:
            raise forms.ValidationError('O CPF precisa corresponder ao seu cadastro.')
        return value


class SignedForm(forms.Form):
    document = forms.FileField(label='PDF assinado pelo gov.br')

    def clean_document(self):
        import pymupdf
        file = self.cleaned_data['document']
        if file.size > 10 * 1024 * 1024:
            raise forms.ValidationError('Envie um PDF de até 10 MB.')
        try:
            data = file.read()
            if not data.startswith(b'%PDF-'):
                raise ValueError()
            with pymupdf.open(stream=data, filetype='pdf') as pdf:
                if pdf.is_encrypted or not pdf.page_count:
                    raise ValueError()
        except Exception:
            raise forms.ValidationError('Envie um PDF válido, sem senha.')
        finally:
            file.seek(0)
        return file


@staff_member_required(login_url='login')
@never_cache
def contract_settings(request):
    config = CreditAgreementSettings.load()
    form = SettingsForm(request.POST or None, instance=config)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.updated_by = request.user
        obj.save()
        messages.success(request, 'Modelo salvo. Contratos já emitidos permanecem preservados.')
        return redirect('credit_contract_settings')
    return render(request, 'accounts/credit_settings.html', {'form': form})


@login_required
@never_cache
def my_contract(request):
    if request.user.is_staff:
        return redirect('credit_contract_settings')
    profile = request.user.profile
    identity_form = IdentityForm(profile=profile)
    signed_form = SignedForm()
    if request.method == 'POST':
        with transaction.atomic():
            profile = ClientProfile.objects.select_for_update().get(pk=profile.pk)
            agreement = profile.credit_agreements.order_by('-id').first()
            action = request.POST.get('action')
            if action == 'issue':
                identity_form = IdentityForm(request.POST, profile=profile)
                if profile.registration_status != ClientProfile.APPROVED or profile.pre_approved_credit_limit <= 0:
                    messages.error(request, 'Aguarde a aprovação do cadastro e do limite.')
                elif not CreditAgreementSettings.load().esta_completo():
                    # Sem os dados do vendedor o contrato sairia em branco, e um
                    # contrato assim nao vale. Melhor nem emitir.
                    messages.error(request, 'O contrato ainda não está disponível. Fale com a loja.')
                elif agreement and agreement.status != CreditAgreement.REJECTED:
                    messages.info(request, 'Seu contrato já está disponível abaixo.')
                elif identity_form.is_valid():
                    config = CreditAgreementSettings.load()
                    CreditAgreement.objects.create(profile=profile,
                        snapshot={'seller_name': config.seller_name, 'seller_cpf': config.seller_cpf,
                                  'seller_phone': config.seller_phone, 'terms': config.terms,
                                  'buyer_name': request.user.full_name, 'buyer_cpf': identity_form.cleaned_data['cpf'],
                                  'buyer_phone': profile.phone, 'buyer_address': profile.address,
                                  'limit': str(profile.pre_approved_credit_limit),
                                  'date': timezone.localdate().strftime('%d/%m/%Y')})
                    return redirect('credit_contract')
            elif action == 'upload':
                signed_form = SignedForm(request.POST, request.FILES)
                if not agreement or str(agreement.pk) != request.POST.get('agreement_id') or agreement.status != CreditAgreement.ISSUED:
                    messages.error(request, 'Este contrato não está disponível para envio.')
                elif signed_form.is_valid():
                    agreement.signed_document = signed_form.cleaned_data['document']
                    agreement.status = CreditAgreement.SUBMITTED
                    agreement.save(update_fields=['signed_document', 'status'])
                    messages.success(request, 'PDF recebido. Aguarde a conferência do administrador.')
                    return redirect('credit_contract')
    agreement = profile.credit_agreements.order_by('-id').first()
    return render(request, 'accounts/credit_contract.html', {
        'profile': profile, 'agreement': agreement, 'identity_form': identity_form,
        'signed_form': signed_form,
        'can_issue': (
            profile.registration_status == ClientProfile.APPROVED
            and profile.pre_approved_credit_limit > 0
            and CreditAgreementSettings.load().esta_completo()
        ),
    })


def allowed_agreement(request, agreement_id):
    agreements = CreditAgreement.objects.all()
    if not request.user.is_staff:
        agreements = agreements.filter(profile__user=request.user)
    return get_object_or_404(agreements, pk=agreement_id)


def pdf_bytes(agreement):
    import pymupdf
    d = agreement.snapshot
    text = (f"CONTRATO PARTICULAR DE CREDIÁRIO - LINDICE\nContrato {agreement.pk}\n\n"
            f"VENDEDOR: {d['seller_name']}\nCPF: {d['seller_cpf']} | Telefone: {d['seller_phone']}\n\n"
            f"COMPRADOR: {d['buyer_name']}\nCPF: {d['buyer_cpf']} | Telefone: {d['buyer_phone']}\n"
            f"Endereço: {d['buyer_address']}\n\nLimite aprovado: R$ {Decimal(d['limit']):.2f}\nData: {d['date']}\n\n"
            f"{d['terms']}\n\nVENDEDOR: {d['seller_name']}\nAssinatura eletrônica pelo gov.br.\n\n"
            f"COMPRADOR: {d['buyer_name']}\nAssinatura eletrônica pelo gov.br.")
    doc = pymupdf.open()
    page = None
    y = 900
    def line(value):
        nonlocal page, y
        if y > 775:
            page = doc.new_page(width=595, height=842)
            y = 48
        page.insert_text((44, y), value, fontsize=12, fontname='helv')
        y += 17
    for paragraph in text.splitlines():
        if not paragraph:
            line('')
            continue
        current = ''
        for word in paragraph.split():
            if pymupdf.get_text_length((current + ' ' + word).strip(), fontsize=12) > 505:
                if current:
                    line(current)
                    current = ''
                while pymupdf.get_text_length(word, fontsize=12) > 505:
                    count = 1
                    while count < len(word) and pymupdf.get_text_length(word[:count+1], fontsize=12) <= 505:
                        count += 1
                    line(word[:count])
                    word = word[count:]
            current = (current + ' ' + word).strip()
        line(current)
    for number, page in enumerate(doc, 1):
        page.insert_text((44, 815), f'Lindice | Contrato {agreement.pk} | Página {number} de {len(doc)}', fontsize=9)
    result = doc.tobytes()
    doc.close()
    return result


@login_required
@never_cache
def contract_pdf(request, agreement_id):
    agreement = allowed_agreement(request, agreement_id)
    response = HttpResponse(pdf_bytes(agreement), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="contrato-crediario-{agreement.pk}.pdf"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@never_cache
def signed_file(request, agreement_id):
    agreement = allowed_agreement(request, agreement_id)
    if not agreement.signed_document:
        raise Http404()
    return FileResponse(agreement.signed_document.open('rb'), as_attachment=True,
                        filename=f'contrato-{agreement.pk}-assinado.pdf', content_type='application/pdf')


@staff_member_required(login_url='login')
@never_cache
def review_contract(request, profile_id):
    profile = get_object_or_404(ClientProfile, pk=profile_id)
    final_form = SignedForm()
    if request.method == 'POST':
        with transaction.atomic():
            profile = ClientProfile.objects.select_for_update().get(pk=profile.pk)
            agreement = get_object_or_404(CreditAgreement, pk=request.POST.get('agreement_id'), profile=profile)
            if agreement.status != CreditAgreement.SUBMITTED:
                messages.error(request, 'Este contrato não aguarda conferência.')
            elif request.POST.get('action') == 'attach_final':
                final_form = SignedForm(request.POST, request.FILES)
                if final_form.is_valid():
                    agreement.signed_document = final_form.cleaned_data['document']
                    agreement.save(update_fields=['signed_document'])
                    messages.success(request, 'Via final anexada. Confira as assinaturas antes de confirmar o contrato.')
                else:
                    messages.error(request, 'Envie um PDF válido, sem senha, de até 10 MB.')
            elif request.POST.get('action') == 'verify' and request.POST.get('checked') == 'yes':
                agreement.status = CreditAgreement.VERIFIED
                agreement.reviewed_by = request.user
                agreement.reviewed_at = timezone.now()
                agreement.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
                messages.success(request, 'Contrato conferido e liberado.')
            elif request.POST.get('action') == 'reject':
                agreement.status = CreditAgreement.REJECTED
                agreement.reviewed_by = request.user
                agreement.reviewed_at = timezone.now()
                agreement.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
                messages.success(request, 'Contrato devolvido. O cliente poderá emitir e assinar uma nova versão.')
            else:
                messages.error(request, 'Confirme que conferiu a assinatura, os signatários e o conteúdo do documento.')
        return redirect('credit_contract_review', profile_id=profile.pk)
    return render(request, 'accounts/credit_review.html', {'profile': profile, 'final_form': final_form,
        'agreements': profile.credit_agreements.order_by('-id'),
        'sales': profile.user.credit_sales.filter(status=CreditSale.PENDING).order_by('-id')})


@staff_member_required(login_url='login')
@require_POST
def waive_entry(request, sale_id):
    with transaction.atomic():
        sale = get_object_or_404(CreditSale, pk=sale_id)
        if not sale.client_id:
            raise Http404()
        ClientProfile.objects.select_for_update().get(user_id=sale.client_id)
        sale = CreditSale.objects.select_for_update().get(pk=sale_id)
        if sale.status != CreditSale.PENDING:
            messages.error(request, 'Só é possível alterar a entrada antes da confirmação da compra.')
        else:
            sale.entry_waived = request.POST.get('waive') == 'yes'
            sale.entry_waived_by = request.user
            sale.entry_waived_at = timezone.now()
            sale.save(update_fields=['entry_waived', 'entry_waived_by', 'entry_waived_at'])
            messages.success(request, 'Condição da entrada atualizada para esta compra.')
    return redirect('credit_contract_review', profile_id=sale.client.profile.pk)


@login_required
@never_cache
def purchase_pdf(request, sale_id):
    sales = CreditSale.objects.filter(status=CreditSale.ACCEPTED, selected_payment_method=CreditSale.CREDIT)
    if not request.user.is_staff:
        sales = sales.filter(client=request.user)
    sale = get_object_or_404(sales.select_related('credit_agreement'), pk=sale_id)
    if not sale.credit_agreement:
        raise Http404()
    from types import SimpleNamespace
    snapshot = dict(sale.credit_agreement.snapshot)
    schedule = '\n'.join(f'{debt.description} | Vencimento {debt.due_date:%d/%m/%Y} | R$ {debt.amount:.2f}' for debt in sale.debts.order_by('due_date', 'pk'))
    snapshot['terms'] = (f"RESUMO DA COMPRA {sale.sale_code}\n{sale.description}\n"
        f"Entrada acordada: R$ {sale.entry_amount:.2f}\nValor principal financiado: R$ {sale.principal_financed:.2f}\n"
        f"Total a pagar: R$ {sale.selected_total_with_interest:.2f}\n"
        f"Juros mensais do financiamento: {sale.selected_monthly_interest_percent}%\n"
        f"{schedule}\n\n" + snapshot['terms'])
    response = HttpResponse(pdf_bytes(SimpleNamespace(pk=sale.credit_agreement_id, snapshot=snapshot)), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="compra-{sale.pk}-crediario.pdf"'
    return response
