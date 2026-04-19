"""System registry, env I/O, and prompt utilities for the configure command."""

import getpass

SYSTEMS = [
    {
        "name": "Database",
        "description": "PostgreSQL connection (defaults match docker-compose.yml)",
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
        "description": "Scraping, summarization, extraction, resolution, and translation",
        "shareable": True,
        "subsystems": [
            {
                "prefix": "RAGTIME_SCRAPING",
                "label": "Scraping",
                "fields": [
                    ("PROVIDER", "openai", False),
                    ("API_KEY", "", True),
                    ("MODEL", "gpt-4.1-mini", False),
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
        "description": "Qdrant vector database (defaults match docker-compose.yml)",
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
        "name": "Wikidata",
        "description": "Entity lookup via Wikidata API",
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
        "name": "Recovery",
        "description": "Automatic recovery for pipeline failures",
        "shareable": False,
        "subsystems": [
            {
                "prefix": "RAGTIME_RECOVERY",
                "label": "Recovery",
                "fields": [
                    ("AGENT_ENABLED", "false", False),
                    ("AGENT_API_KEY", "", True),
                    ("AGENT_MODEL", "openai:gpt-4.1-mini", False),
                    ("AGENT_TIMEOUT", "120", False),
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
