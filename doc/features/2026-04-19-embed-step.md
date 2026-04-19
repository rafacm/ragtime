# Embed step (pipeline step 9) with Qdrant

**Date:** 2026-04-19

## Problem

The 9th pipeline step (`Episode.Status.EMBEDDING`) existed in the status enum but had no handler — the pipeline dead-ended after `RESOLVING`. The earlier spec called for ChromaDB; this implementation switches to **Qdrant** (stronger payload filtering, production-ready, Qdrant Cloud path if needed) and wires the step end-to-end.

## Changes

1. **Qdrant client wrapper** — new `episodes/vector_store.py`:
   - `QdrantVectorStore` with `ensure_collection()`, `upsert_points()`, `delete_by_episode()`, `from_settings()`.
   - `ensure_collection()` creates the collection (1536-dim, cosine) and indexes `episode_id`, `language`, `entity_ids` for fast payload filtering. If a collection already exists with a different vector dim, it raises with a clear error rather than silently failing on write.
   - Module-level `get_vector_store()` is `@lru_cache(maxsize=1)` — one shared HTTP connection pool per process.
2. **OpenAI embedding provider** — `OpenAIEmbeddingProvider` in `episodes/providers/openai.py` subclasses the pre-existing abstract `EmbeddingProvider`. Batches inputs at `BATCH_SIZE=128`, traced via `@trace_provider`, records input count and vector count as span events.
3. **Provider factory** — `get_embedding_provider()` follows the same shape as the other six provider factories; reads `RAGTIME_EMBEDDING_{PROVIDER,API_KEY,MODEL}`.
4. **Embed step handler** — `embed_episode(episode_id)` in `episodes/embedder.py`:
   - Guards `status == EMBEDDING`; warns and returns otherwise.
   - One `EntityMention` query per episode (grouped by chunk) hydrates entity payloads without N+1.
   - Wipes existing points for the episode (`delete_by_episode`) before upsert — safe for re-runs after a re-chunk.
   - Transitions EMBEDDING → READY on success. On exception: sets status FAILED, records `error_message`, calls `fail_step(..., exc=exc)` so the recovery layer can observe the failure.
   - Zero-chunks episodes transition straight to READY without any Qdrant calls.
5. **Signal wiring** in `episodes/signals.py`:
   - `post_save` branch for `EMBEDDING` dispatches `embed_episode` to Django Q2.
   - New `post_delete` receiver calls `delete_by_episode(instance.pk)` to keep Qdrant consistent with Postgres when an episode is admin-deleted. Errors are logged and swallowed so a transient Qdrant issue can never block a delete.
6. **Settings + env vars** — `RAGTIME_EMBEDDING_{PROVIDER,API_KEY,MODEL}` and `RAGTIME_QDRANT_{HOST,PORT,COLLECTION,API_KEY,HTTPS}` added to `ragtime/settings.py` and `.env.sample`. The old ChromaDB placeholders (`RAGTIME_VECTOR_STORE`, `RAGTIME_CHROMA_HOST`, `RAGTIME_CHROMA_PORT`, `RAGTIME_CHROMA_COLLECTION`) are removed.
7. **Configure wizard** — new Embedding and Vector Store (Qdrant) systems in `_configure_helpers.py::SYSTEMS`. Embedding's API key reuses the shared LLM key flow that already exists in `_prompt_system`.
8. **Docker Compose** — new `qdrant` service (image `qdrant/qdrant:v1.17.1`, ports 6333/6334, `qdrant_data` volume). Healthcheck uses a bash `/dev/tcp` probe on `/readyz`; the Qdrant image ships without `curl` or `wget`.
9. **`manage.py dbreset`** — after recreating the Postgres database, the command also drops the Qdrant collection. Without this, a reset would leave orphaned Qdrant points under chunk IDs that future rows would then collide with.

## Payload schema

| Field | Type | Indexed | Purpose |
|-------|------|---------|---------|
| `chunk_id`, `chunk_index` | int | — | Chunk identity |
| `episode_id` | int | ⚡ | Filter by episode |
| `episode_title`, `episode_url`, `episode_published_at`, `episode_image_url` | str | — | Render citations without a Postgres round-trip |
| `start_time`, `end_time` | float | — | Deep-link to audio position |
| `language` | str | ⚡ | Bias / filter by language |
| `entity_ids` | list[int] | ⚡ | Filter by mentioned entity |
| `entity_names` | list[str] | — | Display without DB hydration |
| `text` | str | — | Snippet for retrieval results |

