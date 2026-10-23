import argparse
import json
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path

SEED = 20261017
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
OUT_DIR = HERE
KEYS_DIR = REPO_ROOT / "course" / "m3-trace-lab" / "tests"
PRICES_SOURCE = (
    REPO_ROOT / "course" / "m0-cost-lab" / "starter" / "src" / "cost_lab" / "prices.json"
)

OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"
MAX_TURNS = 14
TICKETS = (
    ("001-discount-rounding", "retries", "pricing", "test_discount_rounds_half_up"),
    ("002-negative-quantity", "no-cache", "cart", "test_add_negative_quantity_rejected"),
    ("003-out-of-stock-message", "expensive-model", "inventory", "test_reserve_out_of_stock"),
    ("004-coupon-expiry-timezone", "big-context", "coupons", "test_coupon_expires_at_utc"),
    ("005-free-shipping-threshold", "loop", "shipping", "test_free_shipping_at_threshold"),
    ("006-tax-after-discount", "no-cache", "pricing", "test_tax_applies_after_discount"),
    ("007-duplicate-sku-merge", "big-context", "cart", "test_same_sku_merges_lines"),
    ("008-price-format-thousands", "expensive-model", "money", "test_format_thousands"),
    ("009-partial-refund-quantity", "loop", "refunds", "test_partial_refund_keeps_rest"),
    ("010-reservation-release", "retries", "inventory", "test_release_returns_stock"),
)
CAUSES = ("no-cache", "loop", "big-context", "retries", "expensive-model")
TRUNCATED = {"r014", "r039"}
MAX_TURNS_RUN = "r025"
PARALLEL = {"r001", "r008", "r017", "r033"}


def run_id(index: int) -> str:
    return f"r{index + 1:03d}"


@dataclass
class Run:
    rid: str
    ticket: str
    cause: str
    module: str
    test: str
    model: str
    rng: random.Random
    t_ms: int = 0
    api_ms: int = 0
    context: int = 0
    cached: int = 0
    records: list[dict] = field(default_factory=list)
    totals: dict[str, int] = field(
        default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    )
    turns: int = 0
    truncate_now: bool = False

    @property
    def caching(self) -> bool:
        return self.cause != "no-cache"

    def token(self, prefix: str, n: int = 24) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz123456789"
        return prefix + "".join(self.rng.choice(alphabet) for _ in range(n))

    def usage(self, output: int) -> dict[str, int]:
        if self.caching:
            fresh = self.rng.randint(2, 9)
            usage = {
                "input_tokens": fresh,
                "output_tokens": output,
                "cache_read_input_tokens": self.cached,
                "cache_creation_input_tokens": self.context - self.cached - fresh,
            }
            self.cached = self.context - fresh
        else:
            usage = {
                "input_tokens": self.context,
                "output_tokens": output,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            }
        self.totals["input"] += usage["input_tokens"]
        self.totals["output"] += output
        self.totals["cache_read"] += usage["cache_read_input_tokens"]
        self.totals["cache_creation"] += usage["cache_creation_input_tokens"]
        return usage

    def assistant(self, calls: list[tuple], text: str | None = None) -> None:
        output = (
            self.rng.randint(90, 380) * max(1, len(calls)) if calls else self.rng.randint(140, 520)
        )
        latency = self.rng.randint(700, 1700) + output * 14 + self.context // 400
        self.t_ms += latency
        self.api_ms += latency
        self.turns += 1
        usage = self.usage(output)
        message_id = self.token("msg_")
        stop = "tool_use" if calls else "end_turn"
        base = {"type": "assistant", "model": self.model, "message_id": message_id}
        if not calls:
            content = [{"type": "text", "text": text}]
            self.emit({**base, "stop_reason": stop, "usage": usage, "content": content})
            self.context += output
            return
        uses = []
        for i, (name, tool_input, _, _, _) in enumerate(calls):
            block = {"type": "tool_use", "id": self.token("toolu_"), "name": name}
            block["input"] = tool_input
            content = ([{"type": "text", "text": text}] if text and i == 0 else []) + [block]
            self.emit({**base, "stop_reason": stop, "usage": dict(usage), "content": content})
            uses.append(block["id"])
        self.context += output
        if self.rid in TRUNCATED and self.truncate_now:
            return
        start = self.t_ms
        results = []
        for tool_id, (_, _, result, is_error, size) in zip(uses, calls, strict=True):
            results.append((start + self.rng.randint(50, 900), tool_id, result, is_error, size))
        for at, tool_id, result, is_error, size in sorted(results):
            self.t_ms = at
            block = {"type": "tool_result", "tool_use_id": tool_id, "content": result}
            block["is_error"] = is_error
            self.emit({"type": "user", "content": [block]})
            self.context += size

    def emit(self, record: dict) -> None:
        self.records.append({"t_ms": self.t_ms, **record})


