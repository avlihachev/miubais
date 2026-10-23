from serving_lab.types import RequestResult, RunResult, Summary


def percentile(values: list[float], p: float) -> float:
    raise NotImplementedError


def summarise(requests: list[RequestResult], wall_s: float) -> Summary:
    raise NotImplementedError


async def run_async(
    base_url: str,
    *,
    model: str,
    prompts: list[str],
    concurrency: int,
    max_tokens: int,
    timeout_s: float = 60,
    extra_body: dict | None = None,
) -> RunResult:
    raise NotImplementedError


def run(
    base_url: str,
    *,
    model: str,
    prompts: list[str],
    concurrency: int,
    max_tokens: int,
    timeout_s: float = 60,
    extra_body: dict | None = None,
) -> RunResult:
    raise NotImplementedError


def to_markdown(summary: Summary) -> str:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
