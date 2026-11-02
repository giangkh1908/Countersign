"""`NotifyService`: nơi DUY NHẤT chứa phân quyền gửi báo cáo; commit dùng `IntentCommitService` dùng chung.

Chỉ phụ thuộc port (`MessageChannel`, `DeliveryLog`, `IntentIssuer`, `ApprovalVerifier`, `ReplayGuard`,
`Clock`) và client Redis cho taint (module `acme_common.services.taint`, không phải port).

Kiểm quyền và taint ở CẢ prepare lẫn commit (giữa hai bước vai trò đổi, thread có thể đọc thêm tài liệu
mật). Tin đã gửi không thu hồi được nên taint không đọc được (`None`) là TỪ CHỐI (fail-closed), khác ticket.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from acme_common.mcp.errors import ToolError
from acme_common.ports import (
    Approval,
    BackendUnavailable,
    Clock,
    Draft,
    DuplicateIntent,
    ExecutionRolledBack,
    Intent,
    IntentExecutor,
    Principal,
)
from acme_common.services.capabilities import Capability, allows
from acme_common.services.intent_commit import IntentCommitService
from acme_common.services.taint import get_taint

from ..channels import ChannelConfig
from ..ports import (
    ApprovalVerifier,
    ChannelSendError,
    DeliveryLog,
    DeliveryLogUnavailable,
    IntentIssuer,
    MessageChannel,
    ReplayGuard,
)

log = logging.getLogger("acme.mcp_notify.service")

OP = "send_group_report"
MAX_TEXT_CHARS = 3500
# URL trong tin là đường rò dữ liệu kinh điển của prompt injection (RQ3)
_URL = re.compile(
    r"(?i)(?:https?://|ftp://|www\.|\bt\.me/|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|vn|me|ly|co|app|dev|xyz|info|ru|cn)\b)"
)


def has_url(text: str) -> bool:
    return _URL.search(text) is not None


def _valid_text(text: str) -> bool:
    if not 1 <= len(text) <= MAX_TEXT_CHARS or not text.strip():
        return False
    return not any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in text)


class NotifyService:
    def __init__(
        self,
        channels: Mapping[str, ChannelConfig],
        senders: Mapping[str, MessageChannel],
        deliveries: DeliveryLog,
        issuer: IntentIssuer,
        approvals: ApprovalVerifier,
        replay: ReplayGuard,
        clock: Clock,
        redis: Any,
        *,
        replay_ttl_s: int = 180,
    ) -> None:
        missing = {c.adapter for c in channels.values()} - senders.keys()
        if missing:
            raise ValueError(f"no sender for adapters: {sorted(missing)}")
        self.channels = dict(channels)
        self.senders = dict(senders)
        self.deliveries = deliveries
        self.issuer = issuer
        self.approvals = approvals
        self.replay = replay
        self.clock = clock
        self.redis = redis
        self.replay_ttl_s = replay_ttl_s

    # ------------------------------------------------------------------ quyền
    @staticmethod
    def _may_send(p: Principal, cfg: ChannelConfig) -> bool:
        """`REPORT_COMPANY` gửi được mọi kênh; `REPORT_DEPT` chỉ kênh phòng mình (ma trận §1)."""
        if allows(p.roles, Capability.REPORT_COMPANY):
            return True
        return (
            cfg.scope == "dept" and cfg.dept in p.dept and allows(p.roles, Capability.REPORT_DEPT)
        )

    def _channel(self, alias: str) -> ChannelConfig:
        cfg = self.channels.get(alias)
        if cfg is None:
            raise ToolError("not_found", "channel not found")
        return cfg

    async def _authorize(self, p: Principal, thread_id: str | None, alias: str) -> ChannelConfig:
        cfg = self._channel(alias)
        if not self._may_send(p, cfg):
            raise ToolError("forbidden", "not allowed to send to this channel")
        taint = await get_taint(self.redis, p.sub, thread_id)
        if taint is None:
            raise ToolError("forbidden", "taint unknown", details={"reason": "taint_unknown"})
        for source, state in (("thread", taint.thread), ("recent", taint.recent)):
            if state.max_class > cfg.max_class:
                raise ToolError(
                    "forbidden",
                    "content classification above channel limit",
                    details={
                        "reason": "taint_exceeds_channel",
                        "reason_source": source,
                        "max_class": state.max_class,
                        "channel_max_class": cfg.max_class,
                    },
                )
        return cfg

    # ------------------------------------------------------------------ tool
    async def list_report_channels(self, p: Principal) -> dict[str, Any]:
        return {
            "channels": [
                {
                    "channel": c.alias,
                    "scope": c.scope,
                    "dept": c.dept,
                    "max_class": c.max_class,
                }
                for c in self.channels.values()
                if self._may_send(p, c)
            ]
        }

    async def prepare_send_group_report(
        self, p: Principal, thread_id: str | None, args: dict[str, Any]
    ) -> dict[str, Any]:
        alias, text = args["channel"], args["text"]
        if not isinstance(text, str) or not _valid_text(text):
            raise ToolError("invalid_argument", "text is empty, too long or has control characters")
        await self._authorize(p, thread_id, alias)
        norm = {"channel": alias, "text": text}
        flags: list[str] = []
        if has_url(text):
            flags.append("contains_url")
        if args.get("unverified_claims") is True:
            flags.append("unverified_claims")
        draft = Draft(
            target={"channel": alias},
            before={},
            after={"text": text},
            expected_updated_at=None,
            risk_flags=tuple(flags),
            risk="high" if flags else "medium",
        )
        try:
            signed = await self.issuer.issue(OP, norm, p, draft)
        except BackendUnavailable:
            raise ToolError("upstream_unavailable", "intent store unavailable") from None
        return {
            "ok": True,
            "intent_id": signed.intent_id,
            "intent_jws": signed.jws,
            "expires_at": datetime.fromtimestamp(signed.exp, UTC).isoformat(),
            "risk_flags": flags,
            "op": OP,
            "channel": alias,
        }

    async def commit_intent(
        self,
        p: Principal,
        thread_id: str | None,
        intent_id: str,
        approval_token: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        commits = IntentCommitService(
            self.issuer,
            self.approvals,
            self.replay,
            self.clock,
            _NotifyIntentExecutor(self, thread_id),
            replay_ttl_s=self.replay_ttl_s,
        )
        return await commits.commit(p, intent_id, approval_token, args)  # type: ignore[no-any-return]


class _NotifyIntentExecutor(IntentExecutor):
    """Phần gửi tin của luồng commit: phân quyền lại, ghi sổ rồi gửi đúng một lần, tra idempotency."""

    def __init__(self, svc: NotifyService, thread_id: str | None) -> None:
        self._svc = svc
        self._thread_id = thread_id

    async def reauthorize(self, principal: Principal, intent: Intent) -> None:
        if intent.op != OP:
            raise ToolError("invalid_argument", "unsupported operation")
        await self._svc._authorize(principal, self._thread_id, str(intent.args.get("channel", "")))

    async def execute(
        self, intent: Intent, approval: Approval, principal: Principal
    ) -> dict[str, Any]:
        svc = self._svc
        alias, text = str(intent.args["channel"]), str(intent.args["text"])
        cfg = svc._channel(alias)
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            await svc.deliveries.begin(intent.intent_id, alias, sha, principal.sub, approval.jti)
        except DuplicateIntent:
            raise
        except DeliveryLogUnavailable as e:
            if e.not_written:
                raise ExecutionRolledBack from None  # chưa gửi, chưa ghi: prepare lại được
            raise  # không rõ đã ghi chưa: giữ `committing`, không bao giờ gửi
        sender = svc.senders[cfg.adapter]
        status, detail = "sent", ""
        try:
            receipt = await sender.send(cfg.chat_ref, text)
            detail = receipt.message_ref
        except ChannelSendError as e:
            detail = e.kind if e.status is None else f"{e.kind}:{e.status}"
            if e.delivered == "no":
                await self._finish(intent.intent_id, "failed", detail)
                log.warning(
                    "send_failed",
                    extra={"fields": {"channel": alias, "kind": e.kind, "status": e.status}},
                )
                raise ExecutionRolledBack from None
            status = "unknown"
            log.warning(
                "send_unknown",
                extra={"fields": {"channel": alias, "kind": e.kind, "status": e.status}},
            )
        await self._finish(intent.intent_id, status, detail)  # type: ignore[arg-type]
        out: dict[str, Any] = {
            "ok": True,
            "op": OP,
            "channel": alias,
            "delivery": status,
            "text_sha256": sha,
        }
        if status == "sent":
            out["message_ref"] = detail
        else:
            out["notice"] = (
                "Không xác nhận được tin đã đến nhóm hay chưa. Hãy kiểm tra trong nhóm trước khi gửi lại; "
                "hệ thống sẽ không tự gửi lại."
            )
        return out

    async def _finish(self, intent_id: str, status: str, detail: str) -> None:
        try:
            await self._svc.deliveries.finish(intent_id, status, detail)  # type: ignore[arg-type]
        except DeliveryLogUnavailable:
            # tin đã có kết quả; dòng `sending` còn lại được coi là "không chắc" khi tra cứu
            log.warning("delivery_log_finish_failed", extra={"fields": {"intent_id": intent_id}})

    async def applied_details(self, intent_id: str, principal: Principal) -> dict[str, Any] | None:
        rec = await self._svc.deliveries.find(intent_id)
        if rec is None or rec.status == "failed":
            return None
        return {"already_applied": True, "channel": rec.channel, "delivery": rec.status}
