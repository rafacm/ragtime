# Fetch Details Agent — Planning Session

**Date:** 2026-04-28

**Session ID:** 1d70aa4f-1169-4aad-9453-5206dbd5a286

## Summary

Planning session for migrating the `Scrape` pipeline step to a Pydantic AI agent and renaming it to `Fetch Details`. The session walked the design tree branch by branch via `/grill-me`, resolving the agent shape (SDK swap, no tools yet), the rename scope (full rename, breaking change, except the model field), the module layout (`fetch_details_step.py` + `agents/fetch_details.py`), the config convention (Convention B with shared `_model.py` helper), the recovery agent's deprecation path (tools to be absorbed by `fetch_details` and `download` step-agents in subsequent PRs), the agent contract (Pydantic `EpisodeDetails` model with date validator and ISO-639 regex), test design (unit + eval, deferred to a future PR; no-Django agent purity rule), step-orchestrator behaviors to preserve (fast-path skip, empty-field-only merge), the PR shape (one PR, two commits), and concrete implementation specifics (RunPython status migration, helper signature, env-var inventory, Excalidraw flagging, CHANGELOG shape).

## Detailed conversation

### User

> Currently we have a podcast ingestion pipeline that is implemented in Python and uses the OpenAI API to make calls to an LLM. If the pipeline step "Download" fails, then a Pydantic AI-based agent kicks in and attempts to download the episode's MP3 file. From an architecture perspective we are mixing two approaches to call LLMs and if we want to implement an evaluation framework at a later stage it would be good to have an homogeneous LLM calling logic. So the idea would be to keep the pipeline in Python but we would be gradually replacing steps from OpenAI calls to Pydantic AI agents. The first step we would refactor with this approach would be the "Scrape" step. That step's name is currenty too implementation oriented and negative sounding. What we actually want in that step is to get the details of a podcast episode.

### Assistant

Read `episodes/scraper.py`, `episodes/agents/agent.py` (recovery agent), `episodes/providers/factory.py`, and `episodes/models.py` to understand the current shape: scrape is a deterministic two-step (HTML fetch + clean → single structured-output LLM call via `get_scraping_provider().structured_extract(...)`), with no tools or agent loop. The recovery agent is a separate Pydantic AI agent with a Playwright browser context, triggered via signal on scrape/download failures.

Asked the foundational question: what does "replace OpenAI calls with Pydantic AI agents" mean for a step that's currently a single-shot structured extraction? Three options:

- (a) SDK swap, same shape — keep deterministic HTML fetch in Python, replace only the LLM call with `Agent.run(...)` returning a Pydantic model. No tools, no loop. Buys homogeneous instrumentation and unified eval harness.
- (b) Genuinely agentic — give the agent tools (`fetch_html`, `find_audio_links`, etc.) and let it decide. Overlaps with the recovery agent's job.
- (c) Hybrid — single LLM call by default with tool fallbacks.

Recommended (a): the stated motivation is homogeneity for evals, not making scrape smarter. (a) delivers homogeneity with smallest blast radius and keeps the deterministic HTML pipeline reproducible (important for eval datasets — same input HTML must replay identically).

### User

> The underlying objective is that I want to change the current "Scrape" step which has very simple logic and expand it to find out more information about the podcast episode but we can do this once we have implemented (a). Nevertheless, there is already a SCRAPE_SYSTEM_PROMPT that we are using in the "Scrape" step. This prompt would then be moved to the Pydantic AI agent configuration.

### Assistant

Confirmed (a) with the existing `SCRAPE_SYSTEM_PROMPT` lifting cleanly into the Pydantic AI agent config. Future expansion (richer episode info gathering) is the real reason to put the agent shape in place now.

Moved to the rename. Surveyed every place "Scrape" appears: status enum (`Episode.Status.SCRAPING = "scraping"`), pipeline step list, file (`episodes/scraper.py`), function (`scrape_episode`), telemetry span (`@trace_step("scrape_episode")`), model field (`Episode.scraped_html`), env vars (`RAGTIME_SCRAPING_*`), provider factory (`get_scraping_provider`), prompt constants, tests, and the recovery agent's `can_handle` step-name literal.

