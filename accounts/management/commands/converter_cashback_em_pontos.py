"""Converte o saldo de cashback dos clientes em pontos de fidelidade.

Cada real de saldo vira 2 pontos, respeitando o teto configurado na loja. O
saldo antigo e zerado no mesmo passo, para ninguem receber os dois beneficios.

Rode primeiro com --ensaio para ver o que aconteceria sem gravar nada.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import (
    CashbackTransaction,
    PointsTransaction,
    StoreSettings,
    cashback_balance,
    money,
    points_balance,
)

PONTOS_POR_REAL = 2
DESCRICAO = "Conversao do saldo de cashback em pontos"


class Command(BaseCommand):
    help = "Converte o saldo de cashback de cada cliente em pontos (R$ 1 = 2 pontos)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ensaio",
            action="store_true",
            help="Mostra o que seria feito sem gravar nada no banco.",
        )
        parser.add_argument(
            "--pontos-por-real",
            type=int,
            default=PONTOS_POR_REAL,
            help=f"Quantos pontos vale cada real de saldo (padrao: {PONTOS_POR_REAL}).",
        )

    def handle(self, *args, **options):
        ensaio = options["ensaio"]
        taxa = options["pontos_por_real"]
        settings_loja = StoreSettings.load()
        teto = settings_loja.points_cap

        if ensaio:
            self.stdout.write(self.style.WARNING("ENSAIO: nada sera gravado.\n"))

        # Cada cliente que ja teve alguma movimentacao de cashback.
        user_ids = (
            CashbackTransaction.objects.order_by()
            .values_list("user_id", flat=True)
            .distinct()
        )
        convertidos = 0
        pulados = 0
        total_reais = Decimal("0.00")
        total_pontos = 0
        perdidos_no_teto = 0

        for user_id in user_ids:
            transacao = CashbackTransaction.objects.filter(user_id=user_id).first()
            user = transacao.user if transacao else None

            if user is None:
                continue

            # Quem ja foi convertido antes nao entra de novo.
            if PointsTransaction.objects.filter(user=user, description=DESCRICAO).exists():
                pulados += 1
                continue

            saldo = cashback_balance(user)

            if saldo <= 0:
                continue

            pontos_cheios = int(saldo * taxa)
            espaco = max(0, teto - points_balance(user))
            pontos = min(pontos_cheios, espaco)
            perdidos_no_teto += pontos_cheios - pontos

            self.stdout.write(
                f"  {user.email}: R$ {saldo} -> {pontos} pontos"
                + (f" (o teto cortou {pontos_cheios - pontos})" if pontos_cheios > pontos else "")
            )

            if not ensaio:
                with transaction.atomic():
                    if pontos > 0:
                        PointsTransaction.objects.create(
                            user=user,
                            kind=PointsTransaction.ADJUST,
                            points=pontos,
                            description=DESCRICAO,
                        )

                    # Zera o cashback com um lancamento negativo, preservando o
                    # historico de como o saldo foi formado.
                    CashbackTransaction.objects.create(
                        user=user,
                        kind=CashbackTransaction.ADJUST,
                        amount=money(-saldo),
                        description=DESCRICAO,
                    )

            convertidos += 1
            total_reais += saldo
            total_pontos += pontos

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Clientes convertidos: {convertidos}"))

        if pulados:
            self.stdout.write(f"Ja convertidos antes (pulados): {pulados}")

        self.stdout.write(f"Saldo convertido: R$ {money(total_reais)}")
        self.stdout.write(f"Pontos creditados: {total_pontos}")

        if perdidos_no_teto:
            self.stdout.write(
                self.style.WARNING(f"Pontos que nao couberam no teto de {teto}: {perdidos_no_teto}")
            )

        if ensaio:
            self.stdout.write(self.style.WARNING("\nENSAIO: nada foi gravado."))
