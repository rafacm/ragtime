# Session: Step 8 — Extract Entities

**Date:** 2026-03-13
**Session ID:** da971828-9b37-46fe-9338-a5d1cef9606e

## Summary

Implemented Step 8 (Extract Entities): LLM-based entity extraction from episode transcripts with an independently configurable extraction provider, structured JSON output for 7 entity types, and Django admin visibility for extracted entities.

## Conversation

### User

Implement the following plan:

# Step 8: Entity Extraction — Implementation Plan

## Context

The pipeline currently runs through Step 7 (Summarize), which sets status to `EXTRACTING`. Step 8 needs to pick up from there, extract jazz entities from the transcript using an LLM, and store the structured JSON result on the Episode model. The entity types are defined in `entities.csv` and the extraction prompt must be language-aware (podcasts can be in different languages). The LLM/model for extraction should be independently configurable (like summarization).

## Changes

### 1. Entity configuration file: `episodes/entity_types.yaml`

Create `episodes/entity_types.yaml` from the data in `entities.csv`. YAML allows us to define explicit snake_case keys for each entity type, avoiding runtime conversion of names like "Recording Session". Each entry has a `key`, `name`, `description`, and `examples`.

Structure:
```yaml
- key: artist
  name: Artist
  description: Individual musicians or singers.
  examples: Miles Davis, Alice Coltrane

- key: band
  name: Band
  description: Organized groups or ensembles.
  examples: The Jazz Messengers, Snarky Puppy

- key: album
  name: Album
  description: Specific studio or live record releases.
  examples: Kind of Blue, A Love Supreme

- key: composition
  name: Composition
  description: Specific songs, standards, or tunes.
  examples: Take Five, Giant Steps, Summertime

- key: venue
  name: Venue
  description: Physical clubs, theaters, or festivals.
  examples: Village Vanguard, Newport Jazz Festival

- key: recording_session
  name: Recording Session
  description: A specific date/time/place of a recording.
  examples: The Blackhawk Sessions, 1959 Sessions

- key: label
  name: Label
  description: The record company/publisher.
  examples: Blue Note, Impulse!, ECM

- key: year
  name: Year
  description: The specific calendar year mentioned.
  examples: 1959, 1942, 2024

- key: era
  name: Era
  description: Broad historical periods or movements.
  examples: The Swing Era, Prohibition, Post-Bop

- key: city
  name: City
  description: The specific metropolitan area.
  examples: New Orleans, Paris, Tokyo

- key: country
  name: Country
  description: The nation of origin or performance.
  examples: USA, Brazil, Ethiopia, France

- key: sub_genre
  name: Sub-genre
  description: Specific stylistic categories within Jazz.
  examples: Hard Bop, Fusion, Modal, Free Jazz

- key: instrument
  name: Instrument
  description: The tool used to create the music.
  examples: Trumpet, Fender Rhodes, Double Bass

- key: role
  name: Role
  description: The artist's function in that moment.
  examples: Bandleader, Sideman, Arranger, Producer
```

The `key` field is used as the JSON property name in the response schema and stored data. The `name` field is used in prompts and documentation.

### 2. New model field: `episodes/models.py`

Add a `entities_json` field (JSONField, nullable, blank) to store the extracted entities:

```python
# LLM-extracted entities (populated by extractor)
entities_json = models.JSONField(blank=True, null=True)
```

### 3. Migration

Generate migration for the new `entities_json` field.

### 4. New extractor module: `episodes/extractor.py`

Follow the summarizer pattern. Key design:

- **Load entity types from YAML** at module level — read `episodes/entity_types.yaml`, parse with `yaml.safe_load()` into a list of dicts with `key`, `name`, `description`, `examples` fields. Add `pyyaml` dependency via `uv add pyyaml`.
- **Build system prompt** — instructs the LLM to extract entities from a podcast transcript. Include the entity type definitions from the YAML in the prompt (using `name` and `description`). Language-aware: tells the LLM to extract entities as they appear in the transcript (preserving original language names) but use the `key` values for JSON property names.
- **Build JSON schema** — dynamic `response_schema` for `structured_extract()` based on the entity types from YAML. Each entity type `key` becomes a JSON property with `type: ["array", "null"]` containing objects.
- **`extract_entities(episode_id)`** — the async task function:
  1. Fetch episode, validate status is `EXTRACTING`
  2. Check transcript exists
  3. Call `get_extraction_provider().structured_extract(system_prompt, transcript, schema)`
  4. Store result in `episode.entities_json`
  5. Advance status to `DEDUPLICATING`
  6. Error handling → `FAILED`

**System prompt structure:**
```
You are an expert entity extractor specializing in jazz music podcasts.
Given a podcast transcript, extract all mentioned entities organized by type.

Entity types to extract:
- Artist: Individual musicians or singers. Examples: Miles Davis, Alice Coltrane
- Band: Organized groups or ensembles. Examples: The Jazz Messengers, Snarky Puppy
[... all 15 types from CSV ...]

Rules:
- Extract entities exactly as they appear in the transcript
- For each entity, include a "name" field and an optional "context" field with a brief note about how it was mentioned
- If no entities of a given type are found, return null for that type
- Entity type keys must be in English (snake_case), but entity names should preserve the original language from the transcript

{language_instruction}
```

**JSON response schema** (dynamically built from CSV):
```json
{
  "name": "episode_entities",
  "strict": true,
  "schema": {
    "type": "object",
    "properties": {
      "artist": { "type": ["array", "null"], "items": { "type": "object", "properties": { "name": { "type": "string" }, "context": { "type": ["string", "null"] } }, "required": ["name", "context"], "additionalProperties": false } },
      "band": { ... same structure ... },
      ...
    },
    "required": ["artist", "band", ...],
    "additionalProperties": false
  }
}
```

**Language handling** — reuse `ISO_639_LANGUAGE_NAMES` dict and `_ISO_639_RE` from summarizer (import or duplicate). Language instruction tells the LLM: "The transcript is in {language}. Extract entity names as they appear in the transcript."

### 5. Settings: `ragtime/settings.py`

Add entity extraction provider config (following summarization pattern):

```python
# Entity extraction
RAGTIME_EXTRACTION_PROVIDER = os.getenv('RAGTIME_EXTRACTION_PROVIDER', 'openai')
RAGTIME_EXTRACTION_API_KEY = os.getenv('RAGTIME_EXTRACTION_API_KEY', '')
RAGTIME_EXTRACTION_MODEL = os.getenv('RAGTIME_EXTRACTION_MODEL', 'gpt-4.1-mini')
```

### 6. Factory: `episodes/providers/factory.py`

Add `get_extraction_provider()` following the same pattern as `get_summarization_provider()`.

### 7. Signal dispatcher: `episodes/signals.py`

Add dispatch for `EXTRACTING` status:
```python
elif instance.status == Episode.Status.EXTRACTING:
    async_task("episodes.extractor.extract_entities", instance.pk)
```

### 8. Admin: `episodes/admin.py`

- Add `entities_json` to `readonly_fields`
- Add an "Entities" fieldset (shown when `entities_json` is populated), collapsible

### 9. README updates: `README.md`

**Configuration section** — add three new env vars:
- `RAGTIME_EXTRACTION_PROVIDER` — Entity extraction LLM provider (default: `openai`)
- `RAGTIME_EXTRACTION_API_KEY` — API key for the entity extraction provider
- `RAGTIME_EXTRACTION_MODEL` — Entity extraction model name (default: `gpt-4.1-mini`)

**New section: "Extracted Entities"** — add a table with the entity types (Key, Name, Description, Examples columns) and a link to `episodes/entity_types.yaml` for customization.

**Features & Fixes table** — add entry for Step 8.