def cost(totals: dict[str, int], price: dict[str, float]) -> float:
    return (
        totals["input"] * price["input"]
        + totals["output"] * price["output"]
        + totals["cache_read"] * price["cache_read"]
        + totals["cache_creation"] * price["cache_write_5m"]
    ) / 1e6


def pytest_cmd(run: Run, *, whole: bool = False) -> str:
    if whole:
        return "pytest -q"
    return f"pytest --runxfail tests/test_{run.module}.py::{run.test} -q"


def call_read(run: Run, path: str, size: int | None = None) -> tuple:
    size = size or run.rng.randint(400, 2600)
    body = f"     1\t# {path}\n     2\timport decimal\n     3\t...\n({size} tokens)"
    return ("Read", {"file_path": path}, body, False, size)


def call_grep(run: Run, pattern: str) -> tuple:
    size = run.rng.randint(80, 600)
    hits = f"src/tinyshop/{run.module}.py:{run.rng.randint(5, 80)}: {pattern}"
    return ("Grep", {"pattern": pattern, "path": "src"}, hits, False, size)


def call_edit(run: Run, *, error: bool = False) -> tuple:
    path = f"src/tinyshop/{run.module}.py"
    tool_input = {"file_path": path, "old_string": "old line", "new_string": "new line"}
    if error:
        text = "<tool_use_error>String to replace not found in file.</tool_use_error>"
        return ("Edit", tool_input, text, True, run.rng.randint(30, 60))
    text = f"The file {path} has been updated."
    return ("Edit", tool_input, text, False, run.rng.randint(60, 180))


def call_bash(run: Run, command: str, *, passed: bool) -> tuple:
    size = run.rng.randint(200, 1400)
    text = "1 passed in 0.04s" if passed else f"FAILED tests/test_{run.module}.py - AssertionError"
    return ("Bash", {"command": command}, text, False, size)


def opening(run: Run, parallel: bool) -> None:
    symbol = run.test.removeprefix("test_")
    grep = call_grep(run, symbol)
    read = call_read(run, f"src/tinyshop/{run.module}.py")
    if parallel:
        run.assistant([grep, read, call_read(run, f"tests/test_{run.module}.py")], "Looking.")
    else:
        run.assistant([grep], "Let me find where this lives.")
        run.assistant([read], None)


def finish(run: Run) -> None:
    run.assistant([call_bash(run, pytest_cmd(run, whole=True), passed=True)], None)
    run.assistant([], f"Fixed {run.ticket}: corrected the logic in src/tinyshop/{run.module}.py.")


def script(run: Run, parallel: bool) -> None:
    rng = run.rng
    opening(run, parallel)
    if run.cause == "big-context":
        big = f"src/tinyshop/data/{run.module}_catalog.py"
        run.assistant([call_read(run, big, rng.randint(52_000, 58_000))], "Reading the data.")
        if rng.random() < 0.6:
            run.assistant([call_grep(run, run.module)], None)
    if run.cause == "loop":
        run.assistant([call_edit(run)], None)
        command = pytest_cmd(run)
        repeats = MAX_TURNS - run.turns if run.rid == MAX_TURNS_RUN else rng.randint(4, 6)
        for _ in range(repeats):
            run.assistant([call_bash(run, command, passed=False)], "Running the test again.")
        if run.rid in TRUNCATED:
            run.truncate_now = True
            run.assistant([call_bash(run, command, passed=False)])
            return
        if run.rid == MAX_TURNS_RUN:
            return
        run.assistant([call_edit(run)], None)
        run.assistant([call_bash(run, command, passed=True)], None)
        finish(run)
        return
    if run.cause == "retries":
        command = pytest_cmd(run)
        run.assistant([call_edit(run, error=True)], None)
        run.assistant([call_edit(run, error=True)], "The edit missed, retrying.")
        run.assistant([call_read(run, f"src/tinyshop/{run.module}.py")], None)
        run.assistant([call_edit(run)], None)
        run.assistant([call_bash(run, command, passed=True)], None)
        finish(run)
        return
    if rng.random() < 0.5:
        run.assistant([call_read(run, f"tests/test_{run.module}.py")], None)
    if run.rid in TRUNCATED:
        run.truncate_now = True
        run.assistant([call_edit(run)], "Applying the fix.")
        return
    run.assistant([call_edit(run)], "Applying the fix.")
    run.assistant([call_bash(run, pytest_cmd(run), passed=True)], None)
    finish(run)


