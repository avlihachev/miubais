from decimal import Decimal

import pytest
from tinyshop import pricing
from tinyshop.cart import Cart


def test_add_accumulates():
    cart = Cart()
    cart.add("apple", 2)
    cart.add("apple", 1)
    cart.add("pear")
    assert cart.items == {"apple": 3, "pear": 1}


def test_add_zero_rejected():
    with pytest.raises(ValueError, match="quantity must be positive"):
        Cart().add("apple", 0)


def test_total():
    cart = Cart()
    cart.add("apple", 2)
    cart.add("widget", 1)
    assert cart.total(pricing) == Decimal("13.69")


def test_total_with_code():
    cart = Cart()
    cart.add("widget", 1)
    assert cart.total(pricing, code="SAVE10") == Decimal("11.69")


def test_empty_cart_total():
    assert Cart().total(pricing) == Decimal("0.00")


@pytest.mark.xfail(strict=True, reason="ticket 002")
def test_add_negative_quantity_rejected():
    cart = Cart()
    with pytest.raises(ValueError, match="quantity must be positive"):
        cart.add("apple", -1)
    assert cart.items == {}
