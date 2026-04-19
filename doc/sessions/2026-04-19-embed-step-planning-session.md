# Session: Embed step (pipeline step 9) with Qdrant — Planning

**Date:** 2026-04-19

**Session ID:** 0d4117c9-6289-43c1-b25b-8cc326144031

## Summary

Planned the implementation of the 9th pipeline step (Embed), including a switch from the spec's original ChromaDB to Qdrant. Scope covered the Qdrant client wrapper, an OpenAI embedding provider, the step handler, signal wiring for both dispatch and Episode-delete cleanup, configuration surface (`.env.sample`, settings, configure wizard), `dbreset` integration, docker-compose, tests, and the full documentation set.

## Conversation

### User

Help me brainstorm the implementation of the Embed step. Currently we have "Embed step (pipeline step 9): generate multilingual embeddings for transcript chunks and store them in ChromaDB." but I want to question the usage of ChromaDB and use Qdrant instead. In this step we need to 1) generate the embedding and 2) store it in the datbase for later retrieval with the corresponding metadata.

### Assistant

Spawned three `Explore` agents in parallel to map the codebase:

1. The existing pipeline-step architecture (`episodes/models.py::PIPELINE_STEPS`, signal dispatch in `episodes/signals.py`, step module shape in `chunker.py`/`extractor.py`/`resolver.py`, provider factory pattern).
2. How the Scott chatbot expects retrieval metadata to be structured — confirmed no chat app, no retrieval code, no ChromaDB/Qdrant references anywhere yet.
3. The `Chunk` model fields (text, start/end times, segment boundaries, `entities_json`), resolve step output (`EntityMention` links Entity→Episode→Chunk with context and `start_time`), and the current `.env.sample` (already has stub `RAGTIME_VECTOR_STORE`, `RAGTIME_CHROMA_*` placeholders).

Key findings consolidated:

- `Episode.Status.EMBEDDING` exists but has no handler — pipeline dead-ends at RESOLVING.
- `EmbeddingProvider` abstract class exists in `episodes/providers/base.py` with `embed(texts) -> list[list[float]]`; no concrete implementation or factory.
- No `chromadb` / `qdrant` dependency in `pyproject.toml`.
- Steps follow: module at `episodes/<step>.py`, dispatch via signal, `start_step`/`complete_step`/`fail_step` helpers, `@trace_step` telemetry, `@trace_provider` on provider methods.

### Assistant (clarifying questions)

Raised four design questions via AskUserQuestion before writing any plan:

1. **Qdrant deployment mode?** — Docker via compose / embedded / Qdrant Cloud.
2. **Pluggable vector-store abstraction?** — direct Qdrant vs `VectorStoreProvider` factory pattern.
3. **Embedding provider/model default?** — OpenAI `text-embedding-3-small` vs `-3-large` vs Cohere multilingual v3 vs local BGE-M3.
4. **What to embed?** — raw `chunk.text` vs text + entity names vs text + episode context.

### User

Selected the recommended option for each:

- Qdrant via Docker compose.
- Direct Qdrant, no abstraction.
- OpenAI `text-embedding-3-small`.
- Raw `chunk.text` only.

### Assistant

Spawned a `Plan` agent with the full context and constraints. The agent produced a detailed design covering docker-compose entry, dependencies, env vars, the Qdrant wrapper class shape, the OpenAI embedding provider, the Qdrant payload schema, the `embed_episode()` control flow, signal wiring, collection bootstrap strategy (auto-create inside `ensure_collection`, not `AppConfig.ready()`), testing strategy with `QdrantClient(":memory:")`, documentation impact per `CLAUDE.md`, and a risks section.

Verified the agent's assumptions against the real code:

- Factory import shape in `episodes/providers/factory.py`.
- `@trace_provider`, `record_llm_input`, `record_llm_output` usage in `episodes/providers/openai.py`.
- Signal file shape in `episodes/signals.py`.
- `EmbeddingProvider` abstract base in `episodes/providers/base.py`.

Wrote the plan file and called `ExitPlanMode`.

### User

Rejected the first ExitPlanMode call with: "If we delete an episode in the Django UI, do we currently delete all the data in the PostgreSQL tables? We should do the same for the points stored in Qdrant."

### Assistant

Verified: `Chunk.episode`, `EntityMention.episode`, `ProcessingRun.episode`, `PipelineEvent.episode`, `RecoveryAttempt.episode` all cascade on delete in Postgres. Qdrant, being external, would orphan points.

Extended the plan with:

1. A new `Episode deletion → Qdrant cleanup` design section: wire a `post_delete` signal on Episode that calls `get_vector_store().delete_by_episode(episode_id)` inside try/except (log and swallow — never block an admin delete on a transient Qdrant issue).
2. Updated the `episodes/signals.py` change description to include the new `post_delete` receiver and the `post_delete` import.
3. Added two new test cases to `test_embed.py`: "episode delete removes Qdrant points" and "episode delete survives Qdrant failure".

Called `ExitPlanMode` again.

### User

Approved the plan.

### Final design decisions captured in the plan

- **Point ID = `chunk.pk`** (int64) for naturally idempotent upserts.
- **Delete-before-upsert** on every step run so re-chunked episodes don't orphan stale point IDs.
- **Fail-fast dim check** in `ensure_collection()` — guards against accidental `RAGTIME_EMBEDDING_MODEL` swaps.
- **Payload schema**: chunk IDs, episode metadata (title, URL, published_at, image), timestamps, language, resolved entity IDs + names, and raw `text` (duplicated for single-hop retrieval).
- **Indexed payload fields**: `episode_id`, `language`, `entity_ids`.
- **Batch sizes**: OpenAI `BATCH_SIZE=128`, Qdrant `UPSERT_BATCH_SIZE=128`.
- **`dbreset`** also drops the Qdrant collection so fresh databases don't collide with future `chunk.pk` values that could match orphaned points.
- **No retries in v1.** Let exceptions flow to FAILED; add retry logic only if telemetry shows flakiness.
- **No new vector-store abstraction.** Direct Qdrant, drop the placeholder `RAGTIME_VECTOR_STORE` env var.

The plan explicitly flags that `doc/architecture/ragtime-processing-pipeline.svg` will drift (it still shows ChromaDB) and needs a manual Excalidraw regen — diagrams cannot be auto-updated.
