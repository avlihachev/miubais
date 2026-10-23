from capstone.types import Finding, Reconciled, VerifyResult


def only_touched(findings: list[Finding], changed: list[str]) -> list[Finding]:
    raise NotImplementedError


def dedupe(findings: list[Finding]) -> list[Finding]:
    raise NotImplementedError


def threshold(findings: list[Finding], min_confidence: float = 0.6) -> list[Finding]:
    raise NotImplementedError


def reconcile(findings: list[Finding], summary: str, verify: VerifyResult | None) -> Reconciled:
    raise NotImplementedError


def clean(
    findings: list[Finding], changed: list[str], min_confidence: float = 0.6
) -> list[Finding]:
    raise NotImplementedError
