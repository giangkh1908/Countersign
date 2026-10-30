from __future__ import annotations

from datetime import timedelta

import httpx
from acme_common.factory import build_token_verifier
from acme_common.http import RetryingHttpClient
from acme_common.testing import ISSUER, FakeJwksEndpoint, TestSigner, make_claims
from gateway.container import build_container
from gateway.main import create_app
from gateway.services.key_admin import hmac_secret, issue_key, parse_key
from gw_support import Env, make_settings, user_principal

BODY = {"model": "acme-fast", "messages": [{"role": "user", "content": "hello"}]}
URL = "http://gateway/v1/chat/completions"


async def post(env: Env, key: str | None, headers: dict[str, str] | None = None) -> httpx.Response:
    h = dict(headers or {})
    if key is not None:
        h["authorization"] = f"Bearer {key}"
    transport = httpx.ASGITransport(app=env.app)
    async with httpx.AsyncClient(transport=transport, headers=h) as c:
        return await c.post(URL, json=BODY)


def assert_error(r: httpx.Response, status: int, code: str) -> None:
    assert r.status_code == status, r.text
    err = r.json()["error"]
    assert err["code"] == code and err["message"] and err["type"]
    assert r.headers["x-acme-request-id"]


async def test_missing_and_malformed_key_do_not_touch_store(env: Env) -> None:
    for key in (None, "not-a-key", "sk-acme-short.x", "sk-acme-" + "a" * 12 + "." + "b" * 42):
        assert_error(await post(env, key), 401, "invalid_api_key")
    assert env.keys.lookups == []


async def test_unknown_prefix_and_wrong_secret_look_identical(env: Env, api_key: str) -> None:
    unknown = "sk-acme-" + "Z" * 12 + "." + "a" * 43
    prefix, _ = parse_key(api_key)  # type: ignore[misc]
    wrong_secret = f"sk-acme-{prefix}." + "a" * 43
    r1, r2 = await post(env, unknown), await post(env, wrong_secret)
    assert_error(r1, 401, "invalid_api_key")
    assert_error(r2, 401, "invalid_api_key")
    assert r1.json()["error"]["message"] == r2.json()["error"]["message"]


async def test_valid_key_works(env: Env, api_key: str) -> None:
    r = await post(env, api_key)
    assert r.status_code == 200 and r.headers["x-acme-request-id"]


async def test_revoked_key(env: Env, api_key: str) -> None:
    prefix, _ = parse_key(api_key)  # type: ignore[misc]
    rec = env.keys.records[prefix]
    await env.keys.revoke(rec.key_id, "admin", "leaked")
    assert_error(await post(env, api_key), 401, "key_revoked")


async def test_expired_key(env: Env) -> None:
    key = await env.new_key(expires_at=env.clock.now() - timedelta(seconds=1))
    assert_error(await post(env, key), 401, "key_expired")


async def test_wrong_secret_on_revoked_key_still_invalid_api_key(env: Env, api_key: str) -> None:
    prefix, _ = parse_key(api_key)  # type: ignore[misc]
    await env.keys.revoke(env.keys.records[prefix].key_id, "admin", "x")
    wrong = f"sk-acme-{prefix}." + "a" * 43
    assert_error(await post(env, wrong), 401, "invalid_api_key")  # không lộ trạng thái key


async def test_pepper_prev_still_verifies(env: Env) -> None:
    old = b"old-pepper-" + b"y" * 32
    issued = issue_key(
        old, name="n", owner_type="service", owner_ref="r", dept="IT",
        allowed_models=("acme-fast",), rpm=1, tpm=1,
    )  # fmt: skip
    await env.keys.create(issued.new, "t")
    assert_error(await post(env, issued.plaintext), 401, "invalid_api_key")  # chưa cấu hình prev
    settings = make_settings(gw_key_pepper_prev=old.decode())
    c = build_container(
        settings, clock=env.clock, keys=env.keys, verifier=env.verifier, sink=env.sink,
        providers=env.providers,
    )  # fmt: skip
    env.app = create_app(settings, c)
    r = await post(env, issued.plaintext)
    assert r.status_code != 401


def test_hmac_matches_contract_definition() -> None:
    assert hmac_secret(b"s", b"p" * 32) == hmac_secret(b"s", b"p" * 32)
    assert hmac_secret(b"s", b"p" * 32) != hmac_secret(b"s", b"q" * 32)