### 10. Tests: `episodes/tests.py`

- Test `build_system_prompt` with/without language
- Test `build_response_schema` returns valid schema from CSV
- Test `extract_entities` happy path (mock provider, verify JSON stored, status advanced)
- Test `extract_entities` with missing transcript → FAILED
- Test `extract_entities` with wrong status → skip
- Test `extract_entities` with provider error → FAILED
- Test signal dispatch for EXTRACTING status

### 11. Documentation

Per AGENTS.md rules:
- `doc/plans/step-08-extract-entities.md` — this plan
- `doc/features/step-08-extract-entities.md` — feature doc
- `doc/sessions/2026-03-13-step-08-extract-entities.md` — session transcript

## Files to modify/create

| File | Action | Description |
|------|--------|-------------|
| `episodes/entity_types.yaml` | Create | Entity type definitions (from entities.csv, with explicit keys) |
| `episodes/languages.py` | Create | Shared language utilities (extracted from summarizer) |
| `episodes/summarizer.py` | Edit | Import language utils from `episodes/languages.py` |
| `episodes/models.py` | Edit | Add `entities_json` JSONField |
| `episodes/extractor.py` | Create | Entity extraction task module |
| `episodes/providers/factory.py` | Edit | Add `get_extraction_provider()` |
| `ragtime/settings.py` | Edit | Add `RAGTIME_EXTRACTION_*` settings |
| `episodes/signals.py` | Edit | Add EXTRACTING dispatch |
| `episodes/admin.py` | Edit | Add entities_json fieldset |
| `episodes/tests.py` | Edit | Add extraction tests |
| `README.md` | Edit | Config vars, entity table, features entry |
| `episodes/migrations/NNNN_*.py` | Create | Migration for entities_json |
| `doc/plans/step-08-extract-entities.md` | Create | Implementation plan |
| `doc/features/step-08-extract-entities.md` | Create | Feature documentation |
| `doc/sessions/2026-03-13-step-08-extract-entities.md` | Create | Session transcript |

## Shared language module

Extract `ISO_639_LANGUAGE_NAMES`, `_ISO_639_RE`, and language-related helpers into `episodes/languages.py`. Update `episodes/summarizer.py` to import from there. Both summarizer and extractor will share this module.

## Reusable code

- `LLMProvider.structured_extract()` from `episodes/providers/base.py` — same method used by scraper
- `get_summarization_provider()` pattern from `episodes/providers/factory.py` — copy for extraction
- Signal dispatch pattern from `episodes/signals.py`

## Verification

1. `uv run python manage.py makemigrations` — generates migration
2. `uv run python manage.py migrate` — applies it
3. `uv run python manage.py check` — no system check errors
4. `uv run python manage.py test episodes` — all tests pass
5. Manual test: set an episode to EXTRACTING status and verify the extractor runs, stores JSON in entities_json, and advances to DEDUPLICATING


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/2a59d61c-6874-4f8a-953b-4280ec859794.jsonl

### Assistant

I'll start by reading the key files in parallel to understand the current codebase.

Now let me also read the provider base class and README for the sections I need to update.

I have a clear picture of the codebase. Let me implement everything. I'll start by creating the new files and editing existing ones in parallel where possible.

First, let me create the new branch and add the pyyaml dependency.

Now let me create all the new files and edit existing ones.

Now update models.py, settings.py, factory.py, signals.py, and admin.py in parallel.

Now add the entities fieldset in admin.py.

Now create the extractor module.

Now generate the migration and run checks.

Now add the tests. Let me append them to the existing tests file.

Now run the tests.

All 68 tests pass. Now let me update the README and create the documentation files.

Now add the "Extracted Entities" section to the README, right after the Processing Pipeline section.

Now create the documentation files.

Let me read an existing session doc for the format reference.

Now let me read a feature doc for the format.

Now let me create all three doc files.

