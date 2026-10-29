"""Resource server gia lap cho Spike C. Chay: python resource_servers.py tickets|gateway

tickets-mcp  (127.0.0.1:8931): /mcp (phuong an chinh), /mcp-b (phuong an B)
fake gateway (127.0.0.1:8932): /v1/whoami (chinh), /v1-b/whoami (B, minh hoa rui ro)
"""
from __future__ import annotations

import contextvars
import hmac
import json
import os
import sys

import jwt
from jwt import PyJWKClient

ISSUER = os.getenv("ISSUER", "http://keycloak.acme.local:8080/realms/acme")
JWKS = os.getenv("JWKS_URI", "http://localhost:8080/realms/acme/protocol/openid-connect/certs")
ALGS = ["RS256"]  # allowlist
_jwks = PyJWKClient(JWKS, cache_keys=True, lifespan=3600)


class AuthError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def verify(token: str, *, audience: str, scope: str | None = None, azp_allow: set[str] | None = None) -> dict:
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        c = jwt.decode(token, key, algorithms=ALGS, audience=audience, issuer=ISSUER,
                       options={"require": ["exp", "iss", "aud", "sub"]})
    except jwt.ExpiredSignatureError:
        raise AuthError("expired")
    except jwt.InvalidAudienceError:
        raise AuthError("audience", f"can aud={audience}")
    except jwt.InvalidIssuerError:
        raise AuthError("issuer")
    except (jwt.InvalidSignatureError, jwt.DecodeError, jwt.PyJWKClientError, jwt.InvalidAlgorithmError) as e:
        raise AuthError("signature", type(e).__name__)
    except jwt.PyJWTError as e:
        raise AuthError("invalid", type(e).__name__)
    if scope and scope not in c.get("scope", "").split():
        raise AuthError("scope", f"can scope={scope}")
    if azp_allow is not None and c.get("azp") not in azp_allow:
        raise AuthError("azp", f"azp={c.get('azp')}")
    return c


def _identity(c: dict) -> dict:
    return {k: c.get(k) for k in ("sub", "dept", "clearance", "azp", "aud", "scope")}


# ------------------------------------------------------------------ ASGI helpers
async def _send_json(send, status: int, body: dict, headers: list | None = None):
    raw = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), *(headers or [])]})
    await send({"type": "http.response.body", "body": raw})


def _hdr(scope, name: str) -> str | None:
    n = name.lower().encode()
    for k, v in scope["headers"]:
        if k == n:
            return v.decode()
    return None


def _bearer(scope) -> str:
    a = _hdr(scope, "authorization") or ""
    if not a.lower().startswith("bearer "):
        raise AuthError("missing_bearer")
    return a[7:].strip()


async def _reject(send, e: AuthError):
    hv = f'Bearer error="invalid_token", error_description="{e.reason}"'.encode()
    await _send_json(send, 401, {"error": "unauthorized", "reason": e.reason, "detail": e.detail},
                     [(b"www-authenticate", hv)])


# ------------------------------------------------------------------ tickets-mcp
CURRENT: contextvars.ContextVar[dict] = contextvars.ContextVar("current_identity")
AZP_ALLOW = set(os.getenv("SPIKE_C_AZP_ALLOW", "spike-c-login").split(","))


class TicketsAuth:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        path = scope["path"]
        try:
            if path == "/mcp":
                ident = verify(_bearer(scope), audience="tickets-mcp", scope="tickets:read")
            elif path == "/mcp-b":
                verify(_bearer(scope), audience="tickets-mcp", scope="tickets:read", azp_allow={"agent-service"})
                ut = _hdr(scope, "x-acme-user-token")
                if not ut:
                    raise AuthError("missing_user_token")
                ident = verify(ut, audience="agent-service", scope="agent:invoke", azp_allow=AZP_ALLOW)
                scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
            else:
                return await _send_json(send, 404, {"error": "not_found"})
        except AuthError as e:
            return await _reject(send, e)
        CURRENT.set(ident)
        return await self.inner(scope, receive, send)


def build_tickets():
    from fastmcp import FastMCP

    mcp = FastMCP("spike-c-tickets-mcp")

    @mcp.tool
    def whoami() -> dict:
        return _identity(CURRENT.get())

    return TicketsAuth(mcp.http_app(path="/mcp", stateless_http=True))


# ------------------------------------------------------------------ fake llm-gateway
def build_gateway():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    key = os.environ["SPIKE_C_GW_KEY"]

    def make(aud: str, scope: str):
        async def h(request):
            try:
                if not hmac.compare_digest(_bearer(request.scope), key):
                    raise AuthError("api_key")
                ut = request.headers.get("x-acme-user-token")
                if not ut:
                    raise AuthError("missing_user_token")
                c = verify(ut, audience=aud, scope=scope)
            except AuthError as e:
                return JSONResponse({"error": "unauthorized", "reason": e.reason, "detail": e.detail},
                                    status_code=401)
            return JSONResponse(_identity(c))
        return h

    return Starlette(routes=[
        Route("/v1/whoami", make("llm-gateway", "llm:invoke"), methods=["POST"]),
        Route("/v1-b/whoami", make("agent-service", "agent:invoke"), methods=["POST"]),
    ])


if __name__ == "__main__":
    import uvicorn

    which = sys.argv[1]
    _jwks.get_signing_keys()  # warm cache
    app, port = (build_tickets(), 8931) if which == "tickets" else (build_gateway(), 8932)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
