"""`ApprovalService`: chỉ phụ thuộc port (IntentVerifier, ApprovalSigner, RateLimiter, Clock)."""

from __future__ import annotations

from acme_common.ports import Clock, Principal, RateLimiter

from ..ports import ApprovalSigner, ApprovalToken, IntentVerifier, RenderModel, SignerError

# ADR-005 mục 5: token signer không được mang audience của agent/gateway.
_FORBIDDEN_AUDIENCES = frozenset({"agent-service", "llm-gateway"})


class ApprovalService:
    def __init__(
        self,
        intents: IntentVerifier,
        signer: ApprovalSigner,
        limiter: RateLimiter,
        clock: Clock,
        *,
        audience: str = "approval-signer",
        allowed_azp: str = "chat-ui",
        rate_per_hour: int = 30,
    ) -> None:
        self._intents = intents
        self._signer = signer
        self._limiter = limiter
        self._clock = clock
        self._audience = audience
        self._azp = allowed_azp
        self._rate = rate_per_hour

    def check_principal(self, principal: Principal) -> None:
        """Hậu điều kiện ngoài `TokenVerifier` (phòng thủ nhiều lớp): đúng một audience hợp lệ, azp."""
        if (
            self._audience not in principal.audience
            or _FORBIDDEN_AUDIENCES & set(principal.audience)
            or principal.azp != self._azp
        ):
            raise SignerError("forbidden")

    def render(self, intent_jws: str, principal: Principal) -> RenderModel:
        self.check_principal(principal)
        return self._intents.verify(intent_jws, principal)

    async def approve(self, intent_jws: str, principal: Principal) -> tuple[ApprovalToken, float]:
        """Verify lại toàn bộ (không tin lần render), kiểm hiển thị được, rồi ký.

        Trả (token, độ chần chừ giây từ `iat` của intent đến lúc ký).
        """
        self.check_principal(principal)
        intent = self._intents.verify_intent(intent_jws, principal)
        self._intents.verify(intent_jws, principal)  # intent_unrenderable => không ký
        decision = await self._limiter.reserve(
            f"approve:{principal.sub}", 1, limit=self._rate, window_s=3600.0
        )
        if not decision.allowed:
            raise SignerError("rate_limited", retry_after_s=decision.retry_after_s)
        token = self._signer.sign(intent, principal)
        latency = max(0.0, self._clock.now().timestamp() - float(intent.payload["iat"]))
        return token, latency
