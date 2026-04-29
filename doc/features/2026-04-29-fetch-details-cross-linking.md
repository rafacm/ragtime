# Fetch Details Agent — Cross-Linking, Outcomes, Reports

**Date:** 2026-04-29

## Problem

The Fetch Details step was a single LLM call on cleaned HTML: one shot, no tools, no recovery, and no record of what happened beyond the agent's structured output. Several gaps followed:

- A submitted Apple Podcasts URL couldn't be turned into the publisher's canonical page; a publisher canonical page with a JS-hidden audio URL couldn't be cross-linked to its aggregator entry. Both common cases hit the Download step's interactive-UI fallback and burned LLM/Playwright budget for what an iTunes lookup answers in milliseconds.
- The step had only two terminal states (`DOWNLOADING` or `FAILED`). A failed run carried a free-text `error_message` but no machine-readable discrimination — admins couldn't tell "homepage, not an episode" apart from "fetch failed" without reading prose.
- No per-run history. Successive admin re-runs overwrote `Episode.scraped_html` and produced no audit trail of what the agent tried.

## Changes

The Fetch Details step is now a Pydantic AI investigator agent loop. The LLM gets the system prompt + the submitted URL + three keyless tools (`fetch_url`, `search_apple_podcasts`, `search_fyyd`) and chooses freely how to combine them; the loop terminates when it produces a `FetchDetailsOutput`.

The agent emits a wrapped output with three components:

- `details` — episode-level facts (`title`, `description`, `published_at`, `image_url`, `audio_url`, `audio_format`, `language`, `country`, `guid`, `canonical_url`, `source_kind`, `aggregator_provider`).
- `report` — structured trace (`attempted_sources`, booleans for what was discovered or cross-linked, `extraction_confidence`, free-text `narrative`, `hints_for_next_step`).
- `concise` — `outcome` (5-value `Literal`) + `summary` (≤140 chars).

The orchestrator persists every run as a `FetchDetailsRun` row carrying the full structured output, an auto-captured tool-call trace (each tool appends a structured entry to the deps object), the Pydantic AI usage dict, and the DBOS workflow ID. `Episode` columns are overwritten directly by the agent's authoritative output — no empty-field-only merge, no fast-path skip, no `scraped_html` cache.

Five outcomes drive status transitions:

| outcome | `Episode.Status` | `FetchDetailsRun.outcome` |
|---|---|---|
| `ok` | `DOWNLOADING` | `ok` |
| `partial` | `DOWNLOADING` | `partial` |
| `not_a_podcast_episode` | `FAILED` | `not_a_podcast_episode` |
| `unreachable` | `FAILED` | `unreachable` |
| `extraction_failed` | `FAILED` | `extraction_failed` |

Module renames + iTunes addition:

- `episodes/podcast_indexes/` → `episodes/podcast_aggregators/` with `PodcastIndex` → `PodcastAggregator`. Existing fyyd / podcastindex clients move with it; a new `ItunesAggregator` is added.
- Env var `RAGTIME_PODCAST_INDEXES` → `RAGTIME_PODCAST_AGGREGATORS`. `.env.sample` and `core/management/commands/configure.py` updated. Pre-prod, no fallback.
- The Download agent's `lookup_podcast_index` tool now consults the renamed package and the new iTunes provider when configured. The Fetch Details agent's `search_apple_podcasts` and `search_fyyd` tools always have access regardless of `RAGTIME_PODCAST_AGGREGATORS` — they're the keyless cross-linking primitives, not gated configuration.

Data model:

- `Episode` gains `canonical_url`, `source_kind` (TextChoices: `canonical | aggregator | unknown`), `aggregator_provider`, `audio_format`, `country`. `Episode.scraped_html` is dropped (HTML now lives per-tool-call in `FetchDetailsRun.tool_calls_json`, capped to ~5 KB excerpts).
- New `FetchDetailsRun` table: `episode` FK, `run_index` (incremented per episode), `started_at`/`finished_at`, `model`, `outcome` (TextChoices), `output_json`, `tool_calls_json` (default list), `usage_json`, `error_message`, `dbos_workflow_id` (indexed). `unique_together = ("episode", "run_index")`.
- Single migration `0024_fetch_details_cross_linking.py`.

Admin UI:

- `EpisodeAdmin` gains a "Source" fieldset for the new columns, a "Latest Fetch Details run" block (outcome + confidence + summary + narrative + hints + link to the run change page), and an inline runs table.
- New `FetchDetailsRunAdmin` with collapsible sections (Concise / Report / Details / Tool calls / Raw payloads). Implementation uses admin-pattern `mark_safe()` callables — no custom Jinja view.

Tests:

- `episodes/tests/test_fetch_details_agent.py` — `TestModel`-based agent shape + every-outcome path + validators (URL, ISO codes, aggregator normalization, summary length cap).
- `episodes/tests/test_fetch_details_tools.py` — per-tool unit tests with mocked HTTP; `fetch_url` clean-HTML / failure / truncation behavior.
- `episodes/tests/test_fetch_details_step.py` — orchestrator state machine for all 5 outcomes + agent-crash path + run-index increment + tool-call persistence + `dbos_workflow_id` capture + authoritative overwrite.
- `episodes/tests/test_podcast_aggregators.py` — renamed; iTunes coverage added.

## Key parameters

