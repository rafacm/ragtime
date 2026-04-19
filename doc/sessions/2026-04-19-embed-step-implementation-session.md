# Session: Embed step (pipeline step 9) with Qdrant — Implementation

**Date:** 2026-04-19

**Session ID:** 0d4117c9-6289-43c1-b25b-8cc326144031

## Summary

Implemented the 9th pipeline step (Embed) end-to-end in the `feature/embed-step-qdrant` worktree. Added a Qdrant client wrapper, an OpenAI embedding provider, the step handler, signal wiring (dispatch + Episode-delete cleanup), settings, configure wizard integration, `dbreset` integration, Docker Compose service, tests (15 new tests), and the full documentation set. All 276 tests pass.

## Conversation

### User

(Approved the plan at the end of the planning session.)

### Assistant

Verified `main` was clean, pulled latest, created a git worktree on branch `feature/embed-step-qdrant`.

Then implemented the plan in this order:

**1. Dependency.** Added `qdrant-client>=1.12,<2` to `pyproject.toml`. Ran `uv lock && uv sync` — installed `qdrant-client==1.17.1` plus its grpcio/numpy/portalocker transitive deps.

**2. docker-compose.yml.** Added the `qdrant` service at image `qdrant/qdrant:v1.17.1`, exposed ports `127.0.0.1:6333:6333` (HTTP) and `:6334:6334` (gRPC), persistent `qdrant_data` volume, and a bash `/dev/tcp` healthcheck against `/readyz` (the Qdrant image ships without `curl`). Added `qdrant_data` to the top-level `volumes:` block.

**3. `.env.sample` + `ragtime/settings.py`.** Removed the stub `RAGTIME_VECTOR_STORE`, `RAGTIME_CHROMA_HOST`, `RAGTIME_CHROMA_PORT`, `RAGTIME_CHROMA_COLLECTION`. Completed the `RAGTIME_EMBEDDING_*` block with provider/api_key/model. Added a new `RAGTIME_QDRANT_*` block with host/port/collection/api_key/https. Wired matching settings in `ragtime/settings.py` with the standard `os.getenv` defaults.

**4. Configure wizard.** Extended `core/management/commands/_configure_helpers.py::SYSTEMS` with two new entries: `"Embedding"` (subsystem `RAGTIME_EMBEDDING` — PROVIDER/API_KEY/MODEL) and `"Vector Store (Qdrant)"` (subsystem `RAGTIME_QDRANT` — HOST/PORT/COLLECTION/API_KEY/HTTPS). No wizard code changes needed because `_prompt_system` already handles non-shareable systems with optional shared LLM key reuse.

**5. `episodes/vector_store.py`.** New module. `QdrantPoint` dataclass, `QdrantVectorStore` class with `from_settings()` / `ensure_collection()` / `upsert_points()` / `delete_by_episode()`. Constants: `EMBEDDING_DIM=1536`, `DISTANCE=Cosine`, `UPSERT_BATCH_SIZE=128`. `ensure_collection()` verifies an existing collection's vector dim matches the configured model, raising a descriptive `RuntimeError` on mismatch. Payload indexes are created for `episode_id`, `language`, `entity_ids`. Module-level `get_vector_store()` is `@lru_cache(maxsize=1)` for a shared HTTP connection pool.

**6. OpenAI embedding provider.** Added `OpenAIEmbeddingProvider(EmbeddingProvider)` to `episodes/providers/openai.py`, `BATCH_SIZE=128`, decorated with `@trace_provider`, calling `self.client.embeddings.create(model=..., input=batch)` and preserving OpenAI's input order. Records `record_llm_input(model=..., input_count=...)` and `record_llm_output({"vectors": n, "dim": d})` span events. Imported `EmbeddingProvider` from `.base` to make the new class discoverable.

**7. Provider factory.** Added `get_embedding_provider()` to `episodes/providers/factory.py` following the exact shape of the other six factories (reads `RAGTIME_EMBEDDING_{PROVIDER,API_KEY,MODEL}`, raises `ValueError` on missing API key or unknown provider, lazy-imports the concrete class).

**8. `episodes/embedder.py`.** New module. `_build_payloads(episode, chunks)` performs one `EntityMention` query for the whole episode (with `select_related("entity").values(...)`) and groups mentions by `chunk_id` before building the payload dict for each chunk. `embed_episode(episode_id)` is decorated with `@trace_step("embed")` and follows the same guard/start_step/try/fail_step pattern as `extract_entities` / `resolve_entities`. Key behaviour:

- Status guard: if `episode.status != EMBEDDING`, log and return.
- Zero chunks: transition straight to READY with no Qdrant calls.
- Happy path: `ensure_collection()` → `delete_by_episode(episode.pk)` → embed all chunk texts in one provider call (batched internally) → build payloads → `upsert_points()` → EMBEDDING → READY.
- On exception: set status FAILED, record `error_message`, call `fail_step(..., exc=exc)` so the recovery layer gets the failure event.

