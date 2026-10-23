from miubais.tutor.leak import (
    exercise_leak_terms,
    find_leaks,
    leak_terms,
    learner_identifiers,
    stoplist,
    write_leak_terms,
)


def _tree(tmp_path):
    ref = tmp_path / "reference"
    starter = tmp_path / "starter"
    tests = tmp_path / "tests"
    for d in (ref, starter, tests):
        d.mkdir()
    (ref / "lab.py").write_text(
        "def add(a, b):\n    return compute_total_secret(a, b)\n\n"
        'def compute_total_secret(a, b):\n    note = "do not reveal this"\n    return a + b\n'
    )
    (starter / "lab.py").write_text("def add(a, b):\n    return None\n")
    (tests / "test_lab.py").write_text(
        "from lab import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    return ref, starter, tests


def test_leak_terms_exclude_names_present_in_starter_or_tests(tmp_path):
    ref, starter, tests = _tree(tmp_path)
    terms = leak_terms(ref, starter, tests)
    assert "compute_total_secret" in terms
    assert "do not reveal this" in terms
    assert "add" not in terms


def test_names_mentioned_in_tests_text_are_not_terms(tmp_path):
    ref, starter, tests = _tree(tmp_path)
    (tests / "notes.md").write_text("see compute_total_secret")
    assert "compute_total_secret" not in leak_terms(ref, starter, tests)


def test_find_leaks_is_whole_word_and_case_sensitive_for_identifiers():
    terms = {"compute_total_secret", "do not reveal this"}
    assert find_leaks("call compute_total_secret now", terms) == ["compute_total_secret"]
    assert find_leaks("compute_total_secret2 COMPUTE_TOTAL_SECRET", terms) == []
    assert find_leaks("`compute_total_secret()`", terms) == ["compute_total_secret"]


def test_find_leaks_matches_literals_as_case_insensitive_substrings():
    terms = {"do not reveal this", "item-"}
    assert find_leaks("please Do not reveal this ok", terms) == ["do not reveal this"]
    assert find_leaks("ids look like item-3", terms) == ["item-"]


def test_fixtures_and_readme_are_public(tmp_path):
    ref, starter, tests = _tree(tmp_path)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "x.json").write_text('{"compute_total_secret": 1}')
    readme = tmp_path / "README.md"
    readme.write_text("never say do not reveal this")
    terms = leak_terms(ref, starter, tests, fixtures, readme)
    assert "compute_total_secret" not in terms and "do not reveal this" not in terms


def test_stoplist_words_are_never_terms(tmp_path):
    ref, starter, tests = _tree(tmp_path)
    (ref / "more.py").write_text("def cache_control():\n    content = 1\n    return content\n")
    terms = leak_terms(ref, starter, tests)
    assert {"cache_control", "content"} <= stoplist()
    assert "cache_control" not in terms and "content" not in terms


def test_leak_ignore_removes_terms(sample_ex, tmp_path):
    import shutil

    from miubais.exercises import load_exercise

    shutil.copytree(sample_ex.dir, tmp_path / "ex")
    ex = load_exercise(tmp_path / "ex")
    (ex.reference_dir / "extra.py").write_text("def hidden_alpha():\n    hidden_beta = 1\n")
    assert {"hidden_alpha", "hidden_beta"} <= exercise_leak_terms(ex)
    (ex.reference_dir / ".leak-ignore").write_text("hidden_alpha\n")
    terms = exercise_leak_terms(ex)
    assert "hidden_alpha" not in terms and "hidden_beta" in terms


def test_learner_identifiers_reads_only_added_lines():
    diff = "--- a\n+++ b\n-old_name = 1\n+new_name = helper(x)\n context_name\n"
    assert learner_identifiers(diff) == {"new_name", "helper", "x"}


def test_write_leak_terms_sorted_lines(sample_ex, tmp_path):
    import shutil

    shutil.copytree(sample_ex.dir, tmp_path / "ex")
    from miubais.exercises import load_exercise

    ex = load_exercise(tmp_path / "ex")
    path = write_leak_terms(ex, {"zeta_name", "alpha_name"})
    assert path == ex.tests_dir / ".leak-terms"
    assert path.read_text() == "alpha_name\nzeta_name\n"


def _reference_with(tmp_path, source: str):
    ref, starter, tests = _tree(tmp_path)
    (ref / "extra.py").write_text(source)
    return leak_terms(ref, starter, tests)


def test_short_literals_of_common_words_are_not_terms(tmp_path):
    terms = _reference_with(
        tmp_path,
        'A = "the value is empty"\nB = "returned none here"\nC = "price list is empty for SKU-42"\n',
    )
    assert "the value is empty" not in terms
    assert "price list is empty for SKU-42" in terms


def test_multi_line_literals_become_one_term_per_meaningful_line(tmp_path):
    source = (
        'PROMPT = """You fix one ticket in the repository.\n'
        "Only edit files under src/ and never tests/.\n"
        ")\n"
        '---\n"""\n'
    )
    terms = _reference_with(tmp_path, source)
    assert "You fix one ticket in the repository." in terms
    assert "Only edit files under src/ and never tests/." in terms
    assert not any("\n" in t for t in terms)
    assert ")" not in terms and "---" not in terms


def test_literals_without_letters_are_not_terms(tmp_path):
    terms = _reference_with(tmp_path, 'ROW = "| --- | --- | ---: | ---: |"\n')
    assert "| --- | --- | ---: | ---: |" not in terms
