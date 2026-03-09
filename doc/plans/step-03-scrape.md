# Step 3: Scrape — Extract Episode Metadata via LLM

## Goal

Given an episode URL, fetch the HTML page, clean it, send it to an LLM with a structured prompt, and extract: title, description, published date, image URL, language, and audio URL (MP3). Introduce Django Q2 for async task execution and the full LLM provider abstraction.

## Decisions

| Question | Answer |
|----------|--------|
| Metadata fields | `title`, `description`, `published_at`, `image_url`, `language`, `audio_url` |
| Store cleaned HTML | Yes — `scraped_html` TextField on Episode |
| New status | `scraping` (between `pending` and `downloading`) |
| Incomplete extraction | `needs_review` status — user fills missing fields in admin, then resumes |
| Provider abstraction | Full (`base.py` + `factory.py`), OpenAI first |
| Default LLM model | `gpt-4.1-mini` via `RAGTIME_LLM_MODEL` env var |
| HTTP + HTML cleaning | `httpx` + `beautifulsoup4` |
| Trigger | Auto on episode creation (Django Q2 `async_task`) |
| Prompt location | Python constant in scrape module |

## Architecture

### Signal Flow

```
Episode.save() (new, status=pending)
  → post_save signal
    → django_q async_task(scrape_episode, episode.id)
      → fetch HTML (httpx)
      → clean HTML (beautifulsoup4: strip script/style/nav/footer/etc.)
      → store cleaned HTML on episode.scraped_html
      → call LLM provider with prompt + cleaned HTML
      → parse JSON response
      → if all required fields present:
          → update episode fields, set status=scraping → downloading  (NOT downloading yet — just scraping, next step handles downloading)
          → actually: set status=scraping at start, then on success keep scraping done...
```

Let me clarify the status transitions:

```
pending → scraping        (task starts)
scraping → pending        (success — all fields extracted, ready for next pipeline step)
scraping → needs_review   (incomplete — missing required fields)
needs_review → pending    (user fills fields in admin, triggers re-queue)
scraping → failed         (unrecoverable error — HTTP failure, LLM error, etc.)
```

> **Why back to `pending` on success?** The next pipeline step (Step 4: Download) will pick up episodes in `pending` status that have their metadata populated. Alternatively, we set status to `downloading` directly — but that couples scrape to download. For now, we advance to `downloading` to signal "scrape done, ready for download step." When Step 4 is implemented, it will pick up from `downloading`.

**Revised status transitions:**

```
pending → scraping        (Q2 task starts)
scraping → downloading    (success — all fields extracted)
scraping → needs_review   (LLM returned incomplete/null fields)
needs_review → scraping   (user fills fields in admin + clicks "Reprocess")
scraping → failed         (unrecoverable: HTTP error, LLM API error, timeout)
```

### Provider Abstraction

```
episodes/providers/
├── __init__.py
├── base.py          # Abstract base classes: LLMProvider, TranscriptionProvider, EmbeddingProvider
└── factory.py       # get_llm_provider(), get_transcription_provider(), get_embedding_provider()
└── openai.py        # OpenAILLMProvider (first concrete implementation)
```

**LLMProvider base class** (only methods needed for scrape):

```python
class LLMProvider(ABC):
    @abstractmethod
    def structured_extract(self, system_prompt: str, user_content: str, response_schema: dict) -> dict:
        """Send prompt + content to LLM, get structured JSON back."""
        ...
```

**OpenAI implementation** uses the `openai` Python SDK with `response_format={"type": "json_schema", ...}` for structured output.

### HTML Cleaning Strategy

Strip these tags entirely (including content): `script`, `style`, `noscript`, `iframe`, `svg`, `canvas`, `nav`, `footer`, `header` (site header, not content header).

Keep: `meta`, `title`, `article`, `main`, `p`, `h1`-`h6`, `a`, `img`, `audio`, `source`, `time`, `span`, `div`.

Preserve `<meta>` tags (og:title, og:description, og:image, etc.) — these are rich metadata sources.

Preserve `<a href="...mp3">` and `<audio><source src="...mp3">` — needed for audio URL extraction.

Truncate the cleaned HTML to ~30,000 characters to stay within LLM context limits.

### LLM Prompt

