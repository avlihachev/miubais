import httpx
from miubais.freshness.links import check, check_all, load_ignore


def make(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ok_link():
    http = make(lambda r: httpx.Response(200))
    result = check("https://a.com/x", http=http)
    assert result.ok and result.status == 200 and not result.redirected


def test_redirect_marks_redirected():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://a.com/new"})
        return httpx.Response(200)

    result = check("https://a.com/old", http=make(handler))
    assert result.ok and result.redirected and result.final_url == "https://a.com/new"


def test_trailing_slash_is_not_redirect():
    def handler(request):
        if request.url.path == "/x":
            return httpx.Response(301, headers={"location": "https://a.com/x/"})
        return httpx.Response(200)

    assert not check("https://a.com/x", http=make(handler)).redirected


def test_head_405_falls_back_to_get():
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(405 if request.method == "HEAD" else 200)

    assert check("https://a.com", http=make(handler)).ok
    assert methods == ["HEAD", "GET"]


def test_404_is_broken():
    result = check("https://a.com/gone", http=make(lambda r: httpx.Response(404)))
    assert not result.ok and result.status == 404


def test_exception_is_broken_with_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    result = check("https://a.com", http=make(handler))
    assert not result.ok and result.status is None and "refused" in result.error


def test_ignored_url(tmp_path):
    (tmp_path / ".freshignore").write_text("https://skip.example.com/*\n")
    ignore = load_ignore(tmp_path)
    result = check(
        "https://skip.example.com/a", http=make(lambda r: httpx.Response(500)), ignore=ignore
    )
    assert result.ok and result.status is None and result.error == "ignored"


def test_load_ignore_missing_file(tmp_path):
    assert load_ignore(tmp_path) == []


def test_check_all_preserves_order_and_dedupes():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200)

    urls = ["https://a.com/1", "https://a.com/2", "https://a.com/1"]
    results = check_all(urls, http=make(handler))
    assert [r.url for r in results] == urls
    assert sorted(seen) == ["https://a.com/1", "https://a.com/2"]
