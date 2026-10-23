from collections.abc import Iterable, Mapping

from harnesskit.testing import Timed
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.util.types import AttributeValue

from trace_lab.types import RunTrace


def record_run(
    timed: Iterable[Timed],
    *,
    ticket_id: str,
    tracer_provider: TracerProvider,
    agent_name: str = "ticket-runner",
    attributes: Mapping[str, AttributeValue] | None = None,
    epoch_ns: int | None = None,
) -> RunTrace:
    raise NotImplementedError


def provider_for_tests() -> tuple[TracerProvider, InMemorySpanExporter]:
    raise NotImplementedError
