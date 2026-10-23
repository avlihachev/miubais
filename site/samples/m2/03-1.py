from evals_lab_lessons import manifest_hash, split_counts, stratified_split

published = {"success": 60} | {
    c: 20
    for c in (
        "loop",
        "scope-creep",
        "silent-skip",
        "policy-denied-retry",
        "tool-result-poisoning",
        "budget-blowout",
        "context-loss",
    )
}
strata, i = {}, 0
for category, count in published.items():
    for _ in range(count):
        i += 1
        strata[f"x{i:03d}"] = category

fractions = {"train": 0.2, "dev": 0.4, "test": 0.4}
splits = stratified_split(strata, fractions, seed=17)
print(split_counts(splits, strata))
print("manifest sha256:", manifest_hash(splits)[:16])
again = stratified_split(strata, fractions, seed=17)
print("same seed, same manifest:", manifest_hash(again) == manifest_hash(splits))
overlap = set(splits["train"]) & (set(splits["dev"]) | set(splits["test"]))
print("ids in train and in dev/test:", len(overlap))
