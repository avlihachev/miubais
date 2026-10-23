import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self

DEFAULT_MAX_TOKENS = 16


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


class FakeOpenAIServer:
    def __init__(
        self,
        *,
        tokens_per_second: float = 50,
        queue_delay_ms: int = 0,
        first_token_ms: int = 20,
        max_concurrent: int = 4,
        model: str = "fake-7b",
        fail_after_tokens: int | None = None,
        fail_status: int | None = None,
        healthy: bool = True,
        health_delay_ms: int = 0,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.tokens_per_second = tokens_per_second
        self.queue_delay_ms = queue_delay_ms
        self.first_token_ms = first_token_ms
        self.model = model
        self.fail_after_tokens = fail_after_tokens
        self.fail_status = fail_status
        self.healthy = healthy
        self.health_delay_ms = health_delay_ms
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()
        self._seen_prompts: set[str] = set()
        self.counters = {
            "running": 0,
            "waiting": 0,
            "ttft_count": 0,
            "ttft_sum": 0.0,
            "e2e_count": 0,
            "e2e_sum": 0.0,
            "prefix_hits": 0,
            "prefix_queries": 0,
        }
        self.server = _Server((host, port), _handler(self))
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def base_url(self) -> str:
        return f"{self.url}/v1"

    def start(self) -> Self:
        self.thread.start()
        return self

    def stop(self) -> None:
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _bump(self, **deltas: float) -> None:
        with self._lock:
            for key, delta in deltas.items():
                self.counters[key] += delta

    def metrics_text(self) -> str:
        with self._lock:
            c = dict(self.counters)
        labels = f'{{model_name="{self.model}"}}'
        rows = [
            ("gauge", "vllm:num_requests_running", c["running"]),
            ("gauge", "vllm:num_requests_waiting", c["waiting"]),
            ("histogram", "vllm:time_to_first_token_seconds_count", c["ttft_count"]),
            (None, "vllm:time_to_first_token_seconds_sum", c["ttft_sum"]),
            ("histogram", "vllm:e2e_request_latency_seconds_count", c["e2e_count"]),
            (None, "vllm:e2e_request_latency_seconds_sum", c["e2e_sum"]),
            ("counter", "vllm:prefix_cache_hits_total", c["prefix_hits"]),
            ("counter", "vllm:prefix_cache_queries_total", c["prefix_queries"]),
        ]
        lines = []
        for kind, name, value in rows:
            if kind is not None:
                base = name.removesuffix("_count").removesuffix("_total")
                lines.append(f"# TYPE {base} {kind}")
            lines.append(f"{name}{labels} {value}")
        return "\n".join(lines) + "\n"

    def _admit(self, prompt: str) -> float:
        received = time.perf_counter()
        prompt_tokens = len(prompt.split())
        with self._lock:
            self.counters["waiting"] += 1
            self.counters["prefix_queries"] += prompt_tokens
            if prompt in self._seen_prompts:
                self.counters["prefix_hits"] += prompt_tokens
            self._seen_prompts.add(prompt)
        time.sleep(self.queue_delay_ms / 1000)
        self._slots.acquire()
        self._bump(waiting=-1, running=1)
        return received

    def _release(self, received: float) -> None:
        self._slots.release()
        self._bump(running=-1, e2e_count=1, e2e_sum=time.perf_counter() - received)

    def _tokens(self, received: float, max_tokens: int):
        start = time.perf_counter() + self.first_token_ms / 1000
        limit = max_tokens if self.fail_after_tokens is None else self.fail_after_tokens
        for i in range(min(max_tokens, limit)):
            delay = start + i / self.tokens_per_second - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            if i == 0:
                self._bump(ttft_count=1, ttft_sum=time.perf_counter() - received)
            yield f"tok{i + 1}" if i == 0 else f" tok{i + 1}"


def _handler(fake: FakeOpenAIServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                time.sleep(fake.health_delay_ms / 1000)
                self._send(200 if fake.healthy else 503, b"", "text/plain")
            elif self.path == "/metrics":
                self._send(200, fake.metrics_text().encode(), "text/plain; version=0.0.4")
            elif self.path == "/v1/models":
                model = {"id": fake.model, "object": "model", "owned_by": "miubais"}
                self._json(200, {"object": "list", "data": [model]})
            else:
                self._json(404, _error(f"no route {self.path}", "not_found"))

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self._json(404, _error(f"no route {self.path}", "not_found"))
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                prompt = " ".join(str(m.get("content", "")) for m in body["messages"])
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                self._json(400, _error(f"bad request: {exc}", "invalid_request_error"))
                return
            if body.get("model") != fake.model:
                self._json(404, _error(f"model {body.get('model')!r} not found", "not_found"))
                return
            if fake.fail_status is not None:
                self._json(fake.fail_status, _error("injected failure", "server_error"))
                return
            max_tokens = int(body.get("max_tokens") or DEFAULT_MAX_TOKENS)
            received = fake._admit(prompt)
            try:
                if body.get("stream"):
                    self._stream(body, prompt, received, max_tokens)
                else:
                    self._complete(prompt, received, max_tokens)
            finally:
                fake._release(received)

        def _complete(self, prompt: str, received: float, max_tokens: int) -> None:
            text = "".join(fake._tokens(received, max_tokens))
            tokens = len(text.split())
            message = {"role": "assistant", "content": text}
            choice = {"index": 0, "message": message, "finish_reason": "length"}
            payload = _envelope("chat.completion", fake.model, [choice])
            payload["usage"] = _usage(prompt, tokens)
            self._json(200, payload)

        def _stream(self, body: dict, prompt: str, received: float, max_tokens: int) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

            def chunk(choices: list[dict], **extra: Any) -> None:
                payload = _envelope("chat.completion.chunk", fake.model, choices, completion_id)
                self._event(json.dumps(payload | extra))

            chunk([{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}])
            sent = 0
            for token in fake._tokens(received, max_tokens):
                chunk([{"index": 0, "delta": {"content": token}, "finish_reason": None}])
                sent += 1
            if fake.fail_after_tokens is not None and sent >= fake.fail_after_tokens:
                return
            chunk([{"index": 0, "delta": {}, "finish_reason": "length"}])
            if (body.get("stream_options") or {}).get("include_usage"):
                chunk([], usage=_usage(prompt, sent))
            self._event("[DONE]")

        def _event(self, data: str) -> None:
            self.wfile.write(f"data: {data}\n\n".encode())
            self.wfile.flush()

        def _json(self, status: int, body: dict) -> None:
            self._send(status, json.dumps(body).encode(), "application/json")

        def _send(self, status: int, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def _envelope(obj: str, model: str, choices: list[dict], completion_id: str = "") -> dict:
    return {
        "id": completion_id or f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": obj,
        "created": int(time.time()),
        "model": model,
        "choices": choices,
    }


def _usage(prompt: str, completion_tokens: int) -> dict:
    prompt_tokens = len(prompt.split())
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _error(message: str, kind: str) -> dict:
    return {"error": {"message": message, "type": kind}}
