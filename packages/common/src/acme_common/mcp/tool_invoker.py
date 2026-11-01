"""`ToolInvoker`: lớp cụ thể (không phải port) bọc handler nghiệp vụ.

Chuỗi: validate schema (jsonschema 2020-12) -> scope lần 2 -> rate limit theo user (`RateLimiter`)
-> timeout -> cắt output -> audit ở `finally` (cả khi bị từ chối/lỗi). Không dùng validator của SDK
nên SDK nào cũng cùng hành vi bảo mật. Message lỗi không chứa giá trị người dùng.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from ..ports.clock import Clock
from ..ports.event_sink import EventSink
from ..ports.rate_limiter import RateLimiter
from ..ports.tool_server_host import RawToolHandler, ToolResult, ToolSpec
from ..services.canonical import canonical_json
from .context import CallerContext, current_auth, thread_id_from_meta
from .errors import ToolError

log = logging.getLogger("acme.mcp.invoker")

_MAX_STR_BYTES = 4096


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """Handler nghiệp vụ có thể trả `dict` thuần, hoặc `ToolOutput` kèm thông tin cho audit
    (`tables_read`, `tables_written`, `rows_returned`, `intent_id`, ...; không chứa nội dung)."""

    data: dict[str, Any]
    audit: dict[str, Any] = field(default_factory=dict)


BusinessHandler = Callable[
    [CallerContext, dict[str, Any]], Awaitable["dict[str, Any] | ToolOutput"]
]


def _cut_str(s: str) -> str:
    b = s.encode("utf-8")
    return s if len(b) <= _MAX_STR_BYTES else b[:_MAX_STR_BYTES].decode("utf-8", "ignore")


def _cap_strings(v: Any) -> Any:
    if isinstance(v, str):
        return _cut_str(v)
    if isinstance(v, dict):
        return {k: _cap_strings(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_cap_strings(x) for x in v]
    return v


def _size(data: Mapping[str, Any]) -> int:
    return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def truncate_output(data: dict[str, Any], max_bytes: int) -> tuple[dict[str, Any], bool, int]:
    """Cắt theo phần tử (bỏ bớt cuối danh sách lớn nhất, không cắt giữa chuỗi) cho đến khi vừa.
    Trả `(data, truncated, omitted)`. Raise `ToolError(internal_error)` nếu không cắt được."""
    data = _cap_strings(data)
    if _size(data) <= max_bytes:
        return data, False, 0
    out = dict(data)
    omitted = 0
    lists = {k: list(v) for k, v in out.items() if isinstance(v, list)}
    while True:
        probe = {**out, **lists, "truncated": True, "omitted": omitted}
        if _size(probe) <= max_bytes:
            return probe, True, omitted
        # danh sách còn phần tử và đang chiếm nhiều nhất
        cand = [k for k, v in lists.items() if v]
        if not cand:
            raise ToolError("internal_error", "output_too_large")
        k = max(cand, key=lambda x: _size({x: lists[x]}))
        lists[k].pop()
        omitted += 1


class ToolInvoker:
    def __init__(
        self,
        *,
        server: str,
        limiter: RateLimiter,
        audit: EventSink,
        clock: Clock,
        rl_capacity: int = 30,
        rl_refill_per_s: float = 1.0,
        audit_sync: bool = True,
    ) -> None:
        self.server = server
        self._limiter = limiter
        self._audit = audit
        self._clock = clock
        self._capacity = rl_capacity
        self._window_s = rl_capacity / rl_refill_per_s
        self._audit_sync = audit_sync
        self.audit_failures = 0  # => metric mcp_audit_fail_total

    def wrap(self, spec: ToolSpec, handler: BusinessHandler) -> RawToolHandler:
        validator = Draft202012Validator(dict(spec.input_schema))
        Draft202012Validator.check_schema(dict(spec.input_schema))

        async def raw(arguments: Mapping[str, Any], meta: Mapping[str, Any]) -> ToolResult:
            return await self._invoke(spec, validator, handler, dict(arguments), meta)

        return raw

    # --- pipeline ---
    async def _invoke(
        self,
        spec: ToolSpec,
        validator: Draft202012Validator,
        handler: BusinessHandler,
        args: dict[str, Any],
        meta: Mapping[str, Any],
    ) -> ToolResult:
        t0 = self._clock.monotonic()
        auth = current_auth()
        info: dict[str, Any] = {}
        error: ToolError | None = None
        result = ToolResult({}, True)
        try:
            if auth is None:
                raise ToolError("unauthorized", "no authenticated principal")
            caller = CallerContext(auth.principal, auth.request_id, thread_id_from_meta(meta))
            # 1. schema
            errs = sorted(validator.iter_errors(args), key=lambda e: list(e.absolute_path))
            if errs:
                fields = sorted({".".join(str(p) for p in e.absolute_path) or "$" for e in errs})
                raise ToolError(
                    "invalid_argument", "arguments rejected", details={"fields": fields[:10]}
                )
            # 2. scope
            missing = sorted(set(spec.required_scopes) - auth.principal.scopes)
            if missing:
                raise ToolError("forbidden", "missing scope", details={"scope": missing})
            # 3. rate limit theo user
            dec = await self._limiter.reserve(
                f"mcp:rl:{self.server}:{auth.principal.sub}",
                spec.cost,
                limit=self._capacity,
                window_s=self._window_s,
            )
            if not dec.allowed:
                raise ToolError(
                    "rate_limited",
                    "too many requests",
                    details={"retry_after_s": max(1, math.ceil(dec.retry_after_s))},
                )
            # 4. timeout
            try:
                async with asyncio.timeout(spec.timeout_s):
                    out = await handler(caller, args)
            except TimeoutError:
                raise ToolError(spec.timeout_code, "timed out") from None
            if isinstance(out, ToolOutput):
                data, info = out.data, dict(out.audit)
            else:
                data = out
            # 5. cắt output
            data, truncated, omitted = truncate_output(data, spec.max_output_bytes)
            info["truncated"] = truncated
            if truncated:
                info["omitted"] = omitted
            info["bytes_out"] = _size(data)
            result = ToolResult(data, False)
        except ToolError as e:
            error = e
            result = ToolResult(e.to_payload(), True)
        except Exception:  # noqa: BLE001 - lỗi lạ: không lộ chi tiết ra ngoài
            log.exception("tool %s crashed", spec.name)
            error = ToolError("internal_error", "internal error")
            result = ToolResult(error.to_payload(), True)
        finally:
            duration_ms = int((self._clock.monotonic() - t0) * 1000)
            await self._write_audit(spec, auth, meta, args, error, info, duration_ms)
        return result

    async def _write_audit(
        self,
        spec: ToolSpec,
        auth: Any,
        meta: Mapping[str, Any],
        args: dict[str, Any],
        error: ToolError | None,
        info: dict[str, Any],
        duration_ms: int,
    ) -> None:
        try:
            p = auth.principal if auth else None
            args_hash = hashlib.sha256(
                json.dumps(args, sort_keys=True, ensure_ascii=False, default=str).encode()
            ).hexdigest()
            info = dict(info)
            intent_id = info.pop("intent_id", None)
            details = {
                "server": self.server,
                "tool": spec.name,
                "args_sha256": args_hash,
                "error_code": error.code if error else None,
                "duration_ms": duration_ms,
                "azp": p.azp if p else None,
                "depts": list(p.dept) if p else [],
                "thread_id": thread_id_from_meta(meta),
                **info,
            }
            canonical_json(details)  # fail sớm nếu có float: audit hash-chain cấm float
            record = {
                "event": "tool_audit",
                "ts": self._clock.now(),
                "request_id": auth.request_id if auth else None,
                "actor_type": "service",
                "actor_id": (p.azp if p and p.azp else self.server),
                "end_user_sub": p.sub if p else None,
                "action": "tool.call",
                "resource": spec.name,
                "decision": error.decision if error else "allow",
                "details": details,
                "intent_id": intent_id,
            }
            if self._audit_sync:
                await asyncio.to_thread(self._audit.append, record, True)
            else:
                self._audit.append(record, False)
        except Exception:  # noqa: BLE001 - audit đọc/ghi lỗi không làm hỏng lời gọi (tăng metric)
            self.audit_failures += 1
            log.exception("tool audit write failed")
