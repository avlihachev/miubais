from retrieval_lab_lessons import corpus_size

size = corpus_size("fixtures/corpus")
print(f"{size['documents']} documents, {size['chars']:,} characters, {size['words']:,} words")
print(f"largest document: {size['largest']:,} characters")
print(f"estimate at 4 characters per token: {size['tokens_estimate']:,} tokens")
print("under 200,000 tokens:", size["tokens_estimate"] < 200_000)
