def reserve(sku: str, qty: int, stock: dict[str, int]) -> dict[str, int]:
    if sku not in stock:
        raise KeyError(f"unknown sku: {sku}")
    if stock[sku] < qty:
        raise ValueError(f"unknown sku: {sku}")
    return stock | {sku: stock[sku] - qty}
