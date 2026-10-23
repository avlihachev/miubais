from dataclasses import dataclass, field
from decimal import Decimal
from types import ModuleType


@dataclass
class Cart:
    items: dict[str, int] = field(default_factory=dict)

    def add(self, sku: str, qty: int = 1) -> None:
        if qty == 0:
            raise ValueError("quantity must be positive")
        self.items[sku] = self.items.get(sku, 0) + qty

    def total(self, pricing: ModuleType, code: str | None = None) -> Decimal:
        subtotal = sum(
            (pricing.unit_price(sku) * qty for sku, qty in self.items.items()), Decimal(0)
        )
        return pricing.discount(subtotal, code)
