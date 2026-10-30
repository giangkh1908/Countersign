"""Hành vi dùng chung của mock_provider: độ trễ, lỗi, đếm token, sinh câu trả lời tất định.

Nguồn cấu hình mỗi request (ưu tiên giảm dần): header `x-mock-<tên>` > `/__control` theo
scope (tên wire format, xem `factory.wire_names()`) > `/__control` scope `*` > env `MOCK_*`.
Tên (`_` thành `-` trong header): ttft_ms, token_delay_ms, output_tokens, error_rate, error,
error_kinds, retry_after_s, hang_s, seed.
`error` = `429|500|503|timeout|stream_cut|none` (ép lỗi; `none` tắt cả lỗi ngẫu nhiên).
"""

import asyncio
import hashlib
import json
import random
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from .settings import Settings

CREATED = 1_700_000_000  # cố định để body tái lập được
ERROR_STATUS = {"429": 429, "500": 500, "503": 503, "timeout": 504}
_TOKEN_RE = re.compile(r"\s*\w+|\s*[^\w\s]")
_TOOL_RE = re.compile(r"([\w.\-]+)?\s*(\{.*\})?", re.DOTALL)
_VOCAB = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
]
_FIELDS: dict[str, type] = {
    "ttft_ms": float,
    "token_delay_ms": float,
    "output_tokens": int,
    "error_rate": float,
    "error": str,
    "error_kinds": str,
    "retry_after_s": int,
    "hang_s": float,
    "seed": int,
}


def tokenize(text: str) -> list[str]:
    """Tách thành "token" (từ hoặc dấu câu, giữ khoảng trắng đứng trước); nối lại = văn bản gốc."""
    return _TOKEN_RE.findall(text)


def count_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


