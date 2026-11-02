"""Harness RQ4: hit rate, độ trễ, token tính phí và rò rỉ chéo phạm vi ở ba mức lặp (0%, 20%, 50%).

Harness chỉ nói chuyện qua `Sender` (port nhỏ của riêng eval): `HttpGatewaySender` gọi gateway thật,
test dùng `Fake*Sender`. Không in prompt, token hay khoá API. Prompt có nonce của lần chạy nên
entry cũ trong cache không làm sai số liệu.

Hai chế độ: `plain` (một lượt user) và `agent` (phát lại hội thoại kiểu agent: system prompt tĩnh, có
`tools`, lượt assistant gọi `search_documents` và lượt tool do script cố định giả lập kết quả tìm kiếm;
đây là lời gọi cuối của agent, đại diện luồng thật vì agent luôn gửi tools).

Định nghĩa:
- lặp hợp lệ: cùng prompt do người CÙNG phạm vi đã hỏi trước đó (được phép trúng);
- thăm dò chéo phạm vi: prompt mà chỉ phạm vi KHÁC đã hỏi (bắt buộc miss; trúng = rò rỉ);
- hit rate "evidence-keyed" là số mô phỏng ngoại tuyến (bỏ phạm vi khỏi khoá), không phải hành vi runtime.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPEAT_LEVELS = (0.0, 0.2, 0.5)


@dataclass(frozen=True, slots=True)
class User:
    name: str
    scope: str  # nhãn phạm vi (vd "IT|1|staff"); cùng nhãn = cùng khoá cache


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": "Tìm trong tài liệu nội bộ.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
            "required": ["query"],
        },
    },
}
AGENT_SYSTEM = "Bạn là trợ lý tra cứu tài liệu nội bộ. Trả lời ngắn gọn, trích dẫn bằng [#số]."


def build_payload(
    prompt: str, mode: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """(messages, tools) của một lượt; `agent`: kết quả tool là hàm cố định của prompt."""
    if mode == "plain":
        return [{"role": "user", "content": prompt}], None
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "search_documents", "arguments": json.dumps({"query": prompt})},
    }
    result = json.dumps({"results": [{"cite": "[#1]", "text": f"đoạn tài liệu cho: {prompt}"}]})
    return (
        [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "call_1", "content": result},
        ],
        [SEARCH_TOOL],
    )


@dataclass(frozen=True, slots=True)
class Sample:
    latency_ms: float
    cache: str | None  # giá trị header x-acme-cache
    tokens: int  # token tính phí (0 khi trúng cache)
    status: int = 200


class Sender(ABC):
    @abstractmethod
    async def send(self, user: User, prompt: str, mode: str = "plain") -> Sample: ...

    async def aclose(self) -> None:  # noqa: B027
        """Giải phóng tài nguyên."""


class HttpGatewaySender(Sender):
    """Gọi `POST /v1/chat/completions` với API key của dịch vụ và user token của từng người dùng."""

    def __init__(self, base_url: str, api_key: str, tokens: dict[str, str], model: str) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, timeout=120)
        self._key, self._tokens, self._model = api_key, tokens, model

    async def send(self, user: User, prompt: str, mode: str = "plain") -> Sample:
        messages, tools = build_payload(prompt, mode)
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": 64,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        t0 = time.perf_counter()
        r = await self._http.post(
            "/v1/chat/completions",
            headers={
                "authorization": f"Bearer {self._key}",
                "x-acme-user-token": self._tokens[user.name],
            },
            json=payload,
        )
        ms = (time.perf_counter() - t0) * 1000
        cache = r.headers.get("x-acme-cache")
        tokens = 0
        if r.status_code == 200 and cache != "exact":
            tokens = int(r.json().get("usage", {}).get("total_tokens", 0))
        return Sample(ms, cache, tokens, r.status_code)

    async def aclose(self) -> None:
        await self._http.aclose()


@dataclass(slots=True)
class LevelResult:
    repeat: float
    n: int = 0
    hits: int = 0
    errors: int = 0
    legit_repeats: int = 0
    legit_hits: int = 0
    cross_probes: int = 0
    cross_scope_hits: int = 0  # PHẢI bằng 0
    tokens: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p50_hit_ms: float | None = None
    p50_miss_ms: float | None = None
    evidence_keyed_hit_rate: float = 0.0
    hit_rate: float = 0.0


@dataclass(slots=True)
class Report:
    label: str
    levels: list[LevelResult] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


async def run_level(
    sender: Sender,
    users: list[User],
    *,
    repeat: float,
    n: int,
    seed: int,
    cross_probe: float = 0.1,
    mode: str = "plain",
) -> LevelResult:
    """Một mức lặp: `repeat` = tỉ lệ request lặp hợp lệ; thêm `cross_probe` thăm dò chéo phạm vi."""
    rng = random.Random(seed)
    nonce = f"{seed:08x}{rng.getrandbits(32):08x}"
    asked: dict[str, set[str]] = {}  # prompt -> các phạm vi đã hỏi
    res = LevelResult(repeat)
    lat: list[float] = []
    hit_lat: list[float] = []
    miss_lat: list[float] = []
    evidence_hits = 0
    for i in range(n):
        user = rng.choice(users)
        prompt = f"[rq4 {nonce}] câu hỏi số {i}"
        legit = cross = False
        seen = [p for p, scopes in asked.items() if user.scope in scopes]
        foreign = [p for p, scopes in asked.items() if user.scope not in scopes]
        roll = rng.random()
        if seen and roll < repeat:
            prompt, legit = rng.choice(seen), True
        elif foreign and roll < repeat + cross_probe:
            prompt, cross = rng.choice(foreign), True
        if prompt in asked:
            evidence_hits += 1  # evidence-keyed sẽ trúng mọi prompt đã thấy, bất kể phạm vi
        sample = await sender.send(user, prompt, mode)
        asked.setdefault(prompt, set()).add(user.scope)
        res.n += 1
        if sample.status != 200:
            res.errors += 1
            continue
        hit = sample.cache == "exact"
        res.hits += hit
        res.tokens += sample.tokens
        lat.append(sample.latency_ms)
        (hit_lat if hit else miss_lat).append(sample.latency_ms)
        if legit:
            res.legit_repeats += 1
            res.legit_hits += hit
        if cross:
            res.cross_probes += 1
            res.cross_scope_hits += hit
    ok = max(1, res.n - res.errors)
    res.hit_rate = res.hits / ok
    res.evidence_keyed_hit_rate = evidence_hits / max(1, res.n)
    res.p50_ms, res.p95_ms = statistics.median(lat) if lat else 0.0, _pct(lat, 0.95)
    res.p50_hit_ms = statistics.median(hit_lat) if hit_lat else None
    res.p50_miss_ms = statistics.median(miss_lat) if miss_lat else None
    return res


async def run_all(
    sender: Sender,
    users: list[User],
    *,
    label: str,
    n: int,
    seed: int = 1,
    levels: tuple[float, ...] = REPEAT_LEVELS,
    mode: str = "plain",
) -> Report:
    rep = Report(label)
    for k, lv in enumerate(levels):
        rep.levels.append(await run_level(sender, users, repeat=lv, n=n, seed=seed + k, mode=mode))
    return rep


def format_table(reports: list[Report]) -> str:
    rows = [
        "| nhãn | lặp | n | hit rate | evidence-keyed* | p50 ms | p95 ms | p50 hit | p50 miss "
        "| token tính phí | lặp hợp lệ trúng | thăm dò chéo / trúng | lỗi |",
        "|" + "---|" * 13,
    ]

    def ms(x: float | None) -> str:
        return "-" if x is None else f"{x:.0f}"

    for r in reports:
        for lv in r.levels:
            rows.append(
                f"| {r.label} | {lv.repeat:.0%} | {lv.n} | {lv.hit_rate:.1%} "
                f"| {lv.evidence_keyed_hit_rate:.1%} | {lv.p50_ms:.0f} | {lv.p95_ms:.0f} "
                f"| {ms(lv.p50_hit_ms)} | {ms(lv.p50_miss_ms)} | {lv.tokens} "
                f"| {lv.legit_hits}/{lv.legit_repeats} | {lv.cross_probes} / {lv.cross_scope_hits} "
                f"| {lv.errors} |"
            )
    rows.append("")
    rows.append("*mô phỏng ngoại tuyến (bỏ phạm vi khỏi khoá), không phải hành vi runtime.")
    return "\n".join(rows)


def leaks(reports: list[Report]) -> int:
    return sum(lv.cross_scope_hits for r in reports for lv in r.levels)


def load_report(path: Path) -> Report:
    d: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return Report(d["label"], [LevelResult(**lv) for lv in d["levels"]])
