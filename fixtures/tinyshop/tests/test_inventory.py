import pytest
from tinyshop.inventory import reserve


def test_reserve_decrements_without_mutating():
    stock = {"apple": 5}
    assert reserve("apple", 2, stock) == {"apple": 3}
    assert stock == {"apple": 5}


def test_reserve_everything():
    assert reserve("apple", 5, {"apple": 5}) == {"apple": 0}


def test_reserve_unknown_sku():
    with pytest.raises(KeyError, match="unknown sku: kiwi"):
        reserve("kiwi", 1, {"apple": 5})


@pytest.mark.xfail(strict=True, reason="ticket 003")
def test_reserve_out_of_stock_message():
    with pytest.raises(ValueError, match=r"^out of stock: apple$"):
        reserve("apple", 6, {"apple": 5})
