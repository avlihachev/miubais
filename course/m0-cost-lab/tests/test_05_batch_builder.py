import json
import re
from types import SimpleNamespace

import pytest
from cost_lab.batch import Item, Outcome, build_batch, join_results

ITEMS = [Item(str(i), f"question {i}") for i in range(1, 7)]
M = "claude-haiku-5-5"


@pytest.fixture
def results(fixture_dir):
    lines = (fixture_dir / "batch_results.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_build_batch_shape_and_deterministic_ids():
    batch = build_batch(ITEMS, model=M, max_tokens=50, system="be brief")
    assert [r["custom_id"] for r in batch] == [f"item-{i}" for i in range(1, 7)]
    assert batch == build_batch(ITEMS, model=M, max_tokens=50, system="be brief")
    assert batch[0]["params"] == {
        "model": M,
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "question 1"}],
        "system": "be brief",
    }


def test_system_is_omitted_when_not_given():
    assert "system" not in build_batch(ITEMS[:1], model=M, max_tokens=50)[0]["params"]


def test_duplicate_ids_raise():
    with pytest.raises(ValueError):
        build_batch([Item("1", "a"), Item("1", "b")], model=M, max_tokens=50)


def test_shuffled_results_join_to_every_item(results):
    outcomes = join_results(ITEMS, results)
    assert set(outcomes) == {str(i) for i in range(1, 7)}
    assert outcomes["4"].kind == "succeeded" and outcomes["4"].text == "answer four"
    assert outcomes["4"].retryable is False
    assert outcomes["1"].kind == "succeeded" and outcomes["6"].kind == "succeeded"


def test_invalid_request_is_not_retryable(results):
    o = join_results(ITEMS, results)["2"]
    assert o.kind == "errored" and o.error_type == "invalid_request_error" and o.retryable is False


def test_expired_is_retryable(results):
    o = join_results(ITEMS, results)["5"]
    assert o.kind == "expired" and o.retryable is True


def test_flattened_error_shape_is_read_too():
    err = {"type": "invalid_request_error", "message": "bad"}
    raw = {"custom_id": "item-1", "result": {"type": "errored", "error": err}}
    o = join_results(ITEMS[:1], [raw])["1"]
    assert o.error_type == "invalid_request_error" and o.retryable is False


def test_other_errors_are_retryable():
    raw = {"custom_id": "item-1", "result": {"type": "errored", "error": {"type": "api_error"}}}
    assert join_results(ITEMS[:1], [raw])["1"].retryable is True
    nested = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    raw = {"custom_id": "item-1", "result": {"type": "errored", "error": nested}}
    assert join_results(ITEMS[:1], [raw])["1"].retryable is True


def test_canceled_is_not_retryable():
    raw = {"custom_id": "item-1", "result": {"type": "canceled"}}
    o = join_results(ITEMS[:1], [raw])["1"]
    assert o.kind == "canceled" and o.retryable is False


def test_missing_result_counts_as_expired():
    o = join_results(ITEMS[:2], [])["2"]
    assert o.kind == "expired" and o.text is None and o.retryable is True


def test_accepts_sdk_style_objects():
    text = SimpleNamespace(text="hello")
    message = SimpleNamespace(content=[text])
    result = SimpleNamespace(type="succeeded", message=message)
    o = join_results(ITEMS[:1], [SimpleNamespace(custom_id="item-1", result=result)])["1"]
    assert o.kind == "succeeded" and o.text == "hello"


@pytest.mark.parametrize("result", [None, {}, {"type": "mystery"}])
def test_missing_or_unknown_result_type_is_unknown_and_retryable(result):
    raw = {"custom_id": "item-1"} if result is None else {"custom_id": "item-1", "result": result}
    o = join_results(ITEMS[:1], [raw])["1"]
    assert o == Outcome("unknown", None, None, True)


@pytest.mark.parametrize("bad_id", ["a b", "ü", "x" * 60])
def test_ids_that_make_an_invalid_custom_id_raise(bad_id):
    with pytest.raises(ValueError):
        build_batch([Item(bad_id, "q")], model=M, max_tokens=50)


def test_custom_ids_match_the_documented_pattern():
    ids = [Item("a_B-9", "q"), Item("x" * 59, "q")]
    for request in build_batch(ids, model=M, max_tokens=50):
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", request["custom_id"])


def test_result_without_custom_id_is_ignored():
    raw = {"result": {"type": "canceled"}}
    assert join_results(ITEMS[:1], [raw])["1"].kind == "expired"


def test_duplicate_custom_id_last_wins():
    first = {"custom_id": "item-1", "result": {"type": "canceled"}}
    last = {"custom_id": "item-1", "result": {"type": "errored", "error": {"type": "api_error"}}}
    assert join_results(ITEMS[:1], [first, last])["1"].kind == "errored"
