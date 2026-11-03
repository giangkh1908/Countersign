"""Catalog alias model đọc từ `config/models.yaml` (contracts §8). Không có tên vendor trong code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import GatewayError


@dataclass(frozen=True, slots=True)
class Price:
    """Bảng giá của một alias: USD trên 1 triệu token (đầu ra = 0 với embedding/rerank)."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0


def _parse_price(alias: str, raw: Any) -> Price | None:
    """Đọc block `price` của alias; None nếu không khai báo. Sai kiểu/âm -> GatewayError."""
    if raw is None:
        return None
    bad = GatewayError("invalid_request", f"Alias '{alias}': price is invalid.")
    if not isinstance(raw, dict) or set(raw) - {"input_per_mtok", "output_per_mtok"}:
        raise bad
    vals: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(v, bool) or not isinstance(v, int | float) or v < 0 or v != v:
            raise bad
        vals[k] = float(v)
    return Price(**vals)


@dataclass(frozen=True, slots=True)
class ModelRef:
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class Resolved:
    requested: str  # alias client gửi
    alias: str
    chain: tuple[ModelRef, ...]
    timeout_s: float
    default_max_output: int
    extra_body: dict[str, Any] = field(
        default_factory=dict
    )  # tham số riêng theo alias, gateway không hiểu nội dung
    price: Price | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingSpec:
    """Block `kind: embedding` của một alias: adapter, id model, số chiều và tuỳ chọn riêng adapter."""

    alias: str
    adapter: str
    model: str
    dim: int
    options: dict[str, Any]  # phần còn lại của block (vd base_url); adapter tự chọn phần cần
    price: Price | None = None


@dataclass(frozen=True, slots=True)
class RerankSpec:
    """Block `kind: rerank` của một alias: adapter, id model và tuỳ chọn riêng adapter."""

    alias: str
    adapter: str
    model: str
    options: dict[str, Any]
    price: Price | None = None


class ModelCatalog:
    def __init__(self, data: dict[str, Any], provider_override: str | None = None) -> None:
        self._aliases: dict[str, dict[str, Any]] = dict(data.get("aliases") or {})
        self._default_max_output = int(data.get("default_max_output") or 4096)
        self._override = provider_override or None

    @classmethod
    def from_file(cls, path: str | Path, provider_override: str | None = None) -> ModelCatalog:
        with open(path, encoding="utf8") as f:
            return cls(yaml.safe_load(f) or {}, provider_override)

    def aliases(self) -> list[str]:
        return sorted(self._aliases)

    def embedding(self, requested: str) -> EmbeddingSpec:
        spec = self._aliases.get(requested)
        if spec is None or spec.get("kind") != "embedding":
            raise GatewayError("invalid_request", f"Unknown embedding model '{requested}'.")
        reserved = {"kind", "adapter", "model", "dim", "price"}
        return EmbeddingSpec(
            alias=requested,
            adapter=str(spec.get("adapter", "")),
            model=str(spec.get("model", "")),
            dim=int(spec.get("dim", 1024)),
            options={k: v for k, v in spec.items() if k not in reserved},
            price=_parse_price(requested, spec.get("price")),
        )

    def rerank(self, requested: str) -> RerankSpec:
        spec = self._aliases.get(requested)
        if spec is None or spec.get("kind") != "rerank":
            raise GatewayError("invalid_request", f"Unknown rerank model '{requested}'.")
        reserved = {"kind", "adapter", "model", "price"}
        return RerankSpec(
            alias=requested,
            adapter=str(spec.get("adapter", "")),
            model=str(spec.get("model", "")),
            options={k: v for k, v in spec.items() if k not in reserved},
            price=_parse_price(requested, spec.get("price")),
        )

    def resolve(self, requested: str) -> Resolved:
        alias = requested
        spec = self._aliases.get(alias)
        if spec is None:
            raise GatewayError("invalid_request", f"Unknown model alias '{requested}'.")
        chain: list[ModelRef] = []
        for item in spec.get("chain") or []:
            provider, _, model = str(item).partition("/")
            chain.append(ModelRef(self._override or provider, model))
        if not chain:
            raise GatewayError("invalid_request", f"Alias '{requested}' is not available.")
        extra_body = spec.get("extra_body") or {}
        if not isinstance(extra_body, dict):
            raise GatewayError(
                "invalid_request", f"Alias '{requested}': extra_body must be a mapping."
            )
        return Resolved(
            requested=requested,
            alias=alias,
            chain=tuple(chain),
            timeout_s=float(spec.get("timeout_s", 60)),
            default_max_output=int(spec.get("default_max_output", self._default_max_output)),
            extra_body=dict(extra_body),
            price=_parse_price(requested, spec.get("price")),
        )