All implementation is complete. Let me run the tests one final time to confirm everything passes.

All 68 tests pass. Here's a summary of what was implemented:

**Step 8: Entity Extraction** — 15 files created/modified:

- **`episodes/entity_types.yaml`** — 15 jazz entity types (artist, band, album, composition, venue, recording_session, label, year, era, city, country, sub_genre, instrument, role)
- **`episodes/languages.py`** — Shared language utilities extracted from summarizer
- **`episodes/summarizer.py`** — Refactored to import from `languages.py`
- **`episodes/models.py`** — Added `entities_json` JSONField
- **`episodes/extractor.py`** — Entity extraction task with language-aware prompt, dynamic JSON schema, provider call
- **`episodes/providers/factory.py`** — Added `get_extraction_provider()`
- **`ragtime/settings.py`** — Added `RAGTIME_EXTRACTION_*` settings
- **`episodes/signals.py`** — Added `EXTRACTING` → `extract_entities` dispatch
- **`episodes/admin.py`** — Added collapsible "Entities" fieldset
- **`episodes/tests.py`** — 13 new tests (68 total)
- **`README.md`** — Config vars, entity type table, features entry
- **`pyproject.toml`/`uv.lock`** — Added `pyyaml`
- **`doc/`** — Plan, feature, and session docs

Would you like me to commit and open a PR?

### User

yes

### Assistant

PR created: https://github.com/rafacm/ragtime/pull/17

The uncommitted change warning is just `entities.csv` which was already untracked before this work.

### User

The generated session file does NOT contain a detailed transcript of the planning session. Can you provide me a list of session IDs and a summary so I can tell you which session I want the transcript for?

### Assistant

That's a lot of sessions. Let me search for the ones related to step-08 / entity extraction planning.

The Explore agent wasn't specific enough. Let me search more precisely — the plan itself referenced session `2a59d61c`, and there are several others. Let me get the first user message from each candidate.

`da971828` is the current session. Let me find the actual planning session — `2a59d61c` was referenced in the plan. Let me look deeper into it.

Found it. Session `2a59d61c-6874-4f8a-953b-4280ec859794` is the planning session. Let me also check other recent sessions that might be related.

Here's what I found so far:

| # | Session ID | Summary |
|---|-----------|---------|
| 1 | `2a59d61c-6874-4f8a-953b-4280ec859794` | **Step 8 planning session** — User asked to plan entity extraction, configure extraction LLM, create config from entities.csv, add README section |
| 2 | `da971828-9b37-46fe-9338-a5d1cef9606e` | **Current session** — Implementation of the Step 8 plan |

Session `2a59d61c` is the planning session referenced in your plan. Which session would you like me to generate the transcript for?

### User

Generate a transcript for session id 2a59d61c-6874-4f8a-953b-4280ec859794 as per the AGENTS.md instructions and replace file @doc/sessions/2026-03-13-step-08-extract-entities.md with it. Look at previous session files in that directory for formatting.

### Assistant

Now let me get more detail on the assistant's key messages — particularly the plan content written, the question asked, and the user's responses.

Now let me get the user responses — particularly the answer to the AskUserQuestion and the feedback that led to the YAML change.

Now I have the full picture. Let me also check if the user's first message was truncated.

Now let me also get the full user feedback about YAML vs CSV.

Now let me also get the assistant's question that was asked.

Now I have all the pieces. Let me also read a previous session doc for exact format reference.

Now I have the format. Let me write the session transcript.

Updated the session transcript with the detailed planning conversation. It now covers the full back-and-forth including:

- The initial request with all requirements
- The assistant exploring the codebase and writing the plan
- The question about shared language module (user chose: extract to shared module)
- The user's feedback about "Recording Session" spaces and switching to YAML
- The plan revisions and final implementation

Would you like me to amend the commit and force push?

### User

yes

### Assistant

Done. Amended and force pushed with the updated session transcript.