`text` is intentionally duplicated from Postgres — Scott gets its snippet + citation in a single Qdrant query. Easy to drop and hydrate from Postgres later if storage costs ever warrant it.

## Key parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `EMBEDDING_DIM` | 1536 | Fixed by `text-embedding-3-small` |
| `DISTANCE` | `COSINE` | Standard for semantic similarity over OpenAI embeddings |
| `OpenAIEmbeddingProvider.BATCH_SIZE` | 128 | OpenAI accepts ≥ 2048 per call, but 128 keeps request payloads manageable and gives one progress tick per batch on long episodes |
| `UPSERT_BATCH_SIZE` | 128 | Matches embedding batch size; keeps a single long-running `upsert` from stalling the step |
| Default model | `text-embedding-3-small` | Multilingual, $0.02 / 1M tokens, widely benchmarked |

## Diagram drift

`doc/architecture/ragtime-processing-pipeline.svg` shows ChromaDB in step 9. The Excalidraw source must be regenerated manually — diagrams cannot be auto-updated after the change.

## Verification

```bash
docker compose up -d qdrant db
uv sync
uv run python manage.py migrate
uv run python manage.py configure          # populate RAGTIME_EMBEDDING_* + RAGTIME_QDRANT_*
uv run python manage.py test episodes.tests.test_embed --verbosity 2
uv run python manage.py test               # full regression — all 276 tests pass
uv run python manage.py runserver
uv run python manage.py qcluster            # separate terminal
```

End-to-end:

1. Submit an episode through the admin.
2. Watch the pipeline walk `scrape → … → resolve → embed → ready`.
3. Verify Qdrant: `curl http://localhost:6333/collections/ragtime_chunks` → `points_count` matches the chunk count.
4. Scroll a sample point:
   ```bash
   curl -s -X POST http://localhost:6333/collections/ragtime_chunks/points/scroll \
     -H 'Content-Type: application/json' \
     -d '{"limit":1,"with_payload":true,"with_vector":false}'
   ```
   → payload includes `chunk_id`, `episode_id`, `start_time`, `entity_ids`, `text`.
5. Delete the episode in the Django admin → `points_count` drops back to 0 for that episode.

## Files modified

| File | Change |
|---|---|
| `episodes/vector_store.py` | **New** — Qdrant client wrapper. |
| `episodes/embedder.py` | **New** — pipeline step 9 handler. |
| `episodes/tests/test_embed.py` | **New** — 15 tests covering step, delete signal, collection bootstrap, and OpenAI batching. |
| `episodes/providers/openai.py` | Added `OpenAIEmbeddingProvider`. |
| `episodes/providers/factory.py` | Added `get_embedding_provider()` and imported `EmbeddingProvider`. |
| `episodes/signals.py` | Added EMBEDDING dispatch branch and `post_delete` Qdrant cleanup. |
| `ragtime/settings.py` | Added `RAGTIME_EMBEDDING_*` and `RAGTIME_QDRANT_*` settings. |
| `core/management/commands/_configure_helpers.py` | Added Embedding and Vector Store (Qdrant) systems. |
| `core/management/commands/dbreset.py` | Drops the Qdrant collection after Postgres recreate. |
| `core/tests/test_configure.py` | Extended the wizard test input sequence to cover the two new systems. |
| `docker-compose.yml` | New `qdrant` service and `qdrant_data` volume. |
| `pyproject.toml` | Added `qdrant-client>=1.12,<2`. |
| `.env.sample` | Removed ChromaDB placeholders; added `RAGTIME_QDRANT_*`; completed `RAGTIME_EMBEDDING_*`. |
| `README.md` | Pipeline table row 9 (Qdrant), Tech Stack (Qdrant), Installation note. |
| `doc/README.md` | Expanded section 9 📐 Embed; updated How Scott Works; added Embed row to telemetry table. |
| `CHANGELOG.md` | Added Embed step under `### Added` and ChromaDB env vars under `### Removed`. |
| `doc/plans/2026-04-19-embed-step.md` | **New** — plan. |
| `doc/features/2026-04-19-embed-step.md` | **New** — this file. |
| `doc/sessions/2026-04-19-embed-step-planning-session.md` | **New** — planning transcript. |
| `doc/sessions/2026-04-19-embed-step-implementation-session.md` | **New** — implementation transcript. |
