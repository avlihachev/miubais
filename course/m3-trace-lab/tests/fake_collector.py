import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Self

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

TRACES_PATH = "/api/public/otel/v1/traces"


class FakeCollector:
    def __init__(self, status: int = 200, *, ok_first: int = 0) -> None:
        self.status = status
        self.ok_first = ok_first
        self.received: list[tuple[dict, ExportTraceServiceRequest]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        collector = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path != TRACES_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return
                request = ExportTraceServiceRequest()
                request.ParseFromString(body)
                collector.received.append((dict(self.headers), request))
                payload = ExportTraceServiceResponse().SerializeToString()
                ok = len(collector.received) <= collector.ok_first
                self.send_response(200 if ok else collector.status)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args) -> None:
                pass

        return Handler

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
