"""System registry, env I/O, and prompt utilities for the configure command."""

import getpass

# Provider-specific default model suffixes for Convention B subsystems
# (e.g. ``RAGTIME_FETCH_DETAILS_MODEL``) where the model string carries
# the provider as a prefix. When the wizard's shared provider changes,
# the suffix is replaced with the matching default so the user gets a
# valid pair on Enter rather than e.g. ``anthropic:gpt-4.1-mini``.
CONVENTION_B_PROVIDER_DEFAULTS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "google": "gemini-2.5-pro",
}

SYSTEMS = [
    {
        "name": "Database",
        "description": "PostgreSQL connection — docker-compose reads these values",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_DB",
                "label": "Database",
                "fields": [
                    ("NAME", "ragtime", False),
                    ("USER", "ragtime", False),
                    ("PASSWORD", "ragtime", True),
                    ("HOST", "localhost", False),
                    ("PORT", "5432", False),
                ],
            },
        ],
    },
    {
        "name": "LLM",
        "description": "Fetch Details, summarization, extraction, resolution, and translation",
        "shareable": True,
        "subsystems": [
            {
                "prefix": "RAGTIME_FETCH_DETAILS",
                "label": "Fetch Details",
                # Convention B: provider is encoded in the model string prefix,
                # e.g. ``openai:gpt-4.1-mini``. No separate PROVIDER field.
                "fields": [
                    ("API_KEY", "", True),
                    ("MODEL", "openai:gpt-4.1-mini", False),
                ],
            },
            {
                "prefix": "RAGTIME_SUMMARIZATION",
                "label": "Summarization",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "gpt-4.1-mini", False),
                ],
            },
            {
                "prefix": "RAGTIME_EXTRACTION",
                "label": "Extraction",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "gpt-4.1-mini", False),
                ],
            },
            {
                "prefix": "RAGTIME_RESOLUTION",
                "label": "Resolution",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "gpt-4.1-mini", False),
                ],
            },
            {
                "prefix": "RAGTIME_TRANSLATION",
                "label": "Translation",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "gpt-4.1-mini", False),
                ],
            },
        ],
    },
    {
        "name": "Transcription",
        "description": "Audio transcription",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_TRANSCRIPTION",
                "label": "Transcription",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "whisper-1", False),
                ],
            },
        ],
    },
    {
        "name": "Embedding",
        "description": "Chunk embeddings for vector retrieval",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_EMBEDDING",
                "label": "Embedding",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "text-embedding-3-small", False),
                ],
            },
        ],
    },
    {
        "name": "Vector Store (Qdrant)",
        "description": "Qdrant vector database — docker-compose reads RAGTIME_QDRANT_PORT",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_QDRANT",
                "label": "Qdrant",
                "fields": [
                    ("HOST", "localhost", False),
                    ("PORT", "6333", False),
                    ("COLLECTION", "ragtime_chunks", False),
                    ("API_KEY", "", True),
                    ("HTTPS", "false", False),
                ],
            },
        ],
    },
    {
        "name": "Scott (RAG chatbot)",
        "description": "LLM + retrieval settings for Scott, the RAG chat agent",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_SCOTT",
                "label": "Scott",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "gpt-4.1-mini", False),
                    ("TOP_K", "5", False),
                    ("SCORE_THRESHOLD", "0.3", False),
                ],
            },
        ],
    },
    {
        "name": "MusicBrainz",
        "description": "Local MusicBrainz Postgres database for foreground entity resolution (https://github.com/rafacm/musicbrainz-database-setup)",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_MUSICBRAINZ_DB",
                "label": "MusicBrainz DB",
                "fields": [
                    ("HOST", "localhost", False),
                    ("PORT", "5432", False),
                    ("NAME", "musicbrainz", False),
                    ("USER", "ragtime", False),
                    ("PASSWORD", "ragtime", True),
                ],
            },
            {
                "prefix": "RAGTIME_MUSICBRAINZ",
                "label": "MusicBrainz schema",
                "fields": [
                    ("SCHEMA", "musicbrainz", False),
                ],
            },
        ],
    },
    {
        "name": "Pipeline",
        "description": "Episode-pipeline parallelism",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME",
                "label": "Pipeline",
                "fields": [
                    ("EPISODE_CONCURRENCY", "4", False),
                ],
            },
        ],
    },
    {
        "name": "Wikidata",
        "description": "Background entity-enrichment via Wikidata API (foreground uses MusicBrainz)",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_WIKIDATA",
                "label": "Wikidata",
                "fields": [
                    ("USER_AGENT", "RAGtime/0.1 (https://github.com/rafacm/ragtime)", False),
                    ("CACHE_BACKEND", "filebased", False),
                    ("CACHE_TTL", "604800", False),
                    ("DEBOUNCE_MS", "300", False),
                    ("MIN_CHARS", "3", False),
                ],
            },
        ],
    },
    {
        "name": "Download Agent",
        "description": "Playwright + podcast-index agent invoked when wget fails",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_DOWNLOAD_AGENT",
                "label": "Download Agent",
                # Convention B: provider encoded in the model string prefix.
                "fields": [
                    ("API_KEY", "", True),
                    ("MODEL", "openai:gpt-4.1-mini", False),
                    ("TIMEOUT", "120", False),
                ],
            },
        ],
    },
    {
        "name": "Podcast Aggregators",
        "description": "Optional fallback sources for the download agent (apple_podcasts, fyyd, podcastindex)",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME",
                "label": "Aggregators (comma-separated, e.g. apple_podcasts,fyyd)",
                "fields": [
                    ("PODCAST_AGGREGATORS", "", False),
                    ("FYYD_API_KEY", "", True),
                    ("PODCASTINDEX_API_KEY", "", True),
                    ("PODCASTINDEX_API_SECRET", "", True),
                ],
            },
        ],
    },
    {
        "name": "Telemetry",
        "description": "OpenTelemetry tracing with optional collectors (console, jaeger, langfuse)",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_OTEL",
                "label": "OpenTelemetry",
                "fields": [
                    ("COLLECTORS", "", False),
                    ("SERVICE_NAME", "ragtime", False),
                    ("JAEGER_ENDPOINT", "http://localhost:4318", False),
                ],
            },
            {
                "prefix": "RAGTIME_LANGFUSE",
                "label": "Langfuse (when enabled as collector)",
                "fields": [
                    ("SECRET_KEY", "", True),
                    ("PUBLIC_KEY", "", True),
                    ("HOST", "http://localhost:3000", False),
                ],
            },
        ],
    },
]


