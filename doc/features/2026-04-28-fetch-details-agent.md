# Fetch Details Agent (was: Scrape step)

**Date:** 2026-04-28

## Problem

The `Scrape` step was the only place in the pipeline still using the
`LLMProvider` abstraction (provider-class + per-step `_PROVIDER` env var)
for an LLM call. Every step we eventually want to evaluate as an
agent — fetch_details, summarize, extract, resolve, translate — needs
to share a homogeneous shape so an evaluation framework can iterate
over them uniformly. Scrape was first because it is structurally
simple (single LLM call, no tools), making it a clean tracer-bullet
slice for the SDK swap and the surrounding rename.

The rename (`Scrape` → `Fetch Details`) is also a UX cleanup: "scrape"
implies a brittle CSS-selector style of extraction, while the step
actually does LLM-based structured extraction over cleaned HTML and
the recovery path uses Playwright. "Fetch Details" describes the
outcome rather than the mechanism.

## Changes

### Pipeline step (`episodes/fetch_details_step.py`)

- File renamed from `episodes/scraper.py`. Function `scrape_episode`
  → `fetch_episode_details`. Telemetry span name flipped to match.
- Step body now calls
  `episodes/agents/fetch_details.py:run(html)` via `asyncio.run`
  (DBOS step bodies are sync). All other behaviors preserved:
  HTML fetch + clean, fast-path skip when required fields are
  pre-filled, empty-field-only merge, completeness check, save-before-
  fail-step ordering for recovery interaction.
- `REQUIRED_FIELDS = ("title", "audio_url")` lives here as the step's
  "ready to advance" contract — distinct from the agent's structured
  output contract.

### Agent (`episodes/agents/fetch_details.py`)

- New module. Imports only Pydantic AI, Pydantic, stdlib, and
  `agents/_model.py`. No Django, no DBOS, no `episodes.models`.
- Exposes `EpisodeDetails` (Pydantic `BaseModel` with date validator
  and ISO-639 regex), `get_agent()` (lazy + memoized), and
  `run(html) -> EpisodeDetails`.
- Single `Agent.run(html)` call — no tools yet. Future PRs add browser
  tools absorbed from the recovery agent.

### Shared model helper (`episodes/agents/_model.py`)

- New module. Pure `build_model(model_string, api_key) -> Model`
  helper. Takes a Convention B `provider:model` string and an API
  key, returns either a concrete Pydantic AI `Model` (for OpenAI) or
  the raw model string (lets Pydantic AI's own env-var resolution
  take over).
- Refactored the recovery agent to use the same helper, eliminating
  duplicated model-construction logic.

### Recovery agent file rename

The recovery cluster is now prefixed `recovery_` to mark it as
transitional — slated for deletion once `fetch_details` and `download`
step-agents absorb its capabilities. Renames (via `git mv`):

| Was | Now |
|---|---|
| `episodes/agents/agent.py` | `episodes/agents/recovery.py` |
| `episodes/agents/browser.py` | `episodes/agents/recovery_browser.py` |
| `episodes/agents/deps.py` | `episodes/agents/recovery_deps.py` |
| `episodes/agents/tools.py` | `episodes/agents/recovery_tools.py` |
| `episodes/agents/resume.py` | `episodes/agents/recovery_resume.py` |

`AgentStrategy.can_handle()` flipped its `"scraping"` literal to
`"fetching_details"`. `_resume_from_scraping` →
`_resume_from_fetching_details`.

### Status enum + data migration

- `Episode.Status.SCRAPING = "scraping"` →
  `Episode.Status.FETCHING_DETAILS = "fetching_details"`.
- `PIPELINE_STEPS` updated.
- Migration `0021_rename_scraping_to_fetching_details` rewrites every
  `"scraping"` literal in DB-side audit columns
  (`Episode.status`, `ProcessingStep.step_name`, `PipelineEvent.step_name`,
  `ProcessingRun.resumed_from_step`) and alters `Episode.status` choices.
  `RunPython` is reversible.

### Workflow integration

- `STEP_FUNCTIONS[Episode.Status.FETCHING_DETAILS]` points at
  `episodes.fetch_details_step.fetch_episode_details`.
- `episodes.providers.factory.get_scraping_provider` deleted.

### Configuration (Convention B)

