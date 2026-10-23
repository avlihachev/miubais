import tempfile
from pathlib import Path

from harness_lab_lessons import EffectLog

calls = []


def post_pr_comment() -> str:
    calls.append("POST /pulls/17/comments")
    return "comment 9001"


def flaky_deploy() -> str:
    raise ConnectionError("connection reset after the request was sent")


def show(label: str, effect) -> None:
    print(f"{label:<26} ran={effect.ran!s:<5} state={effect.state} outcome={effect.outcome}")


with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "effects.sqlite"
    log = EffectLog(db)
    for label in ("first call", "retry in the same process"):
        show(label, log.claim_then_run("001-discount-rounding:pr-comment", post_pr_comment))
    log.close()

    log = EffectLog(db)
    show("after a restart", log.claim_then_run("001-discount-rounding:pr-comment", post_pr_comment))
    print("side effect executed once" if len(calls) == 1 else f"executed {len(calls)} times")

    try:
        log.claim_then_run("001-discount-rounding:deploy", flaky_deploy)
    except ConnectionError as err:
        print("deploy raised:", err)
    show("deploy retry", log.claim_then_run("001-discount-rounding:deploy", flaky_deploy))
    log.close()
