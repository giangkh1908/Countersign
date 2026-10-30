"""Lắp StateGraph từ registry agent (03 §3.4). Không liệt kê tên agent cứng.

START -> begin_turn -> router -> {<route>_agent | direct_answer}
<route>_agent -> <route>_tools -> <route>_agent (vòng ReAct) | final_answer
<route>_tools -> approval (khi có pending_action) -> execute_write | reprepare | final_answer
reprepare -> approval | final_answer ; execute_write -> final_answer -> END ; direct_answer -> END
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..agents import AgentRegistry
from . import nodes
from .state import AgentState, RunContext


def build_graph(checkpointer: Any, registry: AgentRegistry) -> Any:
    g = StateGraph(AgentState, context_schema=RunContext)
    g.add_node("begin_turn", nodes.begin_turn)
    g.add_node("router", nodes.make_router(registry))
    g.add_node("direct_answer", nodes.direct_answer)
    g.add_node("final_answer", nodes.final_answer)
    has_write = False
    for spec in registry.all():
        g.add_node(spec.node_name, nodes.make_agent_node(spec))
        g.add_node(f"{spec.route}_tools", nodes.make_tools_node(spec))
        g.add_conditional_edges(
            spec.node_name, nodes.agent_edge(spec), [f"{spec.route}_tools", "final_answer"]
        )
        if spec.write_ops:
            has_write = True
            g.add_conditional_edges(
                f"{spec.route}_tools", nodes.tools_edge(spec), [spec.node_name, "approval"]
            )
        else:
            g.add_edge(f"{spec.route}_tools", spec.node_name)
    g.add_edge(START, "begin_turn")
    g.add_edge("begin_turn", "router")
    g.add_conditional_edges(
        "router",
        nodes.route_edge(registry),
        [*(s.node_name for s in registry.all()), "direct_answer"],
    )
    g.add_edge("direct_answer", END)
    if has_write:
        g.add_node("approval", nodes.approval_node)
        g.add_node("execute_write", nodes.execute_write)
        g.add_node("reprepare", nodes.make_reprepare(registry))
        g.add_conditional_edges(
            "approval", nodes.approval_edge, ["execute_write", "reprepare", "final_answer"]
        )
        g.add_conditional_edges("reprepare", nodes.reprepare_edge, ["approval", "final_answer"])
        g.add_edge("execute_write", "final_answer")
    g.add_edge("final_answer", END)
    return g.compile(checkpointer=checkpointer)
