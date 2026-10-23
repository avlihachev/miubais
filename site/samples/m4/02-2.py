from retrieval_lab_lessons import cosine, hash_embed, hash_tokens

print(hash_tokens("Cache hits")[:6])
vec = hash_embed("Cache hits")
print(
    f"dims {vec.shape[0]}, nonzero {int((vec != 0).sum())}, norm {float((vec**2).sum()) ** 0.5:.3f}"
)

query = "how do cache hits lower the bill"
for text in (
    "Cache hits are billed at a tenth of the input price.",
    "Cached prefixes make repeated requests cheaper.",
    "Reading from the prompt cache costs less than fresh input.",
    "The tell-tale heart beat louder under the floor.",
):
    print(f"{cosine(hash_embed(query), hash_embed(text)):+.3f}  {text}")
