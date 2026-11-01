import httpx
import pytest
from acme_common.http import HttpError, RetryingHttpClient


def client(handler, attempts: int = 3):
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    c = RetryingHttpClient(
        transport=httpx.MockTransport(handler),
        max_attempts=attempts,
        sleep=fake_sleep,
        rng=lambda: 1.0,
        backoff_base_s=1.0,
        backoff_max_s=3.0,
    )
    return c, sleeps


async def test_retries_5xx_then_succeeds_with_backoff() -> None:
    codes = iter([503, 502, 200])
    c, sleeps = client(lambda r: httpx.Response(next(codes)))
    assert (await c.get("https://x.test/a")).status_code == 200
    assert sleeps == [1.0, 2.0]


async def test_exhausted_retries_raise_classified_error_without_url() -> None:
    c, _ = client(lambda r: httpx.Response(500))
    with pytest.raises(HttpError) as e:
        await c.get("https://secret-host.test/path?token=abc")
    assert e.value.kind == "http_500" and e.value.retryable
    assert "secret-host" not in str(e.value) and "abc" not in str(e.value)


async def test_4xx_fails_fast_and_is_returned() -> None:
    calls = 0

    def handler(r: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "invalid_scope"})

    c, _ = client(handler)
    assert (await c.post("https://x.test/t")).status_code == 400
    assert calls == 1


async def test_429_is_retried_honoring_retry_after() -> None:
    codes = iter([429, 200])

    def handler(r: httpx.Request) -> httpx.Response:
        code = next(codes)
        return httpx.Response(code, headers={"retry-after": "2"} if code == 429 else {})

    c, sleeps = client(handler)
    assert (await c.get("https://x.test")).status_code == 200
    assert sleeps == [2.0]


@pytest.mark.parametrize(
    ("exc", "kind"),
    [(httpx.ConnectTimeout("t"), "timeout"), (httpx.ConnectError("c"), "connection")],
)
async def test_timeout_and_connection_classification(exc: Exception, kind: str) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise exc

    c, _ = client(handler, attempts=2)
    with pytest.raises(HttpError) as e:
        await c.get("https://x.test")
    assert e.value.kind == kind
