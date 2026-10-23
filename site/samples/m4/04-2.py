from pathlib import Path

from retrieval_lab_lessons import live_models_summary

live = live_models_summary(Path("course/m4-retrieval-lab/fixtures/live_local_models_run.json"))
print(f"{live['embedder']} + {live['reranker']}")
print(f"{live['chunks']} chunks, {live['queries']} queries, k={live['k']}, pool {live['pool']}")
for name in ("hybrid", "reranked"):
    row = live[name]
    print(f"  {name:<9}" + "".join(f" {m} {row[m]:.3f}" for m in ("recall", "mrr", "ndcg")))
for kind, (before, after) in live["recall_by_kind"].items():
    print(f"  recall@10 {kind:<10} {before:.3f} -> {after:.3f}")
print(f"pool recall@50 {live['pool_recall']:.3f}")
print(f"index {live['index_seconds']:.0f} s, rerank eval {live['rerank_seconds']:.0f} s")
