# Session: Step 8 — Extract Entities

**Date:** 2026-03-13

## Summary

Planned and implemented Step 8 of the RAGtime pipeline: LLM-based entity extraction from episode transcripts with 15 jazz entity types defined in YAML, a shared language module, and an independently configurable extraction provider.

## Conversation

### User
Let's plan Step 8 — LLM-based entity extraction. The LLM and model should be configured separately so add configuration variables for entity extraction. In file `entities.csv` there is a list with the entities we want to extract from the podcast episode transcripts. Create a configuration file with the contents of the `entities.csv` that will be used to create the prompt for the LLM to extract the entities from the transcript. Also add a section in the README file with a table containing the extracted entities information and a link to the configuration file in case entities are updated. The podcasts can be in different languages so we need to take this into account when creating the prompt. We want the response from the LLM to be in JSON format and we want to store that JSON in the Episode model.

### Assistant
Launched an Explore agent to understand the project structure and conventions. Then read the key files: `episodes/summarizer.py`, `episodes/providers/factory.py`, `ragtime/settings.py`, `episodes/providers/base.py`, `episodes/signals.py`, `episodes/models.py`, `episodes/scraper.py`, `README.md`, `episodes/providers/openai.py`, `episodes/admin.py`, `AGENTS.md`, and the scraper's schema pattern.

Entered plan mode and wrote the implementation plan covering: entity config file (CSV), model field (`entities_json` JSONField), extractor module, settings, factory, signal, admin, tests, README updates, and documentation.

Asked the user: "The summarizer duplicates the ISO_639_LANGUAGE_NAMES dict and language validation. Should I extract these into a shared utility (e.g. `episodes/languages.py`) that both summarizer and extractor import, or just duplicate them in the extractor?"

### User
Extract to shared module.

### Assistant
Updated the plan to include a shared `episodes/languages.py` module and added it to the files table. Attempted to exit plan mode.

### User
Rejected the exit. Asked: "How are we going to handle entity types like 'Recording Session' which have a space? I think it would be better to convert the `entities.csv` file to YAML and already include the entity key there."

### Assistant
Agreed — using YAML allows defining explicit snake_case keys (like `recording_session`) alongside display names, avoiding fragile runtime conversion. Updated the plan:

- Changed entity config from CSV to YAML (`episodes/entity_types.yaml`) with `key`, `name`, `description`, `examples` fields per entity type
- Updated the extractor section to load YAML with `yaml.safe_load()` and added `pyyaml` dependency
- Updated the files table and README section references

Exited plan mode.

### User
Rejected the exit (wanted to review the final plan first).

### Assistant
Acknowledged and waited for feedback on the plan.

### User
(New session) Provided the finalized plan and asked to implement it.

### Assistant
Read all relevant files, created branch `feature/step-08-extract-entities`, and implemented all changes:

1. Added `pyyaml` dependency via `uv add pyyaml`
2. Created `episodes/entity_types.yaml` with 15 entity types
3. Created `episodes/languages.py` with shared language utilities
4. Refactored `episodes/summarizer.py` to import from `languages.py`
5. Added `entities_json` JSONField to `Episode` model
6. Created `episodes/extractor.py` with `build_system_prompt()`, `build_response_schema()`, and `extract_entities()`
7. Added `get_extraction_provider()` to factory
8. Added `RAGTIME_EXTRACTION_*` settings
9. Added `EXTRACTING` dispatch to signals
10. Added collapsible "Entities" fieldset to admin
11. Added 13 new tests (68 total, all passing)
12. Updated README with config vars, entity type table, and features entry
13. Created plan, feature, and session documentation

Generated migration, ran migrate, system check, and all 68 tests passed. Committed, pushed, and opened PR #17.

### User
The generated session file does not contain a detailed transcript of the planning session. Asked for a list of session IDs to identify the planning session.

### Assistant
Searched the JSONL session files and identified session `2a59d61c-6874-4f8a-953b-4280ec859794` as the planning session.

### User
Asked to generate a proper transcript from that session ID and replace the session file.

### Assistant
Read the full planning session transcript from the JSONL file and rewrote `doc/sessions/2026-03-13-step-08-extract-entities.md` with the detailed conversation.
