"""ApprovalFlow: register, verify, approve, decide. Không có khoá ký trong BFF.

Quy tắc chính: chỉ xử lý interrupt BFF đã nhận trong chính phiên này; trình duyệt chỉ gửi định
danh; `approve` đòi `state == verified` và `intent_sha256` khớp thẻ đã verify; `approval_token`
chỉ nằm trong biến cục bộ rồi đi thẳng vào resume.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..adapters.agent_client import AgentClient
from ..adapters.signer_client import SignerClient
from .errors import ApiError, UpstreamStatus
from .session import SessionData, SessionStore, user_hash
from .tokens import TokenService

log = logging.getLogger("bff.approval")

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_TRIES = 3
MAX_APPROVALS_PER_HOUR = 30


class CardBlocked(Exception):
    """Interrupt bị chặn: `reason` ∈ intent_rejected_recently | cards_per_thread_hour."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DisplayField(BaseModel):
    path: str = Field(max_length=200)
    label: str = Field(max_length=200)
    kind: str = Field(max_length=40)
    before: Any = None
    after: Any = None
    changed: bool = False
    sensitive: bool = False


class CardModel(BaseModel):
    interrupt_id: str
    intent_id: str
    op: str
    title: str
    risk: str
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    expires_at: str
    server_time: str
    intent_sha256: str
    display_fields: list[DisplayField] = Field(max_length=64)


def _build_card(interrupt_id: str, rm: dict[str, Any]) -> CardModel:
    display = rm.get("display") or {}
    return CardModel(
        interrupt_id=interrupt_id,
        intent_id=rm["intent_id"],
        op=rm["op"],
        title=display["title"],
        risk=display.get("risk", "medium"),
        risk_flags=rm.get("risk_flags", []),
        expires_at=rm["expires_at"],
        server_time=rm["server_time"],
        intent_sha256=rm["intent_sha256"],
        display_fields=display["display_fields"],
    )


