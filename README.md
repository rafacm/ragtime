<div align="center">
  <picture>
    <img src="ragtime.png" alt="RAGtime -- Retrieval Augmented Generation (RAG) in the Key of Jazz" width="100%">
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
- 🔍 **Entity Extraction** — Identifies jazz entities: artists, bands, albums, venues, recording sessions, record labels, years. Entities are resolved against existing records using LLM-based matching.
- 📇 **Episode Indexing** — Splits transcripts into segments and generates multilingual embeddings stored in ChromaDB. Enables cross-language semantic search so Scott can retrieve relevant content regardless of the question's language.
- 🎷 **Scott — Your Jazz AI** — A conversational agent that answers questions strictly from ingested episode content. Scott responds in the user's language and provides references to specific episodes and timestamps. Responses stream in real-time.

## Processing Pipeline

Each episode goes through the following steps, with status tracked throughout:

| Step | Description | Status |
|------|-------------|--------|
| 1. Submit | User submits an episode page URL | `pending` |
| 2. Dedup | Check if episode URL already exists | `pending` |
| 3. Scrape | Extract metadata (title, description, date, image) + detect language | `scraping` |
| 4. Download | Find and download the audio file | `downloading` |
| 5. Resize | If audio > 25MB, downsample with ffmpeg | `downloading` |
| 6. Transcribe | Whisper transcription with detected language, segment + word timestamps | `transcribing` |
| 7. Summarize | LLM-generated episode summary | `summarizing` |
| 8. Extract | LLM-based entity extraction (artists, albums, venues, etc.) | `extracting` |
| 9. Resolve | LLM-based entity resolution against existing entities in DB | `deduplicating` |
| 10. Chunk | Split transcript by Whisper segments | `embedding` |
| 11. Embed | Generate multilingual embeddings and store in ChromaDB | `embedding` |
| 12. Ready | Episode available for Scott to reference | `ready` |

Any step failure marks the episode as `failed`.

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

- Python 3.13+
- uv
- ffmpeg (for audio downsampling)

### Installation

```
git clone <repo-url>
cd ragtime
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

### Configuration

Set the following environment variables (or use a `.env` file):

- `RAGTIME_LLM_PROVIDER` — LLM provider (`anthropic`, `openai`, etc.)
- `RAGTIME_LLM_API_KEY` — API key for the LLM provider
- `RAGTIME_LLM_MODEL` — LLM model name (default: `gpt-4.1-mini`)
- `RAGTIME_TRANSCRIPTION_PROVIDER` — Transcription backend (`whisper_api`, `whisper_local`, etc.)
- `RAGTIME_TRANSCRIPTION_API_KEY` — API key for transcription (if using API)
- `RAGTIME_EMBEDDING_PROVIDER` — Embedding provider
- `RAGTIME_EMBEDDING_API_KEY` — API key for embeddings (if using API)
- `RAGTIME_VECTOR_STORE` — Vector store backend (`chroma`, etc.)
- `RAGTIME_CHROMA_HOST` — ChromaDB server host (default: `localhost`, omit for embedded/local mode)
- `RAGTIME_CHROMA_PORT` — ChromaDB server port (default: `8000`)
- `RAGTIME_CHROMA_COLLECTION` — ChromaDB collection name (default: `ragtime`)

## Features & Fixes

| Date | Description | Details |
|------|-------------|---------|
| 2026-03-09 | Step 1: Submit Episode — Django project bootstrap, Episode model with status tracking, admin interface | [plan](doc/plans/step-01-submit-episode.md), [feature](doc/features/step-01-submit-episode.md), [session](doc/sessions/2026-03-09-step-01-submit-episode.md) |
| 2026-03-09 | Step 2: Dedup — Duplicate episode detection via unique URL constraint at database level | [plan](doc/plans/step-02-dedup.md), [feature](doc/features/step-02-dedup.md), [session](doc/sessions/2026-03-09-step-02-dedup.md) |
| 2026-03-09 | Step 3: Scrape — LLM-based metadata extraction with Django Q2 async tasks, provider abstraction, and needs_review workflow | [plan](doc/plans/step-03-scrape.md), [feature](doc/features/step-03-scrape.md), [session](doc/sessions/2026-03-09-step-03-scrape.md) |
| 2026-03-09 | Steps 4 & 5: Download & Resize — Audio download with streaming, ffmpeg downsampling for Whisper API limit, error tracking | [plan](doc/plans/step-04-05-download-resize.md), [feature](doc/features/step-04-05-download-resize.md), [session](doc/sessions/2026-03-09-step-04-05-download-resize.md) |
| 2026-03-10 | CI: GitHub Actions — Automated test suite on PRs and pushes to main, README badges for build status, Python, Django, license | [feature](doc/features/ci-github-actions.md), [session](doc/sessions/2026-03-10-ci-github-actions.md) |

## Built with AI

This project was developed with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and reviewed by [Codex](https://openai.com/index/introducing-codex/).

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
