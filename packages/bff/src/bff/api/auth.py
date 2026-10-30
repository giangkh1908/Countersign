"""Router đăng nhập/callback/logout. Mỏng, gọi services. Docs: 07 §2.3, §2.6."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..factory import Container
from ..services.auth import LoginFailed
from ..services.session import SessionData
from .deps import CookieNames, clear_cookie, csrf_session, get_container, set_cookie

router = APIRouter()

LOGIN_COOKIE_TTL_S = 600


def _client_ip(request: Request, trusted_proxy: bool) -> str:
    if trusted_proxy:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _login_error(c: Container, code: str) -> RedirectResponse:
    resp = RedirectResponse(f"/login-error?code={quote(code)}", status_code=302)
    clear_cookie(
        resp, c.settings, CookieNames.for_settings(c.settings).login, httponly=True, samesite="lax"
    )
    return resp


@router.get("/auth/login")
async def login(
    request: Request, return_to: str = "/", c: Container = Depends(get_container)
) -> RedirectResponse:
    await c.limits.check_login(_client_ip(request, c.settings.bff_trusted_proxy))
    try:
        started = await c.auth.start(return_to)
    except LoginFailed as exc:
        return _login_error(c, exc.code)
    resp = RedirectResponse(started.authorize_url, status_code=302)
    set_cookie(
        resp,
        c.settings,
        CookieNames.for_settings(c.settings).login,
        started.state,
        httponly=True,
        samesite="lax",
        max_age=LOGIN_COOKIE_TTL_S,
    )
    return resp


@router.get("/auth/callback")
async def callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    c: Container = Depends(get_container),
) -> RedirectResponse:
    names = CookieNames.for_settings(c.settings)
    if error:
        return _login_error(c, "token_error")
    try:
        done = await c.auth.complete(code, state, request.cookies.get(names.login))
    except LoginFailed as exc:
        return _login_error(c, exc.code)
    resp = RedirectResponse(done.return_to, status_code=302)
    set_cookie(resp, c.settings, names.sid, done.sid, httponly=True, samesite="strict")
    set_cookie(resp, c.settings, names.csrf, done.csrf, httponly=False, samesite="strict")
    clear_cookie(resp, c.settings, names.login, httponly=True, samesite="lax")
    return resp


@router.post("/auth/logout")
async def logout(
    s: SessionData = Depends(csrf_session), c: Container = Depends(get_container)
) -> JSONResponse:
    redirect_url = await c.auth.logout(s)
    names = CookieNames.for_settings(c.settings)
    resp = JSONResponse({"redirect_url": redirect_url})
    clear_cookie(resp, c.settings, names.sid, httponly=True, samesite="strict")
    clear_cookie(resp, c.settings, names.csrf, httponly=False, samesite="strict")
    return resp
