import functools
from typing import Any

import claude_agent_sdk

MESSAGE = "live call under offline grading"


def refuse(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError(MESSAGE)


async def refuse_async(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError(MESSAGE)


def _guard_client(cls: type) -> None:
    original = cls.__init__
    if getattr(original, "__offline_guard__", False):
        return

    @functools.wraps(original)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        # a client on an injected http_client (a recorded transport) cannot reach the network
        if kwargs.get("http_client") is None:
            raise RuntimeError(MESSAGE)
        original(self, *args, **kwargs)

    __init__.__offline_guard__ = True
    cls.__init__ = __init__


def install() -> None:
    claude_agent_sdk.query = refuse
    claude_agent_sdk.ClaudeSDKClient.connect = refuse_async
    try:
        import anthropic
    except ImportError:
        return
    _guard_client(anthropic.Anthropic)
    _guard_client(anthropic.AsyncAnthropic)


install()


def pytest_configure(config: Any) -> None:
    install()
