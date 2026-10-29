# Research 03 — LangGraph, HITL, MCP adapter, UI (reader/Haiku, 2026-10-28)

## Kết luận
- LangGraph **1.2.18** (26/10/2026), Python ≥3.10. HITL chuẩn: `interrupt()` + `Command(resume=...)`, cần checkpointer + `thread_id`. Node được chạy lại từ đầu khi resume → code trước `interrupt()` phải idempotent.
- `HumanInTheLoopMiddleware` (langchain.agents.middleware) có sẵn cho `create_agent` (approve/edit/reject/respond; per-call cần `langchain>=1.4.6`). Với StateGraph tự viết → tự gọi `interrupt()` trong node ghi.
- Router đơn giản → StateGraph tự viết (classifier structured output + `add_conditional_edges`). `langgraph-supervisor` 0.0.31 (11/2025) — PyPI khuyên dùng supervisor-qua-tool trực tiếp. Swarm không cần.
- MCP: `langchain-mcp-adapters` đang được thay bằng `langchain.mcp.MCPAdapter` (beta, `langchain[mcp]>=1.4.0`). Header gắn theo connection → token theo user ⇒ tạo client/tool theo request.
- `ChatOpenAI(base_url=...)`: chỉ theo đúng spec OpenAI, trường lạ bị bỏ. Khi dùng `OPENAI_BASE_URL`, `stream_usage` mặc định tắt → đặt `stream_usage=True`. `bind_tools(strict=True)` được hỗ trợ.
- Eval: LangSmith (đóng), **Langfuse (MIT, self-host)**, Phoenix (OTel). Routing accuracy phải tự xây tập có nhãn (50–100 câu).
- UI: Agent Chat UI (MIT, nối LangGraph server, hỗ trợ interrupt theo docs frontend) — nhanh nhất; Chainlit nếu cần tùy biến nút duyệt.

## Mẫu HITL
```python
from langgraph.types import interrupt, Command

def write_ticket_gate(state):
    decision = interrupt({"action": "create_ticket", "payload": state["draft"]})
    if decision.get("type") != "approve":
        return {"status": "rejected"}
    return {"status": "approved"}   # tool thật chạy ở node sau

graph = builder.compile(checkpointer=checkpointer)  # PostgresSaver khi production
config = {"configurable": {"thread_id": tid}}
graph.invoke(input, config)
graph.invoke(Command(resume={"type": "approve"}), config)
```

## Nguồn
- https://pypi.org/project/langgraph/
- https://docs.langchain.com/oss/python/langgraph/human-in-the-loop
- https://docs.langchain.com/oss/python/langchain/human-in-the-loop.md
- https://pypi.org/project/langgraph-supervisor/
- https://docs.langchain.com/oss/python/langchain/mcp
- https://www.scalekit.com/blog/langgraph-mcp-per-user-oauth (bên thứ ba)
- https://docs.langchain.com/oss/python/integrations/chat/openai
- https://github.com/langchain-ai/agent-chat-ui , https://docs.langchain.com/oss/python/langchain/frontend/overview

## Chưa xác minh
- Phiên bản `langchain-mcp-adapters`, `langgraph-checkpoint-postgres`; hỗ trợ interrupt của Chainlit/Open WebUI; so sánh eval platform dựa trên nguồn thứ cấp.
