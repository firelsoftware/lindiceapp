"""Cadastra os smartwatches e fones do catalogo Wearzone na loja.

Os precos de venda saem das regras da loja (o dobro do atacado, com piso), e o
preco de atacado nunca vai para a vitrine: fica so em wholesale_price, que e
campo interno. As fotos vem de accounts/seed/wearzone/, recortadas do catalogo.

Rode com --ensaio para ver o que seria feito sem gravar nada.
"""

import logging
from decimal import Decimal
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import (
    SupplierProduct,
    SupplierProductVariant,
    credit_price_from_retail,
    retail_price_from_wholesale,
)

logger = logging.getLogger(__name__)

PASTA_FOTOS = Path(__file__).resolve().parent.parent.parent / "seed" / "wearzone"

SMARTWATCH = "Smartwatches"
FONE = "Fones de ouvido"

# atacado = preco de 5 a 50 pecas do catalogo (o dono nao compra como VIP).
CATALOGO = [
    {
        "slug": "easy", "codigo": "WZ-EASY", "nome": "Smartwatch Wearzone Easy",
        "categoria": SMARTWATCH, "atacado": "95.00",
        "chamada": "O smartwatch à prova d'água mais barato do Brasil.",
        "descricao": "Design moderno, funções completas e resistência à água para te acompanhar "
                     "em todos os momentos com leveza, praticidade e estilo.",
        "cores": ["Preto", "Prata", "Rosa"],
        "recursos": [
            "Funções para o dia a dia: notificações, alarmes, controle de música e clima",
            "Resistência 1ATM: proteção contra respingos e chuva",
            "Mais de 100 modos esportivos",
            "7 dias de bateria",
            "Tela TFT com cores nítidas",
            "Monitoramento de batimentos, sono e atividade diária",
        ],
        "ficha": ["Tela: TFT", "Resistência à água: 1 ATM", "Autonomia: Até 7 dias em uso típico"],
    },
    {
        "slug": "pulse", "codigo": "WZ-PULSE", "nome": "Smartwatch Wearzone Pulse",
        "categoria": SMARTWATCH, "atacado": "110.00",
        "chamada": "Mais performance. Mais liberdade. Todos os dias.",
        "descricao": "Design moderno, recursos completos e resistência à prova d'água para "
                     "acompanhar sua rotina com estilo.",
        "cores": ["Preto", "Azul", "Dourado", "Verde"],
        "recursos": ["Mais de 100 modos esportivos", "Monitoramento de saúde", "Notificações no pulso"],
        "ficha": [],
    },
    {
        "slug": "life", "codigo": "WZ-LIFE", "nome": "Smartwatch Wearzone Life",
        "categoria": SMARTWATCH, "atacado": "140.00",
        "chamada": "Design que combina com você. Performance que acompanha sua rotina.",
        "descricao": "O smartwatch redondo que une elegância e tecnologia no mesmo pulso.",
        "cores": ["Preto", "Prata", "Rosa"],
        "recursos": ["Mais de 100 modos esportivos", "Monitoramento de saúde", "Design redondo elegante"],
        "ficha": [],
    },
    {
        "slug": "kron", "codigo": "WZ-KRON", "nome": "Smartwatch Wearzone Kron",
        "categoria": SMARTWATCH, "atacado": "170.00",
        "chamada": "Performance que acompanha você.",
        "descricao": "O equilíbrio entre tecnologia, resistência e elegância, projetado para "
                     "superar limites e facilitar o que realmente importa.",
        "cores": ["Preto", "Prata", "Laranja", "Verde"],
        "recursos": ["GPS integrado", "Tela AMOLED", "Resistência 3ATM", "7 dias de bateria"],
        "ficha": ["Tela: AMOLED", "GPS: Integrado", "Resistência à água: 3 ATM"],
    },
    {
        "slug": "action", "codigo": "WZ-ACTION", "nome": "Smartwatch Wearzone Action",
        "categoria": SMARTWATCH, "atacado": "199.00",
        "chamada": "Pronto para qualquer desafio.",
        "descricao": "O parceiro ideal para quem busca mais performance, conectividade e "
                     "liberdade em todos os momentos.",
        "cores": ["Preto", "Prata", "Roxo", "Rosa"],
        "recursos": ["GPS integrado", "Alexa integrada", "Resistência 3ATM", "Conexão com Strava"],
        "ficha": ["GPS: Integrado", "Resistência à água: 3 ATM"],
    },
    {
        "slug": "horizon-lite-plus", "codigo": "WZ-HLITE", "nome": "Smartwatch Wearzone Horizon Lite+",
        "categoria": SMARTWATCH, "atacado": "199.00",
        "chamada": "Conectividade total. Liberdade ilimitada.",
        "descricao": "O smartwatch completo para quem quer mais: faça chamadas e baixe seus "
                     "aplicativos favoritos direto do pulso.",
        "cores": ["Preto", "Prata"],
        "recursos": ["Chamadas pelo relógio", "Aplicativos no pulso", "Monitoramento de saúde"],
        "ficha": [],
    },
    {
        "slug": "horizon-titan", "codigo": "WZ-HTITAN", "nome": "Smartwatch Wearzone Horizon Titan",
        "categoria": SMARTWATCH, "atacado": "269.00",
        "chamada": "Tecnologia que acompanha seu ritmo. Em qualquer lugar.",
        "descricao": "Construção robusta para quem leva a rotina a sério, dentro e fora do treino.",
        "cores": ["Preto"],
        "recursos": ["Resistência reforçada", "GPS integrado", "Bateria de longa duração"],
        "ficha": [],
    },
    {
        "slug": "brave", "codigo": "WZ-BRAVE", "nome": "Smartwatch Wearzone Brave",
        "categoria": SMARTWATCH, "atacado": "285.00",
        "chamada": "Feito para quem não para.",
        "descricao": "Resistente, completo e com GPS integrado de alta precisão. O parceiro "
                     "ideal para superar limites nos esportes.",
        "cores": ["Preto", "Prata"],
        "recursos": ["GPS de alta precisão", "Resistência reforçada", "Mais de 100 modos esportivos"],
        "ficha": ["GPS: Integrado (alta precisão)"],
    },
    {
        "slug": "flare", "codigo": "WZ-FLARE", "nome": "Smartwatch Wearzone Flare",
        "categoria": SMARTWATCH, "atacado": "285.00",
        "chamada": "Seu ritmo. Sua melhor versão.",
        "descricao": "Mais que um smartwatch, o Flare é o parceiro para acompanhar cada etapa "
                     "da sua rotina com resistência de nível militar.",
        "cores": ["Preto", "Prata", "Dourado"],
        "recursos": [
            "GPS de dupla frequência",
            "Resistência à água do mar (5ATM)",
            "Resistência militar IP69K",
            "10 dias de bateria",
        ],
        "ficha": ["GPS: Dupla frequência", "Resistência à água: 5 ATM", "Proteção: IP69K"],
    },
    {
        "slug": "dune", "codigo": "WZ-DUNE", "nome": "Smartwatch Wearzone Dune",
        "categoria": SMARTWATCH, "atacado": "319.00",
        "chamada": "Ideal para tênis e beach tennis. GPS integrado, 5ATM, até 6 dias de bateria.",
        "descricao": "Desenvolvido especialmente para quem pratica esportes com raquete, como "
                     "tênis e beach tennis. No modo de tênis, o aplicativo mostra uma análise "
                     "detalhada do desempenho: eficiência, resistência, defesa, distribuição de "
                     "golpes, forehand, backhand, posição dos golpes e velocidade da raquete. "
                     "Ao mesmo tempo, é um smartwatch esportivo completo, com mais de 100 "
                     "modalidades, ótimo também para corrida, ciclismo, caminhada e natação.",
        "cores": ["Bege", "Preto"],
        "recursos": [
            "Análise de performance para esportes com raquete",
            "Indicadores de eficiência, resistência e defesa",
            "Análise de forehand e backhand",
            "Monitoramento da velocidade da raquete",
            "Mais de 100 modos esportivos",
            "GPS integrado",
            "Monitoramento de frequência cardíaca",
            "Monitoramento de oxigênio no sangue (SpO2)",
            "Monitoramento de sono e estresse",
            "Resistência à água de 5 ATM",
            "Controle de música e da câmera",
            "Mostradores personalizados com fotos",
        ],
        "ficha": [
            "Aplicativo: FITBEING", "Tela: AMOLED 39 mm", "Tamanho: 42 mm",
            "GPS: Integrado (alta precisão)", "Acelerômetro: Suporte a 6 eixos",
            "Bateria: 300 mAh", "Autonomia: Até 6 dias em uso típico",
            "Resistência à água: 5 ATM", "Pulseira: Pino 18 mm",
        ],
        "peso_g": 172, "altura": "5.5", "largura": "9.0", "comprimento": "9.0",
    },
    {
        "slug": "zone-buds-01", "codigo": "WZ-BUDS01", "nome": "Fone Wearzone Zone Buds 01",
        "categoria": FONE, "atacado": "70.00",
        "chamada": "Seu som. Seu ritmo. Sem limites.",
        "descricao": "Qualidade de áudio premium e chamadas nítidas em um fone feito para o dia a dia.",
        "cores": ["Preto", "Branco"],
        "recursos": ["Áudio premium", "Chamadas nítidas", "Estojo de carregamento"],
        "ficha": [],
    },
    {
        "slug": "wz06", "codigo": "WZ-06", "nome": "Fone Wearzone WZ06",
        "categoria": FONE, "atacado": "90.00",
        "chamada": "Som que te envolve. Liberdade que te acompanha.",
        "descricao": "Tecnologia inteligente para entregar uma experiência sonora pura, "
                     "chamadas cristalinas e liberdade total no seu dia.",
        "cores": ["Preto", "Branco"],
        "recursos": ["Som envolvente", "Chamadas cristalinas", "Estojo de carregamento"],
        "ficha": [],
    },
    {
        "slug": "wz08", "codigo": "WZ-08", "nome": "Headset Wearzone WZ08",
        "categoria": FONE, "atacado": "150.00",
        "chamada": "O headset mais vendido do Brasil.",
        "descricao": "Imersão total com cancelamento de ruído avançado, conforto premium e "
                     "bateria para o dia todo.",
        "cores": ["Preto", "Branco"],
        "recursos": ["Cancelamento de ruído avançado", "Conforto premium", "Bateria para o dia todo"],
        "ficha": [],
    },
]


