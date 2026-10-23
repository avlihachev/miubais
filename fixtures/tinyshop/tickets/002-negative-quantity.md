# 002: Cart accepts negative quantities

**Symptom.** `Cart.add("apple", -1)` quietly lowers the line, and with an empty cart it creates a
line with quantity -1, so the total goes negative. Zero is already rejected; anything below zero
should be rejected the same way, with `ValueError("quantity must be positive")`, and leave the cart
unchanged.

**Failing test.** `tests/test_cart.py::test_add_negative_quantity_rejected`

**Acceptance.** From the repository root,
`pytest --runxfail tests/test_cart.py::test_add_negative_quantity_rejected -q`
passes, the rest of the suite still passes, and no test file is edited.
