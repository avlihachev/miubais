from serving_lab_lessons.scaling import windowed_recommendations

waiting = [2, 1, 3, 2, 1, 14, 2, 1, 2, 3, 10, 11, 12, 10, 11, 9, 3, 2, 1, 2, 1, 1, 2, 1, 1]
series = [(minute * 60, w) for minute, w in enumerate(waiting)]
policy = {"target": 4, "low": 1, "high": 4}

rows = windowed_recommendations(series, **policy, up_window_s=120, down_window_s=300)
print(f"{'minute':<16}" + "".join(f"{t // 60:>3}" for t, *_ in rows))
print(f"{'waiting':<16}" + "".join(f"{w:>3}" for w in waiting))
for label, column in [("each sample", 1), ("min over 120 s", 2), ("max over 300 s", 3)]:
    print(f"{label:<16}" + "".join(f"{row[column]:>3}" for row in rows))