Proposed `fetch_details` as the new name (parallels `download`, intent-oriented, survives future expansion). Laid out three rename-scope options: surface-only, full rename, full rename minus the model field. Recommended full rename minus the model field plus a one-release env-var alias.

### User

> Let's go with fetch_details as the name and for a full rename since we have not yet made any release. We need to add to the CHANGELOG that there is breaking change but that's all. We also need to make sure we update the Excallidraw diagrams mentioning this step and the documentation.

### Assistant

Locked in `fetch_details` and full rename. Noted doc surfaces to hit at implementation time: README pipeline table, `doc/README.md` step descriptions, `.env.sample`, `configure` wizard, Excalidraw files in `doc/` (manual-update flag).

Moved to the most load-bearing remaining decision: config convention. The codebase has two incompatible conventions — Convention A (provider triple: `_PROVIDER` + `_MODEL` + `_API_KEY`, used by scrape, summarize, extract, resolve, translate, embed) and Convention B (Pydantic AI colon-prefixed model string + API key, used by recovery agent). Picking the wrong one now means re-migrating later. Recommended Option 3 — adopt Convention B as the canonical shape for all future step-agents, extract `_build_model()` from `agents/agent.py` into a shared helper.

### User

> Let's go for option 3.

### Assistant

Locked in Convention B + shared model-builder helper. Moved to module layout. Today `episodes/agents/` is single-purpose (recovery only); generic names like `agent.py`, `deps.py`, `tools.py` become ambiguous once `fetch_details` joins. Surveyed three layouts: flat with disambiguating filenames, sub-packages per agent, and a split between step orchestration and the agent itself.

Recommended Layout 1 + (3b) split: rename `episodes/scraper.py` to `episodes/details.py` (step orchestration), put the agent in `episodes/agents/fetch_details.py` (pure agent, no DB/status logic), rename recovery files to `recovery_*.py`, add `_model.py` helper. Reasoning: separation of concerns (agent testable in isolation against fixed HTML), Layout 2 is overkill for SDK-swap agents that are ~30–50 lines, renaming recovery files is cheap now and pays off as soon as a second step migrates.

### User

> Why not rename episodes/scraper.py to episodes/fetch_details_step.py to be more explicit about what that module does?

### Assistant