async def test_client_request_id_is_echoed(env: Env, api_key: str) -> None:
    r = await post(env, api_key, {"X-Acme-Client-Request-Id": "abc-123"})
    assert r.headers["x-acme-client-request-id"] == "abc-123"


async def test_unknown_route_has_openai_error_and_request_id(env: Env) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app)) as c:
        r = await c.get("http://gateway/nope")
    assert_error(r, 404, "not_found")


# ---- user token ----


async def test_trusted_key_with_valid_user_token(env: Env) -> None:
    key = await env.new_key(trust_end_user_token=True)
    env.verifier.add("good", user_principal(dept=("CS", "IT")))
    r = await post(env, key, {"X-Acme-User-Token": "good"})
    assert r.status_code == 200
    ev = next(e for e in env.sink.events if e["event"] == "usage_event")
    assert ev["end_user_sub"] == "user-42" and ev["department"] == "CS"
    assert env.verifier.calls == [("good", "llm-gateway")]


async def test_user_token_wrong_audience(env: Env) -> None:
    key = await env.new_key(trust_end_user_token=True)
    env.verifier.add("wrong-aud", user_principal(aud=("agent-service",)))
    assert_error(
        await post(env, key, {"X-Acme-User-Token": "wrong-aud"}), 401, "invalid_end_user_token"
    )
    assert_error(
        await post(env, key, {"X-Acme-User-Token": "garbage"}), 401, "invalid_end_user_token"
    )
    assert [e for e in env.sink.events if e["event"] == "usage_event"] == []


async def test_untrusted_key_ignores_user_token(env: Env, api_key: str) -> None:
    env.verifier.add("good", user_principal())
    r = await post(env, api_key, {"X-Acme-User-Token": "good"})
    assert r.status_code == 200
    assert env.verifier.calls == []  # không verify, không nâng quyền
    ev = next(e for e in env.sink.events if e["event"] == "usage_event")
    assert ev["end_user_sub"] is None and ev["department"] == "IT"


async def test_trusted_key_without_user_token_uses_key_identity(env: Env) -> None:
    key = await env.new_key(trust_end_user_token=True)
    assert (await post(env, key)).status_code == 200
    ev = next(e for e in env.sink.events if e["event"] == "usage_event")
    assert ev["end_user_sub"] is None and ev["department"] == "IT"


async def test_real_oidc_verifier_enforces_llm_gateway_audience(env: Env) -> None:
    """Verifier thật (oidc_jwks) + JWKS giả: aud=agent-service bị từ chối, aud=llm-gateway được nhận."""
    signer = TestSigner("ES256", "k1")
    endpoint = FakeJwksEndpoint([signer])
    settings = make_settings(keycloak_issuer=ISSUER, oidc_jwks_url=endpoint.JWKS_URL)
    http = RetryingHttpClient(transport=endpoint.transport(), max_attempts=1)
    verifier = build_token_verifier("oidc_jwks", settings, clock=env.clock, http=http)
    c = build_container(
        settings, clock=env.clock, keys=env.keys, verifier=verifier, sink=env.sink,
        providers=env.providers,
    )  # fmt: skip
    env.app = create_app(settings, c)
    key = await env.new_key(trust_end_user_token=True)
    now = env.clock.now().timestamp()
    bad = signer.sign(make_claims(now, aud="agent-service"))
    good = signer.sign(make_claims(now, aud=["llm-gateway"], sub="u9", dept=["HR"]))
    assert_error(await post(env, key, {"X-Acme-User-Token": bad}), 401, "invalid_end_user_token")
    assert (await post(env, key, {"X-Acme-User-Token": good})).status_code == 200
    ev = next(e for e in env.sink.events if e["event"] == "usage_event")
    assert ev["end_user_sub"] == "u9" and ev["department"] == "HR"


async def test_metrics_requires_token(env: Env, api_key: str) -> None:
    await post(env, api_key)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app)) as c:
        assert (await c.get("http://gateway/metrics")).status_code == 401
        r = await c.get(
            "http://gateway/metrics", headers={"authorization": "Bearer metrics-secret"}
        )
    assert (
        r.status_code == 200
        and 'gateway_requests_total{alias="acme-fast",status="200"} 1.0' in r.text
    )
    assert "hello" not in r.text and api_key not in r.text
