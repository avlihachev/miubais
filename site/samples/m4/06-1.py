from retrieval_lab_lessons import toy_check

answers = {
    "cited": "Hits cost a tenth of the input price [2]. Writes cost more [1][3].",
    "one uncited": "Hits cost a tenth of the input price [2]. This makes caching always worth it.",
    "out of range": "Hits cost a tenth of the input price [7].",
    "refusal": "I cannot answer from the sources.",
}
for name, text in answers.items():
    print(f"{name:<13} {toy_check(text, sources=5)}")