| Removed | Added |
|---|---|
| `RAGTIME_SCRAPING_PROVIDER` | (provider encoded in model string prefix) |
| `RAGTIME_SCRAPING_MODEL=gpt-4.1-mini` | `RAGTIME_FETCH_DETAILS_MODEL=openai:gpt-4.1-mini` |
| `RAGTIME_SCRAPING_API_KEY` | `RAGTIME_FETCH_DETAILS_API_KEY` |

- `ragtime/settings.py`, `.env.sample`, `core/management/commands/_configure_helpers.py` updated.
- Configure wizard now skips writing `_PROVIDER` for subsystems whose
  fields don't include one — Convention B subsystems (currently only
  fetch_details) cleanly opt out without a special-case flag.
- API-key sharing across the LLM group still works for the new
  subsystem (the wizard writes the shared key as
  `RAGTIME_FETCH_DETAILS_API_KEY`).

## Key parameters

| Parameter | Value | Why |
|---|---|---|
| `RAGTIME_FETCH_DETAILS_MODEL` default | `openai:gpt-4.1-mini` | Same model used for the previous `Scrape` step. |
| `REQUIRED_FIELDS` | `("title", "audio_url")` | Step's "ready to advance" contract. Title is what the user sees; audio_url is what the next step downloads. |
| `MAX_HTML_LENGTH` | `30_000` | Unchanged from Scrape — fits in the model's context with budget for the system prompt. |

## Verification

```bash
docker compose up -d
uv run python manage.py migrate              # applies 0021 rename migration
uv run python manage.py configure --show     # confirm new RAGTIME_FETCH_DETAILS_* vars
uv run python manage.py test                 # full suite, 338 tests
```

End-to-end: submit an episode through the admin or CLI, watch its
status move `pending → queued → fetching_details → downloading → ...`.
With `RAGTIME_OTEL_COLLECTORS=jaeger`, the trace span for the step
appears as `fetch_episode_details`.

## Files modified

| File | Change |
|---|---|
| `episodes/fetch_details_step.py` | Renamed from `scraper.py`. Calls fetch_details agent. |
| `episodes/agents/fetch_details.py` | New: Pydantic AI agent. |
| `episodes/agents/_model.py` | New: shared `build_model` helper. |
| `episodes/agents/recovery*.py` | Renamed (was `agent`/`browser`/`deps`/`tools`/`resume`). Recovery agent uses `_model.py`. |
| `episodes/agents/__init__.py` | Re-exports updated for renames. |
| `episodes/recovery.py` | `can_handle()` literal flipped. |
| `episodes/agents/recovery_resume.py` | `_resume_from_scraping` → `_resume_from_fetching_details`. |
| `episodes/models.py` | Status enum rename + `PIPELINE_STEPS` updated. |
| `episodes/workflows.py` | `STEP_FUNCTIONS` updated. |
| `episodes/admin.py` | Status enum references updated. |
| `episodes/providers/factory.py` | `get_scraping_provider` deleted. |
| `episodes/migrations/0021_rename_scraping_to_fetching_details.py` | New: data migration + status choices alter. |
| `ragtime/settings.py`, `.env.sample`, `core/management/commands/_configure_helpers.py`, `core/management/commands/configure.py` | Convention B env vars; wizard skips `_PROVIDER` for Convention B subsystems. |
| `episodes/tests/test_fetch_details_step.py` | Renamed; rewritten to use `Agent.override(model=TestModel())` + agent validator tests. |
| `episodes/tests/test_*.py`, `core/tests/test_configure.py` | Renames (`SCRAPING` → `FETCHING_DETAILS`, `step_name="scraping"` → `"fetching_details"`, agent module imports). |
| `README.md`, `AGENTS.md`, `doc/README.md` | Pipeline table + step descriptions reflect rename. |
| `CHANGELOG.md` | New `## 2026-04-28` entry. |

### Diagrams (manual update required)

CLAUDE.md flags Excalidraw files as not auto-updatable. Both
`.excalidraw` source and `.svg` render need updating in
`doc/architecture/`:

- `ragtime-processing-pipeline.{excalidraw,svg}` — rename "Scrape" box to "Fetch Details".
- `ragtime-processing-pipeline-with-recovery.{excalidraw,svg}` — same rename.
- `ragtime-recovery.{excalidraw,svg}` — review for any "scraping" labels.

The PR description includes a checklist for these.
