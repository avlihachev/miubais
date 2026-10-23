import os
import re
from pathlib import Path

import pytest
import yaml

KEY = Path(__file__).resolve().parent / "KEY.yaml"
WORKLOADS = {
    "agent coding tickets": ("agent", "coding"),
    "support chat": ("support", "chat"),
    "embeddings and retrieval": ("embedding", "retrieval"),
    "judge and evals": ("judge", "eval"),
}
PLACES = {
    "self-hosted vllm": re.compile(r"vllm", re.IGNORECASE),
    "api": re.compile(r"(?<![\w-])api(?![\w-])", re.IGNORECASE),
    "local": re.compile(r"(?<![\w-])local(?![\w-])", re.IGNORECASE),
}
MIN_AGREEMENT = 3
MIN_WHY_WORDS = 5
MIN_RISKS = 3
MIN_RISK_WORDS = 8
CELL = re.compile(r"(?<!\\)\|")
WORD = re.compile(r"[A-Za-z0-9][\w'-]*")
BULLET = re.compile(r"^([-*]|\d+[.)])\s+")
HEADING = re.compile(r"^(#+)\s*(.*?)\s*#*$")
TOKENS_PER_DAY = re.compile(r"tokens?\s*(?:per|a|/|each)\s*day", re.IGNORECASE)
REPLICAS = re.compile(
    r"\d+\s+(?:[\w-]+\s+){0,2}replicas?\b|\breplicas?\s*(?:\|\s*)?[:=|]\s*\d+", re.IGNORECASE
)
OPERATION = re.compile(r"\d[^\n=]*?\s[×x*/÷]\s+\(?\d|\d\s*[×*/÷]\s*\(?\d")


@pytest.fixture(scope="module")
def plan() -> str:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "SERVING_PLAN.md"
    if not path.is_file():
        pytest.fail(f"write {path.name} in your workspace root")
    return path.read_text()


@pytest.fixture(scope="module")
def key() -> dict[str, list[str]]:
    return yaml.safe_load(KEY.read_text())["placements"]


def workload_of(cell: str) -> str | None:
    text = cell.lower()
    found = [n for n, words in WORKLOADS.items() if any(re.search(rf"\b{w}", text) for w in words)]
    return found[0] if len(found) == 1 else None


def places_in(cell: str) -> set[str]:
    return {place for place, pattern in PLACES.items() if pattern.search(cell)}


def parse_rows(text: str) -> list[tuple[str, str, str, str]]:
    rows, in_plan = [], False
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            in_plan = False
            continue
        cells = [c.strip() for c in CELL.split(line.strip().strip("|"))]
        if not in_plan:
            in_plan = any(c.lower().strip("`* ").startswith("where") for c in cells)
            continue
        if len(cells) != 4:
            continue
        workload = workload_of(cells[0])
        if workload:
            rows.append((workload, cells[1], cells[2], cells[3]))
    return rows


def agreement(rows, key: dict[str, list[str]]) -> int:
    return sum(1 for workload, where, _, _ in rows if places_in(where) & set(key.get(workload, [])))


def section(text: str, title: str) -> str:
    lines, level = [], None
    for line in text.splitlines():
        heading = HEADING.match(line.strip())
        if heading and level is not None and len(heading.group(1)) <= level:
            break
        if level is not None:
            lines.append(line)
        elif heading and re.match(title, heading.group(2), re.IGNORECASE):
            level = len(heading.group(1))
    return "\n".join(lines)


def bullets(text: str) -> list[str]:
    found, open_item = [], False
    for line in text.splitlines():
        item = line.strip()
        if BULLET.match(item):
            found.append(BULLET.sub("", item))
            open_item = True
        elif open_item and item and line[:1].isspace():
            found[-1] += " " + item
        else:
            open_item = False
    return found


def capacity_problems(text: str) -> list[str]:
    found = []
    capacity = section(text, r"capacity\b")
    if not capacity.strip():
        return ["add a '## Capacity' section"]
    if not any(
        TOKENS_PER_DAY.search(line) and re.search(r"\d", line) for line in capacity.splitlines()
    ):
        found.append("give a figure in tokens per day")
    if not REPLICAS.search(capacity):
        found.append("give the number of replicas, as '2 replicas'")
    if not (OPERATION.search(capacity) and "=" in capacity):
        found.append("show the arithmetic, as '3 × 400 = 1,200'")
    return found


def test_one_row_per_workload(plan):
    found = sorted(workload for workload, *_ in parse_rows(plan))
    assert found == sorted(WORKLOADS), (
        f"expected one row for each of {list(WORKLOADS)}, got {found}"
    )


def test_every_row_names_one_place_a_model_and_a_why(plan):
    for workload, where, model, why in parse_rows(plan):
        assert len(places_in(where)) == 1, f"{workload}: name one of local, self-hosted vLLM, API"
        assert model.strip("`* "), f"{workload}: name the model"
        assert len(WORD.findall(why)) >= MIN_WHY_WORDS, f"{workload}: say why in a sentence"


