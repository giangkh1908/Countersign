"""Dựng khoá exact cache (cache-observability.md §1). Hàm thuần, không I/O.

    cache:v1:{ver}:{dept}:{clearance}:{roles}:{model}:{sha256}

- Phạm vi quyền (dept, clearance, roles) lấy từ `Principal` đã xác minh, ở dạng literal. Mỗi phần
  tử phải qua allowlist ký tự; sai thì KHÔNG cache (trả None), để `:` trong dept không tạo được
  khoá trùng của phạm vi khác.
- Phạm vi và model còn nằm cả trong chuỗi băm, nên dù phần literal có trùng thì digest vẫn khác.
- `ver` (GW_CACHE_INDEX_VERSION) tăng khi nạp lại index/đổi embedding: entry cũ không bao giờ trúng.
- Không cache khi: không có user token, request có tools/tool_choice, hội thoại đã chứa lượt tool.
- `strict=False` (nhánh `evidence-keyed` của RQ4) bỏ phạm vi khỏi khoá. CHỈ dùng trong harness
  đo; runtime của gateway luôn `strict=True`.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from acme_common.ports import Principal

KEY_PREFIX = "cache:v1"
_SAFE = re.compile(r"\A[A-Za-z0-9_.\-]{1,64}\Z")
_EMPTY = "~"  # không thuộc allowlist nên không trùng với giá trị thật
_TOOL_MARKERS = ("tool_calls", "tool_call_id", "function_call")


def valid_token(value: str) -> bool:
    return bool(_SAFE.match(value))


def _join(values: tuple[str, ...]) -> str | None:
    if not values:
        return _EMPTY
    if not all(valid_token(v) for v in values):
        return None
    return ",".join(sorted(set(values)))


def _has_tool_turn(messages: list[dict[str, Any]]) -> bool:
    return any(
        m.get("role") in ("tool", "function") or any(k in m for k in _TOOL_MARKERS)
        for m in messages
    )


def build_cache_key(
    *,
    user: Principal | None,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    index_version: str,
    strict: bool = True,
) -> str | None:
    """Trả khoá, hoặc None nếu request không đủ điều kiện cache."""
    if user is None or tools or tool_choice is not None or _has_tool_turn(messages):
        return None
    if not valid_token(index_version):
        return None
    dept = _join(user.dept)
    roles = _join(user.roles)
    if dept is None or roles is None:
        return None
    clearance = _EMPTY if user.clearance is None else str(int(user.clearance))
    if not strict:
        dept = roles = clearance = "*"
    model_seg = re.sub(r"[^A-Za-z0-9_.\-]", "_", f"{provider}.{model}")[:96]
    canonical = json.dumps(
        {
            "messages": messages,
            "params": params,
            "model": [provider, model],
            "scope": [dept, clearance, roles],
            "ver": index_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"{KEY_PREFIX}:{index_version}:{dept}:{clearance}:{roles}:{model_seg}:{digest}"
