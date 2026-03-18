<div align="center">
  <picture>
    <img src="ragtime.svg" alt="RAGtime -- Retrieval Augmented Generation (RAG) in the Key of Jazz" width="100%">
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

## Status

> RAGtime is under active development.

### What's already implemented

- **Episode ingestion**: submit episodes by URL, metadata scraping, audio download, transcription, summarization,  chunking, entity extraction and resolution with [Wikidata](https://www.wikidata.org/) integration.
- **Episode management UI**: Django admin interface to view episode status and metadata and browse extracted entities.
- **Configuration wizard**: interactive `manage.py configure` command for all `RAGTIME_*` env vars.
- **LLM observability**: optional [Langfuse](https://langfuse.com) integration for tracing and monitoring LLM calls across the pipeline.

### What's coming

- **Embed step** (pipeline step 9): generate multilingual embeddings for transcript chunks and store them in [ChromaDB](https://www.trychroma.com/).
- **Scott — the RAG chatbot** (pipeline step 10 + chat app): conversational agent that answers questions strictly from ingested content, with episode/timestamp references, multilingual support, and streaming responses.

See [CHANGELOG.md](CHANGELOG.md) for the full list of implemented features, fixes, implementation plans, feature documentation and session transcripts.

## Processing Pipeline

Each step is a standalone module (`episodes/<step>.py`) that updates the episode's `status` field when it completes. A [`post_save` signal](episodes/signals.py) watches for status changes and dispatches the next step as an async [Django Q2](https://django-q2.readthedocs.io/) task — no central orchestrator needed. Any failure sets `status` to `failed` and halts the chain.

```
📥 Submit  → 🕷️ Scrape  → ⬇️ Download  → 🎙️ Transcribe → 📋 Summarize
                                                            ↓
✅ Ready   ← 📐 Embed   ← 🧩 Resolve   ← 🔍 Extract    ← ✂️ Chunk
```

### Steps

#### 1. 📥 Submit (status: `pending`)

User submits an episode page URL. Duplicate URLs are rejected.

#### 2. 🕷️ Scrape (status: `scraping`)

Extract metadata (title, description, date, image, audio URL) and detect language via LLM-based structured extraction. Episodes with missing required fields (title or audio URL) are flagged for manual review (`needs_review`).

#### 3. ⬇️ Download (status: `downloading`)

Download the audio file and extract duration.

#### 4. 🎙️ Transcribe (status: `transcribing`)

Send audio to the Whisper API (or a local Whisper-compatible endpoint) for transcription, producing segment and word-level timestamps in the detected language. Files that exceed the configurable size limit (default 25 MB) are [adaptively downsampled](doc/features/adaptive-audio-resize-tiers.md) with ffmpeg — the gentlest settings that fit are chosen based on episode duration, from 128 kbps for slightly oversized files down to 32 kbps for very long episodes.

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

**Entity types** (musician, musical group, album, composed musical work, music venue, recording session, record label, year, historical period, city, country, music genre, musical instrument, role) are stored in the database and managed via Django admin. Each entity type has a **[Wikidata](https://www.wikidata.org/) class Q-ID** (e.g., [Q639669](https://www.wikidata.org/wiki/Q639669) for "musician") used for candidate lookup during resolution. An initial set of 14 types is defined in [`episodes/initial_entity_types.yaml`](episodes/initial_entity_types.yaml) — load them with:

```
uv run python manage.py load_entity_types
```

New types can be added through Django admin; existing types can be deactivated (set `is_active = False`) to exclude them from future extractions without deleting historical data. Types that have existing entities cannot be deleted (protected by referential integrity).

#### 8. 🧩 Resolve entities (status: `resolving`)

**Entity Linking (NEL)** — maps extracted mentions to canonical entity records, deduplicating across chunks.

Aggregates all extracted names across every chunk, then resolves **once per entity type** using LLM-based fuzzy matching against two sources:

1. **Existing DB records** — prevents duplicates when the same entity was seen in a previous episode.
2. **[Wikidata](https://www.wikidata.org/) candidates** — searches by name and type, presenting candidates (with Q-IDs and descriptions) to the LLM for confirmation. Matched entities receive a `wikidata_id` for canonical identification.

**Example** — continuing from the extract step, suppose the episode's chunks collectively mention "Bird", "Charlie Parker", "Yardbird", and "Dizzy Gillespie":

| Extracted mentions | Resolved to (canonical entity) | Wikidata ID |
|---|---|---|
| Bird, Charlie Parker, Yardbird | Charlie Parker | [Q103767](https://www.wikidata.org/wiki/Q103767) |
| Dizzy Gillespie | Dizzy Gillespie | [Q49575](https://www.wikidata.org/wiki/Q49575) |

All three surface forms collapse into a single `Entity` record for Charlie Parker. An `EntityMention` is created for each (entity, chunk) pair, preserving which chunks mentioned the entity and the context of each mention.

This two-phase design (extract then resolve) is intentional: extraction is cheap and parallelizable per chunk, while resolution requires cross-chunk aggregation and knowledge base lookups. It also allows re-running resolution independently — e.g., after improving matching logic — without re-extracting.

Search Wikidata from the CLI with:

```
uv run python manage.py lookup_entity "Miles Davis"
uv run python manage.py lookup_entity --type artist "Miles Davis"
```

#### 9. 📐 Embed (status: `embedding`)

Generate multilingual embeddings for transcript chunks and store in [ChromaDB](https://www.trychroma.com/).

#### 10. ✅ Ready (status: `ready`)

Episode fully processed and available for Scott to query.

## How Scott Works

Scott is a strict RAG (Retrieval-Augmented Generation) agent:

1. User asks a question in any language
2. The question is embedded using the configured multilingual embedding model
3. Relevant transcript chunks are retrieved from ChromaDB
4. The LLM generates an answer strictly from the retrieved content
5. The response includes references to specific episodes and timestamps
6. If no relevant content exists, Scott says so — no hallucinated answers

Scott responds in the user's language, regardless of the source episode's language. Cross-language retrieval is handled by multilingual embeddings.

## Getting Started

### Prerequisites

- [Python 3.13+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/) (for audio downsampling)
- [wget](https://www.gnu.org/software/wget/) (for audio downloading)

### Installation

```
git clone <repo-url>
cd ragtime
uv sync
uv run python manage.py migrate

# Seed initial entity types
uv run python manage.py load_entity_types

# Interactive setup wizard for RAGTIME_* env vars
uv run python manage.py configure

# Start the web server
uv run python manage.py runserver

# Start the Django Q2 task worker (separate terminal)
uv run python manage.py qcluster
```

### Configuration

You can run `uv run python manage.py configure` to launch an interactive setup wizard for all `RAGTIME_*` env vars.

Alternatively, copy [`.env.sample`](.env.sample) to `.env` and fill in your values.

## LLM Observability (Langfuse)

RAGtime optionally integrates with [Langfuse](https://langfuse.com) to trace all LLM calls across the pipeline. When enabled, every OpenAI API call is captured with prompts, completions, token usage, latency, and cost — grouped by `ProcessingRun`.

### What is traced

| Pipeline step | Function | LLM calls |
|---|---|---|
| Scrape | `scrape_episode` | Structured metadata extraction |
| Transcribe | `transcribe_episode` | Whisper API transcription |
| Summarize | `summarize_episode` | Summary generation |
| Extract | `extract_entities` | Per-chunk entity extraction |
| Resolve | `resolve_entities` | Entity resolution against DB |

### Setup

1. Install the optional dependency:
   ```
   uv sync --extra observability
   ```

2. Run Langfuse locally via Docker Compose.

   See [this walk through guide](https://langfuse.com/self-hosting/deployment/docker-compose).

3. Configure via the wizard or `.env`:
   ```
   uv run python manage.py configure
   ```
   Or set these variables in `.env`:
   ```
   RAGTIME_LANGFUSE_ENABLED=true
   RAGTIME_LANGFUSE_SECRET_KEY=sk-lf-...
   RAGTIME_LANGFUSE_PUBLIC_KEY=pk-lf-...
   RAGTIME_LANGFUSE_HOST=http://localhost:3000
   ```

4. Process an episode and view traces at `http://localhost:3000`.

When disabled (the default), Langfuse is never imported and there is zero overhead.

## Tech Stack

- **Runtime**: Python 3.13
- **Framework**: Django 5.2
- **Database**: SQLite
- **Vector Store**: ChromaDB
- **Task Queue**: Django Q2
- **Transcription**: Configurable — Whisper API (default), local Whisper, etc.
- **LLM**: Configurable — Claude (Anthropic), GPT (OpenAI), etc.
- **Embeddings**: Configurable — must support multilingual models for cross-language retrieval
- **Frontend**: Django templates + HTMX + Tailwind CSS
- **Package Manager**: uv

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