def test_placements_agree_with_the_key(plan, key):
    agreed = agreement(parse_rows(plan), key)
    assert agreed >= MIN_AGREEMENT, f"{agreed} of 4 placements agree with the key, need 3"


def test_the_capacity_estimate(plan):
    assert capacity_problems(plan) == []


def test_risks(plan):
    risks = bullets(section(plan, r"risks$"))
    assert risks, "add a '## Risks' section with one risk per bullet"
    short = [r for r in risks if len(WORD.findall(r)) < MIN_RISK_WORDS]
    assert len(risks) - len(short) >= MIN_RISKS, f"need 3 risks of 8 words or more, short: {short}"


def test_the_key_uses_the_vocabulary(key):
    assert sorted(key) == sorted(WORKLOADS)
    assert {p for allowed in key.values() for p in allowed} <= set(PLACES)


def _table(places: dict[str, str]) -> str:
    rows = [f"| {w} | {p} | some model | because it fits the case |" for w, p in places.items()]
    return "| workload | where | model | why |\n|---|---|---|---|\n" + "\n".join(rows)


def test_a_constant_placement_is_rejected(key):
    for place in ("local", "self-hosted vLLM", "API"):
        rows = parse_rows(_table(dict.fromkeys(WORKLOADS, place)))
        assert agreement(rows, key) < MIN_AGREEMENT, place


def test_three_right_is_enough_and_two_is_not(key):
    answers = {w: allowed[0] for w, allowed in key.items()}
    wrong = {w: next(p for p in PLACES if p not in allowed) for w, allowed in key.items()}
    assert agreement(parse_rows(_table(answers)), key) == 4
    names = list(WORKLOADS)
    assert agreement(parse_rows(_table(answers | {names[0]: wrong[names[0]]})), key) == 3
    two_wrong = answers | {n: wrong[n] for n in names[:2]}
    assert agreement(parse_rows(_table(two_wrong)), key) == 2


def test_cells_are_read_by_word():
    assert places_in("**self-hosted vLLM** (EU cluster)") == {"self-hosted vllm"}
    assert places_in("`API`") == {"api"}
    assert places_in("local or API") == {"local", "api"}
    assert places_in("on-premises box") == set()
    assert places_in("api-gateway") == set()
    assert workload_of("Agent coding tickets") == "agent coding tickets"
    assert workload_of("Embeddings / retrieval") == "embeddings and retrieval"
    assert workload_of("support chat and judge") is None
    assert workload_of("workload") is None


def test_the_capacity_section_is_read_with_its_subsections():
    text = (
        "# Plan\n\n## Capacity\n\n### Support chat\n\n"
        "- 12,000 turns × 200 = 2,400,000 output tokens per day\n- 2 replicas\n\n## Risks\n"
    )
    assert capacity_problems(text) == []
    assert capacity_problems("## Capacity\n\n2 replicas, 38M tokens\n") == [
        "give a figure in tokens per day",
        "show the arithmetic, as '3 × 400 = 1,200'",
    ]
    assert capacity_problems("## Capacity\n\n38M tokens/day = 1 × 38M\n") == [
        "give the number of replicas, as '2 replicas'"
    ]
    assert capacity_problems("## Cost\n\n2 replicas\n") == ["add a '## Capacity' section"]
    assert REPLICAS.search("| replicas | 2 |") and REPLICAS.search("replicas: 3")


def test_the_risks_section_is_read_by_bullets():
    text = (
        "## Risks\n\n- one two three\n"
        "1. the replica count assumes the measured rate holds at peak\n"
        "* a third risk that is long enough to count here too\n\n## Other\n\n- not a risk\n"
    )
    assert bullets(section(text, r"risks$")) == [
        "one two three",
        "the replica count assumes the measured rate holds at peak",
        "a third risk that is long enough to count here too",
    ]


def test_a_wrapped_risk_is_read_as_one_bullet():
    text = (
        "## Risks\n\n- the replica count assumes\n  the measured rate holds at peak\n"
        "- second risk\nnot indented, so not part of it\n"
    )
    assert bullets(section(text, r"risks$")) == [
        "the replica count assumes the measured rate holds at peak",
        "second risk",
    ]


def test_only_the_placement_table_is_read():
    text = (
        _table({"agent coding tickets": "API"})
        + "\n\n## Capacity\n\n| workload | tokens per day | replicas | USD a month |\n"
        "| --- | --- | --- | --- |\n| support chat | 38.4M | 2 | 3,600 |\n"
    )
    assert parse_rows(text) == [
        ("agent coding tickets", "API", "some model", "because it fits the case")
    ]
    assert parse_rows("| support chat | self-hosted vLLM | m | a reason of five words |\n") == []
