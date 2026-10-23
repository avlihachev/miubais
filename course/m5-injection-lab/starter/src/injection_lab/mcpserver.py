from pathlib import Path


class FixtureTokenVerifier:
    def __init__(self, tokens: Path, *, resource: str) -> None:
        raise NotImplementedError

    async def verify_token(self, token: str):
        raise NotImplementedError


def build(tokens: Path, *, resource: str, issuer: str, tickets: Path | None = None):
    raise NotImplementedError


def app(server, *, host: str = "127.0.0.1", gate: bool = True):
    raise NotImplementedError


def client_config(url: str, token: str) -> dict:
    raise NotImplementedError


def sdk_options(url: str, token: str, *, allow: list[str]):
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
