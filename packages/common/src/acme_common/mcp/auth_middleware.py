"""`AuthMiddleware` ASGI bọc `ToolServerHost.asgi_app()` (ADR-003, 02 §1.4).

Không dùng auth của SDK. Thứ tự: Origin -> đường dẫn công khai -> Bearer -> `TokenVerifier` -> azp ->
đọc body (<=256 KiB, một JSON-RPC object) -> scope của tool (nếu `tools/call`) -> đặt contextvar.
Rate limit nằm ở `ToolInvoker` (theo user, có audit), không ở đây.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Collection, Sequence
from typing import Any

from ..ports.errors import TokenInvalid, TokenServiceUnavailable
from ..ports.token_verifier import TokenVerifier
from .context import AuthContext, reset_auth, set_auth

Scope = dict[str, Any]
Receive = Callable[[], Any]
Send = Callable[[dict[str, Any]], Any]

_PRM_PREFIX = "/.well-known/oauth-protected-resource"


class _Reject(Exception):
    def __init__(self, status: int, error: str, **extra: Any) -> None:
        self.status, self.error, self.extra = status, error, extra


class AuthMiddleware:
    def __init__(
        self,
        app: Any,
        *,
        verifier: TokenVerifier,
        audience: str,
        resource_url: str | None = None,
        authorization_servers: Sequence[str] = (),
        scopes_supported: Sequence[str] = (),
        allowed_azp: Collection[str] = (),
        allowed_origins: Collection[str] = (),
        required_scopes_for: Callable[[str], Sequence[str] | None] | None = None,
        mcp_path: str = "/mcp",
        health_path: str = "/healthz",
        max_body_bytes: int = 262_144,
    ) -> None:
        self.app = app
        self.verifier = verifier
        self.audience = audience
        self.resource_url = resource_url
        self.authorization_servers = tuple(authorization_servers)
        self.scopes_supported = tuple(scopes_supported)
        self.allowed_azp = frozenset(allowed_azp)
        self.allowed_origins = frozenset(allowed_origins)
        self.required_scopes_for = required_scopes_for
        self.mcp_path = mcp_path
        self.health_path = health_path
        self.max_body_bytes = max_body_bytes

    # --- helpers ---
    @property
    def _prm_url(self) -> str | None:
        return f"{self.resource_url.rstrip('/')}{_PRM_PREFIX}" if self.resource_url else None

    def _challenge(self, error: str | None, description: str | None, scope: str | None) -> str:
        parts: list[str] = []
        if error:
            parts.append(f'error="{error}"')
        if description:
            parts.append(f'error_description="{description}"')
        if scope:
            parts.append(f'scope="{scope}"')
        if self._prm_url:
            parts.append(f'resource_metadata="{self._prm_url}"')
        return "Bearer " + ", ".join(parts) if parts else "Bearer"

    @staticmethod
    async def _respond(
        send: Send, status: int, body: dict[str, Any], headers: dict[str, str] | None = None
    ) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
        hdrs += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        await send({"type": "http.response.start", "status": status, "headers": hdrs})
        await send({"type": "http.response.body", "body": raw})

    @staticmethod
    def _header(scope: Scope, name: bytes) -> str | None:
        for k, v in scope.get("headers", ()):
            if k.lower() == name:
                return v.decode("latin-1")
        return None

    async def _read_body(self, receive: Receive) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                raise _Reject(400, "client_disconnected")
            chunk = msg.get("body", b"")
            size += len(chunk)
            if size > self.max_body_bytes:
                raise _Reject(413, "body_too_large")
            chunks.append(chunk)
            if not msg.get("more_body", False):
                return b"".join(chunks)

    # --- ASGI ---
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, method = scope["path"], scope["method"]
        if path == self.health_path:
            await self._respond(send, 200, {"status": "ok"})
            return
        if path.startswith(_PRM_PREFIX) and method == "GET":
            doc = {
                "resource": self.resource_url or self.audience,
                "authorization_servers": list(self.authorization_servers),
                "scopes_supported": list(self.scopes_supported),
                "bearer_methods_supported": ["header"],
            }
            await self._respond(send, 200, doc)
            return
        if path != self.mcp_path:
            await self._respond(send, 404, {"error": "not_found"})
            return
        if method != "POST":
            await self._respond(send, 405, {"error": "method_not_allowed"}, {"Allow": "POST"})
            return

        try:
            principal_ctx, replay = await self._authenticate(scope, receive)
        except _Reject as r:
            headers: dict[str, str] = {}
            if r.status in (401, 403) and "challenge" in r.extra:
                headers["WWW-Authenticate"] = r.extra["challenge"]
            if r.status == 503:
                headers["Retry-After"] = "5"
            await self._respond(send, r.status, {"error": r.error}, headers)
            return

        token = set_auth(principal_ctx)
        try:
            await self.app(scope, replay, send)
        finally:
            reset_auth(token)

    async def _authenticate(self, scope: Scope, receive: Receive) -> tuple[AuthContext, Receive]:
        origin = self._header(scope, b"origin")
        if origin is not None and origin not in self.allowed_origins:
            raise _Reject(403, "bad_origin")

        authz = self._header(scope, b"authorization") or ""
        scheme, _, token = authz.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise _Reject(401, "unauthorized", challenge=self._challenge(None, None, None))
        try:
            principal = await self.verifier.verify(token.strip(), self.audience)
        except TokenInvalid as e:
            if e.http_status == 403 and e.reason == "missing_scope":
                chal = self._challenge("insufficient_scope", None, None)
            else:
                chal = self._challenge("invalid_token", e.reason, None)
            raise _Reject(e.http_status, "invalid_token", challenge=chal) from None
        except TokenServiceUnavailable:
            raise _Reject(503, "token_service_unavailable") from None
        if self.allowed_azp and principal.azp not in self.allowed_azp:
            raise _Reject(
                403, "invalid_token", challenge=self._challenge("invalid_token", "bad_azp", None)
            )

        body = await self._read_body(receive)
        try:
            msg = json.loads(body)
        except ValueError:
            raise _Reject(400, "invalid_json") from None
        if not isinstance(msg, dict):
            raise _Reject(400, "batch_not_allowed")
        if msg.get("method") == "tools/call" and self.required_scopes_for is not None:
            params = msg.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            required = self.required_scopes_for(name) if isinstance(name, str) else None
            if required and not set(required) <= principal.scopes:
                raise _Reject(
                    403,
                    "insufficient_scope",
                    challenge=self._challenge("insufficient_scope", None, " ".join(required)),
                )

        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return AuthContext(principal, str(uuid.uuid4())), replay
