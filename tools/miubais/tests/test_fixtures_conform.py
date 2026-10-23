import json
from pathlib import Path

import pytest
from anthropic.types import Message, RawMessageStreamEvent
from anthropic.types.messages import MessageBatchIndividualResponse
from miubais.paths import course_dir
from pydantic import TypeAdapter

NOT_RECORDED = {
    "m2-evals-lab/baseline.json",
    "m2-evals-lab/live_judge_run.json",
    "m2-evals-lab/live_judge_run_2.json",
    "m3-trace-lab/live_traced_run.json",
    "m4-retrieval-lab/live_answer_run.json",
    "m4-retrieval-lab/live_local_models_run.json",
    "m5-injection-lab/live_injection_run.json",
    "m6-serving-lab/live_gateway_run.json",
    "m6-serving-lab/live_local_model_run.json",
    "m7-capstone/live_review_run.json",
    "m7-capstone/live_review_run_v1.json",
}
FIXTURES = sorted(
    path
    for path in course_dir().glob("*/fixtures/*.json")
    if f"{path.parent.parent.name}/{path.name}" not in NOT_RECORDED
)
BATCH_FILES = sorted(course_dir().glob("*/fixtures/batch_*.jsonl"))
EVENTS = TypeAdapter(RawMessageStreamEvent)


def ids(path: Path) -> str:
    return f"{path.parent.parent.name}/{path.name}"


def sse_events(text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def test_there_are_fixtures_to_check():
    assert FIXTURES and BATCH_FILES


@pytest.mark.parametrize("path", FIXTURES, ids=ids)
def test_fixture_body_is_a_valid_message(path):
    fixture = json.loads(path.read_text())
    if "body_text" in fixture:
        events = [EVENTS.validate_python(e) for e in sse_events(fixture["body_text"])]
        assert events[0].type == "message_start" and events[-1].type == "message_stop"
        Message.model_validate(sse_events(fixture["body_text"])[0]["message"])
    else:
        message = Message.model_validate(fixture["body"])
        assert message.model_dump(mode="json", exclude_unset=True) == fixture["body"]


@pytest.mark.parametrize("path", BATCH_FILES, ids=ids)
def test_batch_lines_are_valid_individual_responses(path):
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for line in lines:
        response = MessageBatchIndividualResponse.model_validate(line)
        assert response.model_dump(mode="json", exclude_unset=True) == line
