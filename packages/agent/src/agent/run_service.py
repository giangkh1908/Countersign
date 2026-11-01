"""Chạy một lượt (run/resume) và dịch sự kiện đồ thị thành sự kiện SSE (03 §1.4).

Luôn kết thúc bằng đúng một `done` hoặc `error`. Không bao giờ log nội dung hội thoại hay token.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from acme_common.ports import Principal, TokenExchangeDenied, TokenServiceUnavailable
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from .container import Container
from .graph.nodes import ERROR_EVENT_CODES
from .graph.state import Limits, RunContext
from .llm import CostCollector, current_cost, translate_llm_error
from .ports.errors import ConfigError, GatewayError, ToolUnavailable

log = logging.getLogger("agent.run")
Event = tuple[str, dict[str, Any]]

_ERR_MSG = {
    "auth": "Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.",
    "tool_unavailable": "Công cụ nghiệp vụ tạm thời không phản hồi. Bạn thử lại sau.",
    "provider_unavailable": "Dịch vụ tạm thời không phản hồi. Bạn thử lại sau ít phút.",
    "recursion_limit": "Yêu cầu quá phức tạp, tôi đã dừng để tránh vòng lặp.",
    "invalid_request": "Yêu cầu tiếp tục không hợp lệ.",
    "internal": "Đã xảy ra lỗi nội bộ.",
    "intent_expired": "Đề xuất đã hết hạn nên chưa có gì được thực hiện.",
    "intent_not_found": "Đề xuất không còn hiệu lực nên chưa có gì được thực hiện.",
    "conflict": "Ticket đã thay đổi nên chưa có gì được thực hiện.",
    "approval_expired": "Phê duyệt đã hết hạn nên chưa có gì được thực hiện.",
}


def config_of(thread_id: str) -> dict[str, Any]:
    # ADR-004: configurable chỉ chứa thread_id (metadata checkpoint là plaintext).
    return {"configurable": {"thread_id": thread_id}}


def pending_interrupt(snap: Any) -> dict[str, Any] | None:
    """`{interrupt_id, payload}` của interrupt đang chờ, hoặc None."""
    for it in getattr(snap, "interrupts", ()) or ():
        v = it.value
        if isinstance(v, dict) and "interrupt_id" in v:
            return {"interrupt_id": v["interrupt_id"], "payload": v}
    return None


def _error_event(code: str, message: str | None = None, retryable: bool = False) -> Event:
    return "error", {
        "code": code,
        "message": message or _ERR_MSG.get(code, _ERR_MSG["internal"]),
        "retryable": retryable,
    }


def _classify(exc: BaseException) -> Event:
    if isinstance(exc, GatewayError):
        return _error_event(exc.code, exc.user_message, exc.retryable)
    if (gw := translate_llm_error(exc)) is not None:
        return _error_event(gw.code, gw.user_message, gw.retryable)
    if isinstance(exc, TokenExchangeDenied):
        return _error_event("auth")
    if isinstance(exc, TokenServiceUnavailable):
        return _error_event("provider_unavailable", retryable=True)
    if isinstance(exc, ToolUnavailable):
        return _error_event("tool_unavailable", retryable=exc.retryable)
    if isinstance(exc, GraphRecursionError):
        return _error_event("recursion_limit")
    if isinstance(exc, ValueError) and "resume decision" in str(exc):
        return _error_event("invalid_request")
    if isinstance(exc, ConfigError):
        return _error_event("internal")
    return _error_event("internal")


async def stream_run(
    c: Container, principal: Principal, user_token: str, thread_id: str, graph_input: Any
) -> AsyncIterator[Event]:
    run_id = str(uuid.uuid4())
    cost = CostCollector()
    reset = current_cost.set(cost)
    cfg = config_of(thread_id)
    try:
        yield "run_start", {"run_id": run_id, "thread_id": thread_id, "request_ids": []}
        gw = await c.broker.token_for(principal, user_token, "llm-gateway", ["llm:invoke"])
        s = c.settings
        ctx = RunContext(
            principal=principal,
            user_token=user_token,
            thread_id=thread_id,
            run_id=run_id,
            tool_provider=c.tool_provider,
            make_chat_model=c.chat_factory(gw.value, run_id),
            registry=c.registry,
            clock=c.clock,
            cost=cost,
            limits=Limits(s.agent_max_tool_calls_turn, s.agent_max_react_iters, s.agent_conf_min),
        )
        async for mode, chunk in c.graph.astream(
            graph_input,
            {**cfg, "recursion_limit": s.agent_recursion_limit},
            context=ctx,
            stream_mode=["custom"],
        ):
            if mode == "custom" and isinstance(chunk, dict) and "event" in chunk:
                yield chunk["event"], chunk["data"]
        snap = await c.graph.aget_state(cfg)
        values = snap.values or {}
        await c.repo.touch(thread_id)
        interrupt = pending_interrupt(snap)
        if interrupt:
            yield "interrupt", interrupt
        elif values.get("citations"):
            yield "citations", {"items": values["citations"]}
        msgs = values.get("messages") or []
        last_ai = next((m for m in reversed(msgs) if isinstance(m, AIMessage)), None)
        yield (
            "cost",
            {
                "turn_usd": cost.total_usd,
                "thread_usd": values.get("cost_usd", 0.0),
                "calls": cost.calls,
            },
        )
        wr = values.get("write_result") or {}
        code = (wr.get("error") or {}).get("code") if wr and not wr.get("ok") else None
        if code in ERROR_EVENT_CODES:
            yield _error_event(code)
            return
        if interrupt:
            status = "interrupted"
        elif (values.get("approval") or {}).get("decision") == "reject":
            status = "rejected"
        else:
            status = "completed"
        yield "done", {"status": status, "message_id": getattr(last_ai, "id", None)}
    except Exception as exc:  # luồng phải kết thúc bằng đúng một error
        log.warning("run_failed", extra={"fields": {"type": type(exc).__name__}})
        yield _classify(exc)
    finally:
        current_cost.reset(reset)


def run_input(text: str, client_msg_id: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(text, id=client_msg_id)]}


def resume_input(decision: dict[str, Any]) -> Command:
    return Command(resume=decision)
