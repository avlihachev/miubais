import numpy as np
from retrieval_lab_lessons import toy_mmr

names = ["setup A", "setup A (overlap)", "pricing", "limits"]
relevance = [1.0, 0.97, 0.80, 0.60]
vectors = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.98, 0.2, 0.0],
        [0.3, 0.9, 0.1],
        [0.2, 0.1, 0.95],
    ]
)
for lam in (1.0, 0.7, 0.3):
    order = toy_mmr(relevance, vectors, lam=lam, top_k=3)
    print(f"lambda {lam}: {[names[i] for i in order]}")
