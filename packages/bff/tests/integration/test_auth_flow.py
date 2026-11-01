"""Đăng nhập/callback/logout, cookie, phiên, refresh, hết hạn."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from bff_harness import PUBLIC, Env, build_env, make_settings


def _set_cookie(resp, name: str) -> str:
    for raw in resp.headers.get_list("set-cookie"):
        if raw.startswith(f"{name}="):
            return raw
    raise AssertionError(f"no Set-Cookie for {name}")


async def test_login_redirects_with_pkce_state_nonce_and_login_cookie(env: Env) -> None:
    r = await env.browser.get("/auth/login?return_to=/chat")
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["client_id"] == ["chat-ui"] and q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"][0]
    assert q["state"][0] and q["nonce"][0]
    assert q["redirect_uri"] == [f"{PUBLIC}/auth/callback"]
    cookie = _set_cookie(r, "__Host-login")
    assert q["state"][0] in cookie and "HttpOnly" in cookie and "Secure" in cookie
    assert "samesite=lax" in cookie.lower() and "Max-Age=600" in cookie


async def test_login_return_to_open_redirect_is_neutralised(env: Env) -> None:
    start = await env.browser.get("/auth/login?return_to=//evil.example/x")
    q = parse_qs(urlsplit(start.headers["location"]).query)
    env.idp.nonce = q["nonce"][0]
    done = await env.browser.get(f"/auth/callback?code=c&state={q['state'][0]}")
    assert done.headers["location"] == "/"


async def test_callback_creates_session_with_strict_cookies(env: Env) -> None:
    done = await env.browser.login(env.idp)
    assert done.headers["location"] == "/chat"
    sid = _set_cookie(done, "__Host-sid")
    assert "HttpOnly" in sid and "Secure" in sid and "samesite=strict" in sid.lower()
    assert (
        "Path=/" in sid
        and "Domain" not in sid
        and "Max-Age" not in sid
        and "expires" not in sid.lower()
    )
    csrf = _set_cookie(done, "__Host-csrf")
    assert "HttpOnly" not in csrf and "Secure" in csrf and "samesite=strict" in csrf.lower()
    assert "Max-Age=0" in _set_cookie(done, "__Host-login")  # cookie đăng nhập bị xoá

    sid_value = env.browser.client.cookies.get("__Host-sid")
    raw = await env.redis.hgetall(f"bff:sess:{sid_value}")
    assert raw["sub"] == "user-1" and raw["v"] == "1"
    for field in ("access_enc", "refresh_token_enc", "id_token_enc"):
        assert raw[field]
    blob = "".join(raw.values())
    assert not any(tok in blob for tok in env.idp.issued), "token phải mã hoá trong Redis"


async def test_each_login_gets_a_fresh_sid(env: Env) -> None:
    await env.browser.login(env.idp)
    first = env.browser.client.cookies.get("__Host-sid")
    await env.browser.login(env.idp)
    assert env.browser.client.cookies.get("__Host-sid") != first


async def test_callback_state_must_match_login_cookie_and_is_single_use(env: Env) -> None:
    start = await env.browser.get("/auth/login")
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    env.browser.client.cookies.delete("__Host-login")
    bad = await env.browser.get(f"/auth/callback?code=c&state={state}")
    assert bad.status_code == 302 and bad.headers["location"] == "/login-error?code=state_mismatch"

    start = await env.browser.get("/auth/login")
    q = parse_qs(urlsplit(start.headers["location"]).query)
    env.idp.nonce = q["nonce"][0]
    ok = await env.browser.get(f"/auth/callback?code=c&state={q['state'][0]}")
    assert ok.headers["location"] == "/"
    env.browser.client.cookies.set("__Host-login", q["state"][0], domain="bff.test")
    replay = await env.browser.get(f"/auth/callback?code=c&state={q['state'][0]}")
    assert replay.headers["location"] == "/login-error?code=state_mismatch"


async def test_callback_nonce_mismatch_is_rejected(env: Env) -> None:
    start = await env.browser.get("/auth/login")
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    env.idp.nonce = "attacker-nonce"
    r = await env.browser.get(f"/auth/callback?code=c&state={state}")
    assert r.headers["location"] == "/login-error?code=token_error"
    assert "__Host-sid" not in env.browser.client.cookies


async def test_dev_http_uses_unprefixed_non_secure_cookies() -> None:
    e = await build_env(make_settings(acme_env="dev", bff_public_url="http://bff.test"))
    try:
        e.browser.sid_cookie, e.browser.csrf_cookie = "sid", "csrf"
        e.browser.client.base_url = "http://bff.test"
        start = await e.browser.get("/auth/login", origin="http://bff.test")
        q = parse_qs(urlsplit(start.headers["location"]).query)
        e.idp.nonce = q["nonce"][0]
        done = await e.browser.get(f"/auth/callback?code=c&state={q['state'][0]}")
        sid = _set_cookie(done, "sid")
        assert "Secure" not in sid and "HttpOnly" in sid and "samesite=strict" in sid.lower()
        assert "Strict-Transport-Security" not in done.headers
    finally:
        await e.browser.client.aclose()
        await e.container.aclose()


async def test_me_returns_profile_and_csrf_token(logged_in: Env) -> None:
    r = await logged_in.browser.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "user-1" and body["name"] == "Nguyễn A" and body["email"] == "a@acme.vn"
    assert body["roles"] == ["employee"] and body["depts"] == ["CS"] and body["clearance"] == 1
    assert body["csrf_token"] == logged_in.browser.client.cookies.get("__Host-csrf")
    assert body["link_allowlist"] == []
    assert {"idle_expires_at", "absolute_expires_at", "server_time"} <= body.keys()


async def test_no_cookie_is_session_expired(env: Env) -> None:
    r = await env.browser.get("/api/me")
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "session_expired" and err["retryable"] is False
    assert err["request_id"] == r.headers["x-request-id"]


async def test_absolute_expiry_is_session_expired(logged_in: Env) -> None:
    logged_in.clock.advance(logged_in.settings.bff_session_abs_s + 1)
    r = await logged_in.browser.get("/api/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_expired"
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    assert not await logged_in.redis.exists(f"bff:sess:{sid}")


async def test_idle_expiry_when_redis_key_gone(logged_in: Env) -> None:
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    await logged_in.redis.delete(f"bff:sess:{sid}")
    r = await logged_in.browser.get("/api/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_expired"


async def test_idle_ttl_is_sliding_and_capped_by_absolute(logged_in: Env) -> None:
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    await logged_in.browser.get("/api/me")
    assert 0 < await logged_in.redis.ttl(f"bff:sess:{sid}") <= logged_in.settings.bff_session_idle_s
    logged_in.clock.advance(logged_in.settings.bff_session_abs_s - 100)
    await logged_in.browser.get("/api/me")
    assert await logged_in.redis.ttl(f"bff:sess:{sid}") <= 100


async def test_access_token_refresh_rotates_and_is_used_for_exchange(logged_in: Env) -> None:
    logged_in.clock.advance(290)  # access (300s) còn < 60s
    r = await logged_in.browser.post(
        "/api/chat", json={"text": "hi", "client_msg_id": "5f6f6c0a-2a39-4a41-8a43-1f6f6d7e8a90"}
    )
    assert r.status_code == 200
    assert logged_in.idp.refresh_calls == 1
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    c = logged_in.container
    sess = await c.store.load(sid)
    assert sess.token("login")[0] == "ACCESS-secret-2"
    assert sess.open_field("refresh_token_enc") == "REFRESH-secret-2"  # xoay vòng


async def test_refresh_invalid_grant_destroys_session(logged_in: Env) -> None:
    logged_in.idp.fail_refresh = True
    logged_in.clock.advance(290)
    r = await logged_in.browser.post(
        "/api/chat", json={"text": "hi", "client_msg_id": "5f6f6c0a-2a39-4a41-8a43-1f6f6d7e8a90"}
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_expired"
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    assert not await logged_in.redis.exists(f"bff:sess:{sid}")


async def test_logout_revokes_evicts_clears_cookies_and_returns_end_session(logged_in: Env) -> None:
    sid = logged_in.browser.client.cookies.get("__Host-sid")
    r = await logged_in.browser.post("/auth/logout")
    assert r.status_code == 200
    url = r.json()["redirect_url"]
    q = parse_qs(urlsplit(url).query)
    assert q["post_logout_redirect_uri"] == [PUBLIC] and "id_token_hint" not in q
    assert logged_in.idp.revoked == ["REFRESH-secret-1"]
    assert "/v1/internal/evict" in logged_in.backends.paths("agent.test")
    assert "Max-Age=0" in _set_cookie(r, "__Host-sid")
    assert not [k async for k in logged_in.redis.scan_iter(match=f"bff:sess:{sid}*")]
    assert (await logged_in.browser.get("/api/me")).status_code == 401
