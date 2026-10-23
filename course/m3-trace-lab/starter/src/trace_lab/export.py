from pathlib import Path

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter

from trace_lab.cost import Prices
from trace_lab.types import ExportSummary


def langfuse_headers(public_key: str, secret_key: str) -> dict[str, str]:
    raise NotImplementedError


def langfuse_exporter(
    base_url: str, public_key: str, secret_key: str, *, timeout: float = 5.0
) -> OTLPSpanExporter:
    raise NotImplementedError


def provider(exporter: SpanExporter, *, batch: bool = True) -> TracerProvider:
    raise NotImplementedError


def export_runs(
    runs_dir: Path,
    *,
    base_url: str,
    public_key: str,
    secret_key: str,
    prices: Prices,
    timeout: float = 5.0,
) -> ExportSummary:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
