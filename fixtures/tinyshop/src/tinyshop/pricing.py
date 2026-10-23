from decimal import Decimal

PRICES = {
    "apple": Decimal("0.35"),
    "pear": Decimal("0.45"),
    "widget": Decimal("12.99"),
}
CODES = {
    "SAVE10": Decimal("0.10"),
    "SAVE15": Decimal("0.15"),
    "HALF": Decimal("0.50"),
}


def unit_price(sku: str) -> Decimal:
    if sku not in PRICES:
        raise KeyError(f"unknown sku: {sku}")
    return PRICES[sku]


def discount(total: Decimal, code: str | None) -> Decimal:
    if code is None:
        return total.quantize(Decimal("0.01"))
    if code not in CODES:
        raise ValueError(f"unknown code: {code}")
    cents = total * (1 - CODES[code]) * 100
    return Decimal(round(cents)) / 100
