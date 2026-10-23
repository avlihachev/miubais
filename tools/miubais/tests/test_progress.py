import json

from miubais.progress import Progress, load_progress, record, save_progress


def test_progress_round_trip(tmp_path):
    p = Progress()
    record(p, "x-sample", "01-add", "passed", None)
    save_progress(p, tmp_path, None)
    assert load_progress(tmp_path).exercises["x-sample"]["01-add"].status == "passed"


def test_load_missing_returns_empty(tmp_path):
    assert load_progress(tmp_path).exercises == {}


def test_save_writes_mirror_and_leaves_no_temp_files(tmp_path):
    p = Progress()
    record(p, "x-sample", "01-add", "failed", "/some/out.txt")
    mirror = tmp_path / "ws" / ".progress.json"
    mirror.parent.mkdir()
    save_progress(p, tmp_path / "home", mirror)
    data = json.loads(mirror.read_text())
    assert data["exercises"]["x-sample"]["01-add"]["output_path"] == "/some/out.txt"
    assert [f.name for f in (tmp_path / "home").iterdir()] == ["progress.json"]
