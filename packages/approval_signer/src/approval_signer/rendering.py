"""Dựng render model từ payload intent đã verify. Thuần hàm, không I/O.

Mẫu cố định theo `op`; `display_fields` phủ MỌI khoá của `args_canonical` và `before/after`.
Có khoá lạ / kiểu lạ / giá trị không hiển thị được => `intent_unrenderable`.
Ký tự điều khiển, bidi, zero-width trong phần `display` được escape thành `\\uXXXX` (hiển thị được).
"""

from __future__ import annotations

import json
import unicodedata
from datetime import UTC, datetime
from typing import Any

from .ports import RenderModel, SignerError, VerifiedIntent

# op -> (title, khoá args -> (label, kind), khoá before/after -> (label, kind))
_Spec = dict[str, tuple[str, str]]
_TITLE_LABEL = ("Tiêu đề", "text")
_OPS: dict[str, tuple[str, _Spec, _Spec]] = {
    "create_ticket": (
        "Tạo ticket mới",
        {
            "title": _TITLE_LABEL,
            "body": ("Mô tả", "longtext"),
            "category": ("Loại", "enum"),
            "priority": ("Ưu tiên", "enum"),
            "assignee_dept": ("Phòng xử lý", "text"),
            "classification": ("Mức mật", "enum"),
        },
        {
            "title": _TITLE_LABEL,
            "body": ("Mô tả", "longtext"),
            "category": ("Loại", "enum"),
            "priority": ("Ưu tiên", "enum"),
            "assignee_dept": ("Phòng xử lý", "text"),
            "classification": ("Mức mật", "enum"),
            "status": ("Trạng thái", "enum"),
        },
    ),
    "add_comment": (
        "Thêm bình luận vào {code}",
        {
            "code": ("Ticket", "ticket_ref"),
            "body": ("Nội dung bình luận", "longtext"),
            "internal": ("Nội bộ", "enum"),
        },
        {
            "title": _TITLE_LABEL,
            "body": ("Nội dung bình luận", "longtext"),
            "internal": ("Nội bộ", "enum"),
        },
    ),
    "update_status": (
        "Đổi trạng thái {code}",
        {
            "code": ("Ticket", "ticket_ref"),
            "status": ("Trạng thái mới", "enum"),
            "reason": ("Lý do", "longtext"),
        },
        {
            "title": _TITLE_LABEL,
            "status": ("Trạng thái", "enum"),
            "reason": ("Lý do", "longtext"),
        },
    ),
    "close_ticket": (
        "Đóng ticket {code}",
        {"code": ("Ticket", "ticket_ref"), "resolution": ("Cách xử lý", "longtext")},
        {
            "title": _TITLE_LABEL,
            "status": ("Trạng thái", "enum"),
            "resolution": ("Cách xử lý", "longtext"),
        },
    ),
}
# Gắn op với issuer: op chỉ được nhận từ MCP sở hữu nó. Thêm MCP ghi mới = thêm một dòng ở đây
# (và `_AUD_BY_INTENT_ISS` ở adapters/es256_jwt.py), cùng thư mục khoá `INTENT_PUBLIC_KEYS_DIR/<iss>/`.
ISSUER_OPS: dict[str, frozenset[str]] = {
    "tickets-mcp": frozenset({"create_ticket", "add_comment", "update_status", "close_ticket"}),
}
_TARGET: _Spec = {"ticket_code": ("Ticket", "ticket_ref"), "title": _TITLE_LABEL}
_MAX_STR = 8192
_ESCAPE_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}  # gồm bidi, zero-width, C0/C1
_RISKS = {"low", "medium", "high"}


def escape_text(value: str, *, keep_newlines: bool = False) -> str:
    """Thay ký tự điều khiển/định dạng (bidi U+202A-202E, U+2066-2069, zero-width, C0/C1) bằng `\\uXXXX`."""
    out: list[str] = []
    for ch in value:
        if keep_newlines and ch in "\n\t":
            out.append(ch)
        elif unicodedata.category(ch) in _ESCAPE_CATEGORIES:
            cp = ord(ch)
            out.append(f"\\u{cp:04x}" if cp <= 0xFFFF else f"\\U{cp:08x}")
        else:
            out.append(ch)
    return "".join(out)


