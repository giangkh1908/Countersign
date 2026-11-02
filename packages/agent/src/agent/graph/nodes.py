"""Node của đồ thị. Chỉ import port/registry; sự kiện UI phát qua `get_stream_writer()`.

Quy ước event: writer nhận `{"event": <tên SSE>, "data": {...}}` (custom stream mode).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from acme_common.telemetry import span
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool, ToolException
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError, model_validator

from ..agents import AgentRegistry, AgentSpec
from ..metrics import record_verification, verification_counts
from ..ports.errors import ToolUnavailable
from ..services.answer import build_answer, fit_frame, refusal
from ..services.citation_verifier import CitationVerifier
from ..services.citations import Passage
from .state import AgentState, PendingAction, RunContext

Rt = Runtime[RunContext]
NodeFn = Callable[[AgentState, Rt], Awaitable[dict[str, Any]]]
BASE_ROUTES = ("chitchat", "out_of_scope")
MAX_PREVIEW = 200


def _emit(event: str, data: dict[str, Any]) -> None:
    get_stream_writer()({"event": event, "data": data})


def _emit_text(text: str, node: str) -> None:
    for part in re.findall(r"\S+\s*", text) or [text]:
        _emit("token", {"text": part, "node": node})


def _history(messages: list[BaseMessage], keep_humans: int = 3) -> list[BaseMessage]:
    idx = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    return messages[idx[-keep_humans] :] if len(idx) > keep_humans else list(messages)


def _turn_iters(messages: list[BaseMessage]) -> int:
    n = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage):
            n += 1
    return n


def _text_of(msg: BaseMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c
    return "".join(p.get("text", "") for p in c if isinstance(p, dict))


# ---------------------------------------------------------------- begin_turn
async def begin_turn(state: AgentState, runtime: Rt) -> dict[str, Any]:
    return {
        "route_info": None,
        "pending_action": None,
        "approval": None,
        "write_result": None,
        "citations": [],
        "retrieved": {},
        "retrieval": None,
        "answer_meta": None,
        "turn_base": {"tool_calls": state.get("tool_calls", 0)},
    }


# ---------------------------------------------------------------- router
def _router_prompt(registry: AgentRegistry) -> str:
    labels = [f"- {s.route}: {s.description_vi}" for s in registry.all()]
    labels += [
        "- chitchat: chào hỏi, xã giao, câu hỏi chung không cần tra cứu.",
        "- out_of_scope: yêu cầu ngoài phạm vi trợ lý nội bộ.",
    ]
    ex = [f'"{q}" -> {r}' for s in registry.all() for q, r in s.router_examples]
    return (
        "Bạn là bộ định tuyến. Phân loại tin nhắn CUỐI của người dùng vào đúng một nhãn:\n"
        + "\n".join(labels)
        + "\nVí dụ: "
        + "; ".join(ex)
        + '\nChỉ trả về JSON: {"route": "<nhãn>", "confidence": <0..1>, "reason": "<ngắn>"}.'
    )


def _parse_route(text: str, valid: set[str]) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        route, conf = str(d["route"]), float(d.get("confidence", 1.0))
    except (ValueError, KeyError, TypeError):
        return None
    if route not in valid or not 0.0 <= conf <= 1.0:
        return None
    return {"route": route, "confidence": conf, "reason": str(d.get("reason", ""))[:200]}


def make_router(registry: AgentRegistry) -> NodeFn:
    valid = set(registry.routes()) | set(BASE_ROUTES)
    prompt = _router_prompt(registry)

    async def router(state: AgentState, runtime: Rt) -> dict[str, Any]:
        ctx = runtime.context
        llm = ctx.make_chat_model("router")
        recent = [
            m for m in _history(state["messages"], 2) if isinstance(m, HumanMessage | AIMessage)
        ]
        info = None
        steps = 0
        for _ in range(2):
            steps += 1
            resp = await llm.ainvoke([SystemMessage(prompt), *recent])
            info = _parse_route(_text_of(resp), valid)
            if info:
                break
        clarify = None
        if info is None:
            info = {"route": "chitchat", "confidence": 0.0, "reason": "parse_error"}
            clarify = "Bạn muốn hỏi về tài liệu hay về ticket?"
        elif info["route"] in registry.routes() and info["confidence"] < ctx.limits.conf_min:
            clarify = "Bạn có thể nói rõ hơn là muốn tra cứu tài liệu hay xử lý ticket nào không?"
            info = {**info, "route": "chitchat"}
        info = {**info, "clarify": clarify}
        _emit("route", {k: info[k] for k in ("route", "confidence", "reason")})
        usd, _ = ctx.cost.drain()
        return {"route_info": info, "cost_usd": usd, "step_count": steps}

    return router


def route_edge(registry: AgentRegistry) -> Callable[[AgentState], str]:
    def edge(state: AgentState) -> str:
        spec = registry.by_route((state.get("route_info") or {}).get("route", ""))
        return spec.node_name if spec else "direct_answer"

    return edge


# ---------------------------------------------------------------- direct_answer
async def direct_answer(state: AgentState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    info = state.get("route_info") or {}
    system = (
        "Bạn là trợ lý nội bộ doanh nghiệp, trả lời tiếng Việt ngắn gọn. "
        + ("Hãy hỏi lại người dùng: " + info["clarify"] if info.get("clarify") else "")
        + (
            "Từ chối lịch sự yêu cầu ngoài phạm vi và gợi ý việc bạn làm được (tra cứu tài liệu, xử lý ticket)."
            if info.get("route") == "out_of_scope"
            else ""
        )
    )
    llm = ctx.make_chat_model("direct")
    parts: list[str] = []
    async for chunk in llm.astream([SystemMessage(system), *_history(state["messages"])]):
        t = _text_of(chunk)
        if t:
            parts.append(t)
            _emit("token", {"text": t, "node": "direct_answer"})
    usd, _ = ctx.cost.drain()
    return {"messages": [AIMessage("".join(parts))], "cost_usd": usd, "step_count": 1}


# ---------------------------------------------------------------- ReAct (agent + tools)
async def _tools(ctx: RunContext, spec: AgentSpec) -> list[BaseTool]:
    if spec.node_name not in ctx.tool_cache:
        ctx.tool_cache[spec.node_name] = await ctx.tool_provider.tools_for(
            spec.node_name, ctx.principal, ctx.user_token, thread_id=ctx.thread_id
        )
    return ctx.tool_cache[spec.node_name]


def make_agent_node(spec: AgentSpec) -> NodeFn:
    async def agent(state: AgentState, runtime: Rt) -> dict[str, Any]:
        ctx = runtime.context
        tools = await _tools(ctx, spec)
        used = state.get("tool_calls", 0) - (state.get("turn_base") or {}).get("tool_calls", 0)
        exhausted = (
            used >= ctx.limits.max_tool_calls_turn
            or _turn_iters(state["messages"]) >= ctx.limits.max_react_iters
        )
        llm = ctx.make_chat_model("agent")
        bound = llm if exhausted or not tools else llm.bind_tools(tools)
        prompt: list[BaseMessage] = [
            SystemMessage(spec.system_prompt),
            *_history(state["messages"]),
        ]
        if exhausted:
            prompt.append(
                SystemMessage(
                    "Hết ngân sách tra cứu: hãy trả lời bằng thông tin đã có và nói rõ phần còn thiếu."
                )
            )
        resp = await bound.ainvoke(prompt)
        if exhausted and getattr(resp, "tool_calls", None):
            resp = AIMessage(_text_of(resp) or "Tôi chưa thể hoàn tất việc tra cứu.")
        usd, _ = ctx.cost.drain()
        return {"messages": [resp], "cost_usd": usd, "step_count": 1}

    return agent


def agent_edge(spec: AgentSpec) -> Callable[[AgentState], str]:
    tools_node = f"{spec.route}_tools"

    def edge(state: AgentState) -> str:
        last = state["messages"][-1]
        return tools_node if isinstance(last, AIMessage) and last.tool_calls else "final_answer"

    return edge


def _summary(name: str, ok: bool, data: Any) -> str:
    if not ok:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        return f"lỗi: {err.get('code', 'unknown')}"
    if name == "search_documents" and isinstance(data, dict):
        res = data.get("results", [])
        return f"{len(res)} đoạn từ {len({r.get('doc_id') for r in res})} tài liệu"
    return "ok"


def _content_for_model(data: dict[str, Any]) -> str:
    """Nội dung tool đưa cho mô hình: bỏ `text` thô (chỉ `content` đã spotlight), thêm mã trích `[#id]`."""
    res = [
        {**{k: v for k, v in r.items() if k != "text"}, "cite": f"[#{r['chunk_id']}]"}
        for r in data.get("results", [])
        if isinstance(r, dict)
    ]
    return json.dumps({**data, "results": res}, ensure_ascii=False)


async def _claims_unverified(ctx: RunContext, text: str, retrieved: dict[str, Any]) -> bool:
    """Văn bản agent soạn từ tài liệu có chưa kiểm chứng đủ không? Fail-closed: mọi trường hợp không
    kiểm chứng được (tắt verify, không có đoạn nguồn, judge lỗi) đều tính là chưa kiểm chứng.
    """
    if not (ctx.verify_enabled and ctx.make_judge is not None) or not retrieved or not text.strip():
        return True
    try:
        passages = {k: Passage.model_validate(v) for k, v in retrieved.items()}
        verifier = CitationVerifier(ctx.make_judge(), ctx.verify_cfg)
        ans = await build_answer(text, passages, verifier, ctx.verify_cfg)
    except Exception:  # noqa: BLE001 - lỗi bất kỳ khi kiểm chứng = chưa kiểm chứng
        return True
    return (
        ans.answer_status != "answered"
        or not ans.items
        or bool(ans.verify.get("invalid_refs"))
        or bool(ans.verify.get("dropped_sentences"))
    )


def make_tools_node(spec: AgentSpec) -> NodeFn:
    async def tools_node(state: AgentState, runtime: Rt) -> dict[str, Any]:
        ctx = runtime.context
        by_name = {t.name: t for t in await _tools(ctx, spec)}
        allowed = spec.allowed_tool_names()
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        seen = set(state.get("seen_intents", []))
        out: list[ToolMessage] = []
        passages: dict[str, dict[str, Any]] = {}
        searches = 0
        pending: dict[str, Any] | None = None
        new_seen: list[str] = []
        reads = 0
        for call in last.tool_calls:
            name, args, cid = call["name"], call.get("args", {}), call["id"]
            is_prepare = name in spec.prepare_tools
            if pending is not None and is_prepare:
                out.append(
                    ToolMessage(
                        "Bỏ qua: chỉ xử lý một thao tác mỗi lượt.", tool_call_id=cid, name=name
                    )
                )
                continue
            if name not in allowed or name not in by_name or (not is_prepare and reads >= 3):
                out.append(
                    ToolMessage(
                        "Công cụ không được phép hoặc quá giới hạn.",
                        tool_call_id=cid,
                        name=name,
                        status="error",
                    )
                )
                continue
            reads += 0 if is_prepare else 1
            text_arg = (
                spec.verify_text_arg.get(name.removeprefix("prepare_")) if is_prepare else None
            )
            if text_arg:
                body = args.get(text_arg)
                unverified = await _claims_unverified(
                    ctx,
                    body if isinstance(body, str) else "",
                    {**(state.get("retrieved") or {}), **passages},
                )
                args = {
                    **args,
                    "unverified_claims": unverified or bool(args.get("unverified_claims")),
                }
            _emit(
                "tool_start",
                {
                    "call_id": cid,
                    "agent": spec.route,
                    "tool": name,
                    "args_preview": json.dumps(args, ensure_ascii=False)[:MAX_PREVIEW],
                },
            )
            t0 = time.monotonic()
            ok, content = True, ""
            with span(f"tool.{name}", tool=name) as tsp:
                try:
                    content = str(await by_name[name].ainvoke(args))
                except ToolException as e:
                    ok, content = False, str(e)
                except ToolUnavailable:
                    ok, content = (
                        False,
                        json.dumps({"error": {"code": "upstream_unavailable", "retryable": True}}),
                    )
                tsp.set_attribute("outcome", "ok" if ok else "error")
            try:
                data: Any = json.loads(content)
            except ValueError:
                data = {}
            _emit(
                "tool_end",
                {
                    "call_id": cid,
                    "ok": ok,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "summary": _summary(name, ok, data),
                },
            )
            if ok and is_prepare:
                iid = data.get("intent_id") if isinstance(data, dict) else None
                jws = data.get("intent_jws") if isinstance(data, dict) else None
                exp = data.get("expires_at") if isinstance(data, dict) else None
                if not (iid and jws and exp) or iid in seen:
                    out.append(
                        ToolMessage(
                            "Đề xuất không hợp lệ.", tool_call_id=cid, name=name, status="error"
                        )
                    )
                    continue
                pending = PendingAction(
                    action_id=str(uuid.uuid4()),
                    agent=spec.node_name,
                    op=name.removeprefix("prepare_"),
                    audience=spec.write_audience or "",
                    intent_id=iid,
                    intent_jws=jws,
                    prepare_args=dict(args),
                    expires_at=str(exp),
                ).model_dump()
                new_seen.append(iid)
                content = "Đã chuẩn bị đề xuất, chờ người dùng xác nhận trên giao diện. Chưa có gì được thực hiện."
            elif ok and spec.citations_extractor and isinstance(data, dict) and "results" in data:
                searches += 1
                got = spec.citations_extractor(name, data)
                passages.update({str(p["chunk_id"]): p for p in got})
                content = _content_for_model(data)
            out.append(
                ToolMessage(
                    content, tool_call_id=cid, name=name, status="success" if ok else "error"
                )
            )
        upd: dict[str, Any] = {
            "messages": out,
            "tool_calls": len(last.tool_calls),
        }
        if searches:
            prev = state.get("retrieval") or {}
            n_passages = len({*(state.get("retrieved") or {}), *passages})
            upd["retrieval"] = {
                "searches": prev.get("searches", 0) + searches,
                "passages": n_passages,
            }
            if passages:
                upd["retrieved"] = passages
        if pending:
            upd["pending_action"] = pending
            upd["seen_intents"] = new_seen
        return upd

    return tools_node


def cited_tools_edge(spec: AgentSpec) -> Callable[[AgentState], str]:
    """Agent có trích dẫn: tìm kiếm thành công mà 0 đoạn => từ chối ngay, không gọi mô hình sinh (§5.3.6a)."""

    def edge(state: AgentState) -> str:
        r = state.get("retrieval") or {}
        return "final_answer" if r.get("searches") and not r.get("passages") else spec.node_name

    return edge


def tools_edge(spec: AgentSpec) -> Callable[[AgentState], str]:
    def edge(state: AgentState) -> str:
        pa = state.get("pending_action")
        return "approval" if pa and pa.get("status") == "proposed" else spec.node_name

    return edge


# ---------------------------------------------------------------- approval (HITL)
class Decision(BaseModel):
    type: Literal["approve", "edit", "reject", "refresh"]
    edits: dict[str, Any] | None = None
    approval_token: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Decision:
        if self.type == "approve" and not self.approval_token:
            raise ValueError("approve requires approval_token")
        if self.type != "approve" and self.approval_token:
            raise ValueError("approval_token only valid for approve")
        return self


def interrupt_id_of(action_id: str, intent_id: str) -> str:
    return "int_" + hashlib.sha256(f"{action_id}:{intent_id}".encode()).hexdigest()[:24]


def build_interrupt_payload(pa: PendingAction) -> dict[str, Any]:
    """Chỉ định danh + JWS mờ đục. Không có args/preview/diff."""
    return {
        "interrupt_id": interrupt_id_of(pa.action_id, pa.intent_id),
        "kind": "write_approval",
        "action_id": pa.action_id,
        "intent_id": pa.intent_id,
        "intent_jws": pa.intent_jws,
        "op": pa.op,
        "expires_at": pa.expires_at,
    }


async def approval_node(state: AgentState, runtime: Rt) -> dict[str, Any]:
    pa = PendingAction.model_validate(state["pending_action"])
    raw = interrupt(build_interrupt_payload(pa))  # không có code nào có tác dụng phụ trước dòng này
    try:
        d = Decision.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("invalid resume decision") from exc
    status = {"approve": "approved", "edit": "editing", "refresh": "editing", "reject": "rejected"}[
        d.type
    ]
    return {
        "approval": {
            "decision": d.type,
            "edits": d.edits,
            "approval_token": d.approval_token,
            "reason": d.reason,
        },
        "pending_action": {**pa.model_dump(), "status": status},
    }


def approval_edge(state: AgentState) -> str:
    a, p = state["approval"], state["pending_action"]
    assert a and p
    if a["decision"] == "approve":
        return "execute_write"
    if a["decision"] in ("edit", "refresh"):
        return "reprepare" if p["revisions"] < 3 else "final_answer"
    return "final_answer"


# ---------------------------------------------------------------- reprepare (edit / refresh)
def make_reprepare(registry: AgentRegistry) -> NodeFn:
    async def reprepare(state: AgentState, runtime: Rt) -> dict[str, Any]:
        ctx = runtime.context
        pa = PendingAction.model_validate(state["pending_action"])
        spec = registry.by_node(pa.agent)
        allowed = spec.editable_fields.get(pa.op, frozenset())
        edits = {
            k: v
            for k, v in ((state.get("approval") or {}).get("edits") or {}).items()
            if k in allowed
        }
        args = {**pa.prepare_args, **edits}
        text_arg = spec.verify_text_arg.get(pa.op)
        if (
            text_arg and text_arg in edits
        ):  # người dùng sửa văn bản: kiểm chứng lại, không dùng cờ cũ
            body = args.get(text_arg)
            args["unverified_claims"] = await _claims_unverified(
                ctx, body if isinstance(body, str) else "", state.get("retrieved") or {}
            )
        by_name = {t.name: t for t in await _tools(ctx, spec)}
        tool = by_name.get(f"prepare_{pa.op}")
        fail = {
            "write_result": {"ok": False, "error": {"code": "prepare_failed"}},
            "pending_action": {**pa.model_dump(), "status": "failed"},
        }
        if tool is None:
            return fail
        try:
            data = json.loads(str(await tool.ainvoke(args)))
        except (ToolException, ToolUnavailable, ValueError):
            return fail
        iid = data.get("intent_id")
        if not (iid and data.get("intent_jws") and data.get("expires_at")) or iid in state.get(
            "seen_intents", []
        ):
            return fail
        new = pa.model_copy(
            update={
                "intent_id": iid,
                "intent_jws": data["intent_jws"],
                "expires_at": str(data["expires_at"]),
                "prepare_args": args,
                "status": "proposed",
                "revisions": pa.revisions + 1,
            }
        )
        return {"pending_action": new.model_dump(), "seen_intents": [iid], "approval": None}

    return reprepare


def reprepare_edge(state: AgentState) -> str:
    pa = state.get("pending_action")
    return "approval" if pa and pa.get("status") == "proposed" else "final_answer"


# ---------------------------------------------------------------- execute_write
async def execute_write(state: AgentState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    pa = PendingAction.model_validate(state["pending_action"])
    ap = dict(state["approval"] or {})
    if pa.status == "executed":
        return {}
    cid = str(uuid.uuid4())
    _emit(
        "tool_start",
        {
            "call_id": cid,
            "agent": "ticket",
            "tool": "commit_intent",
            "args_preview": json.dumps({"intent_id": pa.intent_id}),
        },
    )
    t0 = time.monotonic()
    try:
        res = await ctx.tool_provider.commit_intent(
            pa.agent,
            pa.intent_id,
            ap["approval_token"],
            principal=ctx.principal,
            user_token=ctx.user_token,
            thread_id=ctx.thread_id,
        )
    except ToolUnavailable:  # không tự retry
        res = {"ok": False, "error": {"code": "upstream_unavailable", "details": {}}}
    if (
        not res.get("ok")
        and res["error"]["code"] == "approval_replayed"
        and (res["error"].get("details") or {}).get("already_applied")
    ):
        res = {"ok": True, "reconciled": True, **(res["error"].get("details") or {})}
    _emit(
        "tool_end",
        {
            "call_id": cid,
            "ok": bool(res.get("ok")),
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "summary": "ok" if res.get("ok") else f"lỗi: {res['error']['code']}",
        },
    )
    ap["approval_token"] = None  # xoá token khỏi state ngay sau khi dùng
    return {
        "write_result": res,
        "approval": ap,
        "pending_action": {**pa.model_dump(), "status": "executed" if res.get("ok") else "failed"},
        "tool_calls": 1,
    }


# ---------------------------------------------------------------- final_answer
_FAIL_TEXT = {
    "intent_expired": "Đề xuất đã hết hạn nên chưa có gì được thực hiện. Hãy yêu cầu lại để tạo đề xuất mới.",
    "intent_not_found": "Đề xuất không còn hiệu lực nên chưa có gì được thực hiện. Hãy yêu cầu lại.",
    "conflict": "Ticket đã thay đổi hoặc không ở trạng thái cho phép nên chưa có gì được thực hiện. Hãy kiểm tra lại ticket.",
    "approval_expired": "Phê duyệt đã hết hạn nên chưa có gì được thực hiện. Hãy duyệt lại.",
    "forbidden": "Bạn không có quyền thực hiện thao tác này.",
    "not_found": "Không tìm thấy ticket hoặc bạn không có quyền xem.",
    "upstream_unavailable": "Hệ thống ticket tạm thời không phản hồi. Chưa xác nhận được kết quả; hãy kiểm tra lại ticket.",
}
_GENERIC_FAIL = (
    "Không thể thực hiện thao tác (xác thực phê duyệt không hợp lệ). Chưa có gì được thay đổi."
)
# Mã lỗi ghi khiến luồng kết thúc bằng event `error`.
ERROR_EVENT_CODES = frozenset(
    {"intent_expired", "intent_not_found", "conflict", "approval_expired"}
)


def write_outcome_text(state: AgentState) -> str | None:
    wr, ap, pa = state.get("write_result"), state.get("approval"), state.get("pending_action") or {}
    if wr:
        if wr.get("ok"):
            code = (wr.get("ticket") or {}).get("code") or pa.get("prepare_args", {}).get(
                "code", ""
            )
            return f"Đã thực hiện xong thao tác trên ticket {code}.".replace("  ", " ")
        return _FAIL_TEXT.get(wr["error"]["code"], _GENERIC_FAIL)
    if ap and ap.get("decision") == "reject":
        return "Đã hủy đề xuất theo yêu cầu của bạn. Không có thay đổi nào được thực hiện."
    if pa.get("status") == "editing":
        return "Đã đạt giới hạn số lần chỉnh sửa đề xuất. Không có thay đổi nào được thực hiện."
    return None


async def _cited_answer(
    state: AgentState, ctx: RunContext, last: BaseMessage
) -> dict[str, Any] | None:
    """Agent có trích dẫn: resolve mã `[#id]`, kiểm chứng (nếu bật), từ chối khi không đủ nguồn.

    Văn bản được sinh trọn rồi mới phát (bản nháp là một AIMessage hoàn chỉnh), nên không cần sự kiện
    "thay thế văn bản" (rag-citations §5.3).
    """
    r = state.get("retrieval") or {}
    verifying = ctx.verify_enabled and ctx.make_judge is not None
    if r.get("searches") and not r.get("passages"):
        ans = refusal(enabled=verifying)  # truy xuất 0 đoạn: từ chối trước khi sinh
        msg_id = None
    elif isinstance(last, AIMessage) and not last.tool_calls and _text_of(last).strip():
        retrieved = {
            k: Passage.model_validate(v) for k, v in (state.get("retrieved") or {}).items()
        }
        verifier = CitationVerifier(ctx.make_judge(), ctx.verify_cfg) if verifying else None  # type: ignore[misc]
        with span("verification") as vsp:
            ans = await build_answer(_text_of(last), retrieved, verifier, ctx.verify_cfg)
            claims, verified, failed = verification_counts(ans)
            vsp.set_attribute("claims", claims)
            vsp.set_attribute("verified", verified)
            vsp.set_attribute("failed", failed)
        msg_id = last.id
    else:
        return None
    record_verification(ans)
    usd, _ = ctx.cost.drain()
    if ans.verify.get("enabled"):
        ans.verify["cost_usd"] = round(usd, 6)
    payload = fit_frame(ans.payload())
    _emit_text(ans.text, "final_answer")
    meta = {k: payload[k] for k in ("sentences", "answer_status", "verify")}
    return {
        "messages": [AIMessage(ans.text, id=msg_id, additional_kwargs={"citations": payload})],
        "citations": payload["items"],
        "answer_meta": meta,
        "cost_usd": usd,
    }


async def final_answer(state: AgentState, runtime: Rt) -> dict[str, Any]:
    ctx = runtime.context
    text = write_outcome_text(state)
    if text is not None:
        _emit_text(text, "final_answer")
        return {"messages": [AIMessage(text)]}
    last = state["messages"][-1]
    spec = ctx.registry.by_route((state.get("route_info") or {}).get("route", ""))
    if spec is not None and spec.citations_extractor is not None:
        ans = await _cited_answer(state, ctx, last)
        if ans is not None:
            return ans
    if isinstance(last, AIMessage) and not last.tool_calls and _text_of(last).strip():
        _emit_text(_text_of(last), "final_answer")  # bản nháp cuối của agent chính là câu trả lời
        return {}
    text = "Xin lỗi, tôi chưa tạo được câu trả lời. Bạn thử diễn đạt lại nhé."
    _emit_text(text, "final_answer")
    return {"messages": [AIMessage(text)]}
