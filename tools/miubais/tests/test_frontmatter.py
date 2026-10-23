from datetime import date

import pytest
from miubais.freshness.frontmatter import (
    FrontmatterError,
    load_lessons,
    parse_lesson,
    parse_pin_key,
)


def test_parse_lesson_ok(fixture_docs):
    lesson = parse_lesson(fixture_docs / "m1" / "01-harness.md", docs_dir=fixture_docs)
    assert lesson.verified_on == date(2026, 10, 16) and lesson.executed == "local"
    assert lesson.pins["pypi:claude-agent-sdk"] == "0.2.168"
    assert lesson.slug == "m1/01-harness"
    assert len(lesson.sources) == 2 and lesson.sources[0].checked == date(2026, 10, 16)


def test_missing_verified_on_names_file_and_field(fixture_docs):
    with pytest.raises(FrontmatterError) as e:
        parse_lesson(fixture_docs / "m1" / "bad-missing-verified.md")
    assert "bad-missing-verified.md" in str(e.value) and "verified_on" in str(e.value)


def test_bad_executed_names_field(fixture_docs):
    with pytest.raises(FrontmatterError) as e:
        parse_lesson(fixture_docs / "m1" / "bad-executed.md")
    assert "executed" in str(e.value)


def test_parse_pin_key():
    assert parse_pin_key("pypi:langfuse") == ("pypi", "langfuse")
    assert parse_pin_key("github:a/b") == ("github", "a/b")
    with pytest.raises(FrontmatterError):
        parse_pin_key("gem:rails")


def test_unknown_pin_kind_reported_with_path(tmp_path):
    p = tmp_path / "x.md"
    p.write_text(
        "---\ntitle: t\nmodule: m\norder: 1\nverified_on: 2026-10-16\n"
        "executed: none\npins:\n  'gem:rails': '1'\nsources: []\n---\nbody\n"
    )
    with pytest.raises(FrontmatterError) as e:
        parse_lesson(p)
    assert "x.md" in str(e.value) and "gem" in str(e.value)


def test_load_lessons_skips_index_and_raises_on_invalid(fixture_docs, tmp_path):
    with pytest.raises(FrontmatterError):
        load_lessons(fixture_docs)
    good = tmp_path / "m1"
    good.mkdir()
    (good / "01-harness.md").write_text((fixture_docs / "m1" / "01-harness.md").read_text())
    (good / "index.md").write_text("---\nfreshness: skip\n---\n")
    (good / "02-skip.mdx").write_text("---\nfreshness: skip\n---\n")
    lessons = load_lessons(tmp_path)
    assert [x.slug for x in lessons] == ["m1/01-harness"]
