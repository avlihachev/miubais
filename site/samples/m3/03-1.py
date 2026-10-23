import base64

from trace_lab_lessons import langfuse_headers, observations_url, otlp_traces_endpoint

PUBLIC_KEY = "pk-lf-example"
SECRET_KEY = "sk-lf-example"

print("POST", otlp_traces_endpoint("http://localhost:3000/"))
headers = langfuse_headers(PUBLIC_KEY, SECRET_KEY)
for name, value in headers.items():
    print(f"  {name}: {value}")

token = headers["Authorization"].removeprefix("Basic ")
print("  decoded:", base64.b64decode(token).decode())
print("GET ", observations_url("http://localhost:3000", "c6339da141692f1f040f1de64e41c859"))
