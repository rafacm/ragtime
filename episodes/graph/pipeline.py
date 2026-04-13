"""LangGraph ingestion pipeline definition.

Builds a StateGraph that orchestrates the podcast episode processing
steps: scrape → download → transcribe → summarize → chunk → extract
→ resolve → embed.  Conditional edges handle step skipping (when data
already exists) and recovery routing (agent-based recovery for
scraping/downloading failures).
"""

from langgraph.graph import END, StateGraph

from .edges import after_recovery, after_step, route_entry
from .nodes import (
    chunk_node,
    download_node,
    embed_node,
    extract_node,
    recovery_node,
    resolve_node,
    scrape_node,
    summarize_node,
    transcribe_node,
)
from .state import EpisodeState

# Ordered list of (node_name, node_function, next_node_name)
# next_node_name is used for the "continue" path after each step
_STEP_SEQUENCE = [
    ("scrape", scrape_node, "download"),
    ("download", download_node, "transcribe"),
    ("transcribe", transcribe_node, "summarize"),
    ("summarize", summarize_node, "chunk"),
    ("chunk", chunk_node, "extract"),
    ("extract", extract_node, "resolve"),
    ("resolve", resolve_node, "embed"),
    ("embed", embed_node, None),  # embed goes to END
]


def build_pipeline_graph():
    """Build and compile the ingestion pipeline graph."""
    graph = StateGraph(EpisodeState)

    # Entry router node — decides where to start
    graph.add_node("route", lambda state: state)  # pass-through, routing is in edges
    graph.set_entry_point("route")
    graph.add_conditional_edges("route", route_entry)

    # Add step nodes with conditional edges
    for name, node_fn, next_name in _STEP_SEQUENCE:
        graph.add_node(name, node_fn)

        if next_name is not None:
            graph.add_conditional_edges(
                name,
                after_step,
                {
                    "continue": next_name,
                    "recovery": "recovery",
                    END: END,
                },
            )
        else:
            # Last step (embed) → END
            graph.add_edge(name, END)

    # Recovery node
    graph.add_node("recovery", recovery_node)
    graph.add_conditional_edges(
        "recovery",
        after_recovery,
        {
            "route": "route",
            END: END,
        },
    )

    return graph.compile()


# Pre-compiled graph instance
pipeline = build_pipeline_graph()
