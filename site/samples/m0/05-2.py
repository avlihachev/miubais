import json

from pydantic import BaseModel, ValidationError

WRITE_FILE = {
    "name": "write_file",
    "description": "Write a whole file to the workspace.",
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}


class WriteFile(BaseModel):
    path: str
    content: str


def error_result(tool_use_id: str, payload: dict) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(payload),
        "is_error": True,
    }


def tool_result(tool_use_id: str, raw_input: str) -> dict:
    try:
        args = WriteFile.model_validate(json.loads(raw_input))
    except json.JSONDecodeError:
        return error_result(tool_use_id, {"INVALID_JSON": raw_input})
    except ValidationError as exc:
        return error_result(
            tool_use_id, {"INVALID_INPUT": [f"{e['loc'][0]}: {e['msg']}" for e in exc.errors()]}
        )
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": f"wrote {len(args.content)} chars to {args.path}",
    }


print(tool_result("toolu_01", '{"path": "app.py", "content": "print(1)\\n"}'))
print(tool_result("toolu_02", '{"path": "app.py", "content": "print(1'))
print(tool_result("toolu_03", '{"path": "app.py"}'))
