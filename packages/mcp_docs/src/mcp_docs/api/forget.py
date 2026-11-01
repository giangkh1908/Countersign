"""`POST /internal/taint/forget {thread_id}`. Không phải tool, không nằm trong tools/list.

- Token user (`aud=docs-mcp`): `sub` lấy từ JWT, KHÔNG bao giờ từ body.
- Job retention (`azp=agent-maintenance`, scope `docs:forget`): body mang `sub` của chủ thread.
- Xoá khoá thread, không đụng `:recent`; khoá không tồn tại vẫn `204` (không dò được thread).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from acme_common.ports import Clock, EventSink, TokenVerifier
from acme_common.ports.errors import TokenInvalid, TokenServiceUnavailable
from acme_common.services.taint import forget_thread

PATH = "/internal/taint/forget"
MAINTENANCE_AZP = "agent-maintenance"
_MAX_BODY = 4096


class TaintForgetEndpoint:
    def __init__(
        self,
        *,
        verifier: TokenVerifier,
        audience: str,
        redis: Any | None,
        audit: EventSink,
        clock: Clock,
        allowed_azp: frozenset[str],
    ) -> None:
        self._verifier = verifier
        self._audience = audience
        self._redis = redis
        self._audit = audit
        self._clock = clock
        self._allowed_azp = allowed_azp

    @staticmethod
    async def _send(send: Any, status: int, body: dict[str, Any] | None = None) -> None:
        raw = json.dumps(body).encode() if body is not None else b""
        hdrs = [(b"content-length", str(len(raw)).encode())]
        if body is not None:
            hdrs.append((b"content-type", b"application/json"))
        await send({"type": "http.response.start", "status": status, "headers": hdrs})
        await send({"type": "http.response.body", "body": raw})

    @staticmethod
    async def _body(receive: Any) -> bytes | None:
        buf = b""
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return None
            buf += msg.get("body", b"")
            if len(buf) > _MAX_BODY:
                return None
            if not msg.get("more_body", False):
                return buf

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["method"] != "POST":
            await self._send(send, 405, {"error": "method_not_allowed"})
            return
        authz = next(
            (
                v.decode("latin-1")
                for k, v in scope.get("headers", ())
                if k.lower() == b"authorization"
            ),
            "",
        )
        scheme, _, token = authz.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            await self._send(send, 401, {"error": "unauthorized"})
            return
        try:
            p = await self._verifier.verify(token.strip(), self._audience)
        except TokenInvalid as e:
            await self._send(send, e.http_status, {"error": "invalid_token"})
            return
        except TokenServiceUnavailable:
            await self._send(send, 503, {"error": "token_service_unavailable"})
            return
        if p.azp not in self._allowed_azp:
            await self._send(send, 403, {"error": "invalid_token"})
            return

        raw = await self._body(receive)
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        thread_id = body.get("thread_id") if isinstance(body, dict) else None
        if (
            not isinstance(thread_id, str)
            or not 0 < len(thread_id) <= 128
            or not thread_id.isprintable()
            or thread_id == "recent"
        ):
            await self._send(send, 400, {"error": "invalid_argument"})
            return

        if p.azp == MAINTENANCE_AZP:
            owner = body.get("sub")
            if "docs:forget" not in p.scopes or not isinstance(owner, str) or not owner:
                await self._send(send, 403, {"error": "forbidden"})
                return
        else:
            if "docs:read" not in p.scopes:
                await self._send(send, 403, {"error": "forbidden"})
                return
            owner = p.sub  # sub chỉ từ JWT

        ok = self._redis is not None and await forget_thread(self._redis, owner, thread_id)
        await self._audit_write(p.azp, owner, thread_id, ok)
        if not ok:
            await self._send(send, 503, {"error": "upstream_unavailable"})
            return
        await self._send(send, 204)

    async def _audit_write(self, azp: str | None, owner: str, thread_id: str, ok: bool) -> None:
        record = {
            "event": "tool_audit",
            "ts": self._clock.now(),
            "request_id": None,
            "actor_type": "service",
            "actor_id": azp or "docs-mcp",
            "end_user_sub": owner,
            "action": "taint.forget",
            "resource": "taint",
            "decision": "allow" if ok else "error",
            "details": {"server": "docs-mcp", "thread_id": thread_id},
            "intent_id": None,
        }
        with contextlib.suppress(Exception):  # audit lỗi không làm hỏng việc xoá
            await asyncio.to_thread(self._audit.append, record, True)
