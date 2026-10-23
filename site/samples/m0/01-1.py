from pathlib import Path

from cost_lab.transport import make_client

FIXTURES = Path("course/m0-cost-lab/fixtures")
USD_PER_MTOK = {"input": 4.00, "output": 20.00}
TRUNCATED = {"max_tokens", "model_context_window_exceeded"}


def cost_usd(usage) -> float:
    return (
        usage.input_tokens * USD_PER_MTOK["input"] + usage.output_tokens * USD_PER_MTOK["output"]
    ) / 1_000_000


def answer(client, prompt: str) -> str:
    response = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    print(
        f"stop_reason={response.stop_reason} "
        f"in={response.usage.input_tokens} out={response.usage.output_tokens} "
        f"cost=${cost_usd(response.usage):.6f}"
    )
    if response.stop_reason in TRUNCATED:
        raise RuntimeError(f"truncated output, refusing to use it: {text!r}")
    return text


def long_answer(client, prompt: str) -> str:
    params = {
        "model": "claude-opus-5-5",
        "max_tokens": 64000,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        client.messages.create(**params)
    except ValueError as exc:
        print(f"non-streaming refused client-side: {str(exc).split('. ')[0]}")
    with client.messages.stream(**params) as stream:
        text = "".join(stream.text_stream)
        final = stream.get_final_message()
    print(f"streamed stop_reason={final.stop_reason} out={final.usage.output_tokens}")
    if final.stop_reason in TRUNCATED:
        raise RuntimeError(f"truncated output, refusing to use it: {text!r}")
    return text


client, transport = make_client(FIXTURES, ["loop_truncated", "stream_truncated"])
for call in (answer, long_answer):
    try:
        call(client, "Price and stock for item A1?")
    except RuntimeError as exc:
        print(exc)
print(f"requests that reached the transport: {len(transport.requests)}")
