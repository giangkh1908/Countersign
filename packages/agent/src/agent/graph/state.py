"""State và RunContext của đồ thị (03 §2).

Quy tắc ADR-004: nội dung nhạy cảm chỉ nằm trong `messages` hoặc channel non-primitive (dict/list);
channel `str`/`int`/`float` chỉ cho cờ/bộ đếm không nhạy cảm. Token KHÔNG vào state: truyền qua
`RunContext` (langgraph `context=`), không qua `config["configurable"]`.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from acme_common.ports import Clock, Principal
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AnyMessage
from langchain_core.tools import BaseTool
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from ..agents import AgentRegistry
from ..llm import CostCollector
from ..ports.tool_provider import ToolProvider


def _merge_citations(a: list[dict], b: list[dict] | None) -> list[dict]:
    if b is None:
        return a
    if b == []:
        return []  # begin_turn reset
    seen = {(c["doc_id"], c.get("chunk_ord")) for c in a}
    return a + [c for c in b if (c["doc_id"], c.get("chunk_ord")) not in seen]


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    route_info: dict | None  # {route, confidence, reason, clarify}: dict vì reason là văn bản tự do
    pending_action: dict | None  # PendingAction.model_dump()
    approval: dict | None  # {decision, edits, approval_token, reason}; token xoá sau execute_write
    write_result: dict | None
    citations: Annotated[list[dict], _merge_citations]
    seen_intents: Annotated[
        list[str], operator.add
    ]  # chống replay intent_id trong thread (ADR-005)
    cost_usd: Annotated[float, operator.add]
    step_count: Annotated[int, operator.add]
    tool_calls: Annotated[int, operator.add]
    turn_base: dict | None  # {tool_calls}: mốc đầu lượt


class PendingAction(BaseModel):
    action_id: str
    agent: str  # node_name của agent đã prepare
    op: str
    audience: str
    intent_id: str
    intent_jws: str
    prepare_args: dict[str, Any]
    expires_at: str
    status: str = "proposed"  # proposed | approved | editing | rejected | executed | failed
    revisions: int = 0


@dataclass
class Limits:
    max_tool_calls_turn: int = 8
    max_react_iters: int = 6
    conf_min: float = 0.5


@dataclass
class RunContext:
    """Dữ liệu theo run, KHÔNG vào checkpoint."""

    principal: Principal
    user_token: str
    thread_id: str
    run_id: str
    tool_provider: ToolProvider
    make_chat_model: Callable[[str], BaseChatModel]
    registry: AgentRegistry
    clock: Clock
    cost: CostCollector
    limits: Limits = field(default_factory=Limits)
    tool_cache: dict[str, list[BaseTool]] = field(default_factory=dict)
