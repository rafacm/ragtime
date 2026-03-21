# Session: Step 3 — Scrape

**Date:** 2026-03-09
**Session ID:** 2bf6969f-4284-41f0-b8f2-0e2ed93eb4b4

## Summary

*(No summary available)*

## Conversation

### User

<ide_selection>The user selected the lines 27 to 27 from /Users/rafa/Develop/projects/ragtime/README.md:
Extract metadata (title, description, date, image) + detect language

This may or may not be related to the current task.</ide_selection>
Let's plan Step 3 - Scrape - Extract metadata (title, description, date, image) + detect language. Ask me any clarifying questions and wait for my approval before proceeding with the implementation. The status of the episode should be changed to `scraping` in the README.md file. For this step we need to introduce Django Q2. Additional requirements are:
- given the URL of the episode, the HTML should be retrieved, cleaned up to strip any non-needed tags like `<script>` and such
- this HTML will be passed to a configurable LLM together with a prompt template and a JSON response format with the expected output
- the implemented logic should handle the case when it was not possible to extract the necessary information and allow the user to manually add the missing information manually.
- once the user has added the information manually, the episode should be further processed
- it should be possible to see the status of the Django Q2 task in the admin interface

### Assistant

Let me review the current state of the project first.

Good overview of the current state. Here are my clarifying questions before planning:

**Metadata & Model:**
1. The Episode model currently only has `url`, `status`, and timestamps. For scrape, I'd add: `title` (CharField), `description` (TextField), `published_at` (DateField), `image_url` (URLField), `language` (CharField, e.g. "en", "es"). Any other fields you want extracted, or adjustments to these?

2. Should we add a `scrape_html` (TextField) to store the cleaned HTML for debugging/re-processing, or discard it after extraction?

**Status:**
3. You want a new `scraping` status added to the Status choices — confirmed. Should it go between `pending` and `downloading` in the enum order?

**LLM Provider:**
4. This is the first step requiring an LLM. Should I implement the full provider abstraction (`episodes/providers/base.py`, `factory.py`) now, or a minimal version just for the scrape step? Which provider to implement first — Anthropic (Claude)?

5. For the LLM model, should it be configurable via env var (e.g. `RAGTIME_LLM_MODEL`)? Any default preference (e.g. `claude-sonnet-4-20250514`)?

**HTML Fetching:**
6. For HTTP requests and HTML cleaning, I'm thinking `httpx` + `beautifulsoup4`. Good with that, or prefer something else?

**Failure & Manual Editing:**
7. When the LLM can't extract some fields, I'm thinking: set status to a new `needs_review` status (or reuse `failed`?), and make the metadata fields editable in the admin. The admin would show a button/action to resume processing once fields are filled. Which approach do you prefer for the status?

**Django Q2:**
8. The scrape step would be the first async task. Should episode submission (saving in admin) automatically trigger the scrape task via Q2, or should there be a manual "Process" admin action?

**Prompt Template:**
9. Should the prompt template live as a Python constant in the codebase, or in a separate file (e.g. `episodes/prompts/scrape.txt`)? I'd lean toward a Python constant for simplicity.

### User

The scraping logic should also extract the URL of the MP3 file for the podcast audio. Update the plan with this information and provide a Markdown template with the answers that you need so I can just copy-paste it and provide my answers.

### Assistant

Here's the template with my suggested defaults — fill in your answers:

```markdown
## Step 3: Scrape — Clarifications

**Metadata & Model:**

1. Fields to extract: `title`, `description`, `published_at`, `image_url`, `language`, `audio_url` (MP3 URL). Add/remove/rename any?
   > 

2. Store cleaned HTML on the Episode model for debugging/re-processing?
   > yes / no

**Status:**

3. Add `scraping` status between `pending` and `downloading`?
   > yes / no

**LLM Provider:**

4. Implement full provider abstraction (`base.py`, `factory.py`) now, or minimal version? Which provider first?
   > full / minimal — provider: anthropic / openai

5. Add `RAGTIME_LLM_MODEL` env var? Default model?
   > yes / no — default: 

**HTML Fetching:**

6. Libraries: `httpx` + `beautifulsoup4` — ok?
   > yes / alternative: 

**Failure & Manual Editing:**

7. When extraction fails or is incomplete: new `needs_review` status, or reuse `failed`?
   > needs_review / failed

8. Auto-trigger scrape on episode creation, or manual admin action?
   > auto / manual

**Prompt Template:**

9. Prompt as Python constant or separate file?
   > constant / file
```

