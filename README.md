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
- 🔍 **Entity Extraction** — Identifies jazz entities: artists, bands, albums, venues, recording sessions, record labels, years. Entities are resolved against existing records using LLM-based matching.
- 📇 **Episode Indexing** — Splits transcripts into segments and generates multilingual embeddings stored in ChromaDB. Enables cross-language semantic search so Scott can retrieve relevant content regardless of the question's language.
- 🎷 **Scott — Your Jazz AI** — A conversational agent that answers questions strictly from ingested episode content. Scott responds in the user's language and provides references to specific episodes and timestamps. Responses stream in real-time.

## Processing Pipeline

Each episode goes through the following steps, with status tracked throughout:

1. 📥 **Submit** (status: `pending`): User submits an episode page URL.
2. 🔁 **Dedup** (status: `pending`): Check if episode URL already exists.
3. 🕷️ **Scrape** (status: `scraping`): Extract metadata (title, description, date, image) + detect language.
4. ⬇️ **Download** (status: `downloading`): Find and download the audio file.
5. 🔊 **Resize** (status: `resizing`): If audio > 25MB, downsample with ffmpeg.
6. 🎙️ **Transcribe** (status: `transcribing`): Whisper transcription with detected language, segment + word timestamps.
7. 📋 **Summarize** (status: `summarizing`): LLM-generated episode summary.
8. ✂️ **Chunk** (status: `chunking`): Split transcript by Whisper segments.
9. 🔍 **Extract** (status: `extracting`): LLM-based entity extraction. Entity types (artist, band, album, composition, venue, recording session, label, year, era, city, country, sub-genre, instrument, role) are stored in the database and managed via Django admin. An initial set of 14 types is defined in [`episodes/initial_entity_types.yaml`](episodes/initial_entity_types.yaml) — load them with `uv run python manage.py load_entity_types`. New types can be added through Django admin; existing types can be deactivated (set `is_active = False`) to exclude them from future extractions without deleting historical data. Types that have existing entities cannot be deleted (protected by referential integrity).
10. 🧩 **Resolve** (status: `resolving`): LLM-based entity resolution against existing entities in DB.
11. 📐 **Embed** (status: `embedding`): Generate multilingual embeddings and store in ChromaDB.
12. ✅ **Ready** (status: `ready`): Episode available for Scott to reference.

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
uv run python manage.py load_entity_types   # Seed initial entity types
uv run python manage.py configure            # Interactive setup wizard for RAGTIME_* env vars
uv run python manage.py runserver
```

### Configuration

You can run `uv run python manage.py configure` to launch an interactive setup wizard for all `RAGTIME_*` env vars.

Alternatively, copy [`.env.sample`](.env.sample) to `.env` and fill in your values.

## Changelog

This project was developed with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and reviewed by [Codex](https://openai.com/index/introducing-codex/). See [CHANGELOG.md](CHANGELOG.md) for the full list of implemented features, fixes, implementation plans, feature documentation and session transcripts.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
