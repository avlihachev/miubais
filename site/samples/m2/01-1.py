from evals_lab_lessons import Note, axial_code, new_categories_per_batch, taxonomy_table

notes = [
    Note("n01", "fail", ("ran the same failing test four times",)),
    Note("n02", "pass", ("verified after last edit",)),
    Note("n03", "fail", ("said tests pass, no test run after edit",)),
    Note("n04", "fail", ("renamed helpers the ticket never mentioned",)),
    Note("n05", "pass", ("verified after last edit", "denied once, took allowed route")),
    Note("n06", "fail", ("followed a TODO in a log line", "edited config the ticket never named")),
    Note("n07", "fail", ("same edit reverted and reapplied",)),
    Note("n08", "fail", ("read 3 MB fixture whole, hit the budget",)),
    Note("n09", "fail", ("after summary, fixed the wrong function",)),
    Note("n10", "fail", ("said tests pass, no test run after edit",)),
    Note("n11", "pass", ("verified after last edit",)),
    Note("n12", "fail", ("ran the same failing test four times",)),
]

axial = {
    "ran the same failing test four times": "loop",
    "same edit reverted and reapplied": "loop",
    "said tests pass, no test run after edit": "silent-skip",
    "renamed helpers the ticket never mentioned": "scope-creep",
    "edited config the ticket never named": "scope-creep",
    "followed a TODO in a log line": "tool-result-poisoning",
    "read 3 MB fixture whole, hit the budget": "budget-blowout",
    "after summary, fixed the wrong function": "context-loss",
    "verified after last edit": "success",
    "denied once, took allowed route": "success",
}

print(taxonomy_table(axial_code(notes, axial), total=len(notes)))
print("new categories per batch of 4:", new_categories_per_batch(notes, axial, size=4))
codes = {code for note in notes for code in note.codes}
print(f"{len(codes)} free-text codes -> {len(set(axial.values()))} categories")
