"""`IntentCommitService`: thứ tự kiểm approval + máy trạng thái intent + idempotency (approval.md §2.2, §2.3).

Dùng chung cho mọi MCP ghi (tickets-mcp, notify-mcp...). Phần riêng của MCP (phân quyền lại,
thực thi) nằm sau port `IntentExecutor`. Thứ tự kiểm tra và mã lỗi giữ nguyên, không nới điều kiện nào.
"""

from __future__ import annotations

import json
import logging
from typing import Any, NoReturn

from ..mcp.errors import ToolError
from ..ports import (
    ApprovalRejected,
    ApprovalVerifier,
    BackendUnavailable,
    Clock,
    DuplicateIntent,
    ExecutionConflict,
    ExecutionRolledBack,
    ExecutionUnavailable,
    Intent,
    IntentExecutor,
    IntentInvalid,
    IntentIssuer,
    Principal,
    ReplayGuard,
    StoredIntent,
)
from .canonical import canonical_json

log = logging.getLogger("acme.intent_commit")

STALE_COMMITTING_S = 30.0


def args_match(args: dict[str, Any], st: StoredIntent) -> bool:
    try:
        return canonical_json(args).decode("utf-8") == st.payload.get("args_canonical")
    except (ValueError, TypeError):
        return False


def intent_from(st: StoredIntent) -> Intent:
    """Dựng `Intent` từ payload đã verify (không từ agent)."""
    pl = st.payload
    try:
        args = json.loads(pl["args_canonical"])
        if not isinstance(args, dict) or not isinstance(pl["op"], str):
            raise ValueError
        return Intent(
            intent_id=st.intent_id,
            op=pl["op"],
            sha256=st.sha256,
            sub=st.sub,
            args=args,
            before=dict(pl.get("before") or {}),
            after=dict(pl.get("after") or {}),
            expected_updated_at=pl.get("expected_updated_at"),
            target=dict(pl.get("target") or {}),
        )
    except (KeyError, ValueError, TypeError):
        raise ToolError(
            "intent_mismatch", "malformed intent", details={"reason": "format"}
        ) from None


