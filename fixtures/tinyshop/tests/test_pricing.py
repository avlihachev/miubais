from decimal import Decimal

import pytest
from tinyshop.pricing import discount, unit_price


def test_unit_price():
    assert unit_price("apple") == Decimal("0.35")
    assert unit_price("widget") == Decimal("12.99")


def test_unit_price_unknown_sku():
    with pytest.raises(KeyError, match="unknown sku: kiwi"):
        unit_price("kiwi")


def test_discount_without_code_keeps_total():
    assert discount(Decimal("12.25"), None) == Decimal("12.25")


def test_discount_save10():
    assert discount(Decimal("10.00"), "SAVE10") == Decimal("9.00")


def test_discount_unknown_code():
    with pytest.raises(ValueError, match="unknown code: FREE"):
        discount(Decimal("10.00"), "FREE")


@pytest.mark.xfail(strict=True, reason="ticket 001")
def test_discount_rounds_half_up():
    assert discount(Decimal("12.25"), "SAVE10") == Decimal("11.03")
    assert discount(Decimal("0.25"), "HALF") == Decimal("0.13")