class ApprovalFlow:
    def __init__(
        self,
        store: SessionStore,
        tokens: TokenService,
        signer: SignerClient,
        agent: AgentClient,
        *,
        max_cards_per_thread_hour: int,
        rejected_ttl_s: int,
    ) -> None:
        self._store = store
        self._tokens = tokens
        self._signer = signer
        self._agent = agent
        self._max_cards = max_cards_per_thread_hour
        self._rej_ttl = rejected_ttl_s

    # --- đăng ký interrupt nhận từ agent ---
    async def register(
        self, s: SessionData, thread_id: str, payload: dict[str, Any]
    ) -> dict[str, str]:
        """Ghi `pend`; trả phần công khai (không có `intent_jws`). Raise `CardBlocked`/`ValueError`."""
        interrupt_id = payload.get("interrupt_id")
        body = payload.get("payload", payload)
        intent_id, jws, op, exp = (
            body.get(k) for k in ("intent_id", "intent_jws", "op", "expires_at")
        )
        if not (isinstance(interrupt_id, str) and _ID.match(interrupt_id)):
            raise ValueError("interrupt_id")
        if not all(isinstance(v, str) and v for v in (intent_id, jws, op, exp)):
            raise ValueError("payload")
        existing = await self._store.pend_get(s.sid, interrupt_id)
        if existing and existing["thread_id"] == thread_id and existing["intent_id"] == intent_id:
            # tải lại trang / gửi lại cùng interrupt: không đếm thẻ, giữ nguyên state
            return {
                "interrupt_id": interrupt_id,
                "intent_id": intent_id,
                "op": op,
                "expires_at": exp,
            }
        if await self._store.rej_has(s.sid, intent_id):
            raise CardBlocked("intent_rejected_recently")
        cards_key = f"bff:sess:u:{user_hash(s.sub)}:cards:{thread_id}"
        if await self._store.incr(cards_key, 3600) > self._max_cards:
            raise CardBlocked("cards_per_thread_hour")
        await self._store.pend_put(
            s.sid,
            interrupt_id,
            {
                "thread_id": thread_id,
                "intent_id": intent_id,
                "intent_jws": jws,
                "op": op,
                "expires_at": exp,
                "state": "seen",
                "tries": 0,
            },
        )
        return {"interrupt_id": interrupt_id, "intent_id": intent_id, "op": op, "expires_at": exp}

    async def _pend(self, s: SessionData, thread_id: str, interrupt_id: str) -> dict[str, Any]:
        if not _ID.match(interrupt_id):
            raise ApiError(404, "interrupt_not_found")
        pend = await self._store.pend_get(s.sid, interrupt_id)
        if pend is None or pend["thread_id"] != thread_id:
            raise ApiError(404, "interrupt_not_found")
        if pend["state"] == "dead":
            raise ApiError(410, "intent_expired")
        return pend

    def _audit(self, s: SessionData, **fields: object) -> None:
        log.info("approval_audit", extra={"fields": {"sub": s.sub, **fields}})

    async def _mark_dead_if_expired(
        self, s: SessionData, interrupt_id: str, exc: UpstreamStatus
    ) -> None:
        if exc.status == 410 or exc.code == "intent_expired":
            await self._store.pend_update(s.sid, interrupt_id, state="dead")

    # --- verify ---
    async def verify(self, s: SessionData, thread_id: str, interrupt_id: str) -> CardModel:
        pend = await self._pend(s, thread_id, interrupt_id)
        try:
            rm = await self._tokens.call(
                s, "signer", lambda tok: self._signer.verify_intent(pend["intent_jws"], tok)
            )
        except UpstreamStatus as exc:
            await self._mark_dead_if_expired(s, interrupt_id, exc)
            self._audit(
                s,
                thread_id=thread_id,
                interrupt_id=interrupt_id,
                decision="verify",
                result=f"upstream_{exc.status}",
            )
            raise
        try:
            card = _build_card(interrupt_id, rm)
        except (KeyError, TypeError, ValidationError):
            raise ApiError(502, "upstream_unavailable", True) from None
        await self._store.pend_update(
            s.sid, interrupt_id, state="verified", rm_sha=card.intent_sha256
        )
        self._audit(
            s,
            thread_id=thread_id,
            interrupt_id=interrupt_id,
            intent_id=card.intent_id,
            decision="verify",
            result="ok",
        )
        return card

    # --- approve ---
    async def approve(
        self, s: SessionData, thread_id: str, interrupt_id: str, shown_sha: str
    ) -> tuple[httpx.Response, str | None]:
        pend = await self._pend(s, thread_id, interrupt_id)
        if pend["state"] != "verified" or pend.get("rm_sha") != shown_sha:
            raise ApiError(422, "intent_mismatch")
        if pend["tries"] >= MAX_TRIES:
            raise ApiError(429, "rate_limited", True)
        if (
            await self._store.incr(f"bff:sess:u:{user_hash(s.sub)}:appr", 3600)
            > MAX_APPROVALS_PER_HOUR
        ):
            raise ApiError(429, "rate_limited", True)
        await self._store.pend_update(s.sid, interrupt_id, tries=pend["tries"] + 1)
        if not await self._store.gate(s.sid, interrupt_id):
            raise ApiError(409, "conflict")
        try:
            ap = await self._tokens.call(
                s, "signer", lambda tok: self._signer.approve(pend["intent_jws"], tok)
            )
            approval_token = ap.get("approval_token")
            if not isinstance(approval_token, str) or not approval_token:
                raise ApiError(502, "upstream_unavailable", True)
            decision = {"type": "approve", "approval_token": approval_token}
            resp = await self._tokens.call(
                s, "agent", lambda tok: self._agent.resume(tok, thread_id, interrupt_id, decision)
            )
        except BaseException as exc:
            await self._store.gate_release(s.sid, interrupt_id)
            if isinstance(exc, UpstreamStatus):
                await self._mark_dead_if_expired(s, interrupt_id, exc)
            self._audit(
                s,
                thread_id=thread_id,
                interrupt_id=interrupt_id,
                intent_id=pend["intent_id"],
                decision="approve",
                result="error",
            )
            raise
        await self._store.pend_delete(s.sid, interrupt_id)
        self._audit(
            s,
            thread_id=thread_id,
            interrupt_id=interrupt_id,
            intent_id=pend["intent_id"],
            decision="approve",
            result="ok",
        )
        expires = ap.get("expires_at")
        return resp, expires if isinstance(expires, str) else None

    # --- edit / reject / refresh ---
    async def decide(
        self, s: SessionData, thread_id: str, interrupt_id: str, decision: dict[str, Any]
    ) -> httpx.Response:
        if decision.get("type") == "approve":
            raise ApiError(400, "invalid_request")
        pend = await self._pend(s, thread_id, interrupt_id)
        resp = await self._tokens.call(
            s, "agent", lambda tok: self._agent.resume(tok, thread_id, interrupt_id, decision)
        )
        if decision.get("type") == "reject":
            await self._store.rej_add(
                s.sid, self._rej_ttl, pend["intent_id"], pend.get("rm_sha", "")
            )
        await self._store.pend_delete(s.sid, interrupt_id)
        self._audit(
            s,
            thread_id=thread_id,
            interrupt_id=interrupt_id,
            intent_id=pend["intent_id"],
            decision=decision.get("type"),
            result="ok",
        )
        return resp