def _unrenderable(*fields: str) -> SignerError:
    return SignerError("intent_unrenderable", fields=sorted(set(fields)))


def _scalar(value: Any, path: str) -> Any:
    ok = value is None or isinstance(value, (bool, int, str))
    if not ok or (isinstance(value, str) and len(value) > _MAX_STR):
        raise _unrenderable(path)
    return value


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _unrenderable(path)
    return value


def _shown(value: Any, kind: str) -> Any:
    if isinstance(value, str):
        return escape_text(value, keep_newlines=kind == "longtext")
    return value


def _field(
    path: str, spec: tuple[str, str], before: Any, after: Any, *, sensitive: bool = False
) -> dict[str, Any]:
    label, kind = spec
    return {
        "path": path,
        "label": label,
        "kind": kind,
        "before": _shown(before, kind),
        "after": _shown(after, kind),
        "changed": before != after,
        "sensitive": sensitive,
    }


def build_render_model(intent: VerifiedIntent, now: datetime) -> RenderModel:
    p = intent.payload
    op = p.get("op")
    if op not in _OPS:
        raise _unrenderable("op")
    title_tpl, arg_spec, ba_spec = _OPS[op]
    target = _mapping(p.get("target"), "target")
    before = _mapping(p.get("before"), "before")
    after = _mapping(p.get("after"), "after")
    raw_args = p.get("args_canonical")
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else None
    except ValueError:
        args = None
    args = _mapping(args, "args_canonical")

    bad = [f"target.{k}" for k in target if k not in _TARGET]
    bad += [f"before.{k}" for k in before if k not in ba_spec]
    bad += [f"after.{k}" for k in after if k not in ba_spec]
    bad += [f"args.{k}" for k in args if k not in arg_spec]
    if bad:
        raise _unrenderable(*bad)
    if not after or not args:
        raise _unrenderable("after" if not after else "args_canonical")
    if op != "create_ticket" and "ticket_code" not in target:
        raise _unrenderable("target.ticket_code")
    for group, prefix in ((target, "target"), (before, "before"), (after, "after"), (args, "args")):
        for k, v in group.items():
            _scalar(v, f"{prefix}.{k}")

    flags = p.get("risk_flags", [])
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise _unrenderable("risk_flags")
    internal = args.get("internal") is True

    fields = [_field(f"target.{k}", _TARGET[k], v, v) for k, v in target.items()]
    fields += [
        _field(f"args.{k}", arg_spec[k], None, v, sensitive=internal and k == "body")
        for k, v in args.items()
    ]
    keys = sorted(set(before) | set(after))
    fields += [
        _field(
            f"after.{k}",
            ba_spec[k],
            before.get(k),
            after.get(k),
            sensitive=internal and k == "body",
        )
        for k in keys
    ]
    diff = [
        {
            "field": k,
            "before": _shown(before.get(k), ba_spec[k][1]),
            "after": _shown(after.get(k), ba_spec[k][1]),
        }
        for k in keys
        if before.get(k) != after.get(k)
    ]
    risk = p.get("risk")
    if risk not in _RISKS:
        risk = (
            "high"
            if "possible_downgrade" in flags
            else ("medium" if op == "close_ticket" else "low")
        )
    code = escape_text(str(target.get("ticket_code") or args.get("code") or ""))
    try:
        exp = datetime.fromtimestamp(int(p["exp"]), UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise _unrenderable("exp") from None
    return RenderModel(
        intent_id=intent.intent_id,
        op=op,
        target=target,
        before=before,
        after=after,
        risk_flags=list(flags),
        expires_at=exp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        intent_sha256=intent.sha256,
        server_time=now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        display={
            "title": title_tpl.format(code=code),
            "risk": risk,
            "display_fields": fields,
            "diff": diff,
        },
    )
