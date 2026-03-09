# Step 3: Scrape — Extract Episode Metadata via LLM

## Problem

After an episode URL is submitted and dedup passes, the system needs to extract metadata (title, description, date, image, language, audio URL) from the episode's web page. This must happen asynchronously to avoid blocking the admin interface, and should gracefully handle cases where the LLM cannot extract all required fields.

## Changes

- **Episode model** — Added seven new fields: `title`, `description`, `published_at`, `image_url`, `language`, `audio_url`, and `scraped_html`. Added two new statuses: `scraping` and `needs_review`.
- **Provider abstraction** — Introduced `episodes/providers/` package with abstract base classes (`LLMProvider`, `TranscriptionProvider`, `EmbeddingProvider`), an OpenAI concrete implementation using structured outputs (Responses API with JSON schema), and a factory that reads Django settings.
- **Scraper module** — `episodes/scraper.py` handles HTML fetching (httpx), cleaning (BeautifulSoup strips script/style/nav/footer tags, truncates to 30k chars), and LLM-based metadata extraction. The `scrape_episode` task function orchestrates the full flow.
- **Django Q2 integration** — Added as async task queue with ORM broker. Episodes are automatically queued for scraping on creation via a `post_save` signal. Task history is visible in the Django admin (Success/Failure tables).
- **Admin enhancements** — Metadata fields are conditionally editable (only when status is `needs_review`). A "Reprocess" admin action re-queues selected episodes for scraping. Cleaned HTML is shown in a collapsible debug section.
- **Settings** — Added `python-dotenv` for `.env` file loading, Django Q2 cluster configuration, and `RAGTIME_LLM_*` settings.

### Status transitions

```
pending → scraping → downloading     (happy path: all required fields extracted)
                   → needs_review    (incomplete: title or audio_url missing)
                   → failed          (HTTP error, LLM API error)
needs_review → scraping → downloading (user fills fields + clicks "Reprocess")
```

### Smart re-processing

When reprocessing after `needs_review`:
1. If `scraped_html` is already stored, the HTTP fetch is skipped.
2. If the user has filled all required fields (`title` + `audio_url`), the LLM call is skipped entirely and the episode advances to `downloading`.
3. Otherwise, the LLM re-extracts from the cached HTML, only updating empty fields.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `MAX_HTML_LENGTH` | 30,000 chars | Fits within LLM context limits while preserving most page content |
| `REQUIRED_FIELDS` | `title`, `audio_url` | Minimum fields needed to proceed to download step |
| HTTP timeout | 30 seconds | Generous for slow podcast sites |
| Q2 task timeout | 300 seconds (5 min) | Accounts for LLM API latency |
| Q2 retry | 600 seconds (10 min) | Allows API rate limits to clear |
| Q2 max_attempts | 1 | Avoids repeated LLM costs on persistent failures |
| Default LLM model | `gpt-4.1-mini` | Cost-effective for structured extraction |

## Verification

```bash
# 1. Set environment variable
echo 'RAGTIME_LLM_API_KEY=sk-...' >> .env

# 2. Apply migrations
uv run python manage.py migrate

# 3. Start dev server + Q2 worker
uv run python manage.py runserver      # Terminal 1
uv run python manage.py qcluster      # Terminal 2

# 4. In admin, add a new episode with a podcast URL
# 5. Observe: status changes pending → scraping → downloading (or needs_review)
# 6. Check metadata fields are populated
# 7. If needs_review: edit missing fields, select episode, run "Reprocess" action
# 8. Check Django Q2 admin: Successful tasks / Failed tasks

# Run tests
uv run python manage.py test episodes
```

Expected: 25 tests pass. Episodes with valid podcast URLs get metadata extracted. Episodes with unparseable pages get `needs_review` status.

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Added django-q2, openai, httpx, beautifulsoup4, python-dotenv |
| `ragtime/settings.py` | dotenv loading, `django_q` in INSTALLED_APPS, Q_CLUSTER config, RAGTIME_LLM_* settings |
| `episodes/models.py` | Added metadata fields, scraped_html, scraping/needs_review statuses |
| `episodes/providers/__init__.py` | New — package init |
| `episodes/providers/base.py` | New — LLMProvider, TranscriptionProvider, EmbeddingProvider ABCs |
| `episodes/providers/openai.py` | New — OpenAI structured output implementation |
| `episodes/providers/factory.py` | New — get_llm_provider() factory |
| `episodes/scraper.py` | New — HTML fetch/clean, LLM extraction prompt/schema, scrape_episode task |
| `episodes/signals.py` | New — post_save auto-queues scrape on episode creation |
| `episodes/apps.py` | Signal registration in ready() |
| `episodes/admin.py` | Conditional field editing, fieldsets, "Reprocess" action |
| `episodes/tests.py` | 25 tests covering model, HTML cleaning, scrape task, signals, admin |
| `episodes/migrations/0002_*.py` | New fields and status choices migration |
| `README.md` | Step 3 status updated to `scraping`, added RAGTIME_LLM_MODEL env var |