def read_env(path):
    """Parse a .env file into a key-value dict and a list of raw lines.

    Returns (dict, list[str]). Lines preserve original formatting including
    comments and blank lines. Values have surrounding quotes stripped.
    """
    values = {}
    lines = []
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return values, lines

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        values[key] = value

    return values, lines


def write_env(path, values, original_lines):
    """Write values to a .env file, preserving comments and existing structure.

    Updates existing key=value lines in-place, appends new keys at the end.
    """
    written_keys = set()
    new_lines = []

    for line in original_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in values:
                new_lines.append(f"{key}={values[key]}\n")
                written_keys.add(key)
                continue
        new_lines.append(line)

    # Append new keys not already in the file
    for key, value in values.items():
        if key not in written_keys:
            new_lines.append(f"{key}={value}\n")

    with open(path, "w") as f:
        f.writelines(new_lines)


def mask_secret(value):
    """Mask a secret value, showing only the last 4 characters."""
    if not value:
        return ""
    if len(value) >= 4:
        return "***" + value[-4:]
    return "***"


def prompt_value(label, current, is_secret):
    """Prompt the user for a value, showing the current default.

    Uses getpass for secret values (no echo). Returns current value if
    the user presses Enter without typing.
    """
    if is_secret:
        display = mask_secret(current)
    else:
        display = current

    prompt_text = f"  {label} [{display}]: " if display else f"  {label}: "

    if is_secret:
        value = getpass.getpass(prompt=prompt_text)
    else:
        value = input(prompt_text)

    return value if value else current
