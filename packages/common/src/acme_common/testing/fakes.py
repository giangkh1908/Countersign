"""`Fake<Port>`: kế thừa port tường minh, dùng cho test nghiệp vụ (contracts §9.1 mục 9)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from ..ports.clock import Clock
from ..ports.errors import TokenExchangeDenied, TokenInvalid
from ..ports.event_sink import EventRecord, EventSink
from ..ports.rate_limiter import RateLimiter
from ..ports.token_broker import TokenBroker
from ..ports.token_verifier import TokenVerifier
from ..ports.tool_server_host import ASGIApp, RawToolHandler, ToolResult, ToolServerHost, ToolSpec
from ..ports.types import AccessToken, LimitDecision, Principal


class FakeClock(Clock):
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._mono = 1000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds


class FakeTokenVerifier(TokenVerifier):
    """Token -> Principal đăng ký sẵn; token lạ => `TokenInvalid('malformed')`."""

    def __init__(self, principals: dict[str, Principal] | None = None) -> None:
        self.principals = dict(principals or {})
        self.calls: list[tuple[str, str]] = []

    def add(self, token: str, principal: Principal) -> None:
        self.principals[token] = principal

    async def verify(self, token: str, audience: str) -> Principal:
        self.calls.append((token, audience))
        principal = self.principals.get(token)
        if principal is None:
            raise TokenInvalid("malformed")
        if audience not in principal.audience:
            raise TokenInvalid("bad_audience")
        return principal


class FakeTokenBroker(TokenBroker):
    """Cấp token giả `fake:<audience>:<n>`; `deny` là tập audience bị từ chối."""

    def __init__(
        self,
        clock: Clock | None = None,
        *,
        ttl_s: float = 300.0,
        deny: Iterable[str] = (),
    ) -> None:
        self._clock = clock or FakeClock()
        self._ttl = ttl_s
        self.deny = set(deny)
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []  # (sub, audience, scopes)

    async def token_for(
        self,
        principal: Principal,
        user_token: str,
        audience: str,
        scopes: Sequence[str],
    ) -> AccessToken:
        self.calls.append((principal.sub, audience, tuple(sorted(scopes))))
        if audience in self.deny:
            raise TokenExchangeDenied("invalid_scope", http_status=400)
        return AccessToken(
            value=f"fake:{audience}:{len(self.calls)}",
            audience=audience,
            scopes=frozenset(scopes),
            expires_at=self._clock.now().timestamp() + self._ttl,
            sub=principal.sub,
        )


class FakeEventSink(EventSink):
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.sync_flags: list[bool] = []
        self.flushed = 0

    def append(self, record: EventRecord, sync: bool = False) -> None:
        self.events.append(dict(record))
        self.sync_flags.append(sync)

    async def flush(self, timeout_s: float = 5.0) -> None:
        self.flushed += 1


class FakeRateLimiter(RateLimiter):
    """Đếm đơn giản, không nạp lại theo thời gian; `deny_keys` luôn bị từ chối."""

    def __init__(self, deny_keys: Iterable[str] = ()) -> None:
        self.deny_keys = set(deny_keys)
        self.used: dict[str, int] = {}
        self.slots: dict[str, int] = {}

    async def reserve(
        self, key: str, cost: int, *, limit: int, window_s: float = 60.0
    ) -> LimitDecision:
        used = self.used.get(key, 0)
        if key in self.deny_keys or used + cost > limit:
            return LimitDecision(False, max(0, limit - used), window_s)
        self.used[key] = used + cost
        return LimitDecision(True, limit - used - cost)

    async def settle(self, key: str, reserved: int, actual: int) -> None:
        self.used[key] = max(0, self.used.get(key, 0) - reserved + actual)

    async def acquire_slot(self, key_id: str, max_slots: int) -> LimitDecision:
        n = self.slots.get(key_id, 0)
        if key_id in self.deny_keys or n >= max_slots:
            return LimitDecision(False, 0.0, 1.0)
        self.slots[key_id] = n + 1
        return LimitDecision(True, float(max_slots - n - 1))

    async def release_slot(self, key_id: str) -> None:
        self.slots[key_id] = max(0, self.slots.get(key_id, 0) - 1)


class FakeToolServerHost(ToolServerHost):
    """Host giả: lưu handler, `call()` gọi thẳng (không qua giao thức MCP, không auth)."""

    def __init__(self) -> None:
        self.tools: dict[str, tuple[ToolSpec, RawToolHandler]] = {}

    def register(self, spec: ToolSpec, handler: RawToolHandler) -> None:
        if spec.name in self.tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        self.tools[spec.name] = (spec, handler)

    def asgi_app(self) -> ASGIApp:
        async def app(scope, receive, send):  # type: ignore[no-untyped-def]
            if scope["type"] == "http":
                await send({"type": "http.response.start", "status": 204, "headers": []})
                await send({"type": "http.response.body", "body": b""})

        return app

    def tool_manifest(self) -> list[dict[str, object]]:
        return [
            {"name": s.name, "description": s.description, "inputSchema": dict(s.input_schema)}
            for s, _ in self.tools.values()
        ]

    async def call(
        self, name: str, arguments: Mapping[str, object], meta: Mapping[str, object] | None = None
    ) -> ToolResult:
        return await self.tools[name][1](arguments, meta or {})
