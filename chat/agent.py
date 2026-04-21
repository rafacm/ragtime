"""Scott — the strict-RAG jazz podcast chatbot.

Scott is a Pydantic AI agent that answers questions only from ingested
podcast transcripts. It calls :func:`search_chunks` as a tool to retrieve
relevant chunks from Qdrant, cites them with ``[N]`` markers, and refuses
to answer from general knowledge when nothing relevant is found.

The agent is exposed as an ASGI app via ``scott_agent.to_ag_ui(...)`` and
mounted into Django's ASGI stack in :mod:`ragtime.asgi`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from functools import lru_cache
from textwrap import dedent

from django.conf import settings
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.ag_ui import StateDeps

from episodes.vector_store import search_chunks as _search_chunks_helper

logger = logging.getLogger(__name__)


SCOTT_SYSTEM_PROMPT = dedent(
    """
    You are Scott, a jazz podcast expert. You answer strictly from the transcripts
    provided by the `search_chunks` tool.

    **Rules you must follow:**

    1. Before answering any factual question about podcasts, artists, bands,
       albums, venues, sessions, labels, or dates, you MUST call
       `search_chunks` at least once with a well-formed query.
    2. You may call `search_chunks` multiple times with refined or widened
       queries to gather enough context.
    3. Answer ONLY from the chunks returned by the tool. Never answer from
       general knowledge. If no relevant chunks are returned after reasonable
       search, say so plainly and stop.
    4. When you state a fact that comes from a chunk, cite it with a `[N]`
       marker where `N` matches the index shown in the tool results (these
       are 1-indexed and stable across tool calls within the same turn).
    5. Always reply in the language of the user's question, even when the
       retrieved chunks are in a different language. Translate or paraphrase
       the chunk content as needed — never switch to the chunk's language.
    6. Be concise. Prefer two tight paragraphs with citations over a long
       essay. You are not a music critic — you report what the podcasts say.
    """
).strip()


class ScottState(BaseModel):
    """Shared agent state surfaced to the frontend via AG-UI snapshots."""

    retrieved_chunks: list[dict] = Field(default_factory=list)
    conversation_id: int | None = None


def build_model():
    """Build a Pydantic AI model with the API key wired from settings.

    Mirrors the pattern used by ``episodes.agents.agent.build_model`` so
    credentials come from Django settings rather than ambient env vars.
    Built lazily so Django can boot even without Scott credentials present.
    """
    provider_name = settings.RAGTIME_SCOTT_PROVIDER
    model_name = settings.RAGTIME_SCOTT_MODEL
    api_key = settings.RAGTIME_SCOTT_API_KEY

    if provider_name == "openai":
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key=api_key) if api_key else OpenAIProvider()
        return OpenAIResponsesModel(model_name, provider=provider)

    spec = model_name if ":" in model_name else f"{provider_name}:{model_name}"
    return spec


@lru_cache(maxsize=1)
def get_scott_agent() -> Agent[StateDeps[ScottState]]:
    """Construct Scott lazily so tests and management commands don't need
    the OpenAI API key at import time."""

    # Use `instructions=` (the canonical modern way) rather than
    # `system_prompt=` — the latter is mapped differently by
    # OpenAIResponsesModel and was not reaching the LLM, causing Scott
    # to answer from general knowledge instead of calling search_chunks.
    agent: Agent[StateDeps[ScottState]] = Agent(
        model=build_model(),
        deps_type=StateDeps[ScottState],
        instructions=SCOTT_SYSTEM_PROMPT,
    )

    @agent.tool
    def search_chunks(
        ctx: RunContext[StateDeps[ScottState]],
        query: str,
        episode_id: int | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        """Search ingested podcast transcripts for chunks relevant to ``query``.

        Call this before answering any factual question. You may call it
        multiple times with refined queries within a single turn. Results
        accumulate in agent state; the ``[N]`` index assigned to each chunk
        is stable for the duration of the turn.

        Args:
            query: Search query in any language.
            episode_id: Optional episode filter to restrict the search.
            top_k: Override the default number of results for this call.

        Returns:
            A list of chunks with their assigned ``[N]`` citation index,
            episode title, start/end timestamps, language, and text.
        """
        limit = top_k or settings.RAGTIME_SCOTT_TOP_K
        logger.info(
            "scott.search_chunks called query=%r episode_id=%r top_k=%d",
            query,
            episode_id,
            limit,
        )
        results = _search_chunks_helper(
            query=query,
            top_k=limit,
            episode_id=episode_id,
            score_threshold=settings.RAGTIME_SCOTT_SCORE_THRESHOLD,
        )
        logger.info("scott.search_chunks returned %d chunks", len(results))

        state = ctx.deps.state
        existing_ids = {c["chunk_id"] for c in state.retrieved_chunks}
        for result in results:
            if result.chunk_id in existing_ids:
                continue
            state.retrieved_chunks.append(asdict(result))
            existing_ids.add(result.chunk_id)

        return [
            {
                "citation": f"[{idx}]",
                "episode_title": chunk["episode_title"],
                "start_time": round(chunk["start_time"], 1),
                "end_time": round(chunk["end_time"], 1),
                "language": chunk["language"],
                "score": round(chunk["score"], 3),
                "text": chunk["text"],
            }
            for idx, chunk in enumerate(state.retrieved_chunks, start=1)
        ]

    @agent.instructions
    def _inject_registry(ctx: RunContext[StateDeps[ScottState]]) -> str:
        chunks = ctx.deps.state.retrieved_chunks
        if not chunks:
            return ""
        lines = ["Retrieved chunks available for citation:"]
        for idx, chunk in enumerate(chunks, start=1):
            preview = chunk["text"][:200].replace("\n", " ")
            lines.append(
                f"[{idx}] {chunk['episode_title']} "
                f"({chunk['start_time']:.0f}s–{chunk['end_time']:.0f}s): {preview}"
            )
        return "\n".join(lines)

    return agent


async def scott_endpoint(request):
    """Per-request AG-UI endpoint for Scott.

    Constructs a **fresh** :class:`StateDeps[ScottState]` on every call.
    Without this, ``Agent.to_ag_ui()`` would share a single ``deps`` across
    all requests — Pydantic AI's own docstring says so explicitly, and
    ``search_chunks`` mutates ``deps.state.retrieved_chunks``, so
    reusing the singleton would let one user's citation registry bleed
    into another user's turn.
    """
    from pydantic_ai.ag_ui import AGUIAdapter

    return await AGUIAdapter.dispatch_request(
        request,
        agent=get_scott_agent(),
        deps=StateDeps(ScottState()),
    )


@lru_cache(maxsize=1)
def get_agui_app():
    """Return a Starlette ASGI app that dispatches each request to
    :func:`scott_endpoint` with a fresh ``StateDeps`` instance."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    return Starlette(
        routes=[Route("/", scott_endpoint, methods=["POST"])],
    )
