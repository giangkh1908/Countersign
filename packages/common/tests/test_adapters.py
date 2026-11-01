import json
import logging

from acme_common.adapters.in_memory_rate_limiter import InMemoryRateLimiter
from acme_common.adapters.json_log_event_sink import JsonLogEventSink
from acme_common.adapters.system_clock import SystemClock
from acme_common.log import JsonFormatter, bind_request_id, reset_request_id
from acme_common.testing import FakeClock


def test_system_clock_is_aware_utc() -> None:
    c = SystemClock()
    assert c.now().tzinfo is not None and c.monotonic() <= c.monotonic()


async def test_rate_limiter_bucket_refills_with_clock() -> None:
    clock = FakeClock()
    rl = InMemoryRateLimiter(clock)
    assert (await rl.reserve("k", 60, limit=60, window_s=60)).allowed
    denied = await rl.reserve("k", 10, limit=60, window_s=60)
    assert not denied.allowed and denied.retry_after_s == 10
    clock.advance(10)
    assert (await rl.reserve("k", 10, limit=60, window_s=60)).allowed
    await rl.settle("k", reserved=10, actual=0)  # hoàn lại
    assert (await rl.reserve("k", 10, limit=60, window_s=60)).allowed


async def test_rate_limiter_slots() -> None:
    rl = InMemoryRateLimiter(FakeClock())
    assert (await rl.acquire_slot("k", 2)).allowed
    assert (await rl.acquire_slot("k", 2)).allowed
    assert not (await rl.acquire_slot("k", 2)).allowed
    await rl.release_slot("k")
    assert (await rl.acquire_slot("k", 2)).allowed


def test_event_sink_and_formatter_emit_json_without_secrets(caplog) -> None:
    sink = JsonLogEventSink()
    with caplog.at_level(logging.INFO, logger="acme.events"):
        tok = bind_request_id("req-1")
        try:
            sink.append({"event": "usage", "prompt_tokens": 5, "access_token": "SECRET"}, sync=True)
        finally:
            reset_request_id(tok)
    line = json.loads(JsonFormatter("svc").format(caplog.records[0]))
    # request_id gắn lúc format; ở đây format sau reset nên không có, kiểm riêng bên dưới
    assert line["service"] == "svc" and line["prompt_tokens"] == 5 and line["sync"] is True
    assert line["access_token"] == "[redacted]" and "SECRET" not in json.dumps(line)


def test_formatter_includes_request_id_from_contextvar() -> None:
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    tok = bind_request_id("req-42")
    try:
        out = json.loads(JsonFormatter().format(rec))
    finally:
        reset_request_id(tok)
    assert out["request_id"] == "req-42" and out["msg"] == "hello"
