"""Cấu hình kênh báo cáo (actions-roles.md §3). Khai báo ở server; agent chỉ thấy bí danh, không thấy chat ID.

```yaml
channels:
  dept-eng:    { adapter: telegram, chat_ref: TG_CHAT_ENG, scope: dept, dept: ENG, max_class: 1 }
  company-all: { adapter: telegram, chat_ref: TG_CHAT_ALL, scope: company, max_class: 0 }
```

`chat_ref` là TÊN biến môi trường (hoặc `<TÊN>_FILE`) chứa chat ID thật. Kênh nằm ngoài hạ tầng công ty
nên `max_class` bị chặn <= `MAX_EXTERNAL_CLASS` lúc nạp: khai cao hơn thì service không khởi động.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

MAX_EXTERNAL_CLASS = 1
_ALIAS = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_REF = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_DEPT = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
_KEYS = {"adapter", "chat_ref", "scope", "dept", "max_class"}


class ChannelConfigError(ValueError):
    """Cấu hình kênh sai. Message không chứa giá trị bí mật."""


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    alias: str
    adapter: str
    chat_ref: str
    scope: Literal["dept", "company"]
    dept: str | None
    max_class: int


def parse_channels(raw: Any) -> dict[str, ChannelConfig]:
    chans = raw.get("channels") if isinstance(raw, dict) else None
    if not isinstance(chans, dict) or not chans:
        raise ChannelConfigError("channels: cần một map không rỗng")
    out: dict[str, ChannelConfig] = {}
    for alias, c in chans.items():
        if not isinstance(alias, str) or not _ALIAS.fullmatch(alias):
            raise ChannelConfigError("channels: bí danh kênh không hợp lệ")
        if not isinstance(c, dict) or set(c) - _KEYS:
            raise ChannelConfigError(f"channels.{alias}: khoá không hợp lệ")
        adapter, ref, scope = c.get("adapter"), c.get("chat_ref"), c.get("scope")
        if not isinstance(adapter, str) or not adapter:
            raise ChannelConfigError(f"channels.{alias}: thiếu adapter")
        if not isinstance(ref, str) or not _REF.fullmatch(ref):
            raise ChannelConfigError(f"channels.{alias}: chat_ref phải là TÊN biến (A-Z, 0-9, _)")
        if scope not in ("dept", "company"):
            raise ChannelConfigError(f"channels.{alias}: scope phải là dept hoặc company")
        dept = c.get("dept")
        if scope == "dept" and not (isinstance(dept, str) and _DEPT.fullmatch(dept)):
            raise ChannelConfigError(f"channels.{alias}: scope dept cần dept hợp lệ")
        if scope == "company" and dept is not None:
            raise ChannelConfigError(f"channels.{alias}: scope company không có dept")
        mc = c.get("max_class")
        if not isinstance(mc, int) or isinstance(mc, bool) or not 0 <= mc <= MAX_EXTERNAL_CLASS:
            raise ChannelConfigError(
                f"channels.{alias}: max_class phải là số nguyên trong [0, {MAX_EXTERNAL_CLASS}] "
                "(kênh ngoài hạ tầng công ty)"
            )
        out[alias] = ChannelConfig(alias, adapter, ref, scope, dept, mc)
    return out


def load_channels(path: str | Path) -> dict[str, ChannelConfig]:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise ChannelConfigError("không đọc được file cấu hình kênh") from None
    return parse_channels(raw)


def env_chat_resolver(ref: str) -> str | None:
    """Tra chat ID từ biến môi trường `<ref>` hoặc file `<ref>_FILE`."""
    path = os.environ.get(f"{ref}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return os.environ.get(ref) or None
