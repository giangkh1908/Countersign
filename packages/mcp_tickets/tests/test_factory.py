from __future__ import annotations

import pytest
from acme_common.ports.errors import NotConfigured
from acme_common.testing import FakeClock
from cryptography.hazmat.primitives import serialization
from mcp_tickets import factory as f
from mcp_tickets.ports import (
    ApprovalVerifier,
    IntentIssuer,
    ReplayGuard,
    TicketRepository,
)
from mcp_tickets.settings import Settings
from tickets_harness import new_key, pem_private, pem_public


def test_registries_have_expected_names() -> None:
    assert set(f._REPOSITORIES) == {"postgres"}
    assert set(f._ISSUERS) == {"es256_jws"}
    assert set(f._VERIFIERS) == {"es256_jwt"}
    assert set(f._REPLAY_GUARDS) == {"redis", "in_memory"}  # không có adapter permissive


@pytest.mark.parametrize(
    "build",
    [
        lambda s: f.build_ticket_repository("jira", s),
        lambda s: f.build_intent_issuer("permissive", s, redis=None, clock=FakeClock()),
        lambda s: f.build_approval_verifier("permissive", s, clock=FakeClock()),
        lambda s: f.build_replay_guard("memcached", s, redis=None, clock=FakeClock()),
    ],
)
def test_unknown_name_lists_known(build) -> None:
    with pytest.raises(NotConfigured, match=r"known: \["):
        build(Settings())


def test_builds_known_adapters(tmp_path) -> None:
    import fakeredis

    k_intent, k_appr = new_key(), new_key()
    (tmp_path / "i.pem").write_bytes(pem_private(k_intent))
    (tmp_path / "a.pem").write_bytes(pem_public(k_appr))
    s = Settings(
        intent_private_key_path=str(tmp_path / "i.pem"),
        approval_public_key_path=str(tmp_path / "a.pem"),
        mcp_database_url="postgresql://u:p@localhost/tickets",
        audit_hmac_key="k" * 32,
    )
    clock, redis = FakeClock(), fakeredis.FakeAsyncRedis()
    assert isinstance(f.build_ticket_repository("postgres", s), TicketRepository)
    assert isinstance(f.build_intent_issuer("es256_jws", s, redis=redis, clock=clock), IntentIssuer)
    assert isinstance(f.build_approval_verifier("es256_jwt", s, clock=clock), ApprovalVerifier)
    assert isinstance(f.build_replay_guard("redis", s, redis=redis, clock=clock), ReplayGuard)
    assert isinstance(f.build_replay_guard("in_memory", s, redis=None, clock=clock), ReplayGuard)


def test_missing_config_is_explicit() -> None:
    with pytest.raises(NotConfigured, match="MCP_DATABASE_URL"):
        f.build_ticket_repository("postgres", Settings())
    with pytest.raises(NotConfigured, match="INTENT_PRIVATE_KEY_PATH"):
        f.build_intent_issuer("es256_jws", Settings(), redis=None, clock=FakeClock())
    with pytest.raises(NotConfigured, match="APPROVAL_PUBLIC_KEY_PATH"):
        f.build_approval_verifier("es256_jwt", Settings(), clock=FakeClock())


def test_approval_keys_directory(tmp_path) -> None:
    from acme_common.adapters.approval_es256_jwt import load_trusted_keys

    (tmp_path / "ap-1.pem").write_bytes(pem_public(new_key()))
    (tmp_path / "ap-2.pem").write_bytes(pem_public(new_key()))
    assert set(load_trusted_keys(str(tmp_path), "ap-1")) == {"ap-1", "ap-2"}
    bad = tmp_path / "bad.pem"
    bad.write_bytes(
        new_key().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(ValueError):
        load_trusted_keys(str(bad), "ap-1")


def test_settings_defaults_match_env_example() -> None:
    s = Settings()
    assert s.intent_key_id == "tickets-mcp-1" and s.intent_ttl_s == 300
    assert s.taint_policy == "warn" and s.mcp_audience == "tickets-mcp"
    assert s.audit_hmac_key_id == 1  # kế thừa kiểu int của CommonSettings


async def test_app_startup_fails_on_bad_config() -> None:
    from mcp_tickets.main import TicketsMcpApp

    def boom():
        raise ValueError("missing config")

    app = TicketsMcpApp(boom)
    sent: list[dict] = []
    msgs = iter([{"type": "lifespan.startup"}])

    async def receive():
        return next(msgs)

    async def send(m):
        sent.append(m)

    await app({"type": "lifespan"}, receive, send)
    assert sent == [{"type": "lifespan.startup.failed", "message": "ValueError"}]