### User

## Step 3: Scrape — Clarifications

**Metadata & Model:**

1. Fields to extract: `title`, `description`, `published_at`, `image_url`, `language`, `audio_url` (MP3 URL). Add/remove/rename any?
   > no

2. Store cleaned HTML on the Episode model for debugging/re-processing?
   > yes 

**Status:**

3. Add `scraping` status between `pending` and `downloading`?
   > yes 

**LLM Provider:**

4. Implement full provider abstraction (`base.py`, `factory.py`) now, or minimal version? Which provider first?
   > full  — provider: openai
   > 
5. Add `RAGTIME_LLM_MODEL` env var? Default model?
   > yes / no — default: 

**HTML Fetching:**

6. Libraries: `httpx` + `beautifulsoup4` — ok?
   > yes / alternative: 

**Failure & Manual Editing:**

7. When extraction fails or is incomplete: new `needs_review` status, or reuse `failed`?
   > needs_review / failed

8. Auto-trigger scrape on episode creation, or manual admin action?
   > auto / manual

**Prompt Template:**

9. Prompt as Python constant or separate file?
   > constant / file

### Assistant

A few answers were left as the template defaults (5 default model, 7, 8, 9). I'll proceed with these assumptions:

- **5**: `RAGTIME_LLM_MODEL` env var — yes, default `gpt-4.1-mini` (cost-effective for structured extraction)
- **7**: `needs_review` — distinct from `failed` so the user knows manual input is needed
- **8**: `auto` — scrape triggers automatically on episode creation
- **9**: `constant` — simpler, keeps prompt close to the code that uses it

Let me write the plan.

The plan is written at [step-03-scrape.md](doc/plans/step-03-scrape.md). Here's a summary of the key design decisions:

**Status transitions:**
```
pending → scraping → downloading       (happy path)
                   → needs_review       (incomplete extraction)
                   → failed             (HTTP/LLM error)
needs_review → scraping → downloading   (user fills fields + clicks "Reprocess")
```

**Key architecture choices:**
- **Auto-trigger** via `post_save` signal — creating an episode in admin automatically queues the scrape task
- **Smart re-processing** — the scrape task checks which fields are already populated, so if the user fills missing fields in `needs_review`, it skips LLM re-extraction and advances directly
- **Stored HTML** — cleaned HTML saved on the model for debugging and re-processing without re-fetching
- **Full provider abstraction** — `LLMProvider` ABC with `structured_extract()`, OpenAI implementation using structured outputs (JSON schema)
- **Django Q2 with ORM broker** — no Redis needed, task status visible in admin automatically

**10 implementation steps** covering: dependencies, settings, model, providers, scraper, signals, admin, migration, README update, and tests.

Please review and let me know if you'd like any changes before I start implementing.

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/manage.py in the IDE. This may or may not be related to the current task.</ide_opened_file>
Implement

### Assistant

The issue is that `async_task` is imported locally inside the signal handler, so it can't be patched at module level. I need to change the signal to import at module level so it's patchable, and fix the mock paths.

Now fix the mock paths in tests — need to patch `django_q.tasks.async_task` instead of `episodes.signals.async_task`:

The problem is that `async_task` is imported at module level in signals.py but the mock path `episodes.signals.async_task` should work now. Let me also need to handle the `EpisodeModelTests` — those create episodes which trigger the signal. Let me fix:

1. The signal now imports `async_task` at module level, so `episodes.signals.async_task` should be patchable
2. The `EpisodeModelTests` need to also mock the signal since they create episodes
3. The `_create_episode` helper in `ScrapeEpisodeTests` should also work now

But the `EpisodeModelTests` don't mock the signal and will try to actually enqueue tasks. Let me fix them:

All 25 tests pass.

All 25 tests pass. Here's what was implemented:

