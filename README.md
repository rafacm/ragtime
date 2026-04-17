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

## Features

- 🎙️ **Episode Ingestion** — Add podcast episodes by URL. RAGtime scrapes metadata (title, description, date, image), downloads audio, and processes it through the pipeline.
- 📝 **Multilingual Transcription** — Transcribes episodes using configurable backends (Whisper API by default) with segment and word-level timestamps. Supports multiple languages (English, Spanish, German, Swedish, etc.).
- 🔍 **Entity Extraction** — Identifies jazz entities: musicians, musical groups, albums, music venues, recording sessions, record labels, years. Entities are resolved against existing records using LLM-based matching.
- 📇 **Episode Indexing** — Splits transcripts into segments and generates multilingual embeddings stored in ChromaDB. Enables cross-language semantic search so Scott can retrieve relevant content regardless of the question's language.
- 🎷 **Scott — Your Jazz AI** — A conversational agent that answers questions strictly from ingested episode content. Scott responds in the user's language and provides references to specific episodes and timestamps. Responses stream in real-time.
- 📊 **AI Evaluation** — Measures pipeline and Scott quality using [RAGAS](https://docs.ragas.io/) (faithfulness, answer relevancy, context precision/recall) with scores tracked in [Langfuse](https://langfuse.com/docs/scores/model-based-evals/ragas).

## Status

> RAGtime is under active development.

### What's already implemented

- **Episode ingestion**: submit episodes by URL, metadata scraping, audio download, transcription, summarization,  chunking, entity extraction and resolution with [Wikidata](https://www.wikidata.org/) integration.
- **Episode management UI**: Django admin interface to view episode status and metadata and browse extracted entities.
- **Configuration wizard**: interactive `manage.py configure` command for all `RAGTIME_*` env vars.
- **Telemetry**: [OpenTelemetry](https://opentelemetry.io/)-based tracing for pipeline steps and LLM calls with optional collectors: console, [Jaeger](https://www.jaegertracing.io/), and [Langfuse](https://langfuse.com).
- **Agent-based recovery**: [Pydantic AI](https://ai.pydantic.dev/) agent with [Playwright](https://playwright.dev/) browser automation recovers from scraping and downloading failures automatically.

See [CHANGELOG.md](CHANGELOG.md) for the full list of implemented features, fixes, implementation plans, feature documentation and session transcripts.

### What's coming

- **LangGraph pipeline**: migrate the Django Q2 signal-based pipeline to a LangGraph `StateGraph` with autonomous step skipping, recovery routing, and resume-from-failure. Adds LangGraph Studio support for local graph visualization.
- **Embed step** (pipeline step 9): generate multilingual embeddings for transcript chunks and store them in [ChromaDB](https://www.trychroma.com/).
- **Scott — the RAG chatbot** (pipeline step 10 + chat app): conversational agent that answers questions strictly from ingested content, with episode/timestamp references, multilingual support, and streaming responses.
- **AI evaluation**: measure pipeline and Scott quality using [RAGAS](https://docs.ragas.io/) (faithfulness, answer relevancy, context precision/recall) with scores tracked in [Langfuse](https://langfuse.com/docs/scores/model-based-evals/ragas). Enables regression testing across prompt and model changes.

## Processing Pipeline

[![Processing Pipeline](doc/architecture/ragtime-processing-pipeline.svg)](https://app.excalidraw.com/s/3Cob4pHK6Ge/3zFsvWxbOWQ)

Each step updates the episode's `status` field. A `post_save` signal dispatches the next step as an async Django Q2 task. Failures with exceptions trigger the [recovery layer](doc/README.md#recovery).

| # | Step | Status | Description |
|---|------|--------|-------------|
| 1 | 📥 Submit | `pending` | User submits an episode URL |
| 2 | 🕷️ Scrape | `scraping` | Extract metadata and detect language |
| 3 | ⬇️ Download | `downloading` | Download audio and extract duration |
| 4 | 🎙️ Transcribe | `transcribing` | Whisper API transcription with timestamps |
| 5 | 📋 Summarize | `summarizing` | LLM-generated episode summary |
| 6 | ✂️ Chunk | `chunking` | Split transcript into ~150-word chunks |
| 7 | 🔍 Extract | `extracting` | Named entity recognition per chunk |
| 8 | 🧩 Resolve | `resolving` | Entity linking and deduplication via Wikidata |
| 9 | 📐 Embed | `embedding` | Multilingual embeddings into ChromaDB |
| 10 | ✅ Ready | `ready` | Episode available for Scott to query |

_Steps 9–10 (Embed, Ready) are planned and not yet implemented._

See the [full pipeline documentation](doc/README.md) for per-step details, entity types, and the recovery layer.

## Documentation

Detailed documentation lives in the [`doc/`](doc/) directory:

- [Full pipeline documentation](doc/README.md) — per-step details, entity types, recovery layer
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
- [Docker](https://docs.docker.com/get-docker/) (for PostgreSQL)
- [ffmpeg](https://ffmpeg.org/) (for audio downsampling)
- [wget](https://www.gnu.org/software/wget/) (for audio downloading)

### Installation

```bash
git clone <repo-url>
cd ragtime
docker compose up -d              # Start PostgreSQL
uv sync                           # Install dependencies
```

Optional dependency group:

| Extra | Install command | Description |
|-------|----------------|-------------|
| `langfuse` | `uv sync --extra langfuse` | [Langfuse collector for telemetry](doc/README.md#telemetry-opentelemetry) |

Set up the database, create an admin account, and start the services:

```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser   # Create an admin user for the Django admin UI
uv run python manage.py load_entity_types # Seed initial entity types
uv run python manage.py configure         # Interactive setup wizard for RAGTIME_* env vars
uv run python manage.py runserver         # Start the web server
uv run python manage.py qcluster          # Start the Django Q2 task worker (separate terminal)
```

To reset the database (drops all data and recreates):

```bash
uv run python manage.py dbreset
uv run python manage.py createsuperuser   # Recreate the admin account
```

### Configuration

You can run `uv run python manage.py configure` to launch an interactive setup wizard for all `RAGTIME_*` env vars.

Alternatively, copy [`.env.sample`](.env.sample) to `.env` and fill in your values.

## Tech Stack

- **Runtime**: [Python 3.13](https://www.python.org/)
- **Framework**: [Django 5.2](https://www.djangoproject.com/)
- **Database**: [PostgreSQL 17](https://www.postgresql.org/) (via [Docker Compose](https://docs.docker.com/compose/))
- **Vector Store**: [ChromaDB](https://www.trychroma.com/)
- **Task Queue**: [Django Q2](https://django-q2.readthedocs.io/)
- **AI Agents**: [Pydantic AI](https://ai.pydantic.dev/) (recovery agent)
- **Transcription**: Configurable — [Whisper API](https://platform.openai.com/docs/guides/speech-to-text) (default), local Whisper, etc.
- **LLM**: Configurable — [Claude](https://www.anthropic.com/) (Anthropic), [GPT](https://openai.com/) (OpenAI), etc.
- **Embeddings**: Configurable — must support multilingual models for cross-language retrieval
- **AI Evaluation**: [RAGAS](https://docs.ragas.io/) + [Langfuse](https://langfuse.com/)
- **Frontend**: [Django templates](https://docs.djangoproject.com/en/5.2/topics/templates/) + [HTMX](https://htmx.org/) + [Tailwind CSS](https://tailwindcss.com/)
- **Package Manager**: [uv](https://docs.astral.sh/uv/)

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
