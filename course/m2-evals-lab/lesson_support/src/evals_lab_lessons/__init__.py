import hashlib
import json
import math
import random
from collections import Counter
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MIN_TPR = 0.85
MIN_TNR = 0.85
MIN_KAPPA = 0.6
MIN_TRACES = 40


@dataclass(frozen=True)
class Note:
    trace: str
    outcome: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class TaxonomyRow:
    category: str
    traces: int
    fails: int


def axial_code(notes: Iterable[Note], axial: Mapping[str, str]) -> list[TaxonomyRow]:
    traces: Counter[str] = Counter()
    fails: Counter[str] = Counter()
    for note in notes:
        categories = {axial.get(code, "uncoded") for code in note.codes}
        for category in categories:
            traces[category] += 1
            fails[category] += note.outcome == "fail"
    rows = [TaxonomyRow(c, traces[c], fails[c]) for c in traces]
    return sorted(rows, key=lambda r: (-r.fails, -r.traces, r.category))


def taxonomy_table(rows: Sequence[TaxonomyRow], total: int) -> str:
    header = f"{'category':<24} {'traces':>6} {'fails':>5} {'share':>6}"
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.category:<24} {row.traces:>6} {row.fails:>5} {row.traces / total if total else 0.0:>6.0%}"
        )
    return "\n".join(lines)


def new_categories_per_batch(
    notes: Sequence[Note], axial: Mapping[str, str], size: int
) -> list[int]:
    seen: set[str] = set()
    fresh = []
    for start in range(0, len(notes), size):
        batch = {
            axial.get(code, "uncoded") for n in notes[start : start + size] for code in n.codes
        }
        fresh.append(len(batch - seen))
        seen |= batch
    return fresh


@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    tn: int
    fn: int


def confusion(predicted: Sequence[str], gold: Sequence[str], positive: str = "pass") -> Confusion:
    pairs = list(zip(predicted, gold, strict=True))
    return Confusion(
        tp=sum(p == positive and g == positive for p, g in pairs),
        fp=sum(p == positive and g != positive for p, g in pairs),
        tn=sum(p != positive and g != positive for p, g in pairs),
        fn=sum(p != positive and g == positive for p, g in pairs),
    )


def tpr(c: Confusion) -> float:
    return c.tp / (c.tp + c.fn) if c.tp + c.fn else 0.0


def tnr(c: Confusion) -> float:
    return c.tn / (c.tn + c.fp) if c.tn + c.fp else 0.0


@dataclass(frozen=True)
class Agreement:
    kappa: float
    po: float
    pe: float
    n: int


def kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> Agreement:
    pairs = list(zip(a, b, strict=True))
    n = len(pairs)
    if not n:
        return Agreement(0.0, 0.0, 0.0, 0)
    po = sum(x == y for x, y in pairs) / n
    left, right = Counter(a), Counter(b)
    pe = sum(left[k] * right[k] for k in left) / (n * n)
    value = (po - pe) / (1 - pe) if pe < 1 else 0.0
    return Agreement(value, po, pe, n)


def trusted(tpr_value: float, tnr_value: float, kappa_value: float, n: int) -> bool:
    return (
        tpr_value >= MIN_TPR
        and tnr_value >= MIN_TNR
        and kappa_value >= MIN_KAPPA
        and n >= MIN_TRACES
    )


def stratified_split(
    strata: Mapping[str, Hashable], fractions: Mapping[str, float], seed: int
) -> dict[str, list[str]]:
    groups: dict[Hashable, list[str]] = {}
    for item, stratum in sorted(strata.items()):
        groups.setdefault(stratum, []).append(item)
    rng = random.Random(seed)
    splits: dict[str, list[str]] = {name: [] for name in fractions}
    names = list(fractions)
    for stratum in sorted(groups, key=str):
        items = groups[stratum]
        rng.shuffle(items)
        start = 0
        for name in names[:-1]:
            take = round(len(items) * fractions[name])
            splits[name] += items[start : start + take]
            start += take
        splits[names[-1]] += items[start:]
    return {name: sorted(ids) for name, ids in splits.items()}


def split_counts(splits: Mapping[str, Sequence[str]], strata: Mapping[str, Hashable]) -> str:
    names = list(splits)
    values = sorted({strata[i] for ids in splits.values() for i in ids}, key=str)
    header = f"{'stratum':<22}" + "".join(f"{n:>7}" for n in names)
    lines = [header, "-" * len(header)]
    for value in values:
        cells = "".join(f"{sum(strata[i] == value for i in splits[n]):>7}" for n in names)
        lines.append(f"{value!s:<22}{cells}")
    lines.append(f"{'total':<22}" + "".join(f"{len(splits[n]):>7}" for n in names))
    return "\n".join(lines)


