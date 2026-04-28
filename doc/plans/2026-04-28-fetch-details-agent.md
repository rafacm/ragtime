# Fetch Details Agent (was: Scrape step)

**Date:** 2026-04-28

## Goal

Migrate the `Scrape` pipeline step to a Pydantic AI agent, starting a gradual move toward homogeneous LLM calling across the pipeline. This unlocks a future evaluation framework that can iterate over step-agents uniformly. This PR is an SDK swap (single LLM call, no tools) so the agent shape is in place before subsequent PRs grow it (browser tools absorbed from the recovery agent, eventually deprecating the recovery agent altogether).

## Scope

- **In scope:** rename `Scrape` → `Fetch Details` (full rename; breaking change), introduce `episodes/agents/fetch_details.py` Pydantic AI agent and shared `episodes/agents/_model.py` helper, refactor step orchestrator, update workflow dispatch, data migration for status enum, env-var convention shift to Convention B, recovery file renames, doc + CHANGELOG + diagrams.
- **Out of scope (deferred to future PRs):** giving the agent tools (browser use, etc.); migrating the `Download` step to its own agent; deleting the recovery agent; eval/unit tests for the agent; renaming the `Episode.scraped_html` model field.

## Decisions

### Agent shape
- **SDK swap only.** No tools, no agent loop. Single structured-output LLM call via Pydantic AI's `Agent.run`. Future PRs add tools.
- **Module purity rule:** `episodes/agents/fetch_details.py` imports only Pydantic AI, Pydantic, stdlib, and `agents/_model.py`. No Django, no DBOS, no `episodes.models`. Tests can `from episodes.agents.fetch_details import run, EpisodeDetails` without booting Django.

### Rename
- Full rename in this PR: status enum, step list, file names, function names, env vars, configure wizard, telemetry span name, README, `doc/README.md`, `recovery.py` `can_handle` literal, Excalidraw diagrams.
- **Exception:** `Episode.scraped_html` model field stays as-is in this PR; renamed in a future PR.
- Breaking change: yes (env-var names, status string). CHANGELOG entry under `## 2026-04-28` with explicit `**BREAKING**` marker.

### Module layout

```
episodes/
├── fetch_details_step.py           ← was scraper.py; orchestration only
└── agents/
    ├── _model.py                   ← NEW: shared Convention B helper
    ├── fetch_details.py            ← NEW: the agent
    ├── recovery.py                 ← was agent.py
    ├── recovery_browser.py         ← was browser.py
    ├── recovery_deps.py            ← was deps.py
    ├── recovery_tools.py           ← was tools.py
    └── recovery_resume.py          ← was resume.py
```

The `_step` suffix is the marker for migrated-to-agent-pattern step files. Un-migrated steps keep their existing names (`downloader.py`, `transcriber.py`, etc.) until they're migrated in turn. The `recovery_` prefix marks the cluster as transitional — slated for deletion once `fetch_details` and `download` step-agents absorb its capabilities.

### Agent contract

```python
# episodes/agents/fetch_details.py

class EpisodeDetails(BaseModel):
    title: str | None
    description: str | None
    published_at: date | None        # validator parses YYYY-MM-DD
    image_url: str | None
    language: str | None             # regex ^[a-z]{2}$
    audio_url: str | None

SYSTEM_PROMPT = """..."""  # lifted verbatim from current SCRAPE_SYSTEM_PROMPT

def get_agent() -> Agent[None, EpisodeDetails]: ...   # lazy + memoized

async def run(html: str) -> EpisodeDetails: ...
```

- Required + Optional shape (matches current behavior: model produces all keys, may be null).
- URLs as plain `str | None` to preserve relative-URL tolerance in current prompt.
- Lazy `get_agent()` factory; tests use `Agent.override(model=TestModel())`.

### Shared model helper

```python
# episodes/agents/_model.py

def build_model(model_string: str, api_key: str) -> Model:
    """Pure function: colon-prefixed model string + API key → Pydantic AI model.
    No settings reads — caller injects."""
```

- Pure function, no Django imports. Settings reads happen in `get_agent()` factories.
- Recovery agent refactored to use the same helper (reads its `RAGTIME_RECOVERY_AGENT_*` settings inside its own factory, calls `build_model`).

### Step orchestrator (`fetch_details_step.py`)

Owns: status transitions, HTML fetch + clean (`fetch_html`, `clean_html` move here from `scraper.py`), fast-path skip when required fields are pre-filled, empty-field-only merge, completeness check, error handling, `start_step`/`complete_step`/`fail_step` calls.

