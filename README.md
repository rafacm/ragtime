<div align="center">
  <picture>
    <img src="doc/ragtime.svg" alt="RAGtime -- Retrieval Augmented Generation (RAG) in the Key of Jazz" width="100%">
  </picture>
  <br>
  <sub>Image generated with <a href="https://gemini.google/overview/image-generation/">Nano Banana</a> from the cover of <a href="https://en.wikipedia.org/wiki/Ragtime_(novel)">E.L. Doctorow's novel "Ragtime"</a></sub>
</div>

<br>

<div align="center">

[![CI](https://github.com/rafacm/ragtime/actions/workflows/ci.yml/badge.svg)](https://github.com/rafacm/ragtime/actions/workflows/ci.yml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![Django 5.2](https://img.shields.io/badge/django-5.2-green)](https://www.djangoproject.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)

</div>

## What is RAGtime?

RAGtime is a Django application for ingesting jazz-related podcast episodes. It extracts metadata, transcribes audio, identifies jazz entities, and powers **Scott** — a jazz-focused AI agent that answers questions strictly from ingested episode content, with references to specific episodes and timestamps.

<div align="center">
  <img src="doc/ragtime-scott-chat.png" alt="Scott answering questions about Django Reinhardt" width="100%">
</div>

## Features

- 🎙️ **Episode Ingestion** — Add podcast episodes by URL. RAGtime fetches episode details (title, description, date, image), downloads audio, and processes it through the pipeline.
- 📝 **Multilingual Transcription** — Transcribes episodes using configurable backends (Whisper API by default) with segment and word-level timestamps. Supports multiple languages (English, Spanish, German, Swedish, etc.).
- 🔍 **Entity Extraction** — Identifies jazz entities: musicians, musical groups, albums, music venues, recording sessions, record labels, years. Entities are resolved against the local MusicBrainz database (foreground, sub-millisecond) and Wikidata (background, throttled singleton enrichment).
- 📇 **Episode Indexing** — Splits transcripts into segments and generates multilingual embeddings stored in Qdrant. Enables cross-language semantic search so Scott can retrieve relevant content regardless of the question's language.
- 🎷 **Scott — Your Jazz AI** — A conversational agent that answers questions strictly from ingested episode content. Scott responds in the user's language and provides references to specific episodes and timestamps. Responses stream in real-time.
- 📊 **AI Evaluation** — Measures pipeline and Scott quality using [RAGAS](https://docs.ragas.io/) (faithfulness, answer relevancy, context precision/recall) with scores tracked in [Langfuse](https://langfuse.com/docs/scores/model-based-evals/ragas).

## Status

> RAGtime is under active development.

### What's already implemented

- **Episode ingestion**: submit episodes by URL, episode-detail fetching, audio download, transcription, summarization, chunking, entity extraction with foreground resolution against a local [MusicBrainz](https://musicbrainz.org/) Postgres database and background [Wikidata](https://www.wikidata.org/) enrichment, and multilingual embeddings into [Qdrant](https://qdrant.tech/).
- **Episode management UI**: Django admin interface to view episode status and metadata and browse extracted entities.
- **Configuration wizard**: interactive `manage.py configure` command for all `RAGTIME_*` env vars.
- **Telemetry**: [OpenTelemetry](https://opentelemetry.io/)-based tracing for pipeline steps and LLM calls with optional collectors: console, [Jaeger](https://www.jaegertracing.io/), and [Langfuse](https://langfuse.com).
- **Agent-driven download**: when the cheap `wget` path fails, a [Pydantic AI](https://ai.pydantic.dev/) agent with podcast-index lookup ([fyyd](https://fyyd.de/), [podcastindex.org](https://podcastindex.org/)) and [Playwright](https://playwright.dev/) browser automation discovers the audio URL from the publisher's page or interactive UI.
- **Scott chatbot**: strict-RAG conversational agent that answers questions only from ingested episode content, with citations and real-time streaming via [AG-UI](https://github.com/ag-ui-protocol/ag-ui). React frontend built with [assistant-ui](https://www.assistant-ui.com/) and conversation history persisted in Django.

See [CHANGELOG.md](CHANGELOG.md) for the full list of implemented features, fixes, implementation plans, feature documentation and session transcripts.

### What's coming

- **AI evaluation**: measure pipeline and Scott quality using [RAGAS](https://docs.ragas.io/) (faithfulness, answer relevancy, context precision/recall) with scores tracked in [Langfuse](https://langfuse.com/docs/scores/model-based-evals/ragas). Enables regression testing across prompt and model changes.

## Processing Pipeline

[![Processing Pipeline](doc/architecture/ragtime-processing-pipeline.svg)](https://app.excalidraw.com/s/3Cob4pHK6Ge/3zFsvWxbOWQ)

Each step updates the episode's `status` field. A `post_save` signal enqueues a [DBOS](https://docs.dbos.dev/) durable workflow on the `episode_pipeline` queue (default `concurrency=4` via `RAGTIME_EPISODE_CONCURRENCY`) that sequences all steps with PostgreSQL-backed checkpointing — on crash or restart, the workflow resumes from the last completed step. The workflow exposes one `@DBOS.step()` per pipeline phase, so `dbos workflow steps <id>` (and the Episode admin's "View workflow steps" link) shows exactly which phase ran, its output, or the exception raised. Episodes that arrive while all worker slots are busy sit visibly in the `queued` state until DBOS picks them up.

| # | Step | Status | Description |
|---|------|--------|-------------|
| 1 | 📥 Submit | `pending` | User submits an episode URL |
| ⏸ | ⏳ Queue | `queued` | Waiting for a pipeline worker slot |
| 2 | 🕷️ Fetch Details | `fetching_details` | Extract metadata and detect language |
| 3 | ⬇️ Download | `downloading` | Download audio (cheap `wget` first; agent + podcast-index fallback) and extract duration |
| 4 | 🎙️ Transcribe | `transcribing` | Whisper API transcription with timestamps |
| 5 | 📋 Summarize | `summarizing` | LLM-generated episode summary |
| 6 | ✂️ Chunk | `chunking` | Split transcript into ~150-word chunks |
| 7 | 🔍 Extract | `extracting` | Named entity recognition per chunk |
| 8 | 🧩 Resolve | `resolving` | Entity linking + deduplication against the local MusicBrainz database |
| 9 | 📐 Embed | `embedding` | Multilingual embeddings into Qdrant |
| 10 | ✅ Ready | `ready` | Episode available for Scott to query |

Wikidata IDs are filled in *after* `ready` by a separate background DBOS workflow on a singleton-concurrency queue (`wikidata_enrichment`, `concurrency=1`). It tries `MBID → Wikidata` via MusicBrainz external links first (local DB, no network) and falls back to the Wikidata API only when needed. Per-entity, deduplicated globally — common names get enriched once across all episodes.

See the [full pipeline documentation](doc/README.md) for per-step details, the download-agent cascade, and entity types.

## Documentation

Detailed documentation lives in the [`doc/`](doc/) directory:

- [Full pipeline documentation](doc/README.md) — per-step details, the download-agent cascade, entity types
- [How Scott works](doc/README.md#how-scott-works) — RAG architecture and query flow
- [Telemetry (OpenTelemetry)](doc/README.md#telemetry-opentelemetry) — tracing setup, collectors (console, Jaeger, Langfuse)
- [Architecture diagrams](doc/architecture/) — processing pipeline diagram
- [Feature documentation](doc/features/) — per-feature docs with problem, changes, and verification
- [Plans](doc/plans/) — implementation plans
- [Session transcripts](doc/sessions/) — planning and implementation session logs

## Getting Started

### Prerequisites

- [Python 3.13+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/)
- [Node.js](https://nodejs.org/) (for the frontend dev server and build)
- [Docker](https://docs.docker.com/get-docker/) (for PostgreSQL and Qdrant)
- [ffmpeg](https://ffmpeg.org/) (for audio downsampling)
- [wget](https://www.gnu.org/software/wget/) (for audio downloading)

### Installation

```bash
git clone <repo-url>
cd ragtime
uv sync                           # Install dependencies
```

Optional dependency group:

| Extra | Install command | Description |
|-------|----------------|-------------|
| `langfuse` | `uv sync --extra langfuse` | [Langfuse collector for telemetry](doc/README.md#telemetry-opentelemetry) |

### Configuration

Launch the interactive setup wizard for all `RAGTIME_*` env vars:

```bash
uv run python manage.py configure
```

Alternatively, copy [`.env.sample`](.env.sample) to `.env` and fill in your values.

The service variables are read by [`docker-compose.yml`](docker-compose.yml) when the containers start, so the values you set here flow straight through:

- `RAGTIME_DB_NAME`, `RAGTIME_DB_USER`, `RAGTIME_DB_PASSWORD`, `RAGTIME_DB_PORT` → Postgres (defaults: `ragtime` / port `5432`).
- `RAGTIME_QDRANT_PORT` → Qdrant published HTTP port (default: `6333`).

Defaults are used if the variables are unset, so a fresh clone runs with zero configuration.

### Running the services

Start PostgreSQL and Qdrant, apply migrations, create an admin account, and start the application:

```bash
docker compose up -d                      # Start PostgreSQL and Qdrant (both read ports/creds from .env)
uv run python manage.py migrate
uv run python manage.py createsuperuser   # Create an admin user for the Django admin UI
uv run python manage.py load_entity_types # Seed initial entity types
```

#### MusicBrainz database

The foreground entity-resolution step queries a local [MusicBrainz](https://musicbrainz.org/) database to map extracted names to canonical MBIDs in sub-millisecond DB queries (instead of rate-limited Wikidata API calls). One-time import via [`musicbrainz-database-setup`](https://github.com/rafacm/musicbrainz-database-setup):

```bash
# Create an empty 'musicbrainz' database next to the 'ragtime' database.
docker compose exec postgres createdb -U ragtime musicbrainz

# One-shot import — runs the upstream CLI directly from GitHub via uvx,
# downloads the latest MusicBrainz dump, creates the schema, and streams
# COPY for every table. ~30+ minutes depending on disk speed. Resumable.
uvx --from git+https://github.com/rafacm/musicbrainz-database-setup \
  musicbrainz-database-setup run \
  --db postgresql://ragtime:ragtime@localhost:5432/musicbrainz \
  --modules core \
  --latest
```

See [MusicBrainz database](doc/README.md#musicbrainz-database) in the docs for why it's needed, configuration via `RAGTIME_MUSICBRAINZ_*`, optional modules, and tuning tips.

#### Application server (ASGI)

```bash
uv run uvicorn ragtime.asgi:application --host 127.0.0.1 --port 8000
```

The application runs under ASGI via Uvicorn. This is required because Scott's chat endpoint (`/chat/agent/`) uses HTTP+SSE streaming through an ASGI sub-app mounted in `ragtime/asgi.py`. All other routes (admin, episodes, pages) are served by the same process through Django's standard ASGI handler.

> **Note:** `manage.py runserver` still works for non-Scott development (admin, episodes, ingestion pipeline) but does not load the ASGI dispatcher, so the chat endpoint will not function.

#### Frontend dev server (Vite)

```bash
cd frontend && npm install   # First time only
cd frontend && npm run dev   # Vite dev server with HMR on port 5173
```

The Scott chat UI is a React application ([assistant-ui](https://www.assistant-ui.com/) + [AG-UI](https://github.com/ag-ui-protocol/ag-ui)) built with [Vite](https://vite.dev/). During development, Vite serves the frontend with hot module replacement. In production, run `npm run build` and the compiled assets are served by Django via [django-vite](https://github.com/MrBin99/django-vite).

The frontend communicates with the ASGI server over HTTP+SSE (AG-UI protocol), so both the Uvicorn server and the Vite dev server must be running to develop the chat UI.

#### Telemetry (optional)

RAGtime uses OpenTelemetry to trace pipeline steps and LLM calls. The quickest local setup is [Jaeger](https://www.jaegertracing.io/):

```bash
docker run -d --name jaeger -p 4318:4318 -p 16686:16686 jaegertracing/all-in-one:latest
```

Then set `RAGTIME_OTEL_COLLECTORS=jaeger` in `.env`. Traces are viewable at `http://localhost:16686`. See [Telemetry (OpenTelemetry)](doc/README.md#telemetry-opentelemetry) for all collector options (console, Jaeger, Langfuse).

#### Resetting the database

To drop all data and start fresh:

```bash
uv run python manage.py dbreset            # Drop PostgreSQL DB (incl. DBOS tables) + Qdrant collection
uv run python manage.py migrate            # Recreate tables
uv run python manage.py load_entity_types  # Seed entity types
uv run python manage.py createsuperuser    # Recreate the admin account (interactive)
```

Or non-interactively:

```bash
DJANGO_SUPERUSER_PASSWORD=admin uv run python manage.py createsuperuser --username admin --email admin@example.com --noinput
```

## Tech Stack

- **Runtime**: [Python 3.13](https://www.python.org/)
- **Framework**: [Django 5.2](https://www.djangoproject.com/)
- **Database**: [PostgreSQL 17](https://www.postgresql.org/) (via [Docker Compose](https://docs.docker.com/compose/))
- **Vector Store**: [Qdrant](https://qdrant.tech/) (via [Docker Compose](https://docs.docker.com/compose/))
- **Durable Workflows**: [DBOS Transact](https://docs.dbos.dev/) (PostgreSQL-backed durable execution)
- **AI Agents**: [Pydantic AI](https://ai.pydantic.dev/) (fetch-details agent, download agent)
- **Transcription**: Configurable — [Whisper API](https://platform.openai.com/docs/guides/speech-to-text) (default), local Whisper, etc.
- **LLM**: Configurable — [Claude](https://www.anthropic.com/) (Anthropic), [GPT](https://openai.com/) (OpenAI), etc.
- **Embeddings**: Configurable — must support multilingual models for cross-language retrieval
- **AI Evaluation**: [RAGAS](https://docs.ragas.io/) + [Langfuse](https://langfuse.com/)
- **Frontend**: [React 19](https://react.dev/) + [assistant-ui](https://www.assistant-ui.com/) + [Tailwind CSS 4](https://tailwindcss.com/) via [Vite](https://vite.dev/) + [django-vite](https://github.com/MrBin99/django-vite) (Scott chat UI); [Django templates](https://docs.djangoproject.com/en/5.2/topics/templates/) + [HTMX](https://htmx.org/) (other pages)
- **Package Manager**: [uv](https://docs.astral.sh/uv/)

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