**9. Signal wiring.** Edited `episodes/signals.py`:

- Added `elif instance.status == Episode.Status.EMBEDDING: async_task("episodes.embedder.embed_episode", instance.pk)` to the post_save handler.
- Added `@receiver(post_delete, sender=Episode)` handler that lazy-imports `get_vector_store` and calls `delete_by_episode(instance.pk)` inside try/except. Errors are logged via `logger.exception` and swallowed — never block an admin delete on a transient Qdrant issue.
- Added a module `logger` and imported `post_delete` from `django.db.models.signals`.

**10. `manage.py dbreset`.** Extended `core/management/commands/dbreset.py` to, after the Postgres recreate + migrate + entity-type seed, check if the Qdrant collection exists and drop it. Wrapped in try/except so Qdrant being down doesn't fail the dbreset.

**11. Tests.** Added `episodes/tests/test_embed.py` — 15 tests:

- `test_happy_path` — 3 chunks, verifies status transition, point count, payload fields (including `entity_ids=[]` when no mentions).
- `test_entity_mentions_in_payload` — resolved entities landing in `entity_ids` / `entity_names`.
- `test_no_chunks_goes_straight_to_ready`.
- `test_idempotent_rerun` — second run replaces, point count stays 2.
- `test_reembed_after_rechunk_drops_stale_points` — seeds points with stale chunk IDs, deletes + recreates chunks with fresh PKs, verifies only the fresh PK survives.
- `test_wrong_status_is_noop` — RESOLVING status → no writes.
- `test_nonexistent_episode_does_not_raise`.
- `test_provider_failure_marks_failed`.
- `test_qdrant_failure_marks_failed`.
- `test_episode_delete_clears_qdrant_points` — post_delete signal removes the point.
- `test_episode_delete_survives_qdrant_failure` — mocked broken store, delete still succeeds.
- `EnsureCollectionTests::test_idempotent_create`.
- `EnsureCollectionTests::test_dim_mismatch_raises`.
- `OpenAIEmbeddingProviderTests::test_batching_preserves_order` — 300 inputs → 3 calls of 128/128/44, output in input order.
- `OpenAIEmbeddingProviderTests::test_empty_input_short_circuits`.

Tests use `QdrantClient(":memory:")` for zero-network isolation.

**12. Test fixes.**

First run had 3 errors:

- `test_entity_mentions_in_payload` tried to create an `EntityType` with `key="musician"`, but a data migration already seeds that row → `IntegrityError` on unique-constraint. Switched to `EntityType.objects.get_or_create(key="musician", defaults=...)`.
- Two delete tests patched `episodes.signals.get_vector_store`, but the signal imports it lazily from `episodes.vector_store`. Changed both patches to `episodes.vector_store.get_vector_store`.

Second run had 2 errors — configure wizard tests. The wizard test pre-seeds `mock_input.side_effect` and `mock_getpass.side_effect` with exact answer counts. Adding the Embedding and Qdrant systems added 6 new regular inputs (provider, model, host, port, collection, https) and 2 new getpass prompts (embedding API key, qdrant API key). Updated both the `test_shared_mode_wizard` and `test_rerun_preserves_non_ragtime_lines` fixtures with the new entries in the right positions.

Third run: full suite green — 276 tests pass.

**13. Documentation.**

- `README.md`: pipeline table row 9 now says "Multilingual embeddings into Qdrant"; removed the "not yet implemented" footnote; updated "What's already implemented" to mention Qdrant; removed "Embed step" from "What's coming"; Tech Stack and Installation notes updated.
- `doc/README.md`: expanded section 9 📐 Embed from a one-line placeholder to a full description with model, collection, payload schema table, idempotency notes, `post_delete` cleanup, and env vars. Updated "How Scott Works" step 3 (Qdrant in place of ChromaDB). Added the `Embed` row to the telemetry table.
- `CHANGELOG.md`: added `### Added` (Embed step) and `### Removed` (ChromaDB env vars) entries under the existing `## 2026-04-19` section, cross-linking plan / feature / planning session / implementation session.
- Created `doc/plans/2026-04-19-embed-step.md`, `doc/features/2026-04-19-embed-step.md`, `doc/sessions/2026-04-19-embed-step-planning-session.md`, and this file.

### Known diagram drift

`doc/architecture/ragtime-processing-pipeline.svg` still labels step 9 "ChromaDB". The Excalidraw source must be regenerated manually (diagrams cannot be auto-updated). Flagged in the feature doc.

### Verification run

```
uv run python manage.py test --verbosity 0
Ran 276 tests in 15.729s
OK
```

End-to-end verification against a running Qdrant container is documented in the feature doc but was not executed during this implementation session.
