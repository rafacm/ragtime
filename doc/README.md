# RAGtime — Detailed Documentation

> Back to [project README](../README.md)

## Table of Contents

- [Processing Pipeline](#processing-pipeline)
  - [Steps](#steps) (1–10)
- [How Scott Works](#how-scott-works)
- [Wikidata Cache](#wikidata-cache)
- [Telemetry (OpenTelemetry)](#telemetry-opentelemetry)
- [Development](#development)
- [Feature Documentation](#feature-documentation)

## Processing Pipeline

[![Processing Pipeline](architecture/ragtime-processing-pipeline.svg)](https://app.excalidraw.com/s/3Cob4pHK6Ge/3zFsvWxbOWQ)

Each step is implemented by a dedicated function in the `episodes` package (e.g., [`fetch_details_step.fetch_episode_details`](../episodes/fetch_details_step.py), [`downloader.download_episode`](../episodes/downloader.py), [`transcriber.transcribe_episode`](../episodes/transcriber.py)) that updates the episode's `status` field when it completes. A [DBOS durable workflow](../episodes/workflows.py) sequences all steps with PostgreSQL-backed checkpointing — on crash or restart, the workflow resumes from the last completed step. The workflow declares one `@DBOS.step()` per pipeline phase, so DBOS itself owns the per-step audit trail (`dbos workflow steps <id>` or the Episode admin's "View workflow steps" link). A [`post_save` signal](../episodes/signals.py) enqueues the workflow when a new episode is created. Any failure sets `status` to `failed` and the exception is recorded by DBOS verbatim — the Download step in particular raises a structured [`DownloadFailed`](../episodes/downloader.py) carrying `episode_id`, `sources_tried`, `wget_error`, and `agent_message`.

### Steps

#### 1. 📥 Submit (status: `pending`)

User submits an episode page URL. Duplicate URLs are rejected.

#### 2. 🕷️ Fetch Details (status: `fetching_details`)

A [Pydantic AI](https://ai.pydantic.dev/) **investigator agent** ([`episodes/agents/fetch_details.py`](../episodes/agents/fetch_details.py)) classifies the submitted URL (canonical publisher page vs aggregator page) and cross-links between them when extraction from the submitted URL alone is incomplete. The agent decides — within a single `agent.run()` loop — when to fetch additional URLs, when to query Apple Podcasts / fyyd, and what to commit to.

Three keyless tools live in [`episodes/agents/fetch_details_tools.py`](../episodes/agents/fetch_details_tools.py):

- `fetch_url(url)` — `httpx` + `BeautifulSoup`, returns cleaned HTML capped at 30 KB.
- `search_apple_podcasts(show, episode_title)` — iTunes Search API, keyless.
- `search_fyyd(show, episode_title)` — fyyd.de, keyless.

The agent emits a wrapped `FetchDetailsOutput { details, report, concise }`:

- `details` — episode-level facts: `title`, `description`, `published_at`, `image_url`, `audio_url`, `audio_format` (closed `Literal`), `language` (ISO 639-1), `country` (ISO 3166-1 alpha-2), `guid`, `canonical_url`, `source_kind` (`canonical | aggregator | unknown`), `aggregator_provider`.
- `report` — structured trace: `attempted_sources`, `discovered_canonical_url`, `discovered_audio_url`, `cross_linked`, `extraction_confidence` (`high | medium | low`), `narrative` (2–4 sentences), `hints_for_next_step` (carried into the Download step).
- `concise` — `outcome` (5-value enum) + `summary` (≤140 chars).

Five outcomes drive the step's status transitions:

| outcome | `Episode.Status` | Meaning |
|---|---|---|
| `ok` | `DOWNLOADING` | required fields filled, `audio_url` known, confidence high |
| `partial` | `DOWNLOADING` | required fields filled, `audio_url` missing or low confidence (report fed forward to download) |
| `not_a_podcast_episode` | `FAILED` | terminal — page is a homepage / article / non-episode |
| `unreachable` | `FAILED` | network or HTTP fetch failed |
| `extraction_failed` | `FAILED` | page loaded, plausibly an episode, but title couldn't be extracted |

Discrimination among the three terminal outcomes happens on `FetchDetailsRun.outcome` — only one `Episode.Status.FAILED` value is used.

Every run persists a `FetchDetailsRun` row carrying the structured output, the auto-captured tool-call trace (input / output excerpts / `ok` flag), the Pydantic AI usage dict, and the DBOS workflow ID. `Episode` columns are overwritten directly by the agent's authoritative output (no empty-field-only merge); a re-run via the admin `reprocess` action increments `run_index` and overwrites again.

The step orchestrator ([`episodes/fetch_details_step.py`](../episodes/fetch_details_step.py)) is DBOS-agnostic: the `@DBOS.step()` wrapper in `episodes/workflows.py` reads `DBOS.workflow_id` and passes it in. The orchestrator records it onto `FetchDetailsRun.dbos_workflow_id` for cross-reference forensics.

Configure via the wizard or `.env` — Convention B encodes the provider in the model string prefix:

```
RAGTIME_FETCH_DETAILS_API_KEY=sk-your-key
RAGTIME_FETCH_DETAILS_MODEL=openai:gpt-4.1-mini    # or anthropic:claude-sonnet-4-20250514, etc.
```

#### 3. ⬇️ Download (status: `downloading`)

Three-tier cascade implemented in [`episodes/downloader.py`](../episodes/downloader.py):

1. **`wget` on `episode.audio_url`** — sub-second on the happy path, no LLM cost. Most episodes finish here.
2. **Pydantic AI download agent** ([`episodes/agents/download.py`](../episodes/agents/download.py)) — invoked when `wget` fails or `audio_url` is empty. The agent runs as a single [`agent.run()`](https://ai.pydantic.dev/agents/#running-agents) call; Pydantic AI maintains the full tool-call / result history within the run so the agent adapts based on what it has already tried. A 30-request usage limit caps cost per run. The agent has three classes of tools:
   * `lookup_podcast_index` — fans out across configured podcast indexes ([fyyd.de](https://fyyd.de/), [podcastindex.org](https://podcastindex.org/)). Each index is a deterministic source of the publisher's RSS-feed enclosure URL and bypasses interactive UI entirely. The agent tries this first.
   * `download_file` — fetches a known URL via the Playwright request context (shares cookies with any prior page navigation).
   * Browsing — `navigate_to_url`, `find_audio_links`, `click_element`, `intercept_audio_requests`, `analyze_screenshot`, `click_at_coordinates`, `translate_text` — for sites whose audio URL only appears after interactive UI is exercised. When the episode language is known, the agent uses `translate_text` to translate UI labels ("Information", "Download") into the page's language. Screenshots taken during the run are attached to OpenTelemetry traces (and to Langfuse media when that collector is enabled).
3. **Failure** — when both tiers give up, the step raises `DownloadFailed(message, episode_id, sources_tried, wget_error, agent_message)`. DBOS records the exception class + args, so `dbos workflow steps <id>` (and the Episode admin's "View workflow steps" link) shows exactly which sources were tried and why.

On success the step extracts the duration with `mutagen.MP3`, attaches the file to `Episode.audio_file`, and advances `Episode.status` to `transcribing`.

##### Configuring the download agent

Install the Playwright browser once:
```
uv run playwright install chromium
```

Configure via the wizard or set these in `.env`:
```
RAGTIME_DOWNLOAD_AGENT_API_KEY=sk-your-key
RAGTIME_DOWNLOAD_AGENT_MODEL=openai:gpt-4.1-mini   # any Pydantic AI model string
RAGTIME_DOWNLOAD_AGENT_TIMEOUT=120
```

`translate_text` uses the configured translation provider:
```
RAGTIME_TRANSLATION_PROVIDER=openai
RAGTIME_TRANSLATION_API_KEY=sk-your-key
RAGTIME_TRANSLATION_MODEL=gpt-4.1-mini
```

##### Configuring podcast aggregators

`RAGTIME_PODCAST_AGGREGATORS` is an ordered, comma-separated list of providers used by the download agent's `lookup_podcast_index` tool. Empty disables aggregator lookup entirely (the agent falls back to browsing). Supported names:

- `apple_podcasts` (alias `itunes`) — iTunes Search API, keyless.
- `fyyd` — fyyd.de's read API is open. `RAGTIME_FYYD_API_KEY` is optional and only raises rate limits.
- `podcastindex` — podcastindex.org. Requires `RAGTIME_PODCASTINDEX_API_KEY` and `RAGTIME_PODCASTINDEX_API_SECRET`. Tries GUID lookup first when one is available (extracted by fetch-details), falls back to title + show search.

Example:
```
RAGTIME_PODCAST_AGGREGATORS=apple_podcasts,fyyd
RAGTIME_PODCASTINDEX_API_KEY=…
RAGTIME_PODCASTINDEX_API_SECRET=…
```

Independently, the Fetch Details agent always has access to keyless `search_apple_podcasts` and `search_fyyd` tools for cross-linking — these are not gated on `RAGTIME_PODCAST_AGGREGATORS`.

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
| Fetch Details | `fetch_episode_details` | Structured metadata extraction |
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

#### Why it's needed

The foreground [resolve step](#8--resolve-entities-status-resolving) maps extracted names ("Miles Davis", "Blue Note", "Take Five") to canonical MusicBrainz IDs by querying a local MusicBrainz Postgres database. Local lookups are sub-millisecond and parallel-safe — every entity name in every chunk gets a fast DB query instead of a rate-limited Wikidata API call, which is what lets the pipeline finish a typical episode in seconds rather than minutes.

Without the MB database, the resolver still works (it falls back to LLM-only resolution against existing entities), but no MBIDs ever land. Every entity then drops into the slower Wikidata-API path during [background enrichment](#background-wikidata-enrichment), serialized through the singleton `wikidata_enrichment` queue at 5 req/s. The pipeline still produces correct results, just much more slowly.

#### Importing the dump

Use [`musicbrainz-database-setup`](https://github.com/rafacm/musicbrainz-database-setup), a one-shot CLI that downloads the latest dump from the [MetaBrainz mirror](https://wiki.musicbrainz.org/MusicBrainz_Database/Download), creates the schema, and `COPY`s every table:

```bash
# 1. Create the database — defaults to 'musicbrainz', alongside the 'ragtime' DB
#    in the same Postgres instance from docker compose. RAGtime's compose file
#    ships postgres:17-alpine, which satisfies the importer's PostgreSQL 16+
#    requirement out of the box.
docker compose exec postgres createdb -U ragtime musicbrainz

# 2. One-shot import.
#    - `uvx --from git+...` runs the importer's CLI straight from GitHub
#      without a local clone or separate install.
#    - `--db <conninfo>` is libpq-style; user must have SUPERUSER on the DB
#      (the docker-compose 'ragtime' role does, since it owns the cluster).
#    - `--modules core` pulls just the core entity tables RAGtime needs
#      (artist / release_group / work / place / label / area + aliases +
#      l_*_url external links). Skip `derived` / `cover-art` / `wikidocs`
#      unless you want them for other tooling.
#    - `--latest` skips the interactive dump-picker and grabs the newest dump
#      from the MetaBrainz mirror. Use `--date YYYYMMDD-HHMMSS` to pin one.
#    Takes ~30+ minutes depending on disk speed; downloads are resumable and
#    SHA256-verified, COPY parallelizes via pbzip2/lbzip2 if either is on PATH.
uvx --from git+https://github.com/rafacm/musicbrainz-database-setup \
  musicbrainz-database-setup run \
  --db postgresql://ragtime:ragtime@localhost:5432/musicbrainz \
  --modules core \
  --latest
```

The connection string is `postgresql://<user>:<password>@<host>:<port>/<database>`. To put MB in the same Postgres instance as `ragtime`, match the `RAGTIME_DB_*` values in your `.env`; to put it elsewhere, point the `RAGTIME_MUSICBRAINZ_DB_*` env vars at the new host.

#### Configuration

By default RAGtime expects MB at the same Postgres host/port/user/password as the main `ragtime` database, in a database called `musicbrainz`, with the schema name `musicbrainz`. Override per-key via env vars when MB lives elsewhere:

| Env var | Default | Purpose |
|---|---|---|
| `RAGTIME_MUSICBRAINZ_DB_HOST` | inherits `RAGTIME_DB_HOST` | MB Postgres host |
| `RAGTIME_MUSICBRAINZ_DB_PORT` | inherits `RAGTIME_DB_PORT` | MB Postgres port |
| `RAGTIME_MUSICBRAINZ_DB_NAME` | `musicbrainz` | Database name |
| `RAGTIME_MUSICBRAINZ_DB_USER` | inherits `RAGTIME_DB_USER` | Read-only role works |
| `RAGTIME_MUSICBRAINZ_DB_PASSWORD` | inherits `RAGTIME_DB_PASSWORD` | |
| `RAGTIME_MUSICBRAINZ_SCHEMA` | `musicbrainz` | Schema MB tables live in (the upstream importer's default) |

`uv run python manage.py configure` walks all of these interactively under the **MusicBrainz** section of the wizard.

#### Operational notes

- This is a one-time setup. RAGtime only **reads** from MB; it never writes. Re-import is only needed when you want a fresher dump.
- The full `core` module is what RAGtime uses (artist / release_group / work / place / label / area + their `*_alias` and `l_*_url` tables). Optional modules (`derived` / `cover-art` / `wikidocs`) aren't read by RAGtime today — leave them out unless you want them for other tooling.
- The upstream importer is resumable, SHA256-verifies every download, and `pbzip2`/`lbzip2` will roughly halve the COPY phase if available on `$PATH`.

See the [musicbrainz-database-setup project page](https://github.com/rafacm/musicbrainz-database-setup) for the full setup guide: server-side Postgres tuning to halve import time, how to keep the password out of the connection URL via `PGPASSWORD` / `~/.pgpass`, and managed-Postgres caveats.

### Submitting an episode

Episodes are normally submitted from the Django admin UI ([http://localhost:8000/admin/](http://localhost:8000/admin/) → *Episodes* → *Add*). For ad-hoc CLI submission during testing:

```bash
uv run python manage.py submit_episode https://example.com/ep/123
```

The command creates a single ``Episode`` row with ``status=pending``; the ``post_save`` signal then moves it to ``queued`` and enqueues a ``process_episode`` workflow on the ``episode_pipeline`` DBOS queue. Run the command repeatedly for multiple episodes — re-submitting an already-submitted URL is a no-op (the existing row is reported and no second workflow is enqueued).

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
