"""Kiểu dữ liệu trung lập dùng chung ở biên các port (không phụ thuộc vendor)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """Danh tính đã xác minh của một token (contracts §2)."""

    sub: str
    audience: tuple[str, ...]
    azp: str | None
    scopes: frozenset[str]
    expires_at: float  # epoch giây (claim `exp`)
    sid: str | None = None
    dept: tuple[str, ...] = ()
    clearance: int | None = None
    roles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AccessToken:
    """Token đã đổi cho đúng một audience. `value` không bao giờ xuất hiện trong repr/log."""

    value: str
    audience: str
    scopes: frozenset[str]
    expires_at: float  # epoch giây
    sub: str

    def __repr__(self) -> str:
        return (
            f"AccessToken(audience={self.audience!r}, scopes={sorted(self.scopes)!r}, "
            f"sub={self.sub!r}, expires_at={self.expires_at})"
        )


@dataclass(frozen=True, slots=True)
class LimitDecision:
    """Kết quả `RateLimiter`: `allowed=False` thì caller trả 429 kèm `Retry-After`."""

    allowed: bool
    remaining: float = 0.0
    retry_after_s: float = 0.0