The prompt instructs the LLM to extract structured metadata from the cleaned HTML of a podcast episode page. It returns a JSON object with:

```json
{
  "title": "string or null",
  "description": "string or null",
  "published_at": "YYYY-MM-DD or null",
  "image_url": "absolute URL string or null",
  "language": "ISO 639-1 code or null",
  "audio_url": "absolute URL to MP3 or null"
}
```

The prompt will:
- Emphasize looking at `<meta>` OG/Twitter tags first, then page content
- Ask for absolute URLs (resolve relative URLs against the page URL)
- Ask for ISO 639-1 language codes (en, es, de, sv, etc.)
- Return `null` for fields that cannot be confidently determined

### Django Q2 Setup

- Add `django-q2` to dependencies
- Add `django_q` to `INSTALLED_APPS`
- Configure ORM broker (no Redis needed):

```python
Q_CLUSTER = {
    'name': 'ragtime',
    'workers': 2,
    'timeout': 300,        # 5 min per task
    'retry': 600,          # retry after 10 min
    'orm': 'default',
    'save_limit': 250,
    'ack_failures': True,
    'max_attempts': 1,
    'catch_up': False,
}
```

- Run worker with: `uv run python manage.py qcluster`

### Admin Changes

**List view:** Add `title` and `language` to `list_display`.

**Detail view:**
- Metadata fields (`title`, `description`, `published_at`, `image_url`, `language`, `audio_url`) are read-only when status is NOT `needs_review`.
- When status is `needs_review`, metadata fields become editable.
- Add a custom admin action: **"Reprocess episode"** — sets status back to `scraping` and queues a new Q2 task (skipping the HTML fetch, using stored `scraped_html` if the user only filled in missing fields; or re-fetching if they want).
- Actually simpler: the action **"Resume processing"** sets status to `pending` and re-queues the scrape task. The scrape task checks if fields are already populated and skips re-extraction for those.
- `scraped_html` shown as a collapsible read-only field for debugging.

**Revised admin action:** A single **"Reprocess"** button/action that:
1. Sets status to `scraping`
2. Queues `scrape_episode` task via Q2
3. The task checks: if all required fields are now present (user filled them), skip LLM call, advance to `downloading`
4. If still missing fields, re-run LLM extraction (using stored HTML if available)

**Django Q2 admin:** Django Q2 provides its own admin views for `OrmQ` (queued tasks), `Success`, and `Failure` models — these are automatically visible when `django_q` is in `INSTALLED_APPS`.

## Implementation Steps

### 1. Add dependencies to `pyproject.toml`

```
django-q2>=1.7,<2
openai>=1.0,<2
httpx>=0.27,<1
beautifulsoup4>=4.12,<5
python-dotenv>=1.0,<2
```

### 2. Configure settings

- Load `.env` with `python-dotenv` at top of `settings.py`
- Add `django_q` to `INSTALLED_APPS`
- Add `Q_CLUSTER` configuration
- Add `RAGTIME_*` settings from env vars:
  - `RAGTIME_LLM_PROVIDER` (default: `openai`)
  - `RAGTIME_LLM_API_KEY` (required)
  - `RAGTIME_LLM_MODEL` (default: `gpt-4.1-mini`)

### 3. Update Episode model

Add fields:
- `title = models.CharField(max_length=500, blank=True, default="")`
- `description = models.TextField(blank=True, default="")`
- `published_at = models.DateField(null=True, blank=True)`
- `image_url = models.URLField(max_length=2000, blank=True, default="")`
- `language = models.CharField(max_length=10, blank=True, default="")`
- `audio_url = models.URLField(max_length=2000, blank=True, default="")`
- `scraped_html = models.TextField(blank=True, default="")`

Add statuses:
- `SCRAPING = "scraping"` (after PENDING)
- `NEEDS_REVIEW = "needs_review"` (after FAILED)

Update `max_length` on status field to accommodate `needs_review` (12 chars — current max_length=20 is fine).

Update `__str__` to return `self.title or self.url`.

### 4. Create provider abstraction

- `episodes/providers/__init__.py`
- `episodes/providers/base.py` — `LLMProvider` ABC with `structured_extract()` method
- `episodes/providers/openai.py` — `OpenAILLMProvider` using OpenAI SDK structured outputs
- `episodes/providers/factory.py` — `get_llm_provider()` reads `RAGTIME_LLM_PROVIDER` setting

