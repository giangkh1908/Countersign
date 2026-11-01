"""KeyStore Postgres thật. Bỏ qua khi không có `TEST_DATABASE_URL`.

DB phải đã áp `infra/postgres/init/sql/30-gateway.sql` và có phòng ban `TEST_GW_DEPT` (mặc định `IT`).
Chạy bằng role `gw_app` (least privilege, không DELETE): key tạo ra được thu hồi cuối test, không xoá.
"""

from __future__ import annotations

import os

import httpx
import openai
import pytest
from acme_common.testing import FakeClock, FakeEventSink
from gateway.adapters.postgres import PostgresKeyStore, normalize_dsn
from gateway.container import build_container
from gateway.main import create_app
from gateway.ports import KeyAlreadyExists, KeyNotFound
from gateway.services.key_admin import issue_key
from gateway.testing import provider_lookup
from gw_support import ALL_ALIASES, PEPPER, make_mock_app, make_settings

DSN = os.environ.get("TEST_DATABASE_URL")
DEPT = os.environ.get("TEST_GW_DEPT", "IT")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL chưa đặt")


def issue(**kw: object):
    args: dict = {
        "name": "pg-test", "owner_type": "service", "owner_ref": "pg-test", "dept": DEPT,
        "allowed_models": ALL_ALIASES, "rpm": 10, "tpm": 1000,
    }  # fmt: skip
    return issue_key(PEPPER.encode(), **{**args, **kw})


@pytest.fixture
async def store():
    assert DSN
    clock = FakeClock()
    s = PostgresKeyStore(DSN, clock)
    s.clock = clock  # type: ignore[attr-defined]
    yield s
    await s.aclose()


def test_normalize_dsn() -> None:
    assert normalize_dsn("postgresql+asyncpg://u:p@h/d") == "postgresql://u:p@h/d"
    assert normalize_dsn("postgresql://u:p@h/d") == "postgresql://u:p@h/d"


async def test_create_lookup_revoke_roundtrip(store: PostgresKeyStore) -> None:
    issued = issue(trust_end_user_token=True, max_concurrency=3)
    rec = await store.create(issued.new, "pytest")
    try:
        got = await store.lookup(issued.new.prefix)
        assert got == rec
        assert got.secret_hmac == issued.new.secret_hmac and len(got.secret_hmac) == 32
        assert got.dept == DEPT and got.allowed_models == ALL_ALIASES
        assert got.trust_end_user_token
        assert got.max_concurrency == 3 and got.status == "active"
        with pytest.raises(KeyAlreadyExists):
            await store.create(issued.new, "pytest")
    finally:
        await store.revoke(rec.key_id, "pytest", "cleanup")
    # Instance thực hiện thu hồi thấy ngay (L1 bị xoá).
    assert (await store.lookup(issued.new.prefix)).status == "revoked"  # type: ignore[union-attr]
    with pytest.raises(KeyNotFound):
        await store.revoke(rec.key_id, "pytest", "again")
    with pytest.raises(KeyNotFound):
        await store.revoke("not-a-uuid", "pytest", "x")


async def test_unknown_prefix_and_negative_cache(store: PostgresKeyStore) -> None:
    assert await store.lookup("Q" * 12) is None
    # Create sau khi đã có negative cache: create phải xoá negative cache.
    issued = issue()
    await store.lookup(issued.new.prefix)
    rec = await store.create(issued.new, "pytest")
    try:
        assert (await store.lookup(issued.new.prefix)) is not None
    finally:
        await store.revoke(rec.key_id, "pytest", "cleanup")


async def test_l1_ttl_expiry_sees_external_revoke(store: PostgresKeyStore) -> None:
    issued = issue()
    rec = await store.create(issued.new, "pytest")
    clock: FakeClock = store.clock  # type: ignore[attr-defined]
    other = PostgresKeyStore(DSN, clock)  # type: ignore[arg-type]
    try:
        assert (await store.lookup(issued.new.prefix)).status == "active"  # type: ignore[union-attr]
        await other.revoke(rec.key_id, "pytest", "other instance")
        assert (await store.lookup(issued.new.prefix)).status == "active"  # type: ignore[union-attr]  # L1 còn hạn
        clock.advance(11)
        assert (await store.lookup(issued.new.prefix)).status == "revoked"  # type: ignore[union-attr]
    finally:
        await other.aclose()


async def test_gateway_with_real_key_store(store: PostgresKeyStore) -> None:
    """Đầu-cuối: key tạo trong Postgres thật -> gateway (provider = mock_provider in-process)."""
    from gateway.adapters.mock import MockChatProvider

    issued = issue()
    rec = await store.create(issued.new, "pytest")
    sink = FakeEventSink()
    provider = MockChatProvider(
        "http://mock",
        client=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_mock_app()), base_url="http://mock"
        ),
    )
    settings = make_settings()
    c = build_container(
        settings, clock=FakeClock(), keys=store, sink=sink, providers=provider_lookup(mock=provider),
    )  # fmt: skip
    app = create_app(settings, c)
    client = openai.AsyncOpenAI(
        base_url="http://gateway/v1", api_key=issued.plaintext, max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )  # fmt: skip
    r = await client.chat.completions.create(
        model="acme-fast", messages=[{"role": "user", "content": "hi"}]
    )
    assert r.usage.completion_tokens == 8
    ev = sink.events[0]
    assert ev["key_id"] == rec.key_id and ev["department"] == DEPT
    await store.revoke(rec.key_id, "pytest", "cleanup")  # xoá L1 của instance này
    with pytest.raises(openai.AuthenticationError) as e:
        await client.chat.completions.create(
            model="acme-fast", messages=[{"role": "user", "content": "hi"}]
        )
    assert e.value.code == "key_revoked"
