from evals_lab_lessons import confusion, kappa, tnr, tpr, trusted


def expand(cells: dict[tuple[str, str], int]) -> tuple[list[str], list[str]]:
    judge, human = [], []
    for (said, truth), count in cells.items():
        judge += [said] * count
        human += [truth] * count
    return judge, human


outcomes = {("pass", "pass"): 27, ("fail", "pass"): 3, ("fail", "fail"): 17, ("pass", "fail"): 3}
c = confusion(*expand(outcomes))
print(f"outcome: TP={c.tp} FN={c.fn} TN={c.tn} FP={c.fp} TPR={tpr(c):.2f} TNR={tnr(c):.2f}")

categories = {
    ("success", "success"): 26,
    ("loop", "loop"): 6,
    ("silent-skip", "silent-skip"): 5,
    ("success", "silent-skip"): 3,
    ("context-loss", "context-loss"): 4,
    ("loop", "context-loss"): 2,
    ("scope-creep", "scope-creep"): 3,
    ("success", "scope-creep"): 1,
}
judge = kappa(*expand(categories))
print(f"judge:   n={judge.n} po={judge.po:.2f} pe={judge.pe:.2f} kappa={judge.kappa:.2f}")
print("trusted:", trusted(tpr(c), tnr(c), judge.kappa, judge.n))

skewed = {("success", "success"): 45, ("success", "loop"): 3, ("success", "silent-skip"): 2}
lazy = kappa(*expand(skewed))
print(f"lazy:    n={lazy.n} po={lazy.po:.2f} pe={lazy.pe:.2f} kappa={lazy.kappa:.2f}")