@dataclass(frozen=True)
class Plan:
    """Hành vi đã giải quyết cho một request."""

    ttft_ms: float
    token_delay_ms: float
    output_tokens: int
    seed: int
    error: str | None  # 429|500|503|timeout|stream_cut|None
    retry_after_s: int
    hang_s: float

    def cut_at(self, n_pieces: int) -> int | None:
        """Số piece được gửi trước khi ngắt stream; None nếu không ngắt."""
        return max(1, n_pieces // 2) if self.error == "stream_cut" else None


@dataclass
class Reply:
    pieces: list[str]  # text hoặc các mảnh JSON của tool call
    input_tokens: int
    tool_name: str | None = None
    tool_id: str | None = None
    truncated: bool = False  # bị cắt bởi max_tokens

    @property
    def is_tool(self) -> bool:
        return self.tool_name is not None

    @property
    def text(self) -> str:
        return "".join(self.pieces)

    @property
    def output_tokens(self) -> int:
        return len(self.pieces)


@dataclass
class Context:
    settings: Settings
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    counter: int = 0
    stats: dict[tuple[str, int], int] = field(default_factory=dict)

    def base(self) -> dict[str, Any]:
        s = self.settings
        tps = s.mock_tokens_per_sec
        return {
            "ttft_ms": s.mock_ttft_ms,
            "token_delay_ms": 1000.0 / tps if tps > 0 else 0.0,
            "output_tokens": s.mock_output_tokens,
            "error_rate": s.mock_error_rate,
            "error": "",
            "error_kinds": s.mock_error_kinds,
            "retry_after_s": s.mock_retry_after_s,
            "hang_s": s.mock_hang_s,
            "seed": s.mock_seed,
        }

    def plan(self, request: Request, scope: str, prompt: str) -> Plan:
        base = self.base()
        cfg = dict(base)
        for layer in (self.overrides.get("*", {}), self.overrides.get(scope, {})):
            cfg.update(layer)
        explicit_seed = False
        for key in _FIELDS:
            raw = request.headers.get("x-mock-" + key.replace("_", "-"))
            if raw is not None:
                cfg[key] = raw
                explicit_seed = explicit_seed or key == "seed"
        vals: dict[str, Any] = {}
        for key, typ in _FIELDS.items():
            try:
                vals[key] = typ(cfg[key])
            except (TypeError, ValueError):  # giá trị rác -> bỏ qua, dùng env
                vals[key] = typ(base[key])
        self.counter += 1
        # Seed tường minh trên request -> lỗi phụ thuộc prompt; ngược lại phụ thuộc thứ tự request.
        roll_key = digest(prompt) if explicit_seed else self.counter
        return Plan(
            ttft_ms=max(0.0, vals["ttft_ms"]),
            token_delay_ms=max(0.0, vals["token_delay_ms"]),
            output_tokens=max(1, vals["output_tokens"]),
            seed=vals["seed"],
            error=_pick_error(vals, roll_key),
            retry_after_s=vals["retry_after_s"],
            hang_s=vals["hang_s"],
        )

    def count(self, route: str, status: int) -> None:
        key = (route, status)
        self.stats[key] = self.stats.get(key, 0) + 1

    def reset(self) -> None:
        self.overrides.clear()
        self.counter = 0


def _pick_error(vals: dict[str, Any], roll_key: object) -> str | None:
    forced = vals["error"].strip().lower()
    if forced == "none":
        return None
    if forced in ERROR_STATUS or forced == "stream_cut":
        return forced
    rate = vals["error_rate"]
    if rate <= 0:
        return None
    rng = random.Random(digest(vals["seed"], roll_key))
    if rng.random() >= rate:
        return None
    kinds = [k.strip() for k in vals["error_kinds"].split(",") if k.strip()]
    return rng.choice(kinds) if kinds else "500"


def key_ok(request: Request, settings: Settings) -> bool:
    """Chấp nhận mọi key trừ khi `MOCK_REQUIRED_KEY` được đặt."""
    required = settings.mock_required_key
    if not required:
        return True
    h = request.headers
    bearer = h.get("authorization", "").removeprefix("Bearer ").strip()
    candidates = (h.get("x-api-key"), h.get("x-goog-api-key"), request.query_params.get("key"))
    return required in (bearer, *candidates)


async def early_error(
    plan: Plan, body: Callable[[int, str], dict[str, Any]]
) -> JSONResponse | None:
    """Trả response lỗi (429/500/503, hoặc 504 sau khi treo) trước khi sinh nội dung, nếu plan yêu cầu."""
    if plan.error not in ERROR_STATUS:
        return None
    status = ERROR_STATUS[plan.error]
    headers: dict[str, str] = {}
    if plan.error == "timeout":
        await asyncio.sleep(plan.hang_s)
    if status == 429:
        headers["retry-after"] = str(plan.retry_after_s)
    return JSONResponse(body(status, f"mock injected error {plan.error}"), status, headers)


async def sleep_ms(ms: float) -> None:
    if ms > 0:
        await asyncio.sleep(ms / 1000)


async def paced(pieces: list[str], plan: Plan) -> AsyncIterator[str]:
    """Phát từng piece: TTFT trước piece đầu, `token_delay_ms` giữa các piece."""
    await sleep_ms(plan.ttft_ms)
    for i, piece in enumerate(pieces):
        if i:
            await sleep_ms(plan.token_delay_ms)
        yield piece


async def wait_full(reply: Reply, plan: Plan) -> None:
    """Độ trễ của response không stream: TTFT + thời gian sinh toàn bộ token."""
    await sleep_ms(plan.ttft_ms + plan.token_delay_ms * max(0, reply.output_tokens - 1))


def make_reply(
    plan: Plan,
    prompt: str,
    input_text: str,
    tool_names: list[str],
    tool_prefix: str,
    max_tokens: int | None,
) -> Reply:
    """Sinh câu trả lời tất định.

    - Prompt `call_tool:<tên> {json}` + request có tools -> tool call (tên bỏ trống = tool đầu).
    - Prompt `echo: <văn bản>` -> trả lại đúng văn bản.
    - Còn lại -> `mock<hash>` + (output_tokens - 1) từ chọn theo seed và hash prompt.
    Số token output = số piece, nên usage luôn khớp nội dung stream.
    """
    n_in = count_tokens(input_text)
    p = prompt.strip()
    h = digest(plan.seed, p)
    if tool_names and p.startswith(tool_prefix):
        m = _TOOL_RE.fullmatch(p[len(tool_prefix) :].strip())
        name = (m.group(1) if m else None) or tool_names[0]
        if m and name in tool_names:
            try:
                args = json.dumps(json.loads(m.group(2) or "{}"), separators=(",", ":"))
            except ValueError:
                args = "{}"
            return Reply(tokenize(args), n_in, name, "mock_" + h[:16])
    if p.startswith("echo:"):
        pieces = tokenize(p[5:].strip()) or ["ok"]
    else:
        rng = random.Random(h)
        pieces = ["mock" + h[:8]] + [
            " " + rng.choice(_VOCAB) for _ in range(plan.output_tokens - 1)
        ]
    truncated = max_tokens is not None and 0 < max_tokens < len(pieces)
    if truncated and max_tokens is not None:
        pieces = pieces[:max_tokens]
    return Reply(pieces, n_in, truncated=truncated)
