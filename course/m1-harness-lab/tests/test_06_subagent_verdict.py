import json
from pathlib import Path

import pytest
from harness_lab.review import parse_verdict, review_options, reviewer_agent, verdict_schema
from harness_lab.types import Finding

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"}


def _finding(**overrides) -> dict:
    base = {"file": "a.py", "line": 1, "severity": "minor", "note": "n"}
    return {**base, **overrides}


def load(fixture_dir: Path, name: str) -> dict:
    return json.loads((fixture_dir / "verdicts" / f"{name}.json").read_text())


def test_schema_is_exactly_the_spec():
    finding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["file", "line", "severity", "note"],
        "properties": {
            "file": {"type": "string"},
            "line": {"type": "integer", "minimum": 1},
            "severity": {"enum": ["critical", "important", "minor"]},
            "note": {"type": "string"},
        },
    }
    assert verdict_schema() == {
        "type": "object",
        "additionalProperties": False,
        "required": ["approve", "findings"],
        "properties": {
            "approve": {"type": "boolean"},
            "findings": {"type": "array", "items": finding},
        },
    }


def test_schema_shape():
    schema = verdict_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["approve", "findings"]
    item = schema["properties"]["findings"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["file", "line", "severity", "note"]
    assert set(item["properties"]["severity"]["enum"]) == {"critical", "important", "minor"}


def test_schema_is_json_serialisable():
    assert json.loads(json.dumps(verdict_schema())) == verdict_schema()


def test_parse_clean_approval(fixture_dir):
    verdict = parse_verdict(load(fixture_dir, "approve_clean"))
    assert verdict.approve is True
    assert verdict.findings == []


def test_parse_rejection_with_findings(fixture_dir):
    verdict = parse_verdict(load(fixture_dir, "reject_two_findings"))
    assert verdict.approve is False
    assert len(verdict.findings) == 2
    assert verdict.findings[0] == Finding(
        "src/tinyshop/pricing.py", 14, "critical", "discount rounds half up instead of half even"
    )
    assert verdict.findings[1].severity == "minor"


def test_bad_severity_is_rejected(fixture_dir):
    with pytest.raises(ValueError, match="severity"):
        parse_verdict(load(fixture_dir, "bad_severity"))


def test_extra_top_level_key_is_rejected(fixture_dir):
    with pytest.raises(ValueError, match="confidence"):
        parse_verdict(load(fixture_dir, "extra_key"))


def test_extra_finding_key_is_rejected():
    data = {"approve": False, "findings": [_finding(extra="x")]}
    with pytest.raises(ValueError, match="extra"):
        parse_verdict(data)


@pytest.mark.parametrize("missing", ["file", "line", "severity", "note"])
def test_missing_finding_field_is_rejected(missing):
    finding = _finding()
    del finding[missing]
    with pytest.raises(ValueError, match=missing):
        parse_verdict({"approve": False, "findings": [finding]})


@pytest.mark.parametrize("data", [{"approve": True}, {"findings": []}, {}])
def test_missing_top_level_field_is_rejected(data):
    with pytest.raises(ValueError):
        parse_verdict(data)


@pytest.mark.parametrize(
    "data",
    [
        {"approve": "yes", "findings": []},
        {"approve": True, "findings": "none"},
        {"approve": False, "findings": [_finding(line=0)]},
        {"approve": False, "findings": [_finding(line="9")]},
        {"approve": False, "findings": [_finding(line=True)]},
        {"approve": False, "findings": [_finding(file=3)]},
    ],
)
def test_wrong_types_are_rejected(data):
    with pytest.raises(ValueError):
        parse_verdict(data)


def test_reviewer_agent_is_read_only_and_bounded():
    agent = reviewer_agent()
    assert agent.tools == ["Read", "Grep", "Glob"]
    assert not WRITE_TOOLS & set(agent.tools)
    assert agent.maxTurns is not None and agent.maxTurns <= 8
    assert agent.description
    assert "approve" in agent.prompt and "findings" in agent.prompt


def test_review_options_wiring(tmp_path):
    options = review_options(tmp_path)
    assert set(options.agents) == {"reviewer"}
    assert options.agents["reviewer"].tools == ["Read", "Grep", "Glob"]
    assert options.output_format == {"type": "json_schema", "schema": verdict_schema()}
    assert options.allowed_tools == ["Read", "Grep", "Glob", "Agent"]
    assert options.cwd == tmp_path
