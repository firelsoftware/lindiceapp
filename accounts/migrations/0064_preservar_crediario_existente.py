from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def backfill(apps, schema_editor):
    Sale = apps.get_model('accounts', 'CreditSale')
    Debt = apps.get_model('accounts', 'Debt')
    Profile = apps.get_model('accounts', 'ClientProfile')
    alias = schema_editor.connection.alias
    for sale in Sale.objects.using(alias).filter(status='accepted', selected_payment_method='credit').iterator():
        # Historical contracts remain usable; no retroactive signing requirement.
        Profile.objects.using(alias).filter(user_id=sale.client_id).update(credit_contract_required=False)
        debts = list(Debt.objects.using(alias).filter(credit_sale_id=sale.pk).order_by('pk'))
        base = max(Decimal('0.00'), sale.total_amount - sale.welcome_discount_amount - sale.remainder_amount)
        total = sum((d.amount for d in debts), Decimal('0.00'))
        base = min(base, total)
        Sale.objects.using(alias).filter(pk=sale.pk).update(principal_financed=base)
        assigned = Decimal('0.00')
        for index, debt in enumerate(debts):
            part = (base * debt.amount / total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if total else Decimal('0.00')
            part = min(part, base - assigned)
            if index == len(debts)-1:
                part = base - assigned
            assigned += part
            Debt.objects.using(alias).filter(pk=debt.pk).update(principal_amount=part)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0063_crediario_contratos_e_saldo')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
