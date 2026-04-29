# Fetch Details Agent — Cross-Linking, Outcomes, Reports

**Date:** 2026-04-29

## Goal

Expand the Fetch Details step from "single LLM call on cleaned HTML" into a true investigator agent that can classify the submitted URL (canonical vs aggregator), cross-link between publisher sites and aggregators (Apple Podcasts, fyyd) when extraction is incomplete, decide a structured outcome, and produce both a concise message and a detailed agent report. Persist per-run history so admins (and a future Scott UI) can see what the agent did and why.

This PR is the *behavior expansion* on top of the SDK-swap landed in the previous Fetch Details PR. The follow-up after this PR introduces the LLM evaluation framework — see the linked issue.

## Scope

**In scope:**
- Cross-linking agent loop with three keyless tools (`fetch_url`, `search_apple_podcasts`, `search_fyyd`).
- New `FetchDetailsRun` table with full per-run history.
- New `Episode` columns: `canonical_url`, `source_kind`, `aggregator_provider`, `audio_format`, `country`. Drop `Episode.scraped_html`.
- Five-outcome taxonomy with run-level discriminator.
- Structured agent output (`FetchDetailsOutput { details, report, concise }`).
- Rename `episodes/podcast_indexes/` → `episodes/podcast_aggregators/`; iTunes inside; env var renamed.
- Drop legacy `processing.py` shim calls from the new step (module itself untouched — other steps still use it).
- Drop the fast-path skip and the empty-field-only merge.
- Admin UI: new fieldset on `EpisodeAdmin`, latest-run summary block, inline run table, dedicated `FetchDetailsRunAdmin` page.
- Doc deliverables per `CLAUDE.md`.

**Out of scope (deferred):**
- LLM evaluation framework (DeepEval, dataset YAML, CI workflow, VCR cassettes, `agent_config_hash`). Captured in the eval follow-up issue.
- Browser tools (Playwright) inside fetch_details. Stays the download agent's job.
- Spotify support. Add when iTunes coverage proves insufficient.
- Cost tracking on `FetchDetailsRun`. Token usage retained as raw `usage_json` only.
- Light retry on `unreachable`. Revisit when Scott UI lets end-users paste URLs.

## Decisions

### Agent control flow

- **Single Pydantic AI agent loop.** LLM gets system prompt + user message + 3 tools + `output_type=FetchDetailsOutput`. LLM calls tools freely; loop ends with structured output. No code-driven sequence, no Pydantic AI graph.
- **Goal-stated + constraints prompt style.** Tell the agent its job, what counts as success, what to avoid. Don't script tool order. Strawman prompt locked for v0; iteration is the eval PR's job.
- **Hybrid cross-linking.** Agent actively bridges canonical ↔ aggregator when extraction from the submitted URL alone is incomplete.

### Tools

Keyless only. Three tools live in `episodes/agents/fetch_details_tools.py`:

1. `fetch_url(url) -> cleaned_html` — httpx + BeautifulSoup. The agent can fetch any URL, including a cross-linked one.
2. `search_apple_podcasts(show, episode_title) -> list[ItunesEpisodeCandidate]` — iTunes Search API. Free, no auth.
3. `search_fyyd(show, episode_title) -> list[FyydEpisodeCandidate]` — reuses existing keyless mode of `episodes/podcast_aggregators/fyyd.py`.

No Playwright in this PR. No podcastindex.org (key required). No web search. No download_file / intercept_audio_requests / screenshot tools — those belong to the download step.

### Outcome taxonomy

| # | Outcome | Episode.Status | FetchDetailsRun.outcome | Notes |
|---|---|---|---|---|
| 1 | `ok` | `DOWNLOADING` | `ok` | required fields filled, `audio_url` known, confidence high |
| 2 | `partial` | `DOWNLOADING` | `partial` | required fields filled, `audio_url` missing or low confidence; report fed forward to download |
| 3 | `not_a_podcast_episode` | `FAILED` | `not_a_podcast_episode` | terminal, user-error class |
| 4 | `unreachable` | `FAILED` | `unreachable` | network/HTTP fetch failed |
| 5 | `extraction_failed` | `FAILED` | `extraction_failed` | page loaded, plausibly an episode, but title couldn't be extracted |

Terminal outcomes 3 and 5 stay separate so the future UI can give specific feedback. Single `Episode.Status.FAILED` with discrimination on `FetchDetailsRun.outcome` — no new `Episode.Status` values.

