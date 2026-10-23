import importlib
import os
import re
from pathlib import Path

import pytest
from injection_lab.types import ASI_IDS

MIN_AGREEMENT = 8
MAX_NOT_APPLICABLE = 3
MIN_RISKS = 3
MIN_RISK_WORDS = 8
NOT_APPLICABLE = "not applicable"
CONTROLS = (
    "detect.score",
    "detect.evaluate",
    "provenance.wrap",
    "provenance.post_hook",
    "provenance.taint_policy",
    "provenance.compose",
    "secrets.scrub",
    "secrets.scrub_hook",
    "secrets.subprocess_env",
    "secrets.guard_env",
    "mcpserver",
    "audit.AuditLog",
    "audit.verify",
    "audit.checklist",
    "harnesskit.policy.Policy",
    "max_turns",
    "max_budget_usd",
    "read-only tools",
    NOT_APPLICABLE,
)
ASI = re.compile(r"\bASI(0[1-9]|10)\b", re.IGNORECASE)
RISKS = re.compile(r"^#+\s*residual risks\s*$", re.IGNORECASE)
CELL = re.compile(r"(?<!\\)\|")
WORD = re.compile(r"[A-Za-z0-9][\w'-]*")


@pytest.fixture(scope="module")
def model() -> str:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "THREAT_MODEL.md"
    if not path.is_file():
        pytest.fail(f"write {path.name} in your workspace root")
    return path.read_text()


def parse_rows(text: str) -> list[tuple[str, str, str, str]]:
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in CELL.split(line.strip().strip("|"))]
        if not line.lstrip().startswith("|") or len(cells) != 4:
            continue
        found = ASI.search(cells[0])
        if found:
            rows.append((f"ASI{found.group(1)}", cells[1], cells[2], cells[3]))
    return rows


def named(cell: str) -> set[str]:
    text = cell.lower().replace("`", "").replace("*", "")
    return {
        c
        for c in CONTROLS
        if re.search(rf"(?<![\w.]){re.escape(c.lower())}(?![\w-])", text) is not None
    }


def not_applicable(surface: str, control: str) -> bool:
    return any(NOT_APPLICABLE in cell.lower() for cell in (surface, control))


def reason_of(surface: str, control: str) -> str:
    cell = next(c for c in (surface, control) if NOT_APPLICABLE in c.lower())
    return cell.lower().replace("`", "").split(NOT_APPLICABLE, 1)[1].strip(" :;,.-()")


def agreement(rows, key: dict[str, list[str]]) -> int:
    return sum(1 for asi, _, control, _ in rows if named(control) & set(key.get(asi, [])))


def residual_risks(text: str) -> list[str]:
    found, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            inside = bool(RISKS.match(line.strip()))
            continue
        item = line.strip()
        if inside and re.match(r"^([-*]|\d+[.)])\s+", item):
            found.append(re.sub(r"^([-*]|\d+[.)])\s+", "", item))
    return found


def resolves(control: str) -> bool:
    if "." not in control:
        return True
    module, _, attr = control.rpartition(".")
    package = module if module.startswith("harnesskit") else f"injection_lab.{module}"
    return hasattr(importlib.import_module(package), attr)


def test_one_row_per_asi_entry(model):
    found = [asi for asi, *_ in parse_rows(model)]
    assert sorted(found) == list(ASI_IDS), f"expected one row for each of {ASI_IDS}, got {found}"


def test_every_row_has_a_surface_and_a_stage(model):
    empty = [asi for asi, surface, _, stage in parse_rows(model) if not surface or not stage]
    assert not empty, f"fill in the surface and the stage for {empty}"


def test_every_control_names_a_known_control(model):
    unknown = {asi: control for asi, _, control, _ in parse_rows(model) if not named(control)}
    assert not unknown, f"name one of {list(CONTROLS)} in the control column: {unknown}"


