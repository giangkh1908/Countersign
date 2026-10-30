import asyncio
from typing import Any

import pytest
from acme_common.mcp import CallerContext, ToolError, ToolInvoker, ToolOutput
from acme_common.mcp.context import AuthContext, reset_auth, set_auth
from acme_common.mcp.tool_invoker import truncate_output
from acme_common.ports import Principal, ToolSpec
from acme_common.testing import FakeClock, FakeEventSink, FakeRateLimiter

SCHEMA = {
    "type": "object",
    "properties": {"n": {"type": "integer", "minimum": 0}},
    "required": ["n"],
    "additionalProperties": False,
}


def principal(scopes=("docs:read",)) -> Principal:
    return Principal(
        sub="u1", audience=("docs-mcp",), azp="agent-service", scopes=frozenset(scopes),
        expires_at=9e9, dept=("CS",), clearance=1,
    )  # fmt: skip


class Rig:
    def __init__(self, **spec_kw: Any) -> None:
        self.sink, self.limiter, self.clock = FakeEventSink(), FakeRateLimiter(), FakeClock()
        self.inv = ToolInvoker(
            server="docs-mcp", limiter=self.limiter, audit=self.sink, clock=self.clock,
            audit_sync=False,
        )  # fmt: skip
        self.spec = ToolSpec(
            name="t", description="d", input_schema=SCHEMA, required_scopes=("docs:read",),
            **spec_kw,
        )  # fmt: skip
        self.calls = 0

    def raw(self, fn):
        async def handler(ctx: CallerContext, args: dict[str, Any]):
            self.calls += 1
            return await fn(ctx, args)

        return self.inv.wrap(self.spec, handler)

    async def call(self, fn, args, *, scopes=("docs:read",), meta=None):
        tok = set_auth(AuthContext(principal(scopes), "11111111-1111-1111-1111-111111111111"))
        try:
            return await self.raw(fn)(args, meta or {})
        finally:
            reset_auth(tok)


async def ok(ctx, args):
    return {"v": args["n"]}


async def test_success_audited_allow() -> None:
    r = Rig()
    res = await r.call(ok, {"n": 1}, meta={"io.acme/thread_id": "T"})
    assert not res.is_error and res.data == {"v": 1}
    ev = r.sink.events[0]
    assert ev["decision"] == "allow" and ev["details"]["thread_id"] == "T"
    assert ev["actor_id"] == "agent-service" and ev["end_user_sub"] == "u1"
    assert "args_sha256" in ev["details"] and "n" not in ev["details"]


@pytest.mark.parametrize("args", [{}, {"n": "x"}, {"n": 1, "user_id": "evil"}, {"n": -1}])
async def test_bad_schema(args) -> None:
    r = Rig()
    res = await r.call(ok, args)
    assert res.is_error and res.data["code"] == "invalid_argument" and r.calls == 0
    assert "evil" not in str(res.data)
    assert r.sink.events[0]["decision"] == "error"


async def test_missing_scope_forbidden() -> None:
    r = Rig()
    res = await r.call(ok, {"n": 1}, scopes=("tickets:read",))
    assert res.data["code"] == "forbidden" and r.calls == 0
    assert r.sink.events[0]["decision"] == "deny"


async def test_rate_limited_retryable() -> None:
    r = Rig()
    r.limiter.deny_keys.add("mcp:rl:docs-mcp:u1")
    res = await r.call(ok, {"n": 1})
    assert res.data["code"] == "rate_limited" and res.data["retryable"] is True
    assert res.data["details"]["retry_after_s"] >= 1 and r.calls == 0
    assert r.sink.events[0]["decision"] == "deny"


async def test_rate_limit_uses_cost_per_user() -> None:
    r = Rig(cost=5)
    r.inv._capacity = 10  # noqa: SLF001
    assert not (await r.call(ok, {"n": 1})).is_error
    assert not (await r.call(ok, {"n": 1})).is_error
    assert (await r.call(ok, {"n": 1})).data["code"] == "rate_limited"
    assert r.limiter.used["mcp:rl:docs-mcp:u1"] == 10


async def test_timeout_maps_to_configured_code() -> None:
    async def slow(ctx, args):
        await asyncio.sleep(1)

    r = Rig(timeout_s=0.05)
    res = await r.call(slow, {"n": 1})
    assert res.data["code"] == "upstream_unavailable" and res.data["retryable"] is True
    r2 = Rig(timeout_s=0.05, timeout_code="query_timeout")
    assert (await r2.call(slow, {"n": 1})).data["code"] == "query_timeout"
    assert r.sink.events[0]["details"]["error_code"] == "upstream_unavailable"


async def test_output_truncated_by_elements() -> None:
    async def big(ctx, args):
        return ToolOutput(
            {"results": [{"t": "x" * 200} for _ in range(100)]}, {"rows_returned": 100}
        )

    r = Rig(max_output_bytes=2000)
    res = await r.call(big, {"n": 1})
    assert not res.is_error and res.data["truncated"] is True
    assert 0 < len(res.data["results"]) < 100
    assert len(res.data["results"]) + res.data["omitted"] == 100
    d = r.sink.events[0]["details"]
    assert d["truncated"] is True and d["rows_returned"] == 100 and d["bytes_out"] <= 2000


def test_long_string_capped_and_unfittable_errors() -> None:
    data, trunc, _ = truncate_output({"s": "é" * 5000}, 32_768)
    assert not trunc and len(data["s"].encode()) <= 4096
    with pytest.raises(ToolError) as e:
        truncate_output({"a": "x" * 4000, "b": "y" * 4000}, 100)
    assert e.value.code == "internal_error"


async def test_handler_toolerror_and_crash_normalised() -> None:
    async def nf(ctx, args):
        raise ToolError("not_found", "no such ticket")

    async def boom(ctx, args):
        raise RuntimeError("secret-db-password")

    r = Rig()
    assert (await r.call(nf, {"n": 1})).data["code"] == "not_found"
    res = await r.call(boom, {"n": 1})
    assert res.data["code"] == "internal_error" and "secret" not in str(res.data)


async def test_no_principal_unauthorized() -> None:
    r = Rig()
    res = await r.raw(ok)({"n": 1}, {})
    assert res.data["code"] == "unauthorized"


async def test_audit_failure_does_not_break_call() -> None:
    r = Rig()

    def bad(record, sync=False):
        raise OSError("db down")

    r.sink.append = bad  # type: ignore[method-assign]
    res = await r.call(ok, {"n": 1})
    assert not res.is_error and r.inv.audit_failures == 1


async def test_intent_id_goes_to_column_not_details() -> None:
    async def w(ctx, args):
        return ToolOutput({"x": 1}, {"intent_id": "22222222-2222-2222-2222-222222222222"})

    r = Rig()
    await r.call(w, {"n": 1})
    ev = r.sink.events[0]
    assert ev["intent_id"] == "22222222-2222-2222-2222-222222222222"
    assert "intent_id" not in ev["details"]
