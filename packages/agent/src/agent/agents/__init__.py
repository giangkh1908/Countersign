"""Registry agent chuyên trách: mỗi agent là một file khai báo một `AgentSpec`.

Router, graph và allowlist đều đọc từ registry; thêm agent = thêm file + một dòng ở
`factory._AGENTS`, không sửa builder hay node.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ..ports.tool_provider import AgentAccess, ServerAccess

CitationExtractor = Callable[[str, dict[str, Any]], list[dict[str, Any]]]


@dataclass(frozen=True)
class AgentSpec:
    route: str
    node_name: str
    description_vi: str
    router_examples: tuple[tuple[str, str], ...]
    system_prompt: str
    read: tuple[ServerAccess, ...] = ()
    write_ops: frozenset[str] = frozenset()  # cặp prepare_<op> / commit_intent
    write_audience: str | None = None
    write_scopes: tuple[str, ...] = ()
    editable_fields: dict[str, frozenset[str]] = field(default_factory=dict)
    citations_extractor: CitationExtractor | None = None

    @property
    def prepare_tools(self) -> frozenset[str]:
        return frozenset(f"prepare_{op}" for op in self.write_ops)

    def access(self) -> AgentAccess:
        if not self.write_ops or self.write_audience is None:
            return AgentAccess(read=self.read)
        return AgentAccess(
            read=self.read,
            prepare=ServerAccess(
                self.write_audience, self.prepare_tools, self.write_scopes, cache_token=False
            ),
            commit=ServerAccess(
                self.write_audience, frozenset({"commit_intent"}), self.write_scopes, False
            ),
        )

    def allowed_tool_names(self) -> frozenset[str]:
        names: set[str] = set(self.prepare_tools)
        for r in self.read:
            names |= r.tools
        return frozenset(names)


class AgentRegistry:
    def __init__(self, specs: Iterable[AgentSpec]) -> None:
        self._specs = list(specs)
        self._by_route = {s.route: s for s in self._specs}
        self._by_node = {s.node_name: s for s in self._specs}

    def all(self) -> list[AgentSpec]:
        return list(self._specs)

    def routes(self) -> list[str]:
        return [s.route for s in self._specs]

    def by_route(self, route: str) -> AgentSpec | None:
        return self._by_route.get(route)

    def by_node(self, node_name: str) -> AgentSpec:
        return self._by_node[node_name]

    def access_map(self) -> dict[str, AgentAccess]:
        return {s.node_name: s.access() for s in self._specs}
