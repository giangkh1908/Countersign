import io

from acme_common.testing import FakeClock, FakeEventSink
from gateway.cli import check_key, create_key, parser, revoke_key
from gateway.services.key_admin import parse_key
from gateway.testing import FakeKeyStore
from gw_support import Env, make_settings


async def test_create_key_prints_plaintext_once_and_audits(capsys) -> None:
    keys, sink, clock = FakeKeyStore(), FakeEventSink(), FakeClock()
    args = parser().parse_args(
        ["--actor", "alice", "create-key", "--name", "agent", "--dept", "IT",
         "--allowed-models", "acme-fast, acme-smart", "--trust-end-user-token"]
    )  # fmt: skip
    assert await create_key(args, keys, sink, clock, make_settings()) == 0
    out = capsys.readouterr()
    plaintext = out.out.strip()
    parsed = parse_key(plaintext)
    assert parsed and parsed[0] in keys.records
    rec = keys.records[parsed[0]]
    assert rec.allowed_models == ("acme-fast", "acme-smart") and rec.trust_end_user_token
    assert plaintext not in out.err  # stderr chỉ có key_id
    (audit,) = sink.events
    assert (
        audit["event"] == "audit_log"
        and audit["action"] == "key.create"
        and audit["actor_id"] == "alice"
    )
    assert sink.sync_flags == [True]
    assert plaintext not in str(audit) and parsed[1].decode() not in str(audit)


async def test_cli_key_is_usable_then_revoked(env: Env, capsys) -> None:
    args = parser().parse_args(
        ["create-key", "--name", "svc", "--dept", "IT", "--allowed-models", "acme-fast"]
    )
    await create_key(args, env.keys, FakeEventSink(), env.clock, env.settings)
    key = capsys.readouterr().out.strip()
    async with env.gateway_client(key) as c:
        body = {"model": "acme-fast", "messages": [{"role": "user", "content": "hi"}]}
        assert (await c.post("http://gateway/v1/chat/completions", json=body)).status_code == 200
        rec = env.keys.records[parse_key(key)[0]]  # type: ignore[index]
        rv = parser().parse_args(["revoke-key", "--key-id", rec.key_id, "--reason", "leak"])
        assert await revoke_key(rv, env.keys, FakeEventSink(), env.clock, env.settings) == 0
        r = await c.post("http://gateway/v1/chat/completions", json=body)
        assert r.status_code == 401 and r.json()["error"]["code"] == "key_revoked"
        assert await revoke_key(rv, env.keys, FakeEventSink(), env.clock, env.settings) == 1


async def _check(monkeypatch, keys, key: str, settings) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(key + "\n"))
    args = parser().parse_args(["check-key"])
    return await check_key(args, keys, FakeEventSink(), FakeClock(), settings)


async def test_check_key_exit_codes(env: Env, capsys, monkeypatch) -> None:
    args = parser().parse_args(
        ["create-key", "--name", "svc", "--dept", "IT", "--allowed-models", "acme-fast"]
    )
    await create_key(args, env.keys, FakeEventSink(), env.clock, env.settings)
    key = capsys.readouterr().out.strip()
    # tồn tại và active -> 0, không in key
    assert await _check(monkeypatch, env.keys, key, env.settings) == 0
    out = capsys.readouterr()
    assert key not in out.out and key not in out.err
    # key chưa từng có (DB mới) hoặc sai định dạng -> 3
    other = "sk-acme-" + "A" * 12 + "." + "b" * 43
    assert await _check(monkeypatch, env.keys, other, env.settings) == 3
    assert await _check(monkeypatch, env.keys, "rac", env.settings) == 3
    # đã thu hồi -> 3
    rec = env.keys.records[parse_key(key)[0]]  # type: ignore[index]
    rv = parser().parse_args(["revoke-key", "--key-id", rec.key_id, "--reason", "leak"])
    await revoke_key(rv, env.keys, FakeEventSink(), env.clock, env.settings)
    assert await _check(monkeypatch, env.keys, key, env.settings) == 3


async def test_check_key_infra_error_is_not_3(env: Env, monkeypatch) -> None:
    class Broken(FakeKeyStore):
        async def lookup(self, prefix):
            raise ConnectionError("db down")

    key = "sk-acme-" + "A" * 12 + "." + "b" * 43
    assert await _check(monkeypatch, Broken(), key, env.settings) == 2
