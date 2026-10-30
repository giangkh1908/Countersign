from __future__ import annotations

import base64

import pytest
from agent.factory import (
    build_agent_registry,
    build_checkpointer,
    build_conversation_repo,
    build_serde,
    build_tool_provider,
)
from agent.ports.errors import (
    AgentNotConfigured,
    CheckpointerNotConfigured,
    ConfigError,
    ConversationRepoNotConfigured,
    ToolProviderNotConfigured,
)
from agent.settings import Settings
from agent.testing import AUTH, PREPARED, TEST_KEY_B64, FakeToolProvider, route, tool_call

CANARY = "CANARY-SECRET-PHRASE-9137"


async def test_checkpoint_is_ciphertext(make_env):
    env = make_env(
        FakeToolProvider({"prepare_close_ticket": PREPARED}),
        {
            "router": [route("ticket")],
            "agent": [
                tool_call(
                    "prepare_close_ticket", {"code": "TCK-000123", "resolution": "ok xong roi"}
                )
            ],
        },
    )
    tid = await env.new_thread()
    await env.run(tid, f"Dong ticket TCK-000123, {CANARY}")
    saver = env.c.checkpointer
    blobs = [v for v in saver.blobs.values()]
    stored = [t[1] for t in blobs] + [
        v[1] for d in saver.storage.values() for dd in d.values() for v in dd.values()
    ]
    raw = b"".join(s for s in stored if isinstance(s, bytes))
    assert raw and CANARY.encode() not in raw
    # đọc lại qua graph (giải mã đúng khoá) vẫn thấy nội dung
    snap = await env.c.graph.aget_state({"configurable": {"thread_id": tid}})
    assert CANARY in snap.values["messages"][0].content


def test_serde_requires_key_outside_test(monkeypatch):
    monkeypatch.setenv("ACME_ENV", "dev")
    with pytest.raises(ConfigError):
        build_serde(Settings(acme_env="dev"))


def test_serde_rejects_wrong_length_key():
    with pytest.raises(ConfigError):
        build_serde(
            Settings(
                acme_env="test", agent_checkpoint_encryption_key=base64.b64encode(b"short").decode()
            )
        )


def test_wrong_key_cannot_decrypt():
    a = build_serde(Settings(acme_env="test", agent_checkpoint_encryption_key=TEST_KEY_B64))
    b = build_serde(
        Settings(
            acme_env="test", agent_checkpoint_encryption_key=base64.b64encode(b"z" * 32).decode()
        )
    )
    typ, blob = a.dumps_typed({"x": CANARY})
    assert CANARY.encode() not in blob
    with pytest.raises(Exception):  # noqa: B017 - tag xác thực AES-EAX sai
        b.loads_typed((typ, blob))


def test_registry_known_and_unknown():
    s = Settings(acme_env="test")
    assert build_agent_registry(s).routes() == ["docs", "ticket"]
    with pytest.raises(AgentNotConfigured, match="known"):
        build_agent_registry(s, ("nope",))


def test_tool_provider_unknown():
    s = Settings(acme_env="test")
    with pytest.raises(ToolProviderNotConfigured, match="mcp_http"):
        build_tool_provider(
            "nope", s, registry=build_agent_registry(s), broker=None, write_broker=None
        )  # type: ignore[arg-type]


async def test_repo_and_checkpointer_names():
    s = Settings(acme_env="test", agent_checkpoint_encryption_key=TEST_KEY_B64)
    repo, close = await build_conversation_repo("memory", s)
    assert (await repo.create("u", None)).thread_id
    await close()
    saver, close = await build_checkpointer("memory", s)
    assert saver is not None
    await close()
    with pytest.raises(ConversationRepoNotConfigured):
        await build_conversation_repo("nope", s)
    with pytest.raises(CheckpointerNotConfigured):
        await build_checkpointer("nope", s)


def test_auth_header_constant():
    assert AUTH["Authorization"].startswith("Bearer ")
