# Session: Langfuse Observability — Planning

**Date:** 2026-03-16
**Session ID:** 0f60528e-6b16-41a5-b9d0-13c277121673

## Summary

Planned the addition of optional Langfuse LLM observability integration, covering provider-level OpenAI client swap and step-level tracing decorators across the processing pipeline.

## Conversation

### User

Currently we do not have any visibility about all the requests and responses sent to external LLMs. We would like to have that visibility and eventually we would also want to have a way to evaluate the responses we get from the RAG implementation. Which open-source soltions can you suggest to provide us with that visibility?

### Assistant

Let me first understand how LLM calls are currently made in the codebase, then I can give informed recommendations.

Good. Now I have a clear picture of the codebase. Here are my recommendations for open-source LLM observability tools, considering RAGtime's architecture:

---

## Open-Source LLM Observability Solutions

### Top Recommendations

**1. [Langfuse](https://github.com/langfuse/langfuse)** — Best overall fit
- Traces LLM calls with input/output, latency, token usage, cost
- Built-in RAG evaluation (relevance, faithfulness, answer quality)
- Python SDK with decorator-based tracing (`@observe()`)
- Self-hostable (Docker) or cloud
- Supports OpenAI SDK integration via a drop-in wrapper
- Has dataset/experiment management for systematic evaluation
- Active community, well-maintained

**2. [Lunary](https://github.com/lunary-ai/lunary)** — Lightweight alternative
- Simple OpenAI SDK callback integration
- Tracks prompts, completions, costs, and user feedback
- Has evaluation/testing features
- Self-hostable
- Less complex to set up than Langfuse

**3. [Phoenix (Arize)](https://github.com/Arize-ai/phoenix)** — Best for RAG evaluation specifically
- Purpose-built for RAG debugging (retrieval quality, chunk relevance)
- Traces spans across embedding → retrieval → generation
- Built-in evals (hallucination detection, QA correctness)
- Runs as a local server, no external dependencies
- OpenTelemetry-based tracing

**4. [LangSmith alternatives — Opik (Comet)](https://github.com/comet-ml/opik)** — Newer option
- Full tracing, evaluation, and dataset management
- Self-hostable
- OpenAI integration via callbacks

### My Recommendation

**Langfuse** is the strongest fit for RAGtime because:

1. **Minimal integration effort** — It has an OpenAI SDK wrapper that can be swapped into your existing `OpenAILLMProvider` with ~5 lines of code. No need to change the provider abstraction.
2. **Pipeline tracing** — You can trace the full episode pipeline (scrape → summarize → extract → resolve) as a single trace with nested spans, giving visibility into each step.
3. **RAG evaluation** — When you implement the chat/Scott feature, Langfuse has built-in evaluation for retrieval relevance and answer faithfulness.
4. **Cost tracking** — Automatically calculates cost per call and per pipeline run.
5. **Self-hostable** — Docker Compose setup, uses PostgreSQL + ClickHouse. Fits the project's preference for self-contained infrastructure.
6. **Django-friendly** — Pure Python SDK, no framework conflicts.

### Integration Sketch

The integration would look roughly like:
- Wrap the OpenAI client in `episodes/providers/openai.py` with Langfuse's `observe()` decorator or OpenAI wrapper
- Add trace context to each pipeline step in `episodes/signals.py`
- Add `RAGTIME_LANGFUSE_*` env vars for configuration
- Optional: add evaluation hooks for the chat app later

---

Want me to plan a concrete integration of one of these tools? Or would you like me to research any of them in more detail?

### User

How can we tie a RAGtime process run with the information in Langfuse?

### Assistant

Let me look at how pipeline runs are dispatched to understand the correlation points.

Great question. RAGtime already has the right building blocks — here's how the concepts map:

## RAGtime → Langfuse Concept Mapping

| RAGtime | Langfuse | Why |
|---|---|---|
| `ProcessingRun` (pk) | **Session** (`session_id`) | Groups all traces for one episode's full pipeline execution |
| Pipeline step (scrape, summarize, extract…) | **Trace** | One trace per step — each runs as a separate `async_task()` |
| Individual LLM call | **Generation** (span) | e.g., extractor makes N generation calls (one per chunk) |
| `Episode` (pk/title) | **User** or **metadata** | Ties everything back to the episode being processed |

## The Threading Challenge

The main challenge is that each pipeline step runs as an **independent Django Q2 task** — there's no shared in-memory context between steps. Looking at `signals.py`:

```python
async_task("episodes.extractor.extract_entities", instance.pk)
```

Only the `episode.pk` is passed. To correlate with Langfuse, each step function needs to also know the **`ProcessingRun` ID** so it can set the same `session_id` across all traces.

This is already retrievable via `get_active_run(episode)` in `processing.py:32`, so each step can look it up without changing the signal dispatch.

## Concrete Integration Points

**1. At the provider level** (`providers/openai.py`) — instrument the OpenAI client:

Langfuse provides a drop-in wrapper for the OpenAI SDK. Instead of `OpenAI(api_key=...)`, you'd use `langfuse.openai.OpenAI(api_key=...)`. This automatically captures every LLM call (input, output, tokens, latency, cost) with zero changes to `structured_extract()` or `generate()`.

**2. At the step level** (scraper, summarizer, extractor, resolver) — create the trace:

Each step function already calls `start_step()` / `complete_step()`. That's where you'd create a Langfuse trace with:
- `session_id` = `ProcessingRun.pk` (ties all steps together)
- `name` = step name (e.g. "extracting")
- `metadata` = `{"episode_id": episode.pk, "episode_title": episode.title}`

**3. For multi-call steps** (extractor iterates over chunks, resolver over entity types):

Each individual LLM call within a step becomes a **generation span** nested under that step's trace. The Langfuse OpenAI wrapper handles this automatically when you pass the trace context.

## What You'd See in Langfuse

```
Session: ProcessingRun #42 (episode: "Miles Davis at the Blackhawk")
├── Trace: scraping        [1.2s, $0.003]
│   └── Generation: structured_extract (gpt-4.1-mini)
├── Trace: summarizing     [3.4s, $0.008]
│   └── Generation: generate (gpt-4.1-mini)
├── Trace: extracting      [12.1s, $0.045]
│   ├── Generation: chunk 0 structured_extract
│   ├── Generation: chunk 1 structured_extract
│   └── Generation: chunk 2 structured_extract
└── Trace: resolving       [8.7s, $0.032]
    ├── Generation: wikidata match (artist)
    ├── Generation: entity resolution (artist)
    └── Generation: entity resolution (album)
```

Each generation shows full prompt, response, token counts, latency, and cost — all grouped by the processing run.

Want me to create a plan for implementing this integration?

### User

Is there a way to make this optional? That is, RAGtime would work without Langfuse but there is the option to configure Langfuse for visibility.

### Assistant

Yes — there are two complementary approaches:

## Option A: Langfuse OpenAI wrapper with conditional swap

In `providers/openai.py`, conditionally choose which `OpenAI` class to instantiate:

```python
if settings.RAGTIME_LANGFUSE_ENABLED:
    from langfuse.openai import OpenAI  # drop-in, auto-instruments
else:
    from openai import OpenAI           # standard, no tracing
```

The Langfuse `OpenAI` class has the **exact same interface** — all existing code (`client.responses.create()`, `client.audio.transcriptions.create()`) works unchanged. When Langfuse is disabled, there's zero overhead and no Langfuse import.

## Option B: Langfuse `@observe()` decorator for step-level tracing

For the trace/session structure (tying steps to a `ProcessingRun`), you'd use Langfuse's `@observe()` decorator on step functions. This can also be made conditional — a no-op decorator when disabled:

```python
if settings.RAGTIME_LANGFUSE_ENABLED:
    from langfuse.decorators import observe
else:
    def observe(**kwargs):          # no-op passthrough
        def decorator(fn):
            return fn
        return decorator
```

## Configuration

Three new env vars, all optional:

```
RAGTIME_LANGFUSE_ENABLED=true          # default: false
RAGTIME_LANGFUSE_SECRET_KEY=sk-lf-...
RAGTIME_LANGFUSE_PUBLIC_KEY=pk-lf-...
RAGTIME_LANGFUSE_HOST=http://localhost:3000  # for self-hosted
```

When `RAGTIME_LANGFUSE_ENABLED` is not set or `false`, the `langfuse` package isn't even imported. You could also make it a soft dependency — not in the main dependencies but in an optional group in `pyproject.toml`:

```toml
[project.optional-dependencies]
observability = ["langfuse>=2,<3"]
```

So `uv sync` installs RAGtime without Langfuse, and `uv sync --extra observability` adds it.

Both options A and B work together — A gives you automatic generation-level tracing, B gives you the session/trace structure. The conditional logic lives in just two places (provider init + step decorators), so the rest of the codebase is completely unaware of Langfuse.

Want me to plan the full implementation?

### User

For the time being, let's go for Langfuse and implement both Options A and B so we have full observability. Let's add also a section before "Changelog" in the README called "LLM Observability" were we add information about how to setup Langfuse. Ideally with Docker or Docker Compose. We need to update the configuration wizard to handle that and default to not use Langfuse.

### Assistant

Let me explore the configure wizard and README structure, then design the implementation plan.

Now I have a complete picture. Let me design the implementation plan.

Let me verify a few details before finalizing the plan.

Now let me also check the Langfuse SDK's compatibility with the OpenAI `responses.create()` API and Docker Compose setup.

Now I have all the information needed. Let me write the final plan.

The plan is ready. Key points:

- **Optional dependency** via `[project.optional-dependencies]` — `uv sync --extra observability` to install Langfuse
- **Two instrumentation layers**: automatic OpenAI client wrapping (Layer A) + step-level trace grouping by `ProcessingRun` (Layer B)
- **Zero overhead when disabled** — no Langfuse imports, no decorators, no runtime cost
- **One new module** (`episodes/observability.py`) centralizes all Langfuse logic
- **Configure wizard** picks up the new system automatically
- **One known limitation**: Langfuse's `responses.create()` input capture can be inconsistent (Langfuse SDK issue, trace metrics work fine)

The latest Langfuse Python SDK is **v4.0.0** (released March 10, 2026). The search results are inconclusive on whether the `responses.create` input capture issue was fully fixed in v3/v4 — the reports I found reference v3.2.4 where it was still inconsistent.

You're right to challenge that — you likely have more current knowledge. Let me update the plan to use `langfuse>=4,<5` and remove the known limitation note.

Good — `langfuse>=4,<5` is already what the plan has. The plan is updated and ready for review.

Good — the Langfuse v4 API is quite different from what I had in the plan. Key changes:

- Import: `from langfuse import observe, propagate_attributes` (not `langfuse.decorators`)
- Session ID: `propagate_attributes(session_id=..., metadata=...)` context manager (not `langfuse_context.update_current_trace()`)
- OpenAI wrapper: `from langfuse.openai import OpenAI`

Let me update the plan with the correct v4 API.

Now let me update the step files section to clarify how `observe_step` works with the v4 API pattern:

Plan updated to use the Langfuse v4 API (`from langfuse import observe, propagate_attributes`) instead of the deprecated v2 `langfuse.decorators` / `langfuse_context` pattern.

Worktree created. Now exiting plan mode so we can start implementation.

### User

[Request interrupted by user for tool use]