def manifest_hash(splits: Mapping[str, Sequence[str]]) -> str:
    body = json.dumps({k: sorted(v) for k, v in splits.items()}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def pass_at_k(n: int, c: int, k: int) -> float:
    if not 0 < k <= n or not 0 <= c <= n:
        raise ValueError(f"need 0 < k <= n and 0 <= c <= n, got n={n} c={c} k={k}")
    return 1 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    if not 0 < k <= n or not 0 <= c <= n:
        raise ValueError(f"need 0 < k <= n and 0 <= c <= n, got n={n} c={c} k={k}")
    return math.comb(c, k) / math.comb(n, k)


def suite_pass_at_k(runs: Mapping[str, Sequence[bool]], k: int) -> float:
    return sum(pass_at_k(len(r), sum(r), k) for r in runs.values()) / len(runs)


def suite_pass_hat_k(runs: Mapping[str, Sequence[bool]], k: int) -> float:
    return sum(pass_hat_k(len(r), sum(r), k) for r in runs.values()) / len(runs)


EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


@dataclass(frozen=True)
class Trajectory:
    edits: tuple[int, ...]
    test_file_edits: tuple[int, ...]
    test_runs: tuple[int, ...]
    most_repeated_call: int


def trajectory(lines: Iterable[Any], test_command: str = "pytest") -> Trajectory:
    edits, test_edits, runs = [], [], []
    calls: Counter[str] = Counter()
    for line in lines:
        if line.role != "assistant" or not line.tool:
            continue
        args = line.input or {}
        calls[line.tool + json.dumps(args, sort_keys=True)] += 1
        if line.tool in EDIT_TOOLS:
            edits.append(line.n)
            path = str(args.get("file_path", ""))
            if "tests/" in path or path.rsplit("/", 1)[-1].startswith("test_"):
                test_edits.append(line.n)
        elif line.tool == "Bash" and test_command in str(args.get("command", "")):
            runs.append(line.n)
    return Trajectory(tuple(edits), tuple(test_edits), tuple(runs), max(calls.values(), default=0))


def trajectory_checks(t: Trajectory, max_repeats: int = 2) -> dict[str, bool]:
    last_edit = max(t.edits, default=0)
    return {
        "tests ran after the last edit": any(n > last_edit for n in t.test_runs),
        "no test file edited": not t.test_file_edits,
        f"no call repeated more than {max_repeats} times": t.most_repeated_call <= max_repeats,
    }


MAX_PASS_RATE_DROP_TEN_THOUSANDTHS = 200
MAX_COUNT_RISE = 3


@dataclass(frozen=True)
class GateVerdict:
    ok: bool
    reasons: tuple[str, ...]


def ten_thousandths(rate: float) -> int:
    return round(rate * 10_000)


def gate_check(run: Mapping[str, Any], baseline: Mapping[str, Any]) -> GateVerdict:
    reasons = []
    drop = ten_thousandths(baseline["pass_rate"]) - ten_thousandths(run["pass_rate"])
    if drop > MAX_PASS_RATE_DROP_TEN_THOUSANDTHS:
        reasons.append(
            f"pass_rate fell from {baseline['pass_rate']:.4f} to {run['pass_rate']:.4f} "
            f"(more than {MAX_PASS_RATE_DROP_TEN_THOUSANDTHS / 100:g} percentage points)"
        )
    before_counts, after_counts = baseline["counts"], run["counts"]
    for category in sorted(before_counts.keys() | after_counts.keys()):
        before, after = before_counts.get(category, 0), after_counts.get(category, 0)
        if after - before > MAX_COUNT_RISE:
            reasons.append(f"{category} rose from {before} to {after} (more than {MAX_COUNT_RISE})")
    return GateVerdict(not reasons, tuple(reasons))


@dataclass(frozen=True)
class Finding:
    pr: str
    file: str
    line: int
    severity: str


@dataclass(frozen=True)
class ReviewScore:
    reported: int
    reported_true: int
    labelled: int
    labelled_found: int

    @property
    def precision(self) -> float:
        return self.reported_true / self.reported if self.reported else 0.0

    @property
    def recall(self) -> float:
        return self.labelled_found / self.labelled if self.labelled else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def match_findings(
    reported: Sequence[Finding], labels: Sequence[Finding], tolerance: int = 3
) -> list[tuple[Finding, Finding]]:
    free = list(reported)
    pairs = []
    for label in sorted(labels, key=lambda f: (f.pr, f.file, f.line)):
        near = [
            f
            for f in free
            if f.pr == label.pr and f.file == label.file and abs(f.line - label.line) <= tolerance
        ]
        if near:
            best = min(near, key=lambda f: (abs(f.line - label.line), f.line))
            free.remove(best)
            pairs.append((best, label))
    return pairs


def review_scores(
    reported: Sequence[Finding], labels: Sequence[Finding], tolerance: int = 3
) -> dict[str, ReviewScore]:
    pairs = match_findings(reported, labels, tolerance)
    hit_reports = [f for f, _ in pairs]
    hit_labels = [label for _, label in pairs]
    severities = sorted({f.severity for f in [*reported, *labels]})
    scores = {
        s: ReviewScore(
            reported=sum(f.severity == s for f in reported),
            reported_true=sum(f.severity == s for f in hit_reports),
            labelled=sum(f.severity == s for f in labels),
            labelled_found=sum(f.severity == s for f in hit_labels),
        )
        for s in severities
    }
    scores["all"] = ReviewScore(len(reported), len(pairs), len(labels), len(pairs))
    return scores


def review_table(scores: Mapping[str, ReviewScore]) -> str:
    header = (
        f"{'severity':<10} {'reported':>8} {'true':>5} {'labelled':>8} {'found':>5}"
        f" {'precision':>9} {'recall':>6} {'f1':>5}"
    )
    lines = [header, "-" * len(header)]
    for name, s in scores.items():
        lines.append(
            f"{name:<10} {s.reported:>8} {s.reported_true:>5} {s.labelled:>8} {s.labelled_found:>5}"
            f" {s.precision:>9.2f} {s.recall:>6.2f} {s.f1:>5.2f}"
        )
    return "\n".join(lines)
