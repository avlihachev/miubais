MODEL = "claude-haiku-5-5"
KEPT_HEADERS = ("content-type", "request-id")
STATIC = " ".join(
    ["The price list is reviewed every quarter and every SKU keeps a stable id."] * 350
)
SKU_SCHEMA = {
    "type": "object",
    "properties": {"sku": {"type": "string"}},
    "required": ["sku"],
    "additionalProperties": False,
}
TOOLS = [
    {"name": "get_price", "description": "Price of a SKU", "input_schema": SKU_SCHEMA},
    {"name": "get_stock", "description": "Stock of a SKU", "input_schema": SKU_SCHEMA},
]
TOOL_ANSWERS = {"get_price": "12.50", "get_stock": "7"}


def _headers(raw):
    return {k: v for k, v in raw.headers.items() if k.lower() in KEPT_HEADERS}


def _call(client, **params):
    raw = client.messages.with_raw_response.create(**params)
    message = raw.parse()
    fixture = {
        "status": raw.status_code,
        "headers": _headers(raw),
        "body": message.to_dict(mode="json", exclude_none=True),
    }
    return message, fixture


def renumber_tool_uses(fixture):
    blocks = [b for b in fixture["body"]["content"] if b.get("type") == "tool_use"]
    for n, block in enumerate(blocks, start=1):
        block["id"] = f"toolu_{n:02d}"
    return fixture


def _tool_loop(client):
    params = {"model": MODEL, "max_tokens": 300, "tools": TOOLS}
    question = "What is the price and stock of sku A1? Use both tools."
    messages = [{"role": "user", "content": question}]
    first, turn1 = _call(client, messages=messages, **params)
    answers = [
        {"type": "tool_result", "tool_use_id": b.id, "content": TOOL_ANSWERS[b.name]}
        for b in first.content
        if b.type == "tool_use"
    ]
    messages += [
        {
            "role": "assistant",
            "content": [b.to_dict(mode="json", exclude_none=True) for b in first.content],
        },
        {"role": "user", "content": answers},
    ]
    _, turn2 = _call(client, messages=messages, **params)
    return renumber_tool_uses(turn1), turn2


def _cache_pair(client):
    params = {
        "model": MODEL,
        "max_tokens": 16,
        "system": [{"type": "text", "text": STATIC, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "Say ok."}],
    }
    _, write = _call(client, **params)
    _, read = _call(client, **params)
    return write, read


def _stream(client):
    with client.messages.with_streaming_response.create(
        model=MODEL,
        max_tokens=60,
        messages=[{"role": "user", "content": "Describe sku A1 in one short sentence."}],
        stream=True,
    ) as raw:
        text = raw.read().decode()
        return {"status": raw.status_code, "headers": _headers(raw), "body_text": text}


def record(client) -> dict[str, dict]:
    turn1, turn2 = _tool_loop(client)
    write, read = _cache_pair(client)
    return {
        "loop_turn1": turn1,
        "loop_turn2": turn2,
        "cache_write": write,
        "cache_read": read,
        "stream_ok": _stream(client),
    }
