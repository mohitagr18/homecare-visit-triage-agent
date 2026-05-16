"""LangGraph graph wiring.

This is the ONLY file that knows the graph topology.
All other modules are agnostic of the graph.

One-way dependency:
    graph.py imports nodes.py
    nodes.py imports state.py + data layer
    state.py imports nothing from src/

Usage:
    from src.graph import graph            # module-level compiled graph
    from src.graph import build_graph     # factory for testing (fresh instance)
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.nodes import (
    evaluate_node,
    human_review_node,
    ingest_node,
    normalize_node,
    report_node,
    triage_decision,
)
from src.state import BenchmarkState


def build_graph(checkpointer=None) -> StateGraph:
    """Build and compile the benchmark LangGraph.

    Args:
        checkpointer: LangGraph checkpointer for state persistence.
                      Defaults to MemorySaver (in-memory, for testing).
                      Pass a SqliteSaver for persistent HITL workflows.

    Returns:
        Compiled LangGraph ready for invocation.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(BenchmarkState)

    # Add nodes
    builder.add_node("ingest", ingest_node)
    builder.add_node("normalize", normalize_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("report", report_node)

    # Linear edges
    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "normalize")
    builder.add_edge("normalize", "evaluate")

    # Conditional edge after evaluate
    builder.add_conditional_edges(
        "evaluate",
        triage_decision,
        {
            "human_review": "human_review",
            "report": "report",
        },
    )

    # After HITL review, always go to report
    builder.add_edge("human_review", "report")
    builder.add_edge("report", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],   # pause BEFORE human_review executes
    )


# Module-level compiled graph (used by langgraph.json and run_benchmark.py)
graph = build_graph()
