"""Harness RQ4 chạy với sender giả (không cần stack). Sender giả dùng đúng hàm dựng khoá của gateway."""

from __future__ import annotations

import json
from pathlib import Path

from acme_common.ports import Principal
from gateway.ports import CachedResponse
from gateway.services.cache_key import build_cache_key
from gateway.testing import FakeResponseCache

from eval.cache.__main__ import main
from eval.cache.harness import (
    Report,
    Sample,
    Sender,
    User,
    build_payload,
    format_table,
    leaks,
    load_report,
    run_all,
)

USERS = [User("an", "IT|1|staff"), User("binh", "IT|1|staff"), User("chi", "HR|2|mgr")]


class KeyedSender(Sender):
    """Mô phỏng gateway: khoá thật từ phạm vi của người dùng + FakeResponseCache."""

    def __init__(self, enabled: bool, strict: bool = True) -> None:
        self.cache = FakeResponseCache()
        self.enabled, self.strict = enabled, strict

    async def send(self, user: User, prompt: str, mode: str = "plain") -> Sample:
        messages, tools = build_payload(prompt, mode)
        dept, clr, roles = user.scope.split("|")
        p = Principal(
            "u", ("llm-gateway",), None, frozenset(), 2e9, None, (dept,), int(clr), (roles,)
        )
        key = build_cache_key(
            user=p,
            provider="fake",
            model="m",
            messages=messages,
            params={},
            tools=tools,
            tool_choice=None,
            index_version="0",
            strict=self.strict,
        )
        if self.enabled and key and (await self.cache.get(key)):
            return Sample(1.0, "exact", 0)
        if self.enabled and key:
            await self.cache.put(key, CachedResponse("x", "stop", 1, 1, "fake", "m"), 60)
        return Sample(50.0, "miss" if self.enabled else None, 15)


async def test_hit_rate_tracks_repeat_level_and_no_cross_scope_hits() -> None:
    rep = await run_all(KeyedSender(True), USERS, label="on", n=200)
    rates = [lv.hit_rate for lv in rep.levels]
    assert rates[0] == 0.0 and rates[0] < rates[1] < rates[2]
    assert all(lv.legit_hits == lv.legit_repeats for lv in rep.levels)
    assert all(lv.cross_probes > 0 for lv in rep.levels)
    assert leaks([rep]) == 0
    assert rep.levels[2].tokens < rep.levels[0].tokens  # hit không tính phí token
    assert rep.levels[2].p50_hit_ms == 1.0 and rep.levels[2].p50_miss_ms == 50.0


async def test_without_cache_never_hits() -> None:
    rep = await run_all(KeyedSender(False), USERS, label="off", n=60)
    assert all(lv.hits == 0 for lv in rep.levels)


async def test_harness_detects_a_leaky_cache() -> None:
    rep = await run_all(KeyedSender(True, strict=False), USERS, label="leaky", n=200)
    assert leaks([rep]) > 0  # khoá bỏ phạm vi bị bắt là rò


async def test_report_roundtrip_and_cli(tmp_path: Path, capsys) -> None:
    rep = await run_all(KeyedSender(True), USERS, label="on", n=40)
    f = tmp_path / "on.json"
    f.write_text(rep.to_json(), encoding="utf-8")
    back = load_report(f)
    assert isinstance(back, Report) and back.levels[1].n == 40
    assert "| on | 50% |" in format_table([back])
    assert main(["report", str(f)]) == 0
    assert "0, xanh" in capsys.readouterr().out
    leaky = await run_all(KeyedSender(True, strict=False), USERS, label="leaky", n=200)
    g = tmp_path / "leaky.json"
    g.write_text(json.dumps(json.loads(leaky.to_json())), encoding="utf-8")
    assert main(["report", str(g)]) == 1


async def test_agent_mode_replays_tool_conversation_and_still_isolates_scopes() -> None:
    messages, tools = build_payload("hỏi A", "agent")
    assert tools and [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"] and build_payload("hỏi A", "agent") == (messages, tools)
    assert build_payload("hỏi A", "plain") == ([{"role": "user", "content": "hỏi A"}], None)
    rep = await run_all(KeyedSender(True), USERS, label="on-agent", n=200, mode="agent")
    assert rep.levels[0].hit_rate == 0.0 and rep.levels[2].hit_rate > 0.3
    assert leaks([rep]) == 0
