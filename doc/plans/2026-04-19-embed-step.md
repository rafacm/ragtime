# Embed step (pipeline step 9) with Qdrant

**Date:** 2026-04-19

## Context

`Episode.Status.EMBEDDING` exists in the model, but the pipeline has had no handler and dead-ends at `RESOLVING`. This plan implements step 9 (Embed): take every `Chunk.text`, generate a multilingual vector, and persist it in a vector store with the metadata Scott will need to retrieve and cite chunks without a Postgres round-trip per result.

The earlier spec called for ChromaDB. We are switching to **Qdrant** instead — stronger payload indexing, production-ready filtering, and a hosted path (Qdrant Cloud) if ever needed. The ChromaDB placeholder env vars in `.env.sample` are removed.

## Design

### Key decisions

1. **Vector store: Qdrant**, deployed via `docker-compose.yml` alongside Postgres. Connected via `qdrant-client` over HTTP on port 6333.
2. **No pluggable vector-store abstraction.** A small `QdrantVectorStore` wrapper in `episodes/vector_store.py`. The existing `RAGTIME_VECTOR_STORE` placeholder is dropped. Abstraction can happen later if a second implementation is ever needed.
3. **Default embedding model:** OpenAI `text-embedding-3-small` (1536-dim, multilingual, cosine distance). Implemented as `OpenAIEmbeddingProvider` in `episodes/providers/openai.py`, subclassing the existing abstract `EmbeddingProvider` in `episodes/providers/base.py`.
4. **What is embedded:** only raw `chunk.text`. Entity names, episode metadata, and timestamps go into the Qdrant point payload, not into the vector.
5. **Point IDs** are `chunk.pk`. Deterministic IDs make upserts naturally idempotent.
6. **Idempotent re-runs:** before writing, the step calls `delete_by_episode(episode.pk)` so stale chunk IDs from a re-chunk cannot orphan.
7. **Dim detection + fail-fast check:** `detect_embedding_dim()` probes the configured embedding provider once per process (cached) and `ensure_collection()` uses the detected dim for both create and mismatch checks — no hard-coded model→dim map, and any future OpenAI-compatible model works without code changes. `manage.py configure` additionally warns when the user changes the embedding model.

### Payload schema (per point)

| Field | Type | Indexed | Purpose |
|-------|------|---------|---------|
| `chunk_id`, `chunk_index` | int | — | Chunk identity |
| `episode_id` | int | ⚡ | Filter by episode |
| `episode_title`, `episode_url`, `episode_published_at`, `episode_image_url` | str | — | Display without Postgres |
| `start_time`, `end_time` | float | — | Deep-link to audio |
| `language` | str | ⚡ | Bias / filter by language |
| `entity_ids` | list[int] | ⚡ | Filter by mention |
| `entity_names` | list[str] | — | Display without Postgres |
| `text` | str | — | Snippet for retrieval results |

`text` is intentionally duplicated from Postgres — Scott gets snippet + citation in a single query. Easy to drop later if storage becomes a concern.

### Episode deletion

Postgres cascades on `Episode` delete (Chunk, EntityMention, ProcessingRun, PipelineEvent, RecoveryAttempt all `on_delete=CASCADE`), but Qdrant is external. A `post_delete` signal calls `delete_by_episode(instance.pk)` so admin deletes stay consistent. Errors are logged and swallowed — a stale Qdrant point is preferable to a failing admin delete.

### Signal wiring

- `post_save` on Episode: new branch dispatches `episodes.embedder.embed_episode` when `status=EMBEDDING`.
- `post_delete` on Episode: new receiver clears Qdrant points for the deleted episode.

### `dbreset` management command

Postgres reset wipes row IDs; without clearing Qdrant, future `chunk.pk` values could collide with orphaned points. `dbreset` now drops the Qdrant collection after recreating the database.

## Files to create / modify

### New files

| File | Purpose |
|------|---------|
| `episodes/vector_store.py` | `QdrantVectorStore` (ensure_collection, upsert_points, delete_by_episode, from_settings) + `get_vector_store()` singleton. Constants: `EMBEDDING_DIM=1536`, `DISTANCE=COSINE`, `UPSERT_BATCH_SIZE=128`. |
| `episodes/embedder.py` | `embed_episode(episode_id)` decorated with `@trace_step("embed")`. Guards status, builds payloads (one EntityMention query joined by chunk), embeds, delete-then-upsert, EMBEDDING→READY. |
| `episodes/tests/test_embed.py` | Uses `QdrantClient(":memory:")`. Covers happy path, no chunks, idempotent re-run, re-embed after rechunk, wrong status, nonexistent episode, provider/qdrant failure, episode-delete cleanup, dim-mismatch. Also tests `OpenAIEmbeddingProvider` batching with 300 inputs. |
| `doc/plans/2026-04-19-embed-step.md` | This plan. |
| `doc/features/2026-04-19-embed-step.md` | Feature doc. |
| `doc/sessions/2026-04-19-embed-step-planning-session.md` | Planning transcript. |
| `doc/sessions/2026-04-19-embed-step-implementation-session.md` | Implementation transcript. |

