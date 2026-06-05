from decimal import Decimal


SHIPPING_DESTINATION_CHOICES = [
    ("DF", "DF"),
    ("ENTORNO_DF", "Entorno do DF"),
    ("GO", "GO"),
    ("TO", "TO"),
    ("MG", "MG"),
    ("SP", "SP"),
    ("MS", "MS"),
    ("MT", "MT"),
    ("PR", "PR"),
    ("BA", "BA"),
    ("PI", "PI"),
    ("MA", "MA"),
    ("PA", "PA"),
    ("RO", "RO"),
    ("AC", "AC"),
    ("AL", "AL"),
    ("AM", "AM"),
    ("AP", "AP"),
    ("CE", "CE"),
    ("ES", "ES"),
    ("PB", "PB"),
    ("PE", "PE"),
    ("RJ", "RJ"),
    ("RN", "RN"),
    ("RR", "RR"),
    ("RS", "RS"),
    ("SC", "SC"),
    ("SE", "SE"),
]


SHIPPING_COSTS = {
    "DF": Decimal("20.00"),
    "ENTORNO_DF": Decimal("20.00"),
    "GO": Decimal("25.00"),
    "TO": Decimal("30.00"),
    "MG": Decimal("30.00"),
    "SP": Decimal("25.00"),
    "MS": Decimal("30.00"),
    "MT": Decimal("30.00"),
    "PR": Decimal("35.00"),
    "BA": Decimal("35.00"),
    "PI": Decimal("35.00"),
    "MA": Decimal("35.00"),
    "PA": Decimal("35.00"),
    "RO": Decimal("35.00"),
    "AC": Decimal("45.00"),
}


def shipping_cost_for(destination):
    return SHIPPING_COSTS.get(destination, Decimal("40.00"))


def shipping_label_for(destination):
    labels = dict(SHIPPING_DESTINATION_CHOICES)
    return labels.get(destination, destination)


def shipping_choices_with_prices():
    return [
        (value, f"{label} - R$ {shipping_cost_for(value):.2f}".replace(".", ","))
        for value, label in SHIPPING_DESTINATION_CHOICES
    ]
