from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatch
from pathlib import Path

import httpx
from pydantic import BaseModel

TIMEOUT = 10
GET_FALLBACK = {405, 403, 501}


class LinkStatus(BaseModel):
    url: str
    status: int | None = None
    final_url: str | None = None
    ok: bool
    redirected: bool = False
    error: str | None = None


def load_ignore(root: Path) -> list[str]:
    path = root / ".freshignore"
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def _request(http: httpx.Client, url: str) -> httpx.Response:
    try:
        response = http.head(url, follow_redirects=True, timeout=TIMEOUT)
        if response.status_code not in GET_FALLBACK:
            return response
    except httpx.HTTPError:
        pass
    return http.get(url, follow_redirects=True, timeout=TIMEOUT)


def check(url: str, *, http: httpx.Client, ignore: list[str] | None = None) -> LinkStatus:
    if any(fnmatch(url, pattern) for pattern in ignore or []):
        return LinkStatus(url=url, ok=True, error="ignored")
    try:
        response = _request(http, url)
    except httpx.HTTPError as exc:
        return LinkStatus(url=url, ok=False, error=f"{type(exc).__name__}: {exc}")
    final = str(response.url)
    return LinkStatus(
        url=url,
        status=response.status_code,
        final_url=final,
        ok=response.status_code < 400,
        redirected=final.rstrip("/") != url.rstrip("/"),
    )


def check_all(
    urls: list[str],
    *,
    http: httpx.Client,
    concurrency: int = 8,
    ignore: list[str] | None = None,
) -> list[LinkStatus]:
    unique = list(dict.fromkeys(urls))
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = dict(zip(unique, pool.map(lambda u: check(u, http=http, ignore=ignore), unique)))
    return [results[u] for u in urls]
