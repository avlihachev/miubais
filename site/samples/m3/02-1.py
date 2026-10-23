from trace_lab_lessons import anthropic_input_tokens, inference_attributes

turns = {
    "first turn, cache written": {
        "input_tokens": 3,
        "output_tokens": 640,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 9000,
    },
    "later turn, cache hit": {
        "input_tokens": 12,
        "output_tokens": 210,
        "cache_read_input_tokens": 9000,
        "cache_creation_input_tokens": 1500,
    },
    "no caching at all": {
        "input_tokens": 10512,
        "output_tokens": 210,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    },
}

for label, usage in turns.items():
    print(
        f"{label:<26} api input_tokens={usage['input_tokens']:>5}  "
        f"gen_ai.usage.input_tokens={anthropic_input_tokens(usage):>5}"
    )

print()
attributes = inference_attributes(
    "claude-opus-5-5",
    turns["later turn, cache hit"],
    response_id="msg_example",
    finish_reason="tool_use",
)
for key, value in attributes.items():
    print(f"{key} = {value!r}")
