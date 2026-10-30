"""Dependency FastAPI: container, phiên, CSRF, rate limit. Mỏng, gọi services (07 §2.1)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request, Response

from ..factory import Container
from ..services.csrf import csrf_valid
from ..services.errors import ApiError
from ..services.session import SessionData
from ..settings import Settings

SAFE = frozenset({"GET", "HEAD", "OPTIONS"})


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


@dataclass(frozen=True)
class CookieNames:
    sid: str
    csrf: str
    login: str

    @classmethod
    def for_settings(cls, settings: Settings) -> CookieNames:
        # `__Host-` bắt buộc Secure; dev chạy http thì dùng tên không tiền tố (07 §2.2)
        if settings.https:
            return cls("__Host-sid", "__Host-csrf", "__Host-login")
        return cls("sid", "csrf", "login")


def set_cookie(
    resp: Response,
    settings: Settings,
    name: str,
    value: str,
    *,
    httponly: bool,
    samesite: str,
    max_age: int | None = None,
) -> None:
    resp.set_cookie(
        name,
        value,
        httponly=httponly,
        secure=settings.https,
        samesite=samesite,  # type: ignore[arg-type]
        path="/",
        max_age=max_age,
    )


def clear_cookie(
    resp: Response, settings: Settings, name: str, *, httponly: bool, samesite: str
) -> None:
    resp.delete_cookie(
        name,
        path="/",
        secure=settings.https,
        httponly=httponly,
        samesite=samesite,  # type: ignore[arg-type]
    )


def session_dependency(
    bucket: str | None, *, csrf: bool
) -> Callable[[Request, Container], Awaitable[SessionData]]:
    async def dep(request: Request, c: Container = Depends(get_container)) -> SessionData:
        names = CookieNames.for_settings(c.settings)
        sid = request.cookies.get(names.sid, "")
        session = await c.store.load(sid)
        if session is None:
            raise ApiError(401, "session_expired")
        if csrf and request.method not in SAFE:
            ok = csrf_valid(
                c.crypto,
                sid=session.sid,
                header=request.headers.get("x-csrf-token"),
                cookie=request.cookies.get(names.csrf),
            )
            if not ok:
                raise ApiError(403, "csrf_failed")
        if bucket:
            await c.limits.check(session.sid, bucket)
        return session

    return dep


read_session = session_dependency("read", csrf=False)
write_session = session_dependency("write", csrf=True)
llm_session = session_dependency("llm", csrf=True)
csrf_session = session_dependency(None, csrf=True)
