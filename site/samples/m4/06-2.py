from pathlib import Path

from retrieval_lab_lessons import live_answer_summary

live = live_answer_summary(Path("course/m4-retrieval-lab/fixtures/live_answer_run.json"))
print(
    f"model {live['model']}, cap {live['limit_usd']} USD per answer, floor {live['support_floor']}"
)
print(f"{live['answers']} answers ({', '.join(live['kinds'])}), refused {live['refused']}")
print(f"cite a relevant chunk: {live['cite_relevant']}/{live['answers']}")
print(
    f"citations {live['citations']}, invalid {live['invalid']}, uncited sentences {live['uncited']}"
)
print(f"cost {live['cost_usd']} USD of {live['max_total_usd']} allowed")
