from retrieval_lab_lessons import (
    dcg_at_k,
    ideal_dcg,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

ranked = ["d3", "d8", "d1", "d6", "d2"]
relevant = {"d1", "d2", "d5"}
k = 5
print(f"recall@{k}    {recall_at_k(ranked, relevant, k):.3f}")
print(f"precision@{k} {precision_at_k(ranked, relevant, k):.3f}")
print(f"RR          {reciprocal_rank(ranked, relevant):.3f}")
dcg = dcg_at_k(ranked, relevant, k)
print(f"DCG@{k}       {dcg:.4f}")
print(
    f"IDCG over min(k, relevant)=3: {ideal_dcg(3):.4f} -> nDCG {ndcg_at_k(ranked, relevant, k):.4f}"
)
print(f"IDCG over k=5 (wrong):        {ideal_dcg(5):.4f} -> {dcg / ideal_dcg(5):.4f}")
print("one relevant item at rank 1, k=10:", ndcg_at_k(["d1", "x"], {"d1"}, 10))
print(f"  with the ideal over k=10: {1 / ideal_dcg(10):.4f}")
