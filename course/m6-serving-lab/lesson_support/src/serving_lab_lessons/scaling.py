import math
from collections.abc import Sequence


def wanted(waiting: float, *, target: float, low: int, high: int) -> int:
    return min(high, max(low, math.ceil(waiting / target)))


def windowed_recommendations(
    series: Sequence[tuple[int, float]],
    *,
    target: float,
    low: int,
    high: int,
    up_window_s: int,
    down_window_s: int,
) -> list[tuple[int, int, int, int]]:
    raw = [(t, wanted(w, target=target, low=low, high=high)) for t, w in series]
    rows = []
    for t, r in raw:
        up = min(n for s, n in raw if t - up_window_s <= s <= t)
        down = max(n for s, n in raw if t - down_window_s <= s <= t)
        rows.append((t, r, up, down))
    return rows
