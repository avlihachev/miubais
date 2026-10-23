from pathlib import Path

from capstone_lessons import glob_matches, load_rules, rules_for

rules = load_rules(Path("fixtures/go-ts-mini"))
for rule in rules:
    print(f"{rule.name:<11}{', '.join(rule.paths) or '(no paths: always loaded)'}")

print()
changes = {
    "web widget": ["web/src/widgets/due-badge.tsx"],
    "new migration": ["migrations/0009_add_glossary_table.sql", "internal/store/glossaries.go"],
    "contract": ["proto/jobs/v2/glossaries.proto", "CHANGELOG.json"],
    "docs only": ["docs/runbook.md"],
}
for name, files in changes.items():
    print(f"{name:<15}{' '.join(rules_for(rules, files))}")

print()
print(f"{'pattern':<19}{'path':<34}{'** ok':<7}** as *")
for pattern, path in [
    ("**/*.ts", "web/src/api.ts"),
    ("**/*.ts", "api.ts"),
    ("web/**/*.{ts,tsx}", "web/src/widgets/due-badge.tsx"),
    ("migrations/*.sql", "migrations/archive/0001_init.sql"),
]:
    right = glob_matches(pattern, path)
    naive = glob_matches(pattern, path, globstar=False)
    print(f"{pattern:<19}{path:<34}{right!s:<7}{naive}")
