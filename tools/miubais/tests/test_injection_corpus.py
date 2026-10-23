import json
import subprocess
import sys
from collections import Counter

from miubais.paths import repo_root

DATASET = repo_root() / "fixtures" / "injection-corpus"
CORPUS = DATASET / "corpus.jsonl"
KINDS = {"direct", "indirect-tool-result", "indirect-file", "indirect-web", "benign"}
TECHNIQUES = {
    "instruction-override",
    "role-play",
    "fake-system-message",
    "tool-result-injection",
    "data-exfiltration",
    "encoding-obfuscation",
    "delimiter-escape",
    "approval-spoof",
    "none",
}
ASI_IDS = {f"ASI{n:02d}" for n in range(1, 11)}
CHANNELS = {"ticket", "file", "tool_output", "web", "user"}


def load() -> list[dict]:
    return [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]


def test_regenerating_is_byte_identical(tmp_path):
    out = tmp_path / "corpus.jsonl"
    subprocess.run(
        [sys.executable, str(DATASET / "generate.py"), "--out", str(out)],
        check=True,
        capture_output=True,
    )
    assert out.read_bytes() == CORPUS.read_bytes()


def test_count_and_ids():
    rows = load()
    assert len(rows) == 140
    assert [r["id"] for r in rows] == [f"inj{n:03d}" for n in range(1, 141)]


def test_labels_are_in_range():
    for r in load():
        assert r["kind"] in KINDS
        assert r["technique"] in TECHNIQUES
        assert r["asi"] in ASI_IDS or r["asi"] == "none"
        assert r["source_channel"] in CHANNELS
        assert set(r) == {"id", "kind", "technique", "asi", "source_channel", "text"}


def test_lengths_within_limit():
    assert all(0 < len(r["text"]) <= 600 for r in load())


def test_every_technique_has_at_least_eight():
    counts = Counter(r["technique"] for r in load())
    for technique in TECHNIQUES - {"none"}:
        assert counts[technique] >= 8, (technique, counts[technique])


def test_none_technique_only_on_benign():
    for r in load():
        assert (r["technique"] == "none") == (r["kind"] == "benign")


def test_benign_and_hard_negatives():
    rows = load()
    benign = [r for r in rows if r["kind"] == "benign"]
    assert len(benign) >= 50
    hard = [r for r in benign if "ignore" in r["text"].lower() or "system" in r["text"].lower()]
    assert len(hard) >= 30


def test_benign_items_carry_no_asi():
    assert all(r["asi"] == "none" for r in load() if r["kind"] == "benign")


def test_all_ten_asi_ids_appear():
    assert {r["asi"] for r in load()} >= ASI_IDS


def test_urls_do_not_resolve():
    for r in load():
        assert "http://" not in r["text"] or "example.invalid" in r["text"]
        if "https://" in r["text"]:
            assert "example.invalid" in r["text"]
