import pytest
from capstone import rules
from capstone.rules import Rule


def write_rule(root, name, text):
    path = root / ".claude" / "rules" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_loads_the_fixture_s_five_rules(repo):
    loaded = rules.load(repo)
    by_name = {rule.name: rule for rule in loaded}
    assert sorted(by_name) == ["api", "changelog", "migrations", "proto", "web"]
    assert by_name["changelog"].paths == []
    assert by_name["proto"].paths == ["proto/**/*.proto"]
    assert by_name["migrations"].paths == ["migrations/*.sql"]
    assert by_name["api"].paths == ["internal/api/**/*.go", "internal/jobs/**/*.go"]
    assert by_name["web"].paths == ["web/**/*.{ts,tsx}"]


def test_frontmatter_is_stripped_from_the_body(repo):
    by_name = {rule.name: rule for rule in rules.load(repo)}
    assert by_name["proto"].body.startswith("# Proto contract")
    assert "paths:" not in by_name["proto"].body
    assert "---" not in by_name["web"].body
    assert "reserved" in by_name["proto"].body


def test_rules_are_found_recursively_and_unknown_keys_ignored(tmp_path):
    write_rule(tmp_path, "a.md", '---\npaths: "src/**/*.go"\nowner: team-a\n---\n\nA body\n')
    write_rule(tmp_path, "nested/b.md", "B body without frontmatter\n")
    loaded = rules.load(tmp_path)
    assert [rule.body for rule in loaded] == ["A body", "B body without frontmatter"]
    assert loaded[0].paths == ["src/**/*.go"]
    assert loaded[1].paths == []


def test_paths_as_a_comma_separated_string(tmp_path):
    write_rule(tmp_path, "a.md", '---\npaths: "src/**/*.ts, lib/**/*.{ts,tsx}"\n---\nbody\n')
    assert rules.load(tmp_path)[0].paths == ["src/**/*.ts", "lib/**/*.{ts,tsx}"]


def test_invalid_frontmatter_names_the_file(tmp_path):
    write_rule(tmp_path, "bad.md", "---\npaths: **/*.ts\n---\nbody\n")
    with pytest.raises(ValueError, match="bad.md"):
        rules.load(tmp_path)


def test_a_repo_without_rules_has_none(tmp_path):
    assert rules.load(tmp_path) == []


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("**/*.ts", "web/src/api.ts", True),
        ("**/*.ts", "api.ts", True),
        ("**/*.ts", "web/src/api.go", False),
        ("src/**/*", "src/a/b/c.go", True),
        ("src/**/*", "src/c.go", True),
        ("src/**/*", "web/x", False),
        ("src/**/*", "websrc/x", False),
        ("migrations/*.sql", "migrations/0005_x.sql", True),
        ("migrations/*.sql", "migrations/old/0001_x.sql", False),
        ("proto/**/*.proto", "proto/jobs/v1/jobs.proto", True),
        ("web/**/*.{ts,tsx}", "web/src/view.tsx", True),
        ("web/**/*.{ts,tsx}", "web/src/api.ts", True),
        ("web/**/*.{ts,tsx}", "web/src/api.js", False),
        ("{internal,cmd}/**/*.go", "cmd/server/main.go", True),
        ("{internal,cmd}/**/*.go", "tools/x.go", False),
        ("migrations/000?_*.sql", "migrations/0004_index_status.sql", True),
        ("migrations/000?_*.sql", "migrations/0010_x.sql", False),
        ("*.json", "CHANGELOG.json", True),
        ("*.json", "web/tsconfig.json", False),
        ("internal/api/handlers.go", "internal/api/handlers.go", True),
        ("internal/api/handlers.go", "internal/api/handlers_go", False),
    ],
)
def test_matches(pattern, path, expected):
    assert rules.matches(pattern, path) is expected


def test_for_files_puts_unconditional_rules_first_then_matches_in_load_order(repo):
    loaded = rules.load(repo)
    chosen = rules.for_files(loaded, ["web/src/api.ts", "internal/api/handlers.go"])
    assert [rule.name for rule in chosen] == ["changelog", "api", "web"]


def test_for_files_lists_each_rule_once(repo):
    chosen = rules.for_files(
        rules.load(repo), ["internal/api/handlers.go", "internal/api/errors.go"]
    )
    assert [rule.name for rule in chosen] == ["changelog", "api"]


def test_a_rule_without_paths_is_always_included():
    always = Rule(name="always", paths=[], body="x")
    scoped = Rule(name="scoped", paths=["src/**/*"], body="y")
    assert rules.for_files([scoped, always], ["src/a.go"]) == [always, scoped]
    assert rules.for_files([scoped, always], []) == [always]


def test_files_that_match_nothing_get_only_unconditional_rules(repo):
    chosen = rules.for_files(rules.load(repo), ["README.md", "go.mod"])
    assert [rule.name for rule in chosen] == ["changelog"]


def test_proto_and_migrations_match_their_rules(repo):
    loaded = rules.load(repo)
    files = ["proto/jobs/v1/jobs.proto", "migrations/0005_x.sql", "CHANGELOG.json"]
    assert [rule.name for rule in rules.for_files(loaded, files)] == [
        "changelog",
        "migrations",
        "proto",
    ]