### 5. Implement scrape logic

- `episodes/scraper.py`:
  - `fetch_html(url: str) -> str` — httpx GET with reasonable timeout and User-Agent
  - `clean_html(raw_html: str) -> str` — BeautifulSoup strip/clean, truncate
  - `SCRAPE_PROMPT` — system prompt constant
  - `SCRAPE_SCHEMA` — JSON schema for response format
  - `scrape_episode(episode_id: int)` — main task function:
    1. Load episode, set status to `scraping`
    2. If `scraped_html` empty: fetch + clean + store
    3. Check which fields are already populated (user may have filled some)
    4. If all required fields present: advance to `downloading`, return
    5. Call LLM with prompt + HTML
    6. Parse response, update episode fields
    7. If all required fields now present: advance to `downloading`
    8. Else: set status to `needs_review`
    9. On any exception: set status to `failed`

### 6. Add Django signal for auto-trigger

- `episodes/signals.py`:
  - `post_save` on Episode: if created and status is `pending`, queue `scrape_episode`
- `episodes/apps.py`: connect signal in `ready()`

### 7. Update admin

- Make metadata fields conditionally editable (editable when `needs_review`)
- Add "Reprocess" admin action
- Show `scraped_html` as collapsible read-only
- Ensure Django Q2 admin models are visible

### 8. Generate and apply migration

```bash
uv run python manage.py makemigrations episodes
uv run python manage.py migrate
```

### 9. Update README.md

Change Step 3 status from `downloading` to `scraping` in the pipeline table.

### 10. Write tests

- **Model tests:** New fields, new statuses, `__str__` with title
- **Scraper tests:**
  - `clean_html` strips scripts/styles, preserves meta/audio tags
  - `scrape_episode` with mocked HTTP + LLM: success path → status `downloading`
  - `scrape_episode` with incomplete LLM response → status `needs_review`
  - `scrape_episode` with HTTP error → status `failed`
- **Admin tests:**
  - Fields editable in `needs_review` status
  - Reprocess action queues task
- **Signal tests:**
  - Creating episode triggers async task
  - Updating episode does NOT re-trigger

## Files Modified/Created

| File | Change |
|------|--------|
| `pyproject.toml` | Add django-q2, openai, httpx, beautifulsoup4, python-dotenv |
| `ragtime/settings.py` | Load .env, add django_q, Q_CLUSTER config, RAGTIME_* settings |
| `episodes/models.py` | Add metadata fields, scraped_html, scraping/needs_review statuses |
| `episodes/providers/__init__.py` | New — package init |
| `episodes/providers/base.py` | New — LLMProvider ABC |
| `episodes/providers/openai.py` | New — OpenAI structured output implementation |
| `episodes/providers/factory.py` | New — provider factory |
| `episodes/scraper.py` | New — HTML fetch, clean, LLM extraction, task function |
| `episodes/signals.py` | New — post_save auto-trigger |
| `episodes/apps.py` | Connect signal in ready() |
| `episodes/admin.py` | Conditional field editing, reprocess action, Q2 visibility |
| `episodes/tests.py` | Tests for scraper, signals, admin changes |
| `episodes/migrations/0002_*.py` | Generated — new fields and statuses |
| `README.md` | Update Step 3 status to `scraping` |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAGTIME_LLM_PROVIDER` | `openai` | LLM backend |
| `RAGTIME_LLM_API_KEY` | — (required) | API key for the LLM provider |
| `RAGTIME_LLM_MODEL` | `gpt-4.1-mini` | Model to use for structured extraction |

## Running

```bash
# Terminal 1: Django dev server
uv run python manage.py runserver

# Terminal 2: Django Q2 worker
uv run python manage.py qcluster
```

## Verification

1. Start dev server and Q2 worker
2. In admin, create a new Episode with a podcast URL
3. Episode status should change: `pending` → `scraping` → `downloading` (or `needs_review`)
4. Check admin detail view: metadata fields populated
5. If `needs_review`: edit missing fields, click "Reprocess", verify it advances to `downloading`
6. Check Django Q2 admin: task visible in Success or Failure tables
7. Run `uv run python manage.py test episodes` — all tests pass