def model_for(cause: str, attempt: int) -> str:
    if cause == "expensive-model":
        return HAIKU if attempt == 3 else OPUS
    return SONNET


def build(index: int, rng: random.Random, prices: dict) -> tuple[Run, list[dict]]:
    ticket, cause, module, test = TICKETS[index % len(TICKETS)]
    attempt = index // len(TICKETS)
    rid = run_id(index)
    run = Run(rid, ticket, cause, module, test, model_for(cause, attempt), rng)
    run.context = rng.randint(6_500, 8_500)
    session = f"{rng.getrandbits(32):08x}-{rng.getrandbits(16):04x}-4{rng.getrandbits(12):03x}-{0x8000 | rng.getrandbits(14):04x}-{rng.getrandbits(48):012x}"
    run.emit({"type": "meta", "ticket_id": ticket, "session_id": session})
    script(run, rid in PARALLEL or rng.random() < 0.15)
    records = run.records
    if rid in TRUNCATED:
        return run, records
    usd = cost(run.totals, prices[run.model])
    subtype = "error_max_turns" if rid == MAX_TURNS_RUN else "success"
    run.t_ms += rng.randint(20, 120)
    usage = {
        "input_tokens": run.totals["input"],
        "output_tokens": run.totals["output"],
        "cache_read_input_tokens": run.totals["cache_read"],
        "cache_creation_input_tokens": run.totals["cache_creation"],
    }
    model_usage = {
        run.model: {
            "inputTokens": run.totals["input"],
            "outputTokens": run.totals["output"],
            "cacheReadInputTokens": run.totals["cache_read"],
            "cacheCreationInputTokens": run.totals["cache_creation"],
            "webSearchRequests": 0,
            "costUSD": usd,
            "contextWindow": 200_000,
            "maxOutputTokens": 32_000,
        }
    }
    run.emit(
        {
            "type": "result",
            "subtype": subtype,
            "num_turns": run.turns,
            "session_id": session,
            "duration_ms": run.t_ms,
            "duration_api_ms": run.api_ms,
            "total_cost_usd": usd,
            "usage": usage,
            "model_usage": model_usage,
        }
    )
    return run, records


def keys_yaml(runs: list[Run], prices: dict) -> str:
    usd: dict[str, float] = {}
    tokens: dict[str, dict[str, int]] = {}
    for run in runs:
        usd[run.ticket] = usd.get(run.ticket, 0.0) + cost(run.totals, prices[run.model])
        acc = tokens.setdefault(run.ticket, {"input": 0, "cache_read": 0, "cache_creation": 0})
        for key in acc:
            acc[key] += run.totals[key]
    top = sorted(usd, key=lambda t: (-usd[t], t))[:5]
    lines = ["top_five:", *(f"  - {t}" for t in top), "causes:"]
    lines += [f"  {ticket}: {cause}" for ticket, cause, _, _ in TICKETS]
    lines.append("cache_hit_ratio:")
    for ticket, *_ in TICKETS:
        acc = tokens[ticket]
        ratio = acc["cache_read"] / (acc["input"] + acc["cache_read"] + acc["cache_creation"])
        lines.append(f"  {ticket}: {ratio!r}")
    return "\n".join(lines) + "\n"


def manifest(runs: list[Run]) -> str:
    rows = [
        "# MANIFEST",
        "",
        f"Every run is synthetic: written by `generate.py` with seed {SEED}, never recorded live.",
        "`prices.json` is a copy of `course/m0-cost-lab/starter/src/cost_lab/prices.json`.",
        "",
        "| file | provenance | ticket | model | ending |",
        "| --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        last = run.records[-1]
        ending = last["subtype"] if last["type"] == "result" else "truncated"
        rows.append(f"| runs/{run.rid}.jsonl | synthetic | {run.ticket} | {run.model} | {ending} |")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Regenerate the M3 recorded harness runs.")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--keys", type=Path, default=KEYS_DIR)
    args = parser.parse_args(argv)
    rng = random.Random(SEED)
    prices = json.loads(PRICES_SOURCE.read_text())
    runs_dir = args.out / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    args.keys.mkdir(parents=True, exist_ok=True)
    runs = []
    for index in range(40):
        run, records = build(index, rng, prices)
        lines = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
        (runs_dir / f"{run.rid}.jsonl").write_text(lines)
        runs.append(run)
    shutil.copyfile(PRICES_SOURCE, args.out / "prices.json")
    (args.out / "MANIFEST.md").write_text(manifest(runs))
    (args.keys / "KEY.yaml").write_text(keys_yaml(runs, prices))


if __name__ == "__main__":
    main()