### Modified files

- `pyproject.toml` — add `qdrant-client>=1.12,<2`.
- `docker-compose.yml` — add `qdrant` service (image `qdrant/qdrant:v1.17.1`, ports 6333/6334, `qdrant_data` volume, healthcheck via bash `/dev/tcp` probe since the image ships without `curl`).
- `.env.sample` — drop the ChromaDB placeholders (`RAGTIME_VECTOR_STORE`, `RAGTIME_CHROMA_*`), fill in the `RAGTIME_EMBEDDING_*` block, add `RAGTIME_QDRANT_*`.
- `ragtime/settings.py` — add `RAGTIME_EMBEDDING_{PROVIDER,API_KEY,MODEL}` and `RAGTIME_QDRANT_{HOST,PORT,COLLECTION,API_KEY,HTTPS}`.
- `core/management/commands/_configure_helpers.py` — add Embedding + Vector Store (Qdrant) systems to `SYSTEMS`.
- `core/management/commands/dbreset.py` — drop the Qdrant collection after Postgres recreate.
- `core/tests/test_configure.py` — extend the wizard test's mocked input sequences to cover the two new systems.
- `episodes/providers/openai.py` — add `OpenAIEmbeddingProvider` with `BATCH_SIZE=128`, `@trace_provider` on `embed()`.
- `episodes/providers/factory.py` — add `get_embedding_provider()`.
- `episodes/signals.py` — add `EMBEDDING` dispatch branch + `post_delete` Qdrant cleanup receiver.
- `README.md` — pipeline table row 9: ChromaDB → Qdrant. Drop the "not yet implemented" footnote. Remove the "Embed step" bullet from "What's coming". Tech Stack: ChromaDB → Qdrant. Installation note: Qdrant on 6333 after `docker compose up`.
- `doc/README.md` — expand section 9 📐 Embed with the full design. Add an `Embed` row to the telemetry table. Update How Scott Works: ChromaDB → Qdrant.
- `CHANGELOG.md` — `## 2026-04-19` gets `### Added` (Embed step) and `### Removed` (ChromaDB env vars).

### Reused utilities

- `episodes.processing.start_step` / `complete_step` / `fail_step` — step lifecycle + ProcessingStep rows + `step_completed` / `step_failed` signals.
- `episodes.telemetry.trace_step` / `trace_provider` / `record_llm_input` / `record_llm_output` — OTel spans + LLM IO recording.
- `EntityMention.objects.filter(episode=...).select_related("entity").values(...)` — single query to hydrate entity payloads for a whole episode.
- Existing status-guard + try/except + FAILED pattern in `extractor.extract_entities`.

## Diagram drift

`doc/architecture/ragtime-processing-pipeline.svg` shows ChromaDB in step 9. The Excalidraw source must be regenerated manually — flagged in the feature doc.

## Verification

```bash
docker compose up -d qdrant postgres
uv sync
uv run python manage.py migrate
uv run python manage.py configure          # set RAGTIME_EMBEDDING_* + RAGTIME_QDRANT_*
uv run python manage.py test episodes.tests.test_embed
uv run python manage.py test               # full regression
uv run python manage.py runserver          # submit an episode end-to-end
```

End-to-end check: submit an episode; watch it walk `scrape → … → resolve → embed → ready`; `curl http://localhost:6333/collections/ragtime_chunks` shows `points_count > 0`; a scroll query returns a point whose payload carries the expected keys.

## Risks / open questions

1. **Vector dim drift.** Swapping `RAGTIME_EMBEDDING_MODEL` to a different-dim model breaks upserts against an existing collection. Mitigated by runtime dim detection (`detect_embedding_dim()` via a one-token probe) plus a fail-fast check that names both dims and the current model, plus a `manage.py configure` warning that points at `manage.py dbreset` as the recovery path.
2. **Qdrant down mid-pipeline.** Step sets FAILED + `error_message`. The recovery layer currently only retries scrape/download; embed failures escalate to human. Acceptable — re-running is idempotent.
3. **Payload size.** Storing `text` roughly doubles per-point storage. Fine at podcast scale; easy to drop and hydrate from Postgres if it ever hurts.
4. **Entity staleness.** `entity_names` in Qdrant go stale if an Entity is renamed/merged after embed. Known limitation.
5. **Cost.** `text-embedding-3-small` ≈ $0.02 / 1M tokens; a 45-min episode ≈ $0.0002. Negligible.
6. **No retries in v1.** Let exceptions flow to FAILED. Revisit only if telemetry shows flakiness.
7. **Scott (step 10) is out of scope.** Payload was chosen with Scott in mind; no rework expected when that step lands.