**New files:**
- [episodes/providers/base.py](episodes/providers/base.py) — ABC for `LLMProvider`, `TranscriptionProvider`, `EmbeddingProvider`
- [episodes/providers/openai.py](episodes/providers/openai.py) — OpenAI implementation using structured outputs
- [episodes/providers/factory.py](episodes/providers/factory.py) — `get_llm_provider()` factory
- [episodes/scraper.py](episodes/scraper.py) — HTML fetch, clean, LLM extraction, `scrape_episode` task
- [episodes/signals.py](episodes/signals.py) — `post_save` signal auto-queues scrape on episode creation

**Modified files:**
- [pyproject.toml](pyproject.toml) — Added django-q2, openai, httpx, beautifulsoup4, python-dotenv
- [ragtime/settings.py](ragtime/settings.py) — dotenv loading, `django_q` app, `Q_CLUSTER` config, `RAGTIME_*` settings
- [episodes/models.py](episodes/models.py) — Added metadata fields + `scraping`/`needs_review` statuses
- [episodes/apps.py](episodes/apps.py) — Signal registration in `ready()`
- [episodes/admin.py](episodes/admin.py) — Conditional field editing, fieldsets, "Reprocess" action, Django Q2 visible in admin
- [episodes/tests.py](episodes/tests.py) — 25 tests covering model, HTML cleaning, scrape task, signals, admin
- [README.md](README.md) — Step 3 status changed to `scraping`

**To run:**
```bash
# Terminal 1
uv run python manage.py runserver
# Terminal 2
uv run python manage.py qcluster
```

Set `RAGTIME_LLM_API_KEY` in your `.env` file before testing with real episodes.

### User

<ide_selection>The user selected the lines 177 to 177 from /Users/rafa/Develop/projects/ragtime/doc/plans/step-03-scrape.md:
RAGTIME_LLM

This may or may not be related to the current task.</ide_selection>
When testing locally after having defined the `RAGTIME_LLM_API_KEY` I get the following error from the OpenAI API call
```
openai.BadRequestError: Error code: 400 - {'error': {'message': "Missing required parameter: 'text.format.name'.", 'type': 'invalid_request_error', 'param': 'text.format.name', 'code': 'missing_required_parameter'}}
```

### Assistant

The OpenAI structured output API requires a `name` field in the format schema. Let me fix the provider call.

The `format` needs a `name` field at the top level. The `name` is in our schema dict already but the API expects it inside the `format` object, not nested under `schema`. Let me check the schema structure.

The `SCRAPE_RESPONSE_SCHEMA` already has `name` at the top level. The issue is that the `format` dict in the API call needs `name` as a direct key. The schema dict has `name`, `strict`, and `schema` — the whole dict should be passed as the `schema` parameter inside `format`, and the `name` needs to also be at the `format` level.

Looking at the OpenAI Responses API docs, the format should be:
```python
{"type": "json_schema", "name": "...", "schema": {...}}
```

This spreads `name`, `strict`, and `schema` directly into the format dict alongside `type`, which matches what the API expects:

```python
{"type": "json_schema", "name": "episode_metadata", "strict": True, "schema": {...}}
```

Tests still pass. Try your local test again — the fix spreads `name`, `strict`, and `schema` into the format dict so the API gets the required `text.format.name` parameter.

### User

<ide_selection>The user selected the lines 61 to 61 from /Users/rafa/Develop/projects/ragtime/episodes/admin.py:
Reprocess

This may or may not be related to the current task.</ide_selection>
The tests work locally. Update the README.md file to include the new `RAGTIME_LLM_MODEL` environment variable.

### Assistant

Done. Added `RAGTIME_LLM_MODEL` to the Configuration section in [README.md:90](README.md#L90).

### User

Create the corresponding feature and session files and commit the feature.

### Assistant

Committed as `cd68187`. 18 files changed, 1381 insertions — includes plan, feature doc, session doc, and all implementation files.

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/doc/sessions/2026-03-09-step-03-scrape.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Export this session full details as Markdown and replace file 2026-03-09-step-03-scrape.md

### Assistant

Done. Replaced [2026-03-09-step-03-scrape.md](doc/sessions/2026-03-09-step-03-scrape.md) with the full session transcript — includes all 12 conversation steps, every implementation detail, the bug fix, and the complete file list.

### User

Commit this change with a clarifying commit message.

### Assistant

Committed as `bba8aca`.