- **Fast-path skip:** preserved. If required fields (`title`, `audio_url`) already populated (admin reprocess after `needs_review`), skip the LLM call.
- **Empty-field-only merge:** preserved. Never overwrite human-edited fields.
- `REQUIRED_FIELDS = ("title", "audio_url")` lives here, with a comment explaining it's the step's "ready to advance" contract (distinct from the agent's output contract).

### Configuration (Convention B)

| Removed | Added |
|---|---|
| `RAGTIME_SCRAPING_PROVIDER` | (provider encoded in model string prefix) |
| `RAGTIME_SCRAPING_MODEL=gpt-4o-mini` | `RAGTIME_FETCH_DETAILS_MODEL=openai:gpt-4o-mini` |
| `RAGTIME_SCRAPING_API_KEY` | `RAGTIME_FETCH_DETAILS_API_KEY` |

- No `_AGENT` suffix on the new vars. This sets the convention for future step-agents (`RAGTIME_SUMMARIZE_MODEL`, `RAGTIME_EXTRACT_MODEL`, etc.).
- Per-step API key sharing pattern unchanged for now (each step has its own `_API_KEY`).
- Updates: `ragtime/settings.py`, `.env.sample`, `core/management/commands/configure.py`.

### Recovery interaction

- This PR: `AgentStrategy.can_handle()` literal flips `"scraping"` → `"fetching_details"`. Otherwise unchanged.
- Future: recovery agent's tools (browser, screenshots, click, intercept, translate) absorbed into `fetch_details` (URL discovery) and `download` (audio bytes retrieval) step-agents. Once both branches are gone from `can_handle`, `episodes/recovery.py` + `episodes/agents/recovery_*.py` + `RAGTIME_RECOVERY_AGENT_*` env vars + `RecoveryAttempt` model + migrations get deleted.

### Workflow integration

- `STEP_FUNCTIONS[Episode.Status.FETCHING_DETAILS] = "episodes.fetch_details_step.fetch_episode_details"`.
- `PIPELINE_STEPS` updated.
- `episodes.providers.factory.get_scraping_provider` deleted (only six other `get_*_provider` functions remain).

### Status data migration

RunPython migration:
- `Episode.objects.filter(status="scraping").update(status="fetching_details")`
- `ProcessingStep.objects.filter(step_name="scraping").update(step_name="fetching_details")`
- (Grep for any other `"scraping"` literal in DB-persisted columns before finalizing.)

### Tests

- This PR: no new tests written, but the design supports both kinds via `Agent.override(model=...)`. Existing tests that import `scraper.py` or use `SCRAPING` status are updated for the rename.
- Future PR: unit-style tests with `TestModel` (run on every push) + eval-style tests with real LLM and HTML fixtures (path-gated or scheduled).

### PR shape

- **Option I:** one PR, two commits.
- Branch: `feature/fetch-details-agent`.
- Commit 1: rename (status enum, files, env vars, configure wizard, recovery `can_handle` literal, docs, diagrams). Includes status data migration.
- Commit 2: agent migration (introduce `_model.py` and `agents/fetch_details.py`, refactor `fetch_details_step.py` to call agent, delete `get_scraping_provider`).

## Diagrams to update manually

CLAUDE.md flags Excalidraw files as not auto-updatable. Both `.excalidraw` source and `.svg` render need updating:

- `doc/architecture/ragtime-processing-pipeline.{excalidraw,svg}` — rename "Scrape" box to "Fetch Details".
- `doc/architecture/ragtime-processing-pipeline-with-recovery.{excalidraw,svg}` — same rename.
- `doc/architecture/ragtime-recovery.{excalidraw,svg}` — review for any "scraping" labels and update.

PR description includes a checkbox for this.

## Documentation deliverables

- `doc/plans/2026-04-28-fetch-details-agent.md` (this file)
- `doc/features/2026-04-28-fetch-details-agent.md`
- `doc/sessions/2026-04-28-fetch-details-agent-planning-session.md`
- `doc/sessions/2026-04-28-fetch-details-agent-implementation-session.md`
- `README.md` pipeline table updated
- `doc/README.md` step descriptions updated
- `CHANGELOG.md` — `## 2026-04-28` entry with `### Changed` (BREAKING), `### Added`, `### Removed`

## Open items for future PRs

1. Tools migration: give `fetch_details` agent browser tools absorbed from the recovery agent (URL discovery from interactive pages).
2. Download step migration: convert to its own Pydantic AI agent with browser/intercept tools.
3. Recovery agent deletion: once both branches above are gone, remove `recovery.py`, `agents/recovery_*.py`, `RAGTIME_RECOVERY_AGENT_*`, `RecoveryAttempt` model + migrations.
4. Tests: unit + eval suite for `fetch_details` agent.
5. `Episode.scraped_html` field rename.
6. Migrate the remaining steps (`summarize`, `extract`, `resolve`, `translate`, `embed`) to Pydantic AI agents following the same pattern; each one drops its `get_*_provider` factory function in turn.
