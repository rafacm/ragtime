# RAGtime — Detailed Documentation

> Back to [project README](../README.md)

## Table of Contents

- [Processing Pipeline](#processing-pipeline)
  - [Steps](#steps) (1–10)
  - [Recovery](#recovery)
- [How Scott Works](#how-scott-works)
- [Wikidata Cache](#wikidata-cache)
- [Telemetry (OpenTelemetry)](#telemetry-opentelemetry)
- [Development](#development)
- [Feature Documentation](#feature-documentation)

## Processing Pipeline

[![Processing Pipeline](architecture/ragtime-processing-pipeline.svg)](https://app.excalidraw.com/s/3Cob4pHK6Ge/3zFsvWxbOWQ)

Each step is implemented by a dedicated function in the `episodes` package (e.g., [`scraper.scrape_episode`](../episodes/scraper.py), [`downloader.download_episode`](../episodes/downloader.py), [`transcriber.transcribe_episode`](../episodes/transcriber.py)) that updates the episode's `status` field when it completes. A [DBOS durable workflow](../episodes/workflows.py) sequences all steps with PostgreSQL-backed checkpointing — on crash or restart, the workflow resumes from the last completed step. A [`post_save` signal](../episodes/signals.py) starts the workflow when a new episode is created. Any failure sets `status` to `failed`, emits a structured `step_failed` signal, and triggers the [recovery layer](#recovery) which walks a configurable strategy chain (agent → human escalation).

### Steps

#### 1. 📥 Submit (status: `pending`)

User submits an episode page URL. Duplicate URLs are rejected.

#### 2. 🕷️ Scrape (status: `scraping`)

Extract metadata (title, description, date, image, audio URL) and detect language via LLM-based structured extraction. Episodes with missing required fields (title or audio URL) are marked `failed` and escalated to the recovery layer for human review.

#### 3. ⬇️ Download (status: `downloading`)

Download the audio file and extract duration.

#### 4. 🎙️ Transcribe (status: `transcribing`)

Send audio to the Whisper API (or a local Whisper-compatible endpoint) for transcription, producing segment and word-level timestamps in the detected language. Files that exceed the configurable size limit (default 25 MB) are [adaptively downsampled](features/2026-03-15-adaptive-audio-resize-tiers.md) with ffmpeg — the gentlest settings that fit are chosen based on episode duration, from 128 kbps for slightly oversized files down to 32 kbps for very long episodes.

#### 5. 📋 Summarize (status: `summarizing`)

LLM-generated episode summary in the episode's detected language.

#### 6. ✂️ Chunk (status: `chunking`)

Split transcript into ~150-word chunks along Whisper segment boundaries, with 1-segment overlap.

#### 7. 🔍 Extract entities (status: `extracting`)

**Named Entity Recognition (NER)** — identifies entity mentions in the transcript text.

Runs **per chunk**: each chunk is sent to the LLM independently, which returns the entity names and types it finds. This is a surface-level task — the LLM only needs the chunk's text to spot mentions. Results are stored as raw JSON in `Chunk.entities_json`.

At this stage, no `Entity` or `EntityMention` records are created and no deduplication happens. The same entity may appear under different surface forms across chunks (e.g., "Bird" in chunk 3, "Charlie Parker" in chunk 12).

**Example** — given a chunk containing *"Bird played at Birdland alongside Dizzy Gillespie"*, extraction produces:

| Mention | Type |
|---|---|
| Bird | musician |
| Birdland | music venue |
| Dizzy Gillespie | musician |

**Entity types** (musician, musical group, album, composed musical work, music venue, recording session, record label, year, historical period, city, country, music genre, musical instrument, role) are stored in the database and managed via Django admin. Each entity type has a **[Wikidata](https://www.wikidata.org/) class Q-ID** (e.g., [Q639669](https://www.wikidata.org/wiki/Q639669) for "musician") used for candidate lookup during resolution. An initial set of 14 types is defined in [`episodes/initial_entity_types.yaml`](../episodes/initial_entity_types.yaml) — load them with:

```
uv run python manage.py load_entity_types
```

New types can be added through Django admin; existing types can be deactivated (set `is_active = False`) to exclude them from future extractions without deleting historical data. Types that have existing entities cannot be deleted (protected by referential integrity).

#### 8. 🧩 Resolve entities (status: `resolving`)

**Entity Linking (NEL)** — maps extracted mentions to canonical entity records, deduplicating across chunks. Foreground resolution is **MusicBrainz-first** — the local MB Postgres database is queried for candidate MBIDs (sub-millisecond, parallel-safe). Wikidata enrichment runs separately in the background; the foreground never calls the Wikidata API.

Aggregates all extracted names across every chunk, then resolves **once per entity type** using LLM-based fuzzy matching against two sources:

1. **Existing DB records** — prevents duplicates when the same entity was seen in a previous episode.
2. **MusicBrainz candidates** — local DB search by name + alias against the type's MB table (artist, release_group, work, place, label, area), presenting MBID + disambiguation to the LLM. Matched entities receive a `musicbrainz_id` (UUID).

Race-safe under parallel episode pipelines: every `Entity` create goes through `get_or_create` plus a sorted Postgres `pg_advisory_xact_lock` per `(entity_type, name)` (transaction-scoped, so concurrent resolvers serialize on shared names without deadlocking).

**Entity-type to MB-table mapping** (defined in `episodes/initial_entity_types.yaml`):

| Entity type | MB table | MB filter | Foreground source |
|---|---|---|---|
| `musician` | `artist` | `type=Person` | MusicBrainz |
| `musical_group` | `artist` | `type=Group/Orchestra/Choir` | MusicBrainz |
| `album` | `release_group` | `primary_type=Album` | MusicBrainz |
| `composed_musical_work` | `work` | — | MusicBrainz |
| `music_venue` | `place` | — | MusicBrainz |
| `record_label` | `label` | — | MusicBrainz |
| `city` | `area` | `type=City` | MusicBrainz |
| `country` | `area` | `type=Country` | MusicBrainz |
| `recording_session`, `year`, `historical_period`, `music_genre`, `musical_instrument`, `role` | — | — | name-only (background Wikidata) |

**Example** — continuing from the extract step, suppose the episode's chunks collectively mention "Bird", "Charlie Parker", "Yardbird", and "Dizzy Gillespie":

| Extracted mentions | Resolved to (canonical entity) | MBID |
|---|---|---|
| Bird, Charlie Parker, Yardbird | Charlie Parker | `91a05b78-c89f-4d2e-9bf8-f3a4abe44a76` |
| Dizzy Gillespie | Dizzy Gillespie | `0a2f3672-ee44-4c84-9b27-9234e4b27cc1` |

All three surface forms collapse into a single `Entity` record for Charlie Parker. An `EntityMention` is created for each (entity, chunk) pair, preserving which chunks mentioned the entity and the context of each mention.

The newly-created `Entity` rows are enqueued for **background Wikidata enrichment** (see below). The episode itself moves on to the embed step immediately — Wikidata Q-IDs may land minutes/hours later.

This two-phase design (extract then resolve) is intentional: extraction is cheap and parallelizable per chunk, while resolution requires cross-chunk aggregation and knowledge base lookups. It also allows re-running resolution independently — e.g., after improving matching logic — without re-extracting.

##### Background Wikidata enrichment

After foreground resolution, a singleton DBOS workflow on the `wikidata_enrichment` queue (`concurrency=1`, `worker_concurrency=1`) backfills `Entity.wikidata_id`. Per entity, deduplicated globally — common names get enriched once across all episodes.

Strategy:

1. If `Entity.musicbrainz_id` is set, look up the Wikidata link via MusicBrainz's external-links data (local DB join through `l_<entity>_url` → `url`, no network).
2. Otherwise, fall back to the Wikidata API (rate-limited, single concurrent worker by construction).
3. Persist `Entity.wikidata_id` and bookkeeping (`wikidata_status`, `wikidata_attempts`, `wikidata_last_attempted_at`).

Wikidata IDs flow into Scott's search results via search-time hydration (`vector_store.search_chunks()` joins `EntityMention → Entity`). No Qdrant payload mutation needed.

Backfill any pending entities (e.g. after extending `MAX_ATTEMPTS` or after a long Wikidata outage):

```
uv run python manage.py enrich_entities                 # PENDING only
uv run python manage.py enrich_entities --retry-failed  # also FAILED + NOT_FOUND
uv run python manage.py enrich_entities --limit 100
```

Search Wikidata from the CLI with:

```
uv run python manage.py lookup_entity "Miles Davis"
uv run python manage.py lookup_entity --type musician "Miles Davis"
```

#### 9. 📐 Embed (status: `embedding`)

Generate multilingual embeddings for every chunk and upsert them into a [Qdrant](https://qdrant.tech/) collection alongside the metadata Scott needs to cite them.

Default embedding model: OpenAI [`text-embedding-3-small`](https://platform.openai.com/docs/guides/embeddings) (1536-dim, multilingual, cosine distance). Chunks are embedded in batches of 128 texts per OpenAI request; Qdrant points are upserted in batches of 128. The collection is bootstrapped once at process startup (`episodes/apps.ready()`) and defaults to `ragtime_chunks`. Only the raw `chunk.text` is embedded — episode metadata, entity names, and timestamps are **not** stored in Qdrant; they're hydrated from Postgres at search time.

Point IDs are deterministic (`chunk.pk`), so upserts are idempotent. The step always calls `delete_by_episode()` before writing — this keeps re-runs safe after re-chunking, and clears stale points when an episode is re-ingested into zero chunks (otherwise Scott could retrieve content that no longer exists in Postgres).

Vector dimensions are **detected at runtime** by probing the configured embedding provider once per process (one single-word `provider.embed(["dim-probe"])` call, cached via `@lru_cache`). The collection is created with whatever dim the live model produces. If an existing collection was created with a different dim, `ensure_collection()` fails fast with a clear error that names both dims and the current model, protecting against silent schema drift when `RAGTIME_EMBEDDING_MODEL` is changed. `manage.py configure` additionally prints a warning when the user changes the model value, pointing at `manage.py dbreset` as the recovery path. Concurrent cold starts are tolerated — `ensure_collection()` treats a 409 from `create_collection` as success.

Each Qdrant point carries a slim payload (indexed fields marked with ⚡):

| Field | Type | Notes |
|-------|------|-------|
| `chunk_id` | int | FK back to Postgres for search-time hydration |
| `episode_id` ⚡ | int | Filter by episode (Scott's per-episode filter) |
| `language` ⚡ | str | Future per-language filter |
| `entity_ids` ⚡ | list[int] | Entity-faceted retrieval / future ranking |

Everything else Scott displays (episode title, urls, chunk text, entity names, MBIDs, Wikidata IDs) is fetched from Postgres at search time via a single keyed query in `vector_store.search_chunks()`. This makes Postgres the single source of truth — title edits and background Wikidata enrichment flow through immediately without re-embedding or `set_payload` calls.

When an Episode is deleted, a `post_delete` signal calls `delete_by_episode()` to keep Qdrant consistent with Postgres (errors are logged and swallowed — a stale Qdrant point is better than a failing admin delete).

Configure via the wizard (`uv run python manage.py configure`) or manually in `.env`:

```
RAGTIME_EMBEDDING_PROVIDER=openai
RAGTIME_EMBEDDING_API_KEY=sk-your-key
RAGTIME_EMBEDDING_MODEL=text-embedding-3-small

RAGTIME_QDRANT_HOST=localhost
RAGTIME_QDRANT_PORT=6333
RAGTIME_QDRANT_COLLECTION=ragtime_chunks
RAGTIME_QDRANT_API_KEY=
RAGTIME_QDRANT_HTTPS=false
```

`manage.py dbreset` drops the Qdrant collection in addition to recreating Postgres, so a fresh dev database doesn't leave orphaned points under future-colliding chunk IDs.

#### 10. ✅ Ready (status: `ready`)

Episode fully processed and available for Scott to query.

### Recovery

When any pipeline step fails, the [`step_failed` handler](../episodes/recovery.py) triggers the recovery layer, which walks a configurable strategy chain before giving up:

[![Recovery Layer diagram](architecture/ragtime-recovery.svg)](https://app.excalidraw.com/s/3Cob4pHK6Ge/Az6udDWhj7T)

1. **Agent (steps 2–3 only)** — a [Pydantic AI](https://ai.pydantic.dev/) agent with [Playwright](https://playwright.dev/) browser automation navigates the podcast page, finds audio URLs behind JavaScript players or CloudFlare blocks, and downloads files through a real browser. The agent visits the episode page first to establish cookies and session state, then attempts the audio URL directly. When the episode language is known, the agent receives language context and can use a `translate_text` tool to translate UI labels (e.g. "Information", "Download") that may appear in the page's language. On success it resumes the pipeline from the next step automatically. When recovering from a scraping failure, if the agent both finds the audio URL and downloads the MP3 file (using browser cookies), it skips the download step entirely and resumes directly from transcribing — this avoids a redundant `wget` download that would fail without the browser's session cookies. Only applies to scraping and downloading failures. The agent takes a screenshot after every action for full observability.
2. **Human escalation** — for all other failures, or when the agent fails or is disabled, the failure is marked `awaiting_human` for manual resolution in Django admin.

The agent strategy is **off by default**. To enable it, install the Playwright browser and configure:

```
uv run playwright install chromium
```

Configure via the wizard:
```
uv run python manage.py configure
```
or set these variables in `.env`:
```
RAGTIME_RECOVERY_AGENT_ENABLED=true
RAGTIME_RECOVERY_AGENT_API_KEY=sk-your-key
RAGTIME_RECOVERY_AGENT_MODEL=openai:gpt-4.1-mini
```

The agent's LLM provider is fully independent from other subsystems — configure any [Pydantic AI model string](https://ai.pydantic.dev/models/) (e.g., `anthropic:claude-sonnet-4-20250514`). A maximum of 30 LLM requests per recovery attempt prevents runaway costs. Screenshots taken during recovery are attached to traces when telemetry collectors are enabled (binary media attachments require the Langfuse collector).

The `translate_text` tool uses a separate LLM provider to translate UI labels to the episode's language. It is included in the shareable LLM provider group in the configuration wizard. To configure manually, set these variables in `.env`:
```
RAGTIME_TRANSLATION_PROVIDER=openai
RAGTIME_TRANSLATION_API_KEY=sk-your-key
RAGTIME_TRANSLATION_MODEL=gpt-4.1-mini
```

The agent runs as a single [`agent.run()`](https://ai.pydantic.dev/agents/#running-agents) call. Pydantic AI automatically maintains the full conversation history (tool calls, results, LLM responses) across all iterations within that run — the agent sees what it has already tried and adapts its strategy accordingly. No external memory or state management is needed; each recovery attempt is self-contained. The [system prompt](../episodes/agents/agent.py) defines a multi-step strategy and the LLM reasons about which step to try next based on prior tool results within the same run.

The chain order is configured in [`settings.py`](../ragtime/settings.py), and the maximum retry count (default: 5) is controlled by the `MAX_RECOVERY_ATTEMPTS` constant in [`episodes/recovery.py`](../episodes/recovery.py). The system prompt and tool registration are in [`episodes/agents/agent.py`](../episodes/agents/agent.py). The agent tools — `navigate_to_url`, `find_audio_links`, `click_element`, `download_file`, `translate_text`, `analyze_screenshot`, `click_at_coordinates`, `intercept_audio_requests`, and others — are defined in [`episodes/agents/tools.py`](../episodes/agents/tools.py).

## How Scott Works

Scott is a strict RAG (Retrieval-Augmented Generation) agent implemented with Pydantic AI and exposed to the frontend over the AG-UI (HTTP+SSE) protocol.

**Agent loop:**

1. User asks a question in any language.
2. Scott's system prompt mandates calling the `search_chunks` tool before any factual answer.
3. Each `search_chunks(query, episode_id?, top_k?)` call embeds the query with the configured multilingual embedding model and retrieves the top-k matching chunks from Qdrant (with an optional episode filter and a score floor). Results are appended to the agent's `retrieved_chunks` state with stable 1-indexed `[N]` labels.
4. Scott may call `search_chunks` again with a refined or widened query to support follow-ups and multi-hop questions.
5. The LLM answers using only the retrieved chunks and cites each fact with a `[N]` marker. If no relevant chunks are found, Scott says so and stops — no general-knowledge fallback.
6. The response streams token-by-token over SSE; state snapshots drive any live UI (e.g. a source panel).

**Configuration:**

| Setting | Default | Description |
|---|---|---|
| `RAGTIME_SCOTT_PROVIDER` | `openai` | LLM provider (currently only `openai`) |
| `RAGTIME_SCOTT_MODEL` | `gpt-4.1-mini` | Model name |
| `RAGTIME_SCOTT_API_KEY` | — | Provider API key |
| `RAGTIME_SCOTT_TOP_K` | `5` | Chunks returned per `search_chunks` call |
| `RAGTIME_SCOTT_SCORE_THRESHOLD` | `0.3` | Minimum cosine similarity for a chunk to be kept |

**Topology:**

```
Browser (React island: assistant-ui + @assistant-ui/react-ag-ui)
   │   HTTP+SSE (AG-UI protocol)
   ▼
Django ASGI app (ragtime/asgi.py)
   ├── /chat/agent/  → authenticated AG-UI mount → Pydantic AI Agent
   │                    └── @agent.tool search_chunks → episodes/vector_store.py
   │                         └── EmbeddingProvider.embed + Qdrant query_points
   └── everything else → standard Django (pages, auth, admin, episodes API)
```

Scott answers in the user's language regardless of the source episode's language — cross-language retrieval is handled by the multilingual embedding model.

## Wikidata Cache

Wikidata API responses are cached to avoid repeated requests during entity resolution. Each unique entity name can trigger up to 11 API requests (1 search + up to 10 detail lookups), so caching is critical for performance and to avoid IP rate-limiting.

| Setting | Default | Description |
|---------|---------|-------------|
| `RAGTIME_WIKIDATA_CACHE_BACKEND` | `filebased` | `filebased` (default, persistent) or `db` (requires `manage.py createcachetable`) |
| `RAGTIME_WIKIDATA_CACHE_TTL` | `604800` | Cache TTL in seconds (7 days) |

The file-based cache is stored in `.cache/wikidata/` (gitignored). To clear it:

```bash
rm -rf .cache/wikidata/
```

API requests are rate-limited per process via a token bucket (~5 req/s sustained, bursts up to 10). Only cache misses count against the rate limit.

## Telemetry (OpenTelemetry)

RAGtime uses [OpenTelemetry](https://opentelemetry.io/) to trace pipeline steps and LLM calls. Traces can be exported to any combination of collectors: **console** (stdout), **Jaeger** (self-hosted UI), or **Langfuse** (LLM-specific observability).

### What is traced

| Pipeline step | Function | LLM calls |
|---|---|---|
| Scrape | `scrape_episode` | Structured metadata extraction |
| Transcribe | `transcribe_episode` | Whisper API transcription |
| Summarize | `summarize_episode` | Summary generation |
| Extract | `extract_entities` | Per-chunk entity extraction |
| Resolve | `resolve_entities` | Entity resolution against DB |
| Embed | `embed_episode` | OpenAI embeddings (one batch = one child span) |

Each step creates an OTel span with episode metadata. OpenAI API calls are auto-instrumented as child spans.

### Collectors

#### Console

Prints spans to stdout — useful for local debugging.

```
RAGTIME_OTEL_COLLECTORS=console
```

#### Jaeger

[Jaeger](https://www.jaegertracing.io/) is the simplest option for local development — a single Docker container that accepts OTLP traces and provides a search UI.

1. Start Jaeger:
   ```bash
   docker run -d --name jaeger -p 4318:4318 -p 16686:16686 jaegertracing/all-in-one:latest
   ```

2. Set these variables in `.env`:
   ```
   RAGTIME_OTEL_COLLECTORS=jaeger
   RAGTIME_OTEL_JAEGER_ENDPOINT=http://localhost:4318
   ```

3. Process an episode and view traces at `http://localhost:16686`.

#### Langfuse

[Langfuse](https://langfuse.com) provides LLM-specific observability with cost tracking, prompt management, and evaluation. The Langfuse SDK hooks into the shared OTel `TracerProvider` as a `SpanProcessor`, so traces flow through the same pipeline as other collectors. Langfuse-specific features (session grouping via `session_id`/`user_id`, binary screenshot attachments) are preserved.

1. Install the optional Langfuse dependency:
   ```bash
   uv sync --extra langfuse
   ```

2. Run Langfuse locally via Docker Compose. See [Langfuse self-hosting guide](https://langfuse.com/self-hosting/deployment/docker-compose).

   **Port conflict:** Langfuse's docker-compose.yml exposes its PostgreSQL on port 5432, which conflicts with RAGtime's. Run one of these in the Langfuse directory to move it to port 5433:
   ```bash
   # macOS (BSD sed)
   sed -i '' 's/127.0.0.1:5432:5432/127.0.0.1:5433:5432/' docker-compose.yml

   # Linux (GNU sed)
   sed -i 's/127.0.0.1:5432:5432/127.0.0.1:5433:5432/' docker-compose.yml
   ```

3. Set these variables in `.env`:
   ```
   RAGTIME_OTEL_COLLECTORS=langfuse
   RAGTIME_LANGFUSE_SECRET_KEY=sk-lf-...
   RAGTIME_LANGFUSE_PUBLIC_KEY=pk-lf-...
   RAGTIME_LANGFUSE_HOST=http://localhost:3000
   ```

4. Process an episode and view traces at `http://localhost:3000`.

#### Multiple collectors

Enable multiple collectors simultaneously:

```
RAGTIME_OTEL_COLLECTORS=console,jaeger,langfuse
```

### Configuration

Configure via the wizard or `.env`:

```
uv run python manage.py configure
```

| Variable | Default | Purpose |
|---|---|---|
| `RAGTIME_OTEL_COLLECTORS` | `""` (disabled) | Comma-separated: `console`, `jaeger`, `langfuse` |
| `RAGTIME_OTEL_SERVICE_NAME` | `ragtime` | OTel service name |
| `RAGTIME_OTEL_JAEGER_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint for Jaeger |
| `RAGTIME_LANGFUSE_SECRET_KEY` | `""` | Langfuse auth |
| `RAGTIME_LANGFUSE_PUBLIC_KEY` | `""` | Langfuse auth |
| `RAGTIME_LANGFUSE_HOST` | `http://localhost:3000` | Langfuse host |

When no collectors are configured (the default), OTel provides a no-op tracer with zero overhead.

## Development

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) — required for PostgreSQL
- [Python 3.13+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/)

### Starting services

```bash
docker compose up -d    # Start PostgreSQL and Qdrant
```

The `ragtime` database is created automatically on first start. Both ports are bound to `127.0.0.1` (localhost only, not exposed to the network).

#### Application server

```bash
uv run uvicorn ragtime.asgi:application --host 127.0.0.1 --port 8000
```

Uvicorn (ASGI) is required for Scott's streaming chat endpoint. See [Running the services](../README.md#running-the-services) in the root README for full details.

#### Frontend dev server

```bash
cd frontend && npm run dev
```

Vite serves the React chat UI with HMR on port 5173. Both the ASGI server and Vite must be running to develop the chat UI.

### MusicBrainz database

The foreground [resolve step](#8--resolve-entities-status-resolving) queries a local MusicBrainz Postgres database for candidate MBIDs. Without it, the resolver still works (it falls back to LLM-only resolution against existing entities), but MBIDs never land — and every entity drops into the slower Wikidata-API path during background enrichment. With it, the foreground stays sub-millisecond per entity and parallel-safe across episodes.

Use [`musicbrainz-database-setup`](https://github.com/rafacm/musicbrainz-database-setup) to import the dump:

```bash
# 1. Create the database (defaults to 'musicbrainz', alongside the 'ragtime' DB)
docker compose exec postgres createdb -U ragtime musicbrainz

# 2. One-shot import (~30+ minutes; resumable if interrupted)
uvx --from git+https://github.com/rafacm/musicbrainz-database-setup \
  musicbrainz-database-setup run \
  --db postgresql://ragtime:ragtime@localhost:5432/musicbrainz \
  --modules core \
  --latest
```

Connect RAGtime to it via `RAGTIME_MUSICBRAINZ_DB_HOST/_PORT/_NAME/_USER/_PASSWORD` and `RAGTIME_MUSICBRAINZ_SCHEMA` (defaults inherit from `RAGTIME_DB_*`, schema defaults to `musicbrainz`). RAGtime only reads from this database — installs of MB are entirely managed by the upstream tool. PostgreSQL 16+ is required (RAGtime's Docker Compose ships `postgres:17-alpine`).

See the [musicbrainz-database-setup project page](https://github.com/rafacm/musicbrainz-database-setup) for the full setup guide: optional `derived` / `cover-art` / `wikidocs` modules, server-side tuning to halve import time, and how to keep credentials out of the URL.

### Running tests

PostgreSQL must be running before running tests:

```bash
docker compose up -d
uv run python manage.py test
```

Django's test runner creates a temporary `test_ragtime` database automatically and destroys it after the run. In CI, the GitHub Actions workflow starts a PostgreSQL service container with the same credentials.

### Resetting the database

To drop all data and start fresh:

```bash
uv run python manage.py dbreset        # interactive confirmation
uv run python manage.py dbreset --yes  # skip confirmation
```

This drops and recreates the `ragtime` database, runs all migrations, and seeds entity types. Run `createsuperuser` afterwards to recreate the admin account.

## Feature Documentation

Each feature or significant change is documented with:

- **Plan** ([`plans/`](plans/)) — implementation strategy, written before coding begins
- **Feature doc** ([`features/`](features/)) — problem, changes, key parameters, verification, and files modified
- **Session transcripts** ([`sessions/`](sessions/)) — planning and implementation conversation logs with reasoning steps

All documents use a `YYYY-MM-DD-` date prefix. See the [CHANGELOG](../CHANGELOG.md) for a linked index of all features.
