"""HTTP API của approval-signer (05 §5.3). Handler chỉ: Bearer -> TokenVerifier -> service -> map lỗi."""

from __future__ import annotations

import hmac
import logging
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from acme_common.factory import build_clock, build_rate_limiter, build_token_verifier
from acme_common.log import bind_request_id, configure_logging, get_request_id, reset_request_id
from acme_common.ports import Principal, TokenInvalid, TokenServiceUnavailable, TokenVerifier
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .approval import ApprovalService
from .factory import build_approval_signer, build_intent_verifier
from .ports import SignerError
from .settings import Settings

log = logging.getLogger("approval_signer")
_MSG = {
    "unauthorized": "Authentication required.",
    "forbidden": "Not allowed.",
    "intent_expired": "Intent has expired.",
    "intent_mismatch": "Intent does not match the request.",
    "intent_unrenderable": "Intent cannot be displayed safely.",
    "invalid_argument": "Invalid request.",
    "rate_limited": "Too many requests.",
    "upstream_unavailable": "Service temporarily unavailable.",
}


@dataclass
class Deps:
    service: ApprovalService
    tokens: TokenVerifier
    audience: str = "approval-signer"
    metrics_token: str | None = None


class _Metrics:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.latency_sum = 0.0

    def render(self) -> str:
        lines = [f"{k} {v}" for k, v in sorted(self.counts.items())]
        lines.append(f"signer_approval_latency_seconds_sum {self.latency_sum}")
        return "\n".join(lines) + "\n"


def _error(code: str, request_id: str, **details: Any) -> JSONResponse:
    status = SignerError(code).http_status
    retry = details.pop("retry_after_s", None)
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": _MSG.get(code, "Error."),
            "retryable": code in {"upstream_unavailable", "rate_limited"},
            "request_id": request_id,
        }
    }
    if details:
        body["error"]["details"] = details
    headers = {"X-Request-Id": request_id}
    if retry:
        headers["Retry-After"] = str(int(retry) + 1)
    return JSONResponse(body, status_code=status, headers=headers)


def _build_deps(settings: Settings) -> Deps:
    clock = build_clock(settings.clock_adapter, settings)
    return Deps(
        service=ApprovalService(
            build_intent_verifier(settings.intent_verifier_adapter, settings, clock=clock),
            build_approval_signer(settings.approval_signer_adapter, settings, clock=clock),
            build_rate_limiter(settings.rate_limiter_adapter, settings, clock=clock),
            clock,
            audience=settings.signer_audience,
            allowed_azp=settings.signer_allowed_azp,
            rate_per_hour=settings.signer_rl_per_hour,
        ),
        tokens=build_token_verifier(
            settings.token_verifier_adapter, settings.token_verifier_settings, clock=clock
        ),
        audience=settings.signer_audience,
        metrics_token=settings.metrics_token,
    )


def create_app(deps: Deps | None = None) -> FastAPI:
    """Có `deps` (test) thì dùng luôn; không thì dựng từ env lúc khởi động (fail-fast nếu thiếu khoá)."""
    holder: dict[str, Deps] = {} if deps is None else {"d": deps}
    metrics = _Metrics()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if "d" not in holder:
            settings = Settings()
            configure_logging(settings.log_level, "approval-signer")
            holder["d"] = _build_deps(settings)
        yield

    app = FastAPI(title="Approval Signer", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next: Any) -> Response:
        rid_header = request.headers.get("x-request-id", "")
        tok = bind_request_id(rid_header[:64] if rid_header.isalnum() else None)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-Id"] = get_request_id() or ""
        finally:
            reset_request_id(tok)
        return response

    def rid(request: Request) -> str:
        return get_request_id() or ""

    async def authenticate(request: Request) -> Principal:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise SignerError("unauthorized")
        try:
            return await holder["d"].tokens.verify(token.strip(), holder["d"].audience)
        except TokenInvalid as e:
            raise SignerError("unauthorized" if e.http_status == 401 else "forbidden") from None
        except TokenServiceUnavailable:
            raise SignerError("upstream_unavailable") from None

    async def intent_jws(request: Request) -> str:
        try:
            body = await request.json()
        except ValueError:
            raise SignerError("invalid_argument") from None
        value = body.get("intent_jws") if isinstance(body, dict) else None
        if not isinstance(value, str) or not value:
            raise SignerError("invalid_argument")
        return value

    @app.exception_handler(SignerError)
    async def on_signer_error(request: Request, exc: SignerError) -> JSONResponse:
        metrics.counts[f'signer_error_total{{code="{exc.code}"}}'] += 1
        return _error(exc.code, rid(request), **exc.details)

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error", extra={"fields": {"exc_type": type(exc).__name__}})
        return JSONResponse(
            {
                "error": {
                    "code": "upstream_unavailable",
                    "message": _MSG["upstream_unavailable"],
                    "retryable": True,
                    "request_id": rid(request),
                }
            },
            status_code=503,
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics_endpoint(request: Request) -> Response:
        expected = holder["d"].metrics_token if "d" in holder else None
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return _error("unauthorized", rid(request))
        return PlainTextResponse(metrics.render())

    @app.post("/v1/intents/verify")
    async def verify_intent(request: Request) -> dict[str, Any]:
        principal = await authenticate(request)
        jws = await intent_jws(request)
        try:
            model = holder["d"].service.render(jws, principal).to_dict()
        except SignerError as e:
            metrics.counts[f'signer_verify_total{{result="{e.code}"}}'] += 1
            raise
        metrics.counts['signer_verify_total{result="ok"}'] += 1
        return model

    @app.post("/v1/approvals")
    async def approvals(request: Request) -> dict[str, Any]:
        principal = await authenticate(request)
        jws = await intent_jws(request)
        try:
            token, latency = await holder["d"].service.approve(jws, principal)
        except SignerError as e:
            metrics.counts[f'signer_approval_total{{result="{e.code}"}}'] += 1
            raise
        metrics.counts['signer_approval_total{result="ok"}'] += 1
        metrics.latency_sum += latency
        return {
            "approval_token": token.token,
            "jti": token.jti,
            "expires_at": token.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    return app