### Recovery

There is no recovery agent (subsumed into Download in a previous PR; `processing.py` is now a no-op shim). No retry on `unreachable` for now. Revisit when end-user URL paste is added to Scott.

### Agent output schema

```python
class AttemptedSource(BaseModel):
    source: Literal["user_url", "itunes", "fyyd", "cross_link"]
    url_or_query: str
    outcome: Literal["ok", "no_results", "error", "skipped"]
    note: str = ""

class FetchDetailsReport(BaseModel):
    attempted_sources: list[AttemptedSource]
    discovered_canonical_url: bool
    discovered_audio_url: bool
    cross_linked: bool
    extraction_confidence: Literal["high", "medium", "low"]
    narrative: str                          # 2-4 sentences for humans
    hints_for_next_step: str                # for the download agent

class ConciseMessage(BaseModel):
    outcome: Literal["ok", "partial", "not_a_podcast_episode",
                     "unreachable", "extraction_failed"]
    summary: str                            # 1-sentence headline; ≤140 chars

class EpisodeDetails(BaseModel):
    title: str | None
    description: str | None
    published_at: date | None
    image_url: str | None
    audio_url: str | None
    audio_format: Literal["mp3", "m4a", "aac", "ogg", "wav", "opus"] | None
    language: str | None                    # ISO 639-1 (lowercase)
    country: str | None                     # ISO 3166-1 alpha-2 (lowercase)
    guid: str | None
    canonical_url: str | None               # str + http(s):// validator, not HttpUrl
    source_kind: Literal["canonical", "aggregator", "unknown"]
    aggregator_provider: str | None         # free string + whitelist normalize helper

class FetchDetailsOutput(BaseModel):
    details: EpisodeDetails
    report: FetchDetailsReport
    concise: ConciseMessage
```

The concise message is a separate LLM-emitted field, not a truncated narrative — humans frame headlines differently from bodies, and the outcome enum is a structured commitment we want from the LLM directly.

`aggregator_provider` initial whitelist (free string with normalize helper at write time):
`apple_podcasts | spotify | fyyd | overcast | pocketcasts`.

### Data model

#### `Episode` — new columns

```python
class SourceKind(models.TextChoices):
    CANONICAL = "canonical"
    AGGREGATOR = "aggregator"
    UNKNOWN = "unknown"

source_kind = models.CharField(max_length=20, choices=SourceKind.choices,
                               default=SourceKind.UNKNOWN, blank=True)
aggregator_provider = models.CharField(max_length=50, blank=True, default="")
canonical_url = models.URLField(max_length=2000, blank=True, default="")
audio_format = models.CharField(max_length=10, blank=True, default="")
country = models.CharField(max_length=2, blank=True, default="")
```

#### `Episode` — dropped

- `scraped_html` (column + migration). HTML now lives in `tool_calls_json` per-tool-call snippets on `FetchDetailsRun`.

#### `FetchDetailsRun` — new table

```python
class FetchDetailsRun(models.Model):
    episode = models.ForeignKey(Episode, on_delete=models.CASCADE,
                                related_name="fetch_details_runs")
    run_index = models.PositiveIntegerField()  # 1, 2, 3… per episode

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    model = models.CharField(max_length=100, default="")

    class Outcome(models.TextChoices):
        OK = "ok"
        PARTIAL = "partial"
        NOT_A_PODCAST_EPISODE = "not_a_podcast_episode"
        UNREACHABLE = "unreachable"
        EXTRACTION_FAILED = "extraction_failed"

    outcome = models.CharField(max_length=30, choices=Outcome.choices,
                               blank=True, default="")

    output_json = models.JSONField(null=True, blank=True)
    tool_calls_json = models.JSONField(default=list, blank=True)
    usage_json = models.JSONField(null=True, blank=True)

    error_message = models.TextField(blank=True, default="")  # only when no structured output

    dbos_workflow_id = models.CharField(max_length=200, blank=True,
                                        default="", db_index=True)

    class Meta:
        unique_together = [("episode", "run_index")]
        indexes = [
            models.Index(fields=["episode", "-run_index"]),
            models.Index(fields=["outcome"]),
            models.Index(fields=["-started_at"]),
        ]
```

