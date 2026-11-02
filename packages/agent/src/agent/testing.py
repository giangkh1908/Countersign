"""Fake cho test nghiệp vụ của agent (contracts §9.1 mục 9). Mọi fake kế thừa port tường minh."""

from __future__ import annotations

import base64
import json
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any

from acme_common.ports import Principal
from acme_common.testing import FakeClock, FakeTokenBroker, FakeTokenVerifier
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool, StructuredTool, ToolException
from pydantic import BaseModel, ConfigDict

from .container import Container
from .factory import build_agent_registry, build_serde
from .graph.builder import build_graph
from .ports.service_probe import ServiceProbe
from .ports.support_judge import SupportJudge, SupportVerdict
from .ports.tool_provider import ToolProvider
from .settings import Settings

TEST_KEY_B64 = base64.b64encode(b"k" * 32).decode()


class ScriptedChatModel(BaseChatModel):
    """Trả lần lượt các AIMessage đã kịch bản hoá; `bind_tools` trả chính nó."""

    queue: Any  # deque[AIMessage] dùng chung theo role

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _next(self) -> AIMessage:
        if not self.queue:
            raise AssertionError("ScriptedChatModel hết kịch bản")
        return self.queue.popleft()

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        msg = self._next()
        text = msg.content if isinstance(msg.content, str) else ""
        for part in text.split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=part + " "))


def scripted_factory(
    scripts: dict[str, list[AIMessage]],
) -> Callable[[str, str], Callable[[str], BaseChatModel]]:
    queues = {role: deque(msgs) for role, msgs in scripts.items()}

    def chat_factory(gw_token: str, run_id: str) -> Callable[[str], BaseChatModel]:
        return lambda role: ScriptedChatModel(queue=queues.setdefault(role, deque()))

    return chat_factory


class FakeSupportJudge(SupportJudge):
    """Judge giả. `rules`: danh sách (chuỗi con của câu, verdict); mặc định `supported` kèm bằng chứng
    là 30 ký tự đầu của đoạn. `fail=True` ném lỗi truyền tải. Ghi lại mọi lời gọi."""

    def __init__(
        self,
        rules: list[tuple[str, str]] | None = None,
        default: str = "supported",
        fail: bool = False,
    ) -> None:
        self.rules, self.default, self.fail = rules or [], default, fail
        self.calls: list[tuple[str, str]] = []

    async def judge(self, sentence: str, passage: str) -> SupportVerdict:
        self.calls.append((sentence, passage))
        if self.fail:
            raise RuntimeError("judge down")
        verdict = next((v for sub, v in self.rules if sub in sentence), self.default)
        quote = passage.strip()[:30] if verdict != "unsupported" else ""
        return SupportVerdict(
            verdict=verdict,  # type: ignore[arg-type]
            evidence_quote=quote,
            calls=1,
            input_tokens=100,
            output_tokens=20,
        )


_ANY_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": True}


class _AnyArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


class FakeToolProvider(ToolProvider):
    """`responses`: tên tool -> dict (trả JSON) | Exception (ToolException) | callable(args)->dict.

    `commit_result`: kết quả `commit_intent` (mặc định ok). Ghi lại mọi lời gọi.
    """

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        commit_result: dict[str, Any] | None = None,
    ) -> None:
        self.responses = dict(responses or {})
        self.commit_result = commit_result or {
            "ok": True,
            "op": "close_ticket",
            "ticket": {"code": "TCK-000123"},
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits: list[dict[str, Any]] = []
        self.tool_threads: list[str | None] = []

    async def tools_for(
        self,
        agent_name: str,
        principal: Principal,
        user_token: str,
        *,
        thread_id: str | None = None,
    ) -> list[BaseTool]:
        self.tool_threads.append(thread_id)
        return [self._tool(n) for n in self.responses]

    def _tool(self, name: str) -> BaseTool:
        async def run(**kwargs: Any) -> str:
            self.calls.append((name, kwargs))
            r = self.responses[name]
            if callable(r):
                r = r(kwargs)
            if isinstance(r, Exception):
                raise ToolException(str(r))
            return json.dumps(r)

        return StructuredTool(name=name, description=name, args_schema=_ANY_ARGS, coroutine=run)

    async def commit_intent(
        self,
        agent_name: str,
        intent_id: str,
        approval_token: str,
        *,
        principal: Principal,
        user_token: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        self.commits.append(
            {"agent": agent_name, "intent_id": intent_id, "approval_token": approval_token}
        )
        return self.commit_result


def make_principal(sub: str = "u1") -> Principal:
    return Principal(
        sub=sub,
        audience=("agent-service",),
        azp="chat-ui",
        scopes=frozenset({"agent:invoke"}),
        expires_at=9e9,
    )


def build_test_container(
    provider: ToolProvider,
    scripts: dict[str, list[AIMessage]],
    *,
    token: str = "user-token",
    judge: SupportJudge | None = None,
    settings: Settings | None = None,
) -> Container:
    """Container thuần fake (saver mã hoá thật dùng khoá thử nghiệm)."""
    from langgraph.checkpoint.memory import InMemorySaver

    from .adapters.memory_conversations import MemoryConversationRepository

    settings = settings or Settings(acme_env="test", agent_checkpoint_encryption_key=TEST_KEY_B64)
    the_judge = judge or FakeSupportJudge()
    registry = build_agent_registry(settings)
    saver = InMemorySaver(serde=build_serde(settings))
    clock = FakeClock()
    return Container(
        settings=settings,
        verifier=FakeTokenVerifier({token: make_principal()}),
        broker=FakeTokenBroker(clock),
        tool_provider=provider,
        registry=registry,
        graph=build_graph(saver, registry),
        checkpointer=saver,
        repo=MemoryConversationRepository(),
        clock=clock,
        chat_factory=scripted_factory(scripts),
        judge_factory=lambda gw_token, run_id: the_judge,
    )


# --- helper cho test API/SSE ---
TOKEN = "user-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PREPARED = {
    "ok": True,
    "intent_id": "int-1",
    "intent_jws": "jws.opaque.value",
    "expires_at": "2099-01-01T00:00:00Z",
    "risk_flags": [],
    "op": "close_ticket",
    "ticket_code": "TCK-000123",
}


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for frame in text.split("\n\n"):
        ev = data = None
        for line in frame.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            out.append((ev, data))
    return out


def route(name: str) -> AIMessage:
    return AIMessage(json.dumps({"route": name, "confidence": 0.95, "reason": "t"}))


def tool_call(name: str, args: dict[str, Any], cid: str = "c1") -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": cid}])


class FakeServiceProbe(ServiceProbe):
    """Probe giả: `up` là tập URL được coi là khoẻ."""

    def __init__(self, up: set[str] | None = None) -> None:
        self.up = up or set()
        self.calls: list[str] = []

    async def is_reachable(self, url: str) -> bool:
        self.calls.append(url)
        return url in self.up