Considered the consistency wrinkle (other current step files don't have `_step`: `scraper.py`, `downloader.py`, `transcriber.py`, etc.) and laid out three options: (A) `details.py` with no suffix (matches current convention but collides with `agents/fetch_details.py`), (B) `fetch_details_step.py` only — the suffix becomes a marker for migrated-to-agent-pattern step files, (C) rename all the others now for consistency.

Recommended Option B: the `_step` suffix encodes load-bearing information ("this file pairs with an agent at `agents/<name>.py`"); avoids the import-collision risk; inconsistency is temporary and self-documenting; doesn't bundle eight unrelated renames into a PR whose stated purpose is "migrate scrape to Pydantic AI."

### User

> Option B

### Assistant

Locked in Layout 1 + (3b) + Option B suffix. Read `episodes/recovery.py` to understand the current scrape-failure recovery flow. `AgentStrategy.can_handle()` is hardcoded to `event.step_name in ("scraping", "downloading")`. After rename, this string flips to `"fetching_details"`.

Asked: with `fetch_details` becoming a Pydantic AI agent, do these two agents' roles overlap or stay distinct? Recommended keeping them strictly distinct: `fetch_details` takes cleaned HTML and returns metadata (no tools); recovery takes URL + failure context and uses Playwright/screenshots/etc. The shared `_model.py` helper is the only unification needed. Listed concrete changes: update `can_handle` literal, don't merge the agents, don't let `fetch_details` ingest browser tools later without revisiting the boundary.

### User

> We will move functionality from the Recovery Agent to the new agent-based Fetch Details agent by providing tools to the Fetch Details agent like browser use. So the whole Recovery Agent logic will go away in a subsequent PR.

### Assistant

Updated mental model: recovery agent is on a deprecation path. For *this* PR the SDK swap stays unchanged — fetch_details is tools-less; recovery stays operative; `can_handle` literal updates. Implications captured for the plan/feature doc: don't add features to recovery; the deprecation path is "as each step that currently triggers recovery (scrape, download) migrates to a Pydantic AI agent and absorbs the relevant browser/recovery capabilities, the corresponding `can_handle` branch dies; when both branches are gone, delete `recovery.py`, `agents/recovery_*.py`, `RAGTIME_RECOVERY_AGENT_*` env vars, `RecoveryAttempt` model + migrations." Flagged that the future fetch_details agent will conflate metadata extraction and audio-URL recovery; future PRs may want to split them again.

Re-asked Question 6 (still open): given recovery is on a deprecation path, do we still rename recovery files in this PR? Two options: (i) yes, mechanical rename now, or (ii) leave them — code corpse not worth investing in. Recommended (i): deprecation timeline is unknown (could span multiple PRs); diff is mechanical and tiny; makes eventual deletion PR cleaner (`git rm episodes/agents/recovery*.py` is a one-liner); signals "transitional" via the prefix.

### User

> Regarding "One thing worth flagging", we will update the "Downloading" step in a future PR to be an agent that can handle the case when the URL is not available by taking on the current prompt and tools in the Recovery Agent and we will remove the Recovery Agent logic altogether.

### Assistant

Acknowledged the cleaner split: `fetch_details` owns "what is this episode, including where the audio lives" (metadata + URL discovery, with browser fallback once tools land); `download` owns "get the audio bytes onto disk by whatever means" (with browser/cookie/intercept fallback once tools land). This resolves the "two jobs in one agent" concern. Confirmed deprecation timeline involves at least two future PRs, strengthening the case for renaming the recovery files now.

Re-asked Question 6 cleanly.

### User

> Let's go with Option (i)

### Assistant

Locked in Option (i). Moved to the agent's contract: input, output Pydantic model, location.

7a — Output type: recommended Option α (required + Optional, mirrors current "must produce all keys, may be null") with `date | None` for `published_at` (Pydantic validator parses YYYY-MM-DD), regex-constrained `language: str | None`, plain `str | None` for URLs (preserves relative-URL tolerance from the current prompt — `HttpUrl` would reject those).

7b — Run signature: `async def run(html: str) -> EpisodeDetails`. No deps object yet (would be needed once tools land). Step orchestrator does the asyncio bridging.

7c — Pydantic model location: inside `episodes/agents/fetch_details.py` next to the agent. Lifting it into `models.py` muddles persistence model with LLM output schema.

Sketched the agent module skeleton.

### User

> Agree. One additional piece of information. Once we refactor the Find Details as an agent we will build in a subsequent PR tests around that step that are executed for every change we push to the repository. This means that we will want to run the agent without DBOS whatsoever in those tests.

### Assistant

Noted what the constraint already implies (mostly satisfied) and what it changes:

1. Agent module purity: imports only Pydantic AI, Pydantic, stdlib, `agents/_model.py`. No Django/DBOS. Tests can `from episodes.agents.fetch_details import run, EpisodeDetails` without booting Django.
2. Lazy agent construction (build agent on first `run()` call, memoized); recovery agent's `_build_agent()` already does this — same pattern.
3. `agents/_model.py` test seam: recommended Pydantic AI's `agent.override(model=TestModel())` as the idiomatic mechanism. Means `get_agent()` factory in `agents/fetch_details.py` is the one place that reads settings, and tests bypass via `Agent.override`.
4. Telemetry hookup: must be conditional and lazy — don't call `telemetry.is_enabled()` at module import.

Asked Question 8: test shape — unit-style (TestModel, fast, free, every push), eval-style (real LLM, fixtures, regression detection), or both? Recommended both with unit tests as default `manage.py test` target and eval tests gated by path filter or schedule. Sub-questions 8a (this PR or future for fixture stub) and 8b (CI API key path).

### User

> We will go with both types of tests but not in this PR. We will tacke this in a future PR.

### Assistant

Defer test shape to a future PR; this PR just makes the design support both via purity + lazy agent + override seam.

Read `episodes/workflows.py`. Confirmed `STEP_FUNCTIONS` uses string-based dynamic import — dispatcher update is a one-liner. `PIPELINE_STEPS` in `models.py` also updates.

Asked Question 9: reprocess and partial-fill behavior. Two non-obvious behaviors in current `scrape_episode`: fast-path skip (admin reprocess after needs_review skips LLM if all required fields filled) and empty-field-only merge (never overwrite human edits). Both are step orchestration, not agent logic. Three sub-decisions: keep fast-path skip, keep empty-field-only merge, place both in `fetch_details_step.py`. Recommended keeping both behaviors and locating them in the step file. Asked for `scraped_html` field rename preference.

### User

> 9: keep behaviors and keep fetched_html since we will refactor it in a subsequent PR.

### Assistant

Confirmed reading: defer model field rename — `Episode.scraped_html` stays as-is in this PR; the new step file just continues to read/write that attribute. Full-rename exception list is now: `Episode.scraped_html` (deferred), model column (also deferred). Everything else still renames.

Asked Question 10: PR shape. Three options — one PR with two commits, two PRs sequenced, one PR with one commit. Recommended Option I (one PR, two commits): two PRs doubles the doc overhead (CLAUDE.md mandates plan + feature + planning session + implementation session per change); rename and agent migration are causally linked; two commits inside one PR preserves rebase-friendly atomic units (project uses rebase strategy); single CHANGELOG entry is more accurate. Sub-decisions: branch name `feature/fetch-details-agent`; delete `get_scraping_provider` in this PR (pre-prod, no external callers).

### User

> yes

### Assistant

Locked in Option I + branch name + delete factory. Moved to Question 11 — three concrete implementation specifics bundled.

11a — Status enum migration: recommended (ii) RunPython data migration (`Episode.objects.filter(status="scraping").update(status="fetching_details")` and likewise for `ProcessingStep.step_name`). Cheap, atomic with the code change.

11b — `agents/_model.py` helper signature: recommended (β) pure function `build_model(model_string, api_key)`. Settings-reading happens outside the agent module, in the `get_agent()` lazy factory. Recovery agent's existing `_build_model()` gets refactored: settings-reading stays in its module's factory; model construction moves to `_model.py`.

11c — Env var inventory: drop `RAGTIME_SCRAPING_PROVIDER`, replace `RAGTIME_SCRAPING_MODEL` with `RAGTIME_FETCH_DETAILS_MODEL=openai:gpt-4o-mini` (colon-prefix), rename `RAGTIME_SCRAPING_API_KEY` to `RAGTIME_FETCH_DETAILS_API_KEY`. Updates in settings.py, .env.sample, configure wizard. Leave per-step API key sharing pattern as-is.

### User

> yes

### Assistant

Locked in 11a/b/c. Found three Excalidraw files in `doc/architecture/`: `ragtime-processing-pipeline.excalidraw`, `ragtime-processing-pipeline-with-recovery.excalidraw`, `ragtime-recovery.excalidraw` (each with sibling `.svg` render).

Asked Question 12: four small final cleanup items.

12a — Env-var naming: recommended (α) no `_AGENT` suffix on `RAGTIME_FETCH_DETAILS_*` (the `_AGENT` exists on recovery only because there are non-agent recovery vars — `_ENABLED`, `_TIMEOUT`, `_CHAIN`). Sets the precedent for future step-agents.

12b — Excalidraw flagging: section in feature doc listing files and changes; line in CHANGELOG; PR description checkbox. This PR updates two diagrams (pipeline + pipeline-with-recovery) for the rename; recovery diagram needs review for "scraping" labels.

12c — CHANGELOG entry shape: dated section under `## 2026-04-28`, `### Changed` with `**BREAKING**` marker, `### Added`, `### Removed`, links to plan + feature + sessions.

12d — Plan/feature filename stem: `2026-04-28-fetch-details-agent`. Resulting paths for plan, feature, and both session transcripts.

### User

> yes

### Assistant

Locked in 12a/b/c/d. Wrote a consolidated plan summary covering: architecture intent, scope, module layout, agent contract, shared model helper, step orchestrator, configuration, recovery interaction, workflow integration, status migration, tests, PR shape, doc deliverables, diagrams to update, and open items for future PRs. Asked whether to save the plan + planning-session transcript per CLAUDE.md.

### User

> go ahead

### Assistant

Recovered the session UUID (`1d70aa4f-1169-4aad-9453-5206dbd5a286`) from the Claude Code project session log directory. Wrote `doc/plans/2026-04-28-fetch-details-agent.md` and this planning session transcript.
