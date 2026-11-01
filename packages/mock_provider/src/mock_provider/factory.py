"""Factory của mock_provider: chọn wire format theo tên bằng registry dict + lazy import.

Mock_provider là service đứng riêng (không phải port của gateway) nên không có ABC; factory chỉ
gom các router wire-format. Thêm format mới = thêm một file trong `adapters/` + một dòng ở đây.
"""

from collections.abc import Callable

from fastapi import APIRouter

from .behavior import Context


def _load_anthropic(ctx: Context) -> APIRouter:
    from .adapters.anthropic import router

    return router(ctx)


def _load_openai(ctx: Context) -> APIRouter:
    from .adapters.openai import router

    return router(ctx)


def _load_gemini(ctx: Context) -> APIRouter:
    from .adapters.gemini import router

    return router(ctx)


_REGISTRY: dict[str, Callable[[Context], APIRouter]] = {
    "anthropic": _load_anthropic,
    "openai": _load_openai,
    "gemini": _load_gemini,
}


class WireNotConfigured(ValueError):
    pass


def build_router(name: str, ctx: Context) -> APIRouter:
    try:
        loader = _REGISTRY[name]
    except KeyError:
        raise WireNotConfigured(f"wire '{name}' không có; hợp lệ: {sorted(_REGISTRY)}") from None
    return loader(ctx)


def wire_names() -> list[str]:
    return sorted(_REGISTRY)
