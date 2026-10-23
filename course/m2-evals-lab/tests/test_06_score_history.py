import sqlite3
from contextlib import closing

from evals_lab.history import ScoreHistory
from evals_lab.types import CATEGORIES, RunSummary


def summary(run_id: str, at: str, pass_rate: float = 0.5, loops: int = 0) -> RunSummary:
    counts = dict.fromkeys(CATEGORIES, 0) | {"loop": loops, "success": 10 - loops}
    return RunSummary(run_id=run_id, at=at, pass_rate=pass_rate, counts=counts, n=10)


RUNS = [
    summary("zeta", "2026-10-15T09:00:00+00:00", 0.40, 1),
    summary("alpha", "2026-10-16T09:00:00+00:00", 0.50, 2),
    summary("mid", "2026-10-17T09:00:00+00:00", 0.60, 3),
]


def test_trend_returns_the_last_n_oldest_first(tmp_path):
    history = ScoreHistory(tmp_path / "scores.db")
    for run in RUNS:
        history.record(run)
    assert history.trend(3) == RUNS
    assert history.trend(2) == RUNS[1:]
    assert history.trend(1) == RUNS[2:]


def test_trend_survives_reopening_the_file(tmp_path):
    path = tmp_path / "scores.db"
    first = ScoreHistory(path)
    first.record(RUNS[0])
    first.record(RUNS[1])
    second = ScoreHistory(path)
    second.record(RUNS[2])
    assert ScoreHistory(path).trend(3) == RUNS


def test_recording_the_same_run_twice_keeps_one_row(tmp_path):
    path = tmp_path / "scores.db"
    history = ScoreHistory(path)
    for run in RUNS:
        history.record(run)
    history.record(RUNS[0])
    assert history.trend(10) == RUNS
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("select count(*) from runs").fetchone() == (3,)


def test_trend_larger_than_the_table_returns_everything(tmp_path):
    history = ScoreHistory(tmp_path / "scores.db")
    assert history.trend(5) == []
    history.record(RUNS[0])
    assert history.trend(5) == RUNS[:1]


def test_the_table_has_the_documented_columns(tmp_path):
    path = tmp_path / "scores.db"
    ScoreHistory(path).record(RUNS[0])
    with closing(sqlite3.connect(path)) as db:
        columns = [row[1] for row in db.execute("pragma table_info(runs)")]
    assert columns == ["run_id", "at", "pass_rate", "counts_json", "n"]
