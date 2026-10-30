"""Factory của bff: dựng các port theo Settings và nối service (contracts §9.1 mục 5).

`TokenVerifier`/`TokenBroker`/`Clock` chọn adapter theo tên trong config, qua factory của
acme_common (registry dict + lazy import). Không bọc `TokenBroker` bằng `CachingTokenBroker`:
BFF tự cache token theo phiên trong `SessionStore` (D15: không cache chéo phiên).
Redis, httpx là hạ tầng cố định nên dùng trực tiếp.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from acme_common.factory import build_clock, build_token_broker, build_token_verifier
from acme_common.http import RetryingHttpClient
from acme_common.ports import Clock, TokenBroker, TokenVerifier
from redis.asyncio import Redis

from .clients.agent_client import AgentClient
from .clients.signer_client import SignerClient
from .services.approval_flow import ApprovalFlow
from .services.auth import AuthService
from .services.crypto import Crypto
from .services.oidc import OidcClient
from .services.rate_limit import RateLimits
from .services.session import SessionStore
from .services.streams import StreamService
from .services.tokens import TokenService
from .settings import Settings


@dataclass
class Container:
    settings: Settings
    clock: Clock
    redis: Redis
    crypto: Crypto
    store: SessionStore
    oidc: OidcClient
    verifier: TokenVerifier
    tokens: TokenService
    agent: AgentClient
    signer: SignerClient
    flow: ApprovalFlow
    streams: StreamService
    limits: RateLimits
    auth: AuthService
    _http: list[RetryingHttpClient]
    _stream_client: httpx.AsyncClient

    async def aclose(self) -> None:
        for h in self._http:
            await h.aclose()
        await self._stream_client.aclose()
        await self.redis.aclose()


def build_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.bff_redis_url, password=settings.redis_bff_password, decode_responses=True
    )


def build_container(
    settings: Settings,
    *,
    redis: Redis | None = None,
    clock: Clock | None = None,
    verifier: TokenVerifier | None = None,
    broker: TokenBroker | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Container:
    """Các tham số tuỳ chọn cho phép test tiêm fake; production để mặc định."""
    settings.validate_runtime()
    clock = clock or build_clock(settings.clock_adapter, settings)
    idp_http = RetryingHttpClient(
        timeout_s=settings.http_timeout_s,
        max_attempts=settings.http_max_attempts,
        transport=transport,
    )
    # POST tới agent/signer không idempotent: không retry tự động
    svc_http = RetryingHttpClient(
        timeout_s=settings.http_timeout_s, max_attempts=1, transport=transport
    )
    stream_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_s, read=None), transport=transport
    )
    verifier = verifier or build_token_verifier(
        settings.token_verifier_adapter, settings, clock=clock, http=idp_http
    )
    secret = settings.bff_oidc_client_secret or ""
    broker = broker or build_token_broker(
        settings.token_broker_adapter,
        settings,
        clock=clock,
        client_id=settings.bff_oidc_client_id,
        client_secret=secret,
        http=idp_http,
        cache=False,
    )
    crypto = Crypto(settings.session_key_bytes)
    redis = redis or build_redis(settings)
    store = SessionStore(
        redis, crypto, clock, idle_s=settings.bff_session_idle_s, abs_s=settings.bff_session_abs_s
    )
    oidc = OidcClient(
        idp_http,
        issuer=settings.oidc_issuer,
        client_id=settings.bff_oidc_client_id,
        client_secret=secret,
        redirect_uri=f"{settings.public_origin}/auth/callback",
        post_logout_redirect_uri=settings.bff_public_url,
        token_url=settings.oidc_token_url,
    )
    tokens = TokenService(
        broker,
        verifier,
        oidc,
        store,
        clock,
        login_audience=settings.bff_oidc_client_id,
        signer_ttl_s=settings.bff_signer_token_ttl_s,
    )
    agent = AgentClient(settings.bff_agent_url, svc_http, stream_client)
    signer = SignerClient(settings.bff_signer_url, svc_http)
    limits = RateLimits(store)
    flow = ApprovalFlow(
        store,
        tokens,
        signer,
        agent,
        max_cards_per_thread_hour=settings.bff_max_cards_per_thread_hour,
        rejected_ttl_s=settings.bff_rejected_ttl_s,
    )
    streams = StreamService(
        tokens,
        agent,
        flow,
        limits,
        heartbeat_s=settings.bff_stream_heartbeat_s,
        idle_s=settings.bff_stream_idle_s,
        max_s=settings.bff_stream_max_s,
    )
    auth = AuthService(
        store, oidc, verifier, tokens, agent, clock, client_id=settings.bff_oidc_client_id
    )
    return Container(
        settings,
        clock,
        redis,
        crypto,
        store,
        oidc,
        verifier,
        tokens,
        agent,
        signer,
        flow,
        streams,
        limits,
        auth,
        [idp_http, svc_http],
        stream_client,
    )