Notes:
- Single `output_json` column; field-level Postgres JSONB queries are sufficient.
- `tool_calls_json` is auto-captured from Pydantic AI's run messages — separate from the agent's self-narrated `attempted_sources`. LLM self-narration is interpretation; the trace is fact.
- `usage_json` keeps raw Pydantic AI usage; no extracted token columns this PR (defer to eval / cost work).
- No `latest_run` FK on `Episode` — always query via the related manager to avoid staleness.
- `dbos_workflow_id` captured from `DBOS.workflow_id` at orchestrator entry; passed in as argument from the `@DBOS.step()` wrapper to keep the orchestrator DBOS-import-free.

### Behavior

- **Agent output is authoritative.** Orchestrator overwrites Episode fields directly. No empty-field-only merge. Re-run will overwrite — that's correct given there's no re-run flow with admin-edited values today.
- **No fast-path skip.** Dropped — there's no `NEEDS_REVIEW` path that produced its precondition.
- **No HTML caching on Episode.** Per-tool-call HTML snippets (capped ~5 KB) live in `tool_calls_json` on `FetchDetailsRun`.
- **Re-run via existing `reprocess` admin action.** `run_index` increments naturally.

### File / module layout

```
episodes/
├── agents/
│   ├── _model.py                          (existing)
│   ├── fetch_details.py                   (expand: schemas, prompt, agent factory)
│   ├── fetch_details_tools.py             (NEW)
│   └── fetch_details_deps.py              (NEW)
├── fetch_details_step.py                  (rewrite orchestrator)
├── podcast_aggregators/                   (RENAMED from podcast_indexes/)
│   ├── __init__.py
│   ├── base.py                            (rename PodcastIndex → PodcastAggregator)
│   ├── factory.py                         (uses RAGTIME_PODCAST_AGGREGATORS)
│   ├── fyyd.py
│   ├── itunes.py                          (NEW)
│   └── podcastindex.py                    (used by download only)
└── tests/
    ├── test_fetch_details_step.py         (expand)
    ├── test_fetch_details_agent.py        (NEW — TestModel-based)
    └── test_fetch_details_tools.py        (NEW — mocked HTTP)
```

This layout puts everything fetch_details-specific under either the `episodes/agents/fetch_details*` glob or `episodes/tests/test_fetch_details*` glob, so the eval workflow's path filter (in the follow-up issue) is concise.

### DBOS

- One `@DBOS.step()` wraps the orchestrator (same shape as today). No per-tool DBOS steps — would couple tools to DBOS, violate the agent module's purity rule, and the cost of replay-on-crash is small (cents).
- `dbos_workflow_id = DBOS.workflow_id` read in the wrapper, passed as argument into the orchestrator.
- `_raise_if_failed(...)` typed-exception pattern preserved at the end of the step wrapper.

### Admin UI

- **`EpisodeAdmin`**: new "Source" fieldset for new columns; latest-run summary block at the top (outcome badge + concise summary + report narrative + hints); inline `TabularInline`-style runs table; existing `reprocess` admin action handles re-run unchanged.
- **`FetchDetailsRunAdmin`** (new): collapsible sections — Concise / Report / Details / Tool calls / Raw payloads (`output_json`, `usage_json`, `dbos_workflow_id` link).
- Implementation: admin-pattern `mark_safe()` callables. No custom Jinja view in this PR.

### Migration

Single migration file `0NNN_fetch_details_cross_linking.py` covering:
- Add `FetchDetailsRun` table.
- Add Episode columns: `canonical_url`, `source_kind`, `aggregator_provider`, `audio_format`, `country`.
- Drop `Episode.scraped_html`.

Pre-prod, so no data preservation needed.

### Env / config

- **No new env vars.** iTunes and fyyd are keyless.
- **Rename**: `RAGTIME_PODCAST_INDEXES` → `RAGTIME_PODCAST_AGGREGATORS`. Update `.env.sample` and `core/management/commands/configure.py`.
- Existing `RAGTIME_FETCH_DETAILS_MODEL` and `RAGTIME_FETCH_DETAILS_API_KEY` unchanged.

## System prompt (v0 strawman)

