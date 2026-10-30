"""CSRF, Origin, CSP/headers, kích thước body, không có mã ký trong BFF."""

from __future__ import annotations

import re
from pathlib import Path

from bff_harness import MSG_ID, PUBLIC, THREAD, Env, build_env, make_settings

CSP = (
    "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)
CHAT = {"text": "hi", "client_msg_id": MSG_ID}


async def test_missing_csrf_header_is_403(logged_in: Env) -> None:
    r = await logged_in.browser.post("/api/chat", json=CHAT, csrf=False)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


async def test_wrong_csrf_header_is_403(logged_in: Env) -> None:
    r = await logged_in.browser.post("/api/chat", json=CHAT, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


async def test_csrf_must_equal_cookie_and_session_hmac(logged_in: Env) -> None:
    # header == cookie nhưng không phải HMAC của phiên này (kẻ tấn công tự đặt cookie)
    logged_in.browser.client.cookies.set("__Host-csrf", "attacker", domain="bff.test")
    r = await logged_in.browser.post("/api/chat", json=CHAT, headers={"X-CSRF-Token": "attacker"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


async def test_csrf_covers_all_state_changing_methods(logged_in: Env) -> None:
    b = logged_in.browser
    for method, url in [
        ("POST", "/auth/logout"),
        ("POST", "/api/resume"),
        ("POST", "/api/intents/verify"),
        ("POST", "/api/approvals"),
        ("DELETE", f"/api/threads/{THREAD}"),
    ]:
        r = await b.request(method, url, csrf=False, json={} if method == "POST" else None)
        assert r.status_code == 403, (method, url)
        assert r.json()["error"]["code"] == "csrf_failed"


async def test_valid_csrf_passes(logged_in: Env) -> None:
    r = await logged_in.browser.delete(f"/api/threads/{THREAD}")
    assert r.status_code == 204


async def test_wrong_origin_is_blocked_even_with_valid_csrf(logged_in: Env) -> None:
    r = await logged_in.browser.post("/api/chat", json=CHAT, origin="https://evil.example")
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    assert r.headers["x-request-id"] == r.json()["error"]["request_id"]
    assert not logged_in.backends.calls or "/v1/threads" not in logged_in.backends.paths(
        "agent.test"
    )


async def test_origin_missing_requires_sec_fetch_site(logged_in: Env) -> None:
    b = logged_in.browser
    r = await b.delete(f"/api/threads/{THREAD}", origin=None)
    assert r.status_code == 403
    r = await b.delete(
        f"/api/threads/{THREAD}", origin=None, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert r.status_code == 403
    r = await b.delete(
        f"/api/threads/{THREAD}", origin=None, headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 204


async def test_csp_and_security_headers_verbatim(env: Env) -> None:
    for resp in (await env.browser.get("/healthz"), await env.browser.get("/api/me")):
        h = resp.headers
        assert h["content-security-policy"] == CSP
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert h["x-frame-options"] == "DENY"
        assert h["cross-origin-opener-policy"] == "same-origin"
        assert h["cross-origin-resource-policy"] == "same-origin"
        assert "camera=()" in h["permissions-policy"]
        assert h["strict-transport-security"] == "max-age=31536000; includeSubDomains"
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", h["x-request-id"])


async def test_api_and_auth_are_no_store(env: Env) -> None:
    assert (await env.browser.get("/api/me")).headers["cache-control"] == "no-store"
    assert (await env.browser.get("/auth/login")).headers["cache-control"] == "no-store"


async def test_incoming_request_id_is_propagated_only_if_well_formed(env: Env) -> None:
    ok = await env.browser.get("/healthz", headers={"X-Request-Id": "abc-123"})
    assert ok.headers["x-request-id"] == "abc-123"
    bad = await env.browser.get("/healthz", headers={"X-Request-Id": "bad id\twith space"})
    assert bad.headers["x-request-id"] != "bad id\twith space"


async def test_body_over_64kib_is_413(logged_in: Env) -> None:
    r = await logged_in.browser.post(
        "/api/chat", content=b"x" * 70_000, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"


async def test_extra_fields_and_bad_ids_are_400(logged_in: Env) -> None:
    b = logged_in.browser
    r = await b.post("/api/chat", json={**CHAT, "token": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    r = await b.post("/api/intents/verify", json={"thread_id": "not-uuid", "interrupt_id": "int_1"})
    assert r.status_code == 400
    r = await b.post("/api/chat", json={"text": "", "client_msg_id": MSG_ID})
    assert r.status_code == 400


async def test_resume_rejects_type_approve(logged_in: Env) -> None:
    r = await logged_in.browser.post(
        "/api/resume",
        json={"thread_id": THREAD, "interrupt_id": "int_1", "decision": {"type": "approve"}},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


async def test_unknown_api_path_is_json_404(env: Env) -> None:
    r = await env.browser.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_read_rate_limit_returns_429_with_retry_after(logged_in: Env) -> None:
    last = None
    for _ in range(121):
        last = await logged_in.browser.get("/api/me")
    assert last is not None and last.status_code == 429
    assert last.json()["error"]["code"] == "rate_limited" and int(last.headers["retry-after"]) > 0


async def test_login_is_rate_limited_per_ip(env: Env) -> None:
    codes = [(await env.browser.get("/auth/login")).status_code for _ in range(21)]
    assert codes[:20] == [302] * 20 and codes[20] == 429


def test_settings_refuse_unsafe_config() -> None:
    import pytest

    from bff.settings import SettingsError

    with pytest.raises(SettingsError):
        make_settings(acme_env="test", bff_public_url="http://bff.test").validate_runtime()
    with pytest.raises(SettingsError):
        make_settings(bff_session_key="c2hvcnQ").validate_runtime()
    with pytest.raises(SettingsError):
        make_settings(bff_session_key=None).validate_runtime()
    make_settings(acme_env="dev", bff_public_url="http://localhost:8300").validate_runtime()


def test_bff_holds_no_signing_key_or_signing_code() -> None:
    src = Path(__file__).parents[2] / "src" / "bff"
    text = "\n".join(p.read_text(encoding="utf8") for p in src.rglob("*.py"))
    assert not re.search(r"^\s*(import jwt|from jwt)", text, re.M)
    assert "asymmetric" not in text and "private_key" not in text.lower()
    assert PUBLIC  # harness import dùng chung


async def test_static_spa_is_served_with_fallback_and_cache_headers(tmp_path) -> None:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa</html>")
    (root / "assets" / "app-abc123.js").write_text("console.log(1)")
    e = await build_env(make_settings(bff_static_dir=str(root)))
    try:
        idx = await e.browser.get("/")
        assert idx.text == "<html>spa</html>" and idx.headers["cache-control"] == "no-cache"
        assert idx.headers["content-security-policy"] == CSP
        deep = await e.browser.get("/threads/123")
        assert deep.text == "<html>spa</html>"
        asset = await e.browser.get("/assets/app-abc123.js")
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        trav = await e.browser.get("/..%2f..%2fetc/passwd")
        assert trav.text == "<html>spa</html>" or trav.status_code == 404
        missing = await e.browser.get("/api/nope")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    finally:
        await e.browser.client.aclose()
        await e.container.aclose()
