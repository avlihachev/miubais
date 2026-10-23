import pytest
from evals_lab import traces


def test_loads_every_trace_sorted_by_id(traces_dir):
    loaded = traces.load(traces_dir)
    ids = [t.id for t in loaded]
    assert len(loaded) == 200
    assert ids == sorted(ids)
    assert ids[0] == "t001" and ids[-1] == "t200"


def test_line_counts_match_files(traces_dir):
    for trace in traces.load(traces_dir):
        raw = (traces_dir / f"{trace.id}.jsonl").read_text().splitlines()
        assert len(trace.lines) == len(raw)
        assert [line.n for line in trace.lines] == list(range(1, len(raw) + 1))


def test_ignores_files_that_are_not_traces(tmp_path):
    (tmp_path / "t001.jsonl").write_text('{"n": 1, "role": "user", "text": "hi"}\n')
    (tmp_path / "notes.txt").write_text("not a trace")
    assert [t.id for t in traces.load(tmp_path)] == ["t001"]


def test_malformed_file_is_rejected_naming_file_and_line(tmp_path):
    (tmp_path / "t001.jsonl").write_text('{"n": 1, "role": "user", "text": "hi"}\n')
    (tmp_path / "t002.jsonl").write_text(
        '{"n": 1, "role": "user", "text": "hi"}\n{"n": 2, "role": "nobody"}\n'
    )
    with pytest.raises(ValueError, match=r"t002\.jsonl:2"):
        traces.load(tmp_path)


def test_invalid_json_is_rejected_naming_file(tmp_path):
    (tmp_path / "t009.jsonl").write_text("{not json\n")
    with pytest.raises(ValueError, match=r"t009\.jsonl:1"):
        traces.load(tmp_path)


def test_view_is_one_short_line_per_entry(traces_dir):
    trace = next(t for t in traces.load(traces_dir) if t.id == "t001")
    rendered = traces.view(trace).split("\n")
    assert len(rendered) == len(trace.lines)
    assert max(len(row) for row in rendered) <= 140
    for row, line in zip(rendered, trace.lines):
        assert row.startswith(f"{line.n}  {line.role}  ")


def test_view_keeps_the_tool_name_and_input(traces_dir):
    trace = next(t for t in traces.load(traces_dir) if t.id == "t001")
    rendered = traces.view(trace).split("\n")
    assert "Read" in rendered[2] and "tests/test_window.py" in rendered[2]