```
You are a podcast episode metadata investigator.

Inputs:
  - One URL submitted by a user. It may be the publisher's canonical
    episode page, or an aggregator's page (Apple Podcasts, Spotify, etc.).

Your goal:
  1. Determine whether the URL is a podcast episode page at all.
  2. Extract the episode's metadata: title, description, language,
     country, image, published date, audio URL, audio format, GUID.
  3. Classify the URL's source_kind (canonical | aggregator | unknown)
     and the aggregator_provider when applicable.
  4. When extraction is incomplete from the submitted URL alone, use
     your tools to cross-link: an Apple Podcasts URL often advertises
     a canonical URL; a canonical URL with no extractable audio can
     often be found by title+show on iTunes Search or fyyd.
  5. Produce a faithful structured report (what you tried, where each
     value came from, and your honest confidence).

Tools:
  - fetch_url(url): fetches and cleans HTML.
  - search_apple_podcasts(show, episode_title): iTunes Search API.
  - search_fyyd(show, episode_title): fyyd directory search.

Constraints:
  - Use tools only when they help. Redundant calls are a quality regression.
  - Do NOT guess audio URLs you didn't see in a tool result.
  - Use extraction_confidence=high ONLY when you have audio_url AND title
    AND a clear source_kind classification.
  - URLs returned must be absolute (http:// or https://).
  - language: ISO 639-1 (lowercase). country: ISO 3166-1 alpha-2 (lowercase).
  - audio_format: mp3 | m4a | aac | ogg | wav | opus.

Outcome decision rules:
  - ok: required fields filled, audio_url known, confidence high.
  - partial: required fields filled, audio_url missing or low confidence.
  - not_a_podcast_episode: page loaded, but it's clearly a homepage,
    article, or non-episode page.
  - unreachable: HTTP fetch failed (set this when fetch_url errored).
  - extraction_failed: page loaded, seems like an episode, but title
    couldn't be confidently extracted.
```

User message at agent invocation: just `URL: <user_submitted_url>`.

## Tests in this PR

Correctness tests, not quality evaluation:

- `test_fetch_details_agent.py` — `TestModel`-based agent shape: output schema honored, all five outcome paths produce valid output, validators reject malformed input, `EpisodeDetails` field types honor closed `Literal`s.
- `test_fetch_details_tools.py` — per-tool unit tests with mocked HTTP (httpx-mock or responses): `fetch_url` clean-HTML behavior, iTunes search request shape and response parsing, fyyd reuse of existing keyless mode.
- `test_fetch_details_step.py` (expand) — orchestrator: status transitions per outcome, `FetchDetailsRun` row written correctly, `dbos_workflow_id` captured, `Episode` field overwrite per outcome, terminal vs advance state machine.

A small handful of `@pytest.mark.live` smoke tests against real LLMs + real URLs may be included, **skipped by default**, runnable with `pytest -m live` for local sanity checks. Not in CI.

## Documentation deliverables

Per `CLAUDE.md`:

- `doc/plans/2026-04-29-fetch-details-cross-linking.md` (this file).
- `doc/features/2026-04-29-fetch-details-cross-linking.md` (created during implementation).
- `doc/sessions/2026-04-29-fetch-details-cross-linking-planning-session.md` (this conversation, transcribed).
- `doc/sessions/2026-04-29-fetch-details-cross-linking-implementation-session.md` (created during implementation).
- `CHANGELOG.md` entry under `## 2026-04-29` (or implementation date).
- `README.md` and `doc/README.md` updates: pipeline summary mention of cross-linking + outcome taxonomy + new Episode fields.
- Excalidraw diagrams: flag for review (cross-linking changes the step's external behavior; diagram update may be warranted).

## Deferred to follow-up issue (eval PR)

- Hand-curated YAML dataset (~10-15 cases) covering all five outcomes + canonical/aggregator/cross-link mix; include 2-3 absolute-fact cases.
- Framework split: pytest for field-level metrics; DeepEval (gated marker) for prose quality.
- Path-filtered workflow `.github/workflows/fetch-details-eval.yml`:
  ```yaml
  paths:
    - episodes/agents/fetch_details*.py
    - episodes/agents/_model.py
    - episodes/fetch_details_step.py
    - episodes/podcast_aggregators/**
    - episodes/tests/test_fetch_details*.py
    - episodes/tests/fixtures/fetch_details/**
    - .github/workflows/fetch-details-eval.yml
  ```
  Plus `workflow_dispatch`.
- VCR cassettes for HTTP layer; LLM calls live.
- Decide: production model vs cheaper model in CI.
- Add `agent_config_hash = sha256(prompt + model + sorted_tool_names)[:16]` column to `FetchDetailsRun` for cross-version eval grouping.
- Reconsider light retry on `unreachable` once Scott UI lets end-users paste URLs directly.