class Command(BaseCommand):
    help = "Cadastra os smartwatches e fones Wearzone com as fotos e os precos da loja."

    def add_arguments(self, parser):
        parser.add_argument("--ensaio", action="store_true", help="Mostra sem gravar.")
        parser.add_argument("--estoque", type=int, default=10, help="Estoque inicial de cada modelo.")
        parser.add_argument(
            "--refazer",
            action="store_true",
            help="Sobrescreve preco, descricao e recursos dos produtos ja cadastrados.",
        )

    def handle(self, *args, **options):
        ensaio = options["ensaio"]
        estoque = options["estoque"]

        if ensaio:
            self.stdout.write(self.style.WARNING("ENSAIO: nada sera gravado.\n"))

        self.stdout.write(f"{'modelo':34} {'venda':>9} {'crediario':>10}  cores")

        criados = atualizados = preservados = 0
        falhas = []

        for item in CATALOGO:
            atacado = Decimal(item["atacado"])
            venda = retail_price_from_wholesale(atacado)
            crediario = credit_price_from_retail(venda)
            cores = ", ".join(item["cores"])
            self.stdout.write(f"{item['nome']:34} {venda:>9} {crediario:>10}  {cores}")

            if ensaio:
                continue

            try:
              with transaction.atomic():
                existente = SupplierProduct.objects.filter(
                    source=SupplierProduct.SOURCE_WEARZONE, supplier_code=item["codigo"]
                ).first()

                # Produto ja cadastrado nao tem o que a loja editou a mao
                # sobrescrito, a nao ser que peca explicitamente com --refazer.
                if existente and not options["refazer"]:
                    for cor_posicao, cor_nome in enumerate(item["cores"]):
                        SupplierProductVariant.objects.get_or_create(
                            product=existente,
                            name=cor_nome,
                            defaults={"code": f"{item['codigo']}-{cor_nome[:2].upper()}", "position": cor_posicao},
                        )

                    preservados += 1
                    continue

                produto, novo = SupplierProduct.objects.update_or_create(
                    source=SupplierProduct.SOURCE_WEARZONE,
                    supplier_code=item["codigo"],
                    defaults={
                        "name": item["nome"],
                        "brand": "Wearzone",
                        "category": item["categoria"],
                        "description": item["descricao"],
                        "wholesale_price": atacado,
                        "dropshipping_cost": atacado,
                        "suggested_sale_price": venda,
                        "stock_quantity": estoque,
                        "sizes": "Único",
                        "is_active": True,
                        "is_visible": True,
                        "is_featured": item["categoria"] == SMARTWATCH,
                        "highlights": "\n".join(item.get("recursos", [])),
                        "tech_specs": "\n".join(item.get("ficha", [])),
                        "weight_grams": item.get("peso_g"),
                        "height_cm": Decimal(item["altura"]) if item.get("altura") else None,
                        "width_cm": Decimal(item["largura"]) if item.get("largura") else None,
                        "length_cm": Decimal(item["comprimento"]) if item.get("comprimento") else None,
                    },
                )
                # A chamada curta do catalogo fica guardada para a ficha do produto.
                dados = produto.raw_data or {}
                dados["chamada"] = item["chamada"]
                produto.raw_data = dados

                foto = PASTA_FOTOS / f"{item['slug']}.jpg"

                if foto.exists() and not produto.image_file:
                    with foto.open("rb") as arquivo:
                        produto.image_file.save(foto.name, File(arquivo), save=False)

                produto.save()

                for posicao, cor in enumerate(item["cores"]):
                    SupplierProductVariant.objects.update_or_create(
                        product=produto,
                        name=cor,
                        defaults={
                            "code": f"{item['codigo']}-{cor[:2].upper()}",
                            "position": posicao,
                        },
                    )

            except Exception as erro:
                logger.exception("Falha ao importar %s", item["codigo"])
                falhas.append(f"{item['nome']}: {type(erro).__name__} - {erro}")
                self.stdout.write(self.style.ERROR(f"    FALHOU: {type(erro).__name__} - {erro}"))
                continue

            criados += 1 if novo else 0
            atualizados += 0 if novo else 1

        self.stdout.write("")

        if ensaio:
            self.stdout.write(self.style.WARNING("ENSAIO: nada foi gravado."))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"{criados} cadastrados, {atualizados} atualizados, {preservados} mantidos como estavam.")
            )

            if falhas:
                self.stdout.write(self.style.ERROR(f"{len(falhas)} falharam:"))

                for falha in falhas:
                    self.stdout.write(self.style.ERROR(f"  - {falha}"))
