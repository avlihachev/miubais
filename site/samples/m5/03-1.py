import base64
import json

from injection_lab_lessons import minimal_env, toy_scrub

fake_key = "sk-ant-api03-" + "EXAMPLE" * 3
blob = base64.b64encode(f"ANTHROPIC_API_KEY={fake_key}".encode()).decode()
outputs = [
    f"ANTHROPIC_API_KEY={fake_key}",
    "aws_access_key_id = AKIAIOSFODNN7EXAMPLE",
    "curl -H 'Authorization: Bearer not-a-real-token-123' https://api.example.invalid",
    json.dumps({"log": json.dumps({"GITHUB_TOKEN": "ghp_" + "0" * 36})}),
    f"cache entry: {blob}",
    "GET /search?token=page2&sort=asc 200",
]
for text in outputs:
    red = toy_scrub(text)
    print(red.text[:72], red.counts)

parent = {"PATH": "/usr/bin", "HOME": "/home/dev", "AWS_SECRET_ACCESS_KEY": "fake", "CI": "1"}
print("subprocess env:", sorted(minimal_env(parent, {"PYTHONHASHSEED": "0"})))