class IntentCommitService:
    def __init__(
        self,
        issuer: IntentIssuer,
        approvals: ApprovalVerifier,
        replay: ReplayGuard,
        clock: Clock,
        executor: IntentExecutor,
        *,
        replay_ttl_s: int = 180,
    ) -> None:
        self.issuer = issuer
        self.approvals = approvals
        self.replay = replay
        self.clock = clock
        self.executor = executor
        self.replay_ttl_s = replay_ttl_s

    async def commit(
        self,
        p: Principal,
        intent_id: str,
        approval_token: str,
        args: dict[str, Any] | None = None,
    ) -> Any:
        # 1-5: approval
        try:
            ap = self.approvals.verify(approval_token, p, intent_id)
        except ApprovalRejected as e:
            raise ToolError(e.code, e.reason or e.code) from None
        # 6-8: intent đã lưu (verify lại chữ ký), hết hạn, sub/sha
        try:
            st = await self.issuer.load(intent_id)
        except BackendUnavailable:
            raise ToolError("upstream_unavailable", "intent store unavailable") from None
        except IntentInvalid as e:
            raise ToolError(
                "intent_mismatch", "stored intent invalid", details={"reason": e.reason}
            ) from None
        if st is None:
            raise ToolError("intent_not_found", "intent not found")
        if self.clock.now().timestamp() > st.exp:
            raise ToolError("intent_expired", "intent expired")
        if st.sub != p.sub or st.sha256 != ap.intent_sha256 or st.payload.get("sub") != p.sub:
            raise ToolError(
                "intent_mismatch",
                "intent does not match approval",
                details={"reason": "sha256_or_sub"},
            )
        intent = intent_from(st)
        if args is not None and not args_match(args, st):
            raise ToolError(
                "intent_mismatch", "args differ from approved intent", details={"reason": "args"}
            )

        # trạng thái đã biết trước khi tốn tài nguyên (CAS vẫn là quyết định cuối)
        if st.status != "pending":
            await self._not_pending(intent_id, p, st.status, st.owner_jti, st.updated_at)

        # 11: quyền hiện tại (không đốt jti vì lỗi đoán trước được)
        await self.executor.reauthorize(p, intent)
        # 10: jti dùng một lần
        try:
            fresh = await self.replay.consume(ap.jti, self.replay_ttl_s)
        except BackendUnavailable:
            raise ToolError("upstream_unavailable", "replay store unavailable") from None
        if not fresh:
            raise await self._replayed(intent_id, p, True)
        # 9: CAS pending -> committing
        try:
            cas = await self.issuer.begin_commit(intent_id, ap.jti)
        except BackendUnavailable:
            raise ToolError("upstream_unavailable", "intent store unavailable") from None
        if cas.status == "missing":
            raise ToolError("intent_not_found", "intent not found")
        if cas.status != "owned":
            await self._not_pending(intent_id, p, cas.status, cas.owner_jti, cas.updated_at)

        # 12: ta là owner
        try:
            applied = await self.executor.execute(intent, ap, p)
        except ExecutionConflict:
            await self._finish(intent_id, ap.jti, "failed")
            raise ToolError("conflict", "target changed since approval") from None
        except DuplicateIntent:
            await self._finish(intent_id, ap.jti, "committed")
            raise await self._replayed(intent_id, p, True) from None
        except ExecutionRolledBack:
            await self._finish(intent_id, ap.jti, "failed")
            raise ToolError(
                "upstream_unavailable",
                "write rolled back",
                details={"reason": "retry_prepare"},
                retryable=False,
            ) from None
        except ExecutionUnavailable:
            # kết quả không xác định: để `committing`, lần sau (>30s) tra bản ghi idempotency
            raise ToolError(
                "upstream_unavailable", "write outcome unknown", details={"reason": "retry_later"}
            ) from None
        await self._finish(intent_id, ap.jti, "committed")
        return applied

    async def _replayed(self, intent_id: str, p: Principal, known_done: bool) -> ToolError:
        details: dict[str, Any] = {}
        if known_done:
            try:
                found = await self.executor.applied_details(intent_id, p)
            except ExecutionUnavailable:
                found = None
            if found is not None:
                details = found
        return ToolError("approval_replayed", "intent already used", details=details)

    async def _not_pending(
        self, intent_id: str, p: Principal, status: str, owner: str | None, updated_at: float
    ) -> NoReturn:
        """Bảng ánh xạ lỗi cho intent không còn `pending`."""
        if status == "committed":
            raise await self._replayed(intent_id, p, True)
        if status == "committing":
            if self.clock.now().timestamp() - updated_at <= STALE_COMMITTING_S:
                raise await self._replayed(intent_id, p, False)  # owner còn sống
            await self._recover(intent_id, p, owner or "")
        raise ToolError(
            "intent_mismatch", "intent failed; prepare again", details={"reason": "failed"}
        )

    async def _recover(self, intent_id: str, p: Principal, stale_owner: str) -> NoReturn:
        try:
            applied = await self.executor.applied_details(intent_id, p)
        except ExecutionUnavailable:
            raise ToolError("upstream_unavailable", "ticket store unavailable") from None
        new = "committed" if applied is not None else "failed"
        try:
            await self.issuer.recover_stale(intent_id, stale_owner, new)
        except BackendUnavailable:
            raise ToolError("upstream_unavailable", "intent store unavailable") from None
        if applied is not None:
            raise await self._replayed(intent_id, p, True)
        raise ToolError(
            "intent_mismatch", "intent failed; prepare again", details={"reason": "failed"}
        )

    async def _finish(self, intent_id: str, jti: str, new: str) -> None:
        try:
            await self.issuer.finish_commit(intent_id, jti, new)  # type: ignore[arg-type]
        except BackendUnavailable:
            # đã quyết định ở executor; trạng thái Redis tự khôi phục sau 30s
            log.warning("finish_commit failed (state will be recovered)")