| Constant | Value | Why |
|---|---|---|
| `MAX_HTML_LENGTH` (in `fetch_details_tools.py`) | 30 000 | Same budget as the previous single-call extractor — sized so cleaned HTML fits comfortably in a small-context LLM call. |
| `TRACE_HTML_EXCERPT` | 5 000 | What's persisted to `tool_calls_json` per fetch. The full output goes to the LLM; the excerpt is what the admin sees. |
| `FETCH_TIMEOUT` | 30.0 s | Inherited from the previous implementation. Long enough for slow CDN-fronted publisher pages, short enough that an `unreachable` outcome lands in seconds. |
| iTunes `limit=10`, fyyd `count=10` | 10 candidates | Matches existing aggregator clients — enough to find the right episode without overwhelming the LLM. |
| `Concise.summary` cap | 140 chars | Spec'd in the plan; trimmed silently rather than rejected so a stray over-long summary doesn't fail the run. |
| `AGGREGATOR_WHITELIST` | `apple_podcasts, spotify, fyyd, overcast, pocketcasts` | Free-string field with normalize helper — Apple's various brand spellings (`Apple`, `iTunes`, `apple-podcasts`) collapse to the canonical `apple_podcasts`. |

## Verification

```bash
uv run python manage.py test episodes -v 2
uv run python manage.py test                    # full suite
```

Expected: 367 tests pass.

On-device:

```bash
uv run python manage.py runserver --noreload
```

Submit an episode URL via the admin (or the `episodes` API) and verify:

- The Episode change form shows the new "Source" fieldset and a "Latest Fetch Details run" block.
- The inline `Fetch Details runs` table lists each run with outcome, summary, confidence.
- Clicking a run opens the new `FetchDetailsRunAdmin` page with collapsible Concise / Report / Details / Tool calls / Raw payloads sections.
- The DBOS workflow link from the run page resolves to the workflow steps view.

Try a URL classified as canonical (e.g. an NPR episode page) and one classified as aggregator (Apple Podcasts URL) — confirm `Episode.source_kind`, `canonical_url`, and `aggregator_provider` populate accordingly.

## Files modified

- `episodes/agents/fetch_details.py` — rewritten as investigator agent; new schemas (`AttemptedSource`, `FetchDetailsReport`, `ConciseMessage`, `EpisodeDetails`, `FetchDetailsOutput`); validators for URLs / ISO codes / aggregator normalization; tools registered; `run()` returns `(output, deps, usage)`.
- `episodes/agents/fetch_details_tools.py` — new; three keyless tools, all record traces to deps.
- `episodes/agents/fetch_details_deps.py` — new; `FetchDetailsDeps` dataclass with `submitted_url` + `tool_calls`.
- `episodes/fetch_details_step.py` — rewritten orchestrator; persists `FetchDetailsRun`; outcome → status mapping; authoritative-overwrite apply; agent-crash path.
- `episodes/workflows.py` — `fetch_details_step_` reads `DBOS.workflow_id` and passes it to the orchestrator.
- `episodes/models.py` — `Episode` gains source/source_kind/canonical_url/audio_format/country fields; `scraped_html` dropped; new `FetchDetailsRun` model.
- `episodes/migrations/0024_fetch_details_cross_linking.py` — new; auto-generated.
- `episodes/admin.py` — `EpisodeAdmin` gains Source fieldset / latest-run block / inline runs table; new `FetchDetailsRunAdmin` with collapsible sections.
- `episodes/podcast_indexes/` → `episodes/podcast_aggregators/` (rename via `git mv`); class rename `PodcastIndex` → `PodcastAggregator`; new `itunes.py`.
- `episodes/podcast_aggregators/factory.py` — reads `RAGTIME_PODCAST_AGGREGATORS`; supports `apple_podcasts` / `itunes` alias.
- `episodes/agents/download_tools.py` — import + docstring updates for the renamed package.
- `episodes/tests/test_fetch_details_agent.py` — new.
- `episodes/tests/test_fetch_details_tools.py` — new.
- `episodes/tests/test_fetch_details_step.py` — rewritten for the new orchestrator.
- `episodes/tests/test_podcast_aggregators.py` — renamed + iTunes coverage.
- `episodes/tests/test_models.py` — assertion updates for new Episode columns.
- `ragtime/settings.py` — `RAGTIME_PODCAST_INDEXES` → `RAGTIME_PODCAST_AGGREGATORS`.
- `.env.sample` — env var rename + iTunes mention.
- `core/management/commands/_configure_helpers.py` — section renamed; `PODCAST_INDEXES` → `PODCAST_AGGREGATORS`.
- `core/tests/test_configure.py` — comment-only updates for the section rename.
- `README.md` — pipeline-summary line for Fetch Details rewritten.
- `doc/README.md` — Fetch Details section rewritten with the agent / output schema / outcome table; podcast-aggregators section renamed; cross-linking note added.
- `doc/plans/2026-04-29-fetch-details-cross-linking.md` — already in repo.
- `doc/sessions/2026-04-29-fetch-details-cross-linking-planning-session.md` — already in repo.
- `doc/sessions/2026-04-29-fetch-details-cross-linking-implementation-session.md` — new.
- `CHANGELOG.md` — entry under `## 2026-04-29`.

The Excalidraw pipeline diagram (`doc/architecture/ragtime-processing-pipeline.svg`) is now stale — Fetch Details' external behavior changed (cross-linking, outcome taxonomy, per-run history). Flagged for manual regeneration.
