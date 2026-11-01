"""Catalog alias model đọc từ `config/models.yaml` (contracts §5). Không có tên vendor trong code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import GatewayError


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
        return Resolved(
            requested=requested,
            alias=alias,
            chain=tuple(chain),
            timeout_s=float(spec.get("timeout_s", 60)),
            default_max_output=int(spec.get("default_max_output", self._default_max_output)),
        )
