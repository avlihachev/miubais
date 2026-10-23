# tinyshop

A deliberately small shop used as the target repository for harness runs in M1 and later modules.
It is plain Python with no dependencies, so a run costs model turns, not setup time.

## The app

| Module | API |
| --- | --- |
| `tinyshop.pricing` | `unit_price(sku) -> Decimal`, `discount(total, code) -> Decimal` |
| `tinyshop.cart` | `Cart.add(sku, qty=1)`, `Cart.total(pricing, code=None) -> Decimal` |
| `tinyshop.inventory` | `reserve(sku, qty, stock) -> dict` (returns a new stock dict) |

## The tickets

Three bugs are planted on purpose. Each ticket in `tickets/` gives a title, the symptom, the name of
the failing test and the acceptance check.

| Ticket | Bug | Test |
| --- | --- | --- |
| `001-discount-rounding` | `discount` rounds half-cents to even instead of up | `test_pricing.py::test_discount_rounds_half_up` |
| `002-negative-quantity` | `Cart.add` rejects zero but accepts negatives | `test_cart.py::test_add_negative_quantity_rejected` |
| `003-out-of-stock-message` | out of stock reports `unknown sku` | `test_inventory.py::test_reserve_out_of_stock_message` |

Each ticket test is marked `xfail(strict=True)`, so the suite is green while the bug is present:

```bash
PYTHONPATH=fixtures/tinyshop/src uv run --frozen pytest fixtures/tinyshop/tests -q   # 13 passed, 3 xfailed
```

A fix is checked with `--runxfail`, which runs the marked test as a normal one. After a correct fix
the named test passes under `--runxfail`; without the flag that test turns into a strict XPASS
failure, which is the signal to drop the marker when the fix is merged for real. The harness does
not edit tests, so it never touches the marker.

## How a harness works on it

The harness copies this directory to a temporary git repository, then hands one ticket to an agent
through `harnesskit.runner.run_ticket` (or the learner's own runner):

1. The policy makes `src/` the only writable root. Reads are free; writes to `tests/` or
   `tickets/`, dangerous shell commands and redirects outside `src/` are denied by the
   `PreToolUse` hook.
2. The agent reads the ticket, edits `src/`, and runs the acceptance command from the ticket.
3. The run stops on success, `max_turns` or `max_budget_usd`; the report lists the stop reason,
   turns, cost and `files_changed` from `git status`, which should all be under `src/`.
4. The session id is stored per ticket, so a second run on the same ticket resumes the session.

The tests need only pytest and also run from a standalone copy, because `pyproject.toml` sets
`pythonpath = ["src"]`. tinyshop has no lockfile of its own, so in a copy outside this repository
use the course environment, for example
`uv run --project <course root> --frozen pytest --runxfail -q`; a bare `uv run --frozen` there fails
for lack of a `uv.lock`.