def test_not_applicable_is_rare_and_explained(model):
    rows = [r for r in parse_rows(model) if not_applicable(r[1], r[2])]
    assert len(rows) <= MAX_NOT_APPLICABLE, f"{len(rows)} rows are not applicable, at most 3"
    bare = [asi for asi, surface, control, _ in rows if len(reason_of(surface, control)) < 10]
    assert not bare, f"say in one line why there is no surface for {bare}"


def test_controls_agree_with_the_key(model, key):
    agreed = agreement(parse_rows(model), key["controls_by_asi"])
    assert agreed >= MIN_AGREEMENT, f"{agreed} of 10 controls agree with the key, need 8"


def test_residual_risks(model):
    risks = residual_risks(model)
    assert risks, "add a '## Residual risks' section with one risk per bullet"
    short = [r for r in risks if len(WORD.findall(r)) < MIN_RISK_WORDS]
    assert len(risks) - len(short) >= MIN_RISKS, f"need 3 risks of 8 words or more, short: {short}"


def test_the_controls_exist():
    missing = [c for c in CONTROLS if not resolves(c)]
    assert not missing, f"not found in injection_lab or harnesskit: {missing}"


def test_the_key_uses_the_vocabulary(key):
    table = key["controls_by_asi"]
    assert sorted(table) == list(ASI_IDS)
    assert {c for allowed in table.values() for c in allowed} <= set(CONTROLS)


def _table(controls: dict[str, str]) -> str:
    rows = [f"| {asi} | the harness | {c} | 02 |" for asi, c in controls.items()]
    return "| asi | surface in this harness | control | stage |\n|---|---|---|---|\n" + "\n".join(
        rows
    )


def _first_allowed(key) -> dict[str, str]:
    return {asi: f"`{allowed[0]}`" for asi, allowed in key["controls_by_asi"].items()}


def test_a_constant_control_is_rejected(key):
    for control in ("audit.AuditLog", "harnesskit.policy.Policy", "provenance.taint_policy"):
        rows = parse_rows(_table(dict.fromkeys(ASI_IDS, control)))
        assert agreement(rows, key["controls_by_asi"]) < MIN_AGREEMENT, control


def test_three_wrong_is_not_enough(key):
    answers = _first_allowed(key)
    for asi in ASI_IDS[:3]:
        answers[asi] = "`secrets.scrub_hook`"
    rows = parse_rows(_table(answers))
    assert agreement(rows, key["controls_by_asi"]) == 7 < MIN_AGREEMENT


def test_controls_are_read_by_name_not_by_prefix():
    assert named("`provenance.taint_policy` denies Bash") == {"provenance.taint_policy"}
    assert named("**harnesskit.policy.Policy** and `max_turns=12`") == {
        "harnesskit.policy.Policy",
        "max_turns",
    }
    assert named("mcpserver.FixtureTokenVerifier checks the audience") == {"mcpserver"}
    assert named("a firewall") == set()
    assert named("detect.scores") == set()


def test_four_not_applicable_rows_are_too_many():
    text = _table(
        {
            "ASI01": "not applicable: one agent, no peers here",
            "ASI02": "not applicable: one agent, no peers here",
            "ASI03": "not applicable: one agent, no peers here",
            "ASI04": "not applicable: one agent, no peers here",
        }
    )
    rows = [r for r in parse_rows(text) if not_applicable(r[1], r[2])]
    assert len(rows) == 4 > MAX_NOT_APPLICABLE
    assert reason_of(rows[0][1], rows[0][2]) == "one agent, no peers here"
    assert reason_of("the harness", "`not applicable`") == ""


def test_the_risks_section_is_read_by_bullets():
    text = (
        "# Model\n\n## Residual risks\n\n- one two three\n"
        "1. the taint is set after a tool call issued in the same turn\n"
        "* a third risk that is long enough to count here too\n\n## Other\n\n- not a risk\n"
    )
    assert residual_risks(text) == [
        "one two three",
        "the taint is set after a tool call issued in the same turn",
        "a third risk that is long enough to count here too",
    ]
