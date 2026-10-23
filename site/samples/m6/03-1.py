from serving_lab_lessons.streams import DONE, chunk, tally, usage_chunk

answer = [
    (212.0, chunk({"role": "assistant", "content": ""})),
    (240.0, chunk({"content": "Paged"})),
    (281.0, chunk({"content": " blocks"})),
    (322.0, chunk({"content": " hold"})),
    (363.0, chunk({"content": " the cache."})),
    (364.0, chunk({}, finish_reason="stop")),
    (365.0, usage_chunk(prompt_tokens=14, completion_tokens=4)),
    (365.5, DONE),
]
thinking = [(212.0, chunk({"role": "assistant", "content": ""}))]
thinking += [(240.0 + 41 * i, chunk({"reasoning": f" step{i}"})) for i in range(48)]
thinking += [
    (2170.0, chunk({"content": ""}, finish_reason="length")),
    (2171.0, usage_chunk(prompt_tokens=14, completion_tokens=48)),
    (2171.5, DONE),
]
cut = answer[:3]

for line in [answer[0][1], answer[1][1], answer[-1][1]]:
    print(line)
for name, arrivals in [("answer", answer), ("thinking", thinking), ("cut", cut)]:
    t = tally(arrivals)
    print(
        f"{name:<8} content={t.content_tokens} reasoning={t.reasoning_chunks} ttft={t.ttft_ms}"
        f" tps={t.tps and round(t.tps, 1)} finish={t.finish_reason}"
        f" usage={t.usage_completion_tokens} done={t.done} text={t.text!r}"
    )
