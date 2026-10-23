from retrieval_lab_lessons import rrf, score_sum

vector = [("c7", 0.82), ("c2", 0.80), ("c9", 0.79), ("c4", 0.77)]
text = [("c4", 0.31), ("c5", 0.09), ("c7", 0.05)]

print("score sum:", [(cid, round(s, 3)) for cid, s in score_sum([vector, text])])
fused = rrf([[cid for cid, _ in vector], [cid for cid, _ in text]], k=60)
print("rrf k=60: ", [(cid, round(s, 5)) for cid, s in fused])

filler = [f"f{i:02d}" for i in range(1, 30)]
twice = rrf([[*filler, "both"], [*filler, "both"], ["solo"]])
scores = dict(twice)
print(
    f"30th in two lists {scores['both']:.5f} = 2/90, first in one list {scores['solo']:.5f} = 1/61"
)
