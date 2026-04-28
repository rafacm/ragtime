# Download Agent and Recovery Removal — Planning Session

**Date:** 2026-04-28

**Session ID:** feb4fa49-bab7-41e3-bfdc-f9285276dc87

## Summary

Planning session that walked the design tree branch by branch via `/grill-me`, starting from the question "do `ProcessingRun`, `ProcessingStep`, `PipelineEvent`, `RecoveryAttempt` duplicate something DBOS provides already?" and resolving:

- The granularity-and-trim entanglement in the DBOS workflow (one explicit step per pipeline phase + drop bookkeeping steps + drop the parallel Django state machine).
- Collapsing the recovery layer into the `Download` step by making `Download` a Pydantic AI agent (mirroring the `Fetch Details` migration in PR #107).
- Adding podcast indexes (fyyd, podcastindex.org) as an agent-visible tool to handle publishers like ARD Sounds whose audio URL is hidden behind interactive UI — verified concretely by fetching fyyd's API for the user's example episode (Django Reinhardt / WDR Zeitzeichen) and confirming a clean Akamai enclosure URL is returned.
- Relaxing fetch-details `REQUIRED_FIELDS` to `("title",)` only, plus adding `Episode.guid` extraction as a hint for index lookup.
- A 3-tier download cascade (`wget` → podcast index → Playwright agent) with cheap-path-first semantics.
- Deleting `ProcessingRun`, `ProcessingStep`, `PipelineEvent`, `RecoveryAttempt` entirely; using DBOS as state-of-truth; encoding success/failure detail as structured return values and custom exceptions (the only persistent-with-step idiom DBOS supports).
- Single-PR-with-multiple-commits shape per the user's solo-developer preference.

## Detailed conversation

### User

> Does DBOS offer a way to see the running workflows locally? Is there a Django plugin that would expose this information via the Django admin or UI interface?

### Assistant

Web-searched DBOS docs for local workflow visibility and Django integration. Surfaced four mechanisms:

1. CLI: `dbos workflow list`, `dbos workflow get <id>`, `dbos workflow steps <id>`, `dbos workflow queue list`, `dbos workflow cancel/resume/fork`. Reads the same Postgres tables DBOS already maintains.
2. Programmatic: `DBOS.list_workflows()`, `DBOS.list_workflow_steps()` — same data through the Python API.
3. Admin Server: a local REST endpoint DBOS exposes alongside the app process; same data again.
4. DBOS Conductor: a self-hostable web UI (Docker image `dbosdev/conductor`) with workflow + queue dashboards, cancel/resume/fork buttons. Caveat: Conductor is proprietary, free for dev, requires a license key for commercial production use.

For Django integration: no first-party or community plugin exists (`django-dbos` / `dbos-django` searches return nothing relevant; `django-admin-workflow` and `django-workflows` are unrelated FSM libraries). Recommended path: use the CLI for quick checks, run Conductor in Docker if a UI is wanted, or roll a thin Django admin wrapper backed by `DBOS.list_workflows()` (~50–80 lines).

### User

> /grill-me — In the Django app we currently model pipeline events and processing runs, isn't this something that DBOS provides already?

### Assistant

Read `episodes/models.py` (lines 205–339), `episodes/workflows.py`, and surveyed callers. Decomposed the question by model:

- `ProcessingRun`: ~80% subsumed by DBOS workflow records. The remainder: FK to `Episode` (admin convenience) and the partial unique constraint `unique_running_run_per_episode` (race guard).
- `ProcessingStep`: subsumed *at the wrong granularity*. The Django step name is the user-facing pipeline phase (`DOWNLOADING`, `TRANSCRIBING`); DBOS sees `create_run_step`, `execute_pipeline_step`, `is_run_still_active` — internal plumbing. Reconstructing pipeline-phase status from DBOS records requires inspecting `execute_pipeline_step`'s `step_name` argument across calls.
- `PipelineEvent`: not subsumed. Carries `error_type`, `http_status`, `cached_data` for the recovery agent. Domain telemetry, not workflow plumbing.
- `RecoveryAttempt`: not subsumed. Encodes human-in-the-loop semantics (`awaiting_human`, `resolved_by`, strategy `"agent"`). Different concern.

Asked Q1: what's driving the question — delete all, trim some, or sanity-check? Recommended **trim**: drop `ProcessingRun` + `ProcessingStep`, keep `PipelineEvent` + `RecoveryAttempt` since they encode features.

### User

> Can we update the DBOS integration to fix the granularity mismatch you reported so that the DBOS workflow reflects the same steps as the pipeline?

### Assistant

Yes — replace the dynamic-dispatch `execute_pipeline_step(episode_id, step_name)` (which uses `importlib` to look up a string-keyed function path, so DBOS sees one step name 8 times with different inputs) with one explicit `@DBOS.step()` per pipeline phase: `fetch_details_step`, `download_step`, `transcribe_step`, etc. Then `dbos workflow steps <id>` shows those names directly.

But surfaced the catch: even after renaming, the trace still has bookkeeping noise (`create_run_step`, `is_run_still_active`, `did_step_complete`, `mark_run_failed`, `get_pending_resume_step`, `mark_queued`) interleaved with the real steps. Those bookkeeping steps exist *only* to maintain `ProcessingRun`/`ProcessingStep` rows. So granularity and trim are entangled.

Asked Q2: granularity-only / trim-only / both? Recommended **both** — they're cheap together, and the only state worth converging on is "DBOS trace == `PIPELINE_STEPS`." Flagged the `unique_running_run_per_episode` constraint as the non-trivial concern and `did_step_complete`'s "silently-returned step" semantic as code smell to verify.

### User

> Can you reload the local resources you have in the context? I've merged a PR and pulled the changes.

### Assistant

Ran `git branch --show-current`, `git log --oneline -10`, and `git status`. Confirmed we were now on `main` with PR #107 merged (latest commit `1629383`). Re-ran `grep` on `models.py` and `wc -l` on `workflows.py` — both unchanged in structure. Q1/Q2 analysis still applied.

### User

> Additionally, we want to get rid of the Recovery logic and move this logic instead to the "Download" step and make that step an agent like we have done with the "Fetch Details" step.

### Assistant

Read `episodes/downloader.py`, `episodes/fetch_details_step.py`, `episodes/recovery.py`, `episodes/agents/recovery.py`, and `episodes/events.py` to understand the full recovery surface. Sketched what gets deleted (recovery.py, recovery agent module cluster, `RecoveryAttempt`, `run_agent_recovery` workflow, `step_failed` signal, `RAGTIME_RECOVERY_*` settings) vs. what changes shape (`download_episode` becomes the agent driver: cheap path → agent fallback).

Surfaced the load-bearing detail the user hadn't addressed: the recovery agent's `can_handle` returns true for *both* `fetching_details` and `downloading` (recovery.py:48). After collapsing recovery into download, fetch-details has no fallback. Asked Q1: accept the loss, relax fetch-details to advance with title-only, or make fetch-details also an agent? Recommended **relax fetch-details** (drop `audio_url` from `REQUIRED_FIELDS`) — the download agent is already good at finding audio URLs; pushing that responsibility into the download step gives one place that owns "where is the audio."

### User

> I'm also thinking that we could try and use podcast indexes like: https://fyyd.de/, https://podcastindex.org/ or similar (configurable) to see if we can download the episode's audio from those pages. In the case of ARD podcast episodes like this one https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/ it is proving quite challenging to download the audio by the recovery agent.

### Assistant

Acknowledged: indexes are a deterministic, cheap fallback that bypasses the publisher entirely by reading the RSS-feed enclosure the publisher already submitted. Both APIs are usable (podcastindex.org open + GUID search; fyyd German-podcast-heavy, useful for ARD).

Asked Q2: where in the cascade does the lookup live?

- (a) Pre-agent deterministic tier: `wget` → indexes deterministically → agent only on miss.
- (b) Agent-visible tool: agent has `lookup_podcast_index` alongside `find_audio_links`, etc.
- (c) Separate pipeline step before download.

Recommended **(a)** — cheapest tool first, cleaner separation (the agent's job is "browse and click on a publisher's site"; indexes have nothing to do with that). Outlined the resulting flow: `wget known URL` → `query indexes in order` → `agent` → `FAILED`.

### User

> I agree with (b)

### Assistant

Accepted (b) — agent-visible tool. Noted the trade-off (cost-efficiency for agent flexibility) and that the user's ARD example justified giving the agent more tools rather than bypassing it.

Asked Q3: with (b), does the agent run on every download or only after a cheap-path attempt?

- (b1) Always-agent: download step is just "invoke agent"; agent has `wget` as one of its tools.
- (b2) Cheap path first, then agent: mirrors `fetch_details_step.py:95-99`'s `_has_required_fields` short-circuit; if `episode.audio_url` is set, `wget` directly; otherwise invoke agent.

Recommended **(b2)**. Reasons: cost (most episodes have a working `audio_url` from fetch-details — agent overhead is wasted on the happy path); latency (wget is sub-second, agent is 5–30s with browser startup + LLM round-trips); consistency with fetch-details (PR #107 also cheap-paths).

### User

> b2

### Assistant

Locked in (b2). Asked Q4: tool granularity and inputs.

- Axis 1 (granularity): one generic `lookup_podcast_index(...)` that fans out to all configured indexes, vs. one tool per index.
- Axis 2 (inputs): which identifiers — title, show, GUID, feed URL?

Compared the two index APIs: podcastindex.org supports search-by-term, by-GUID, and by-feed-URL; fyyd supports search-by-title and feed-URL but no GUID search. Recommended one generic tool with `(title, show_name, guid)` inputs, plus a coupled fetch-details schema bump to extract `Episode.guid` (small migration, large payoff for non-English shows where transliteration breaks title-only matching).

Asked Q4a (generic vs. one-per-index) and Q4b (add `Episode.guid`?).

### User

> Agreed.

### Assistant

Both Q4a (generic tool) and Q4b (`Episode.guid` field + extraction) confirmed. Moved on to the original unresolved Q2 — the model-deletion question.

Asked Q5: how far do we trim?

- (a) Keep all three (`ProcessingRun`/`Step`/`PipelineEvent`); shrink `PipelineEvent` to drop recovery fields.
- (b) Drop all three; DBOS owns workflow state entirely.
- (c) Drop `ProcessingRun` + `ProcessingStep`, keep slimmed `PipelineEvent`.

Recommended **(b)**: with recovery deleted, `PipelineEvent`'s only structured consumer is gone; DBOS records what these tables record; the `unique_running_run_per_episode` constraint can be replaced by deterministic DBOS workflow IDs (`f"episode-{episode_id}-run-{n}"`); the granularity fix from Q2 falls out for free; manual retry becomes "enqueue with `from_step=...`" (same mechanism the deleted `run_agent_recovery` already uses for resume). Flagged the admin UX downgrade (would need a small ~50-line view that calls `DBOS.list_workflows`) as the only material concern.

### User

> Let's look at this episode https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/ , for instance. The download URL is not shown on the page HTML until one clicks on the three dots (marked with a red 1 and then on "Herunterladen" marked with a red 2 in the attached screenshot). But on the episode's page in fyyd.de https://fyyd.de/episode/13348642 the download URL is clearly visible.

### Assistant

Verified the architectural claim against fyyd's actual API. Fetched `https://api.fyyd.de/0.2/episode?episode_id=13348642` — returned the playable Akamai URL `https://wdrmedien-a.akamaihd.net/medp/podcast/weltweit/fsk0/323/3235880/3235880_60773677.mp3` in a single HTTPS GET. Confirmed: no Playwright, no LLM, no flakiness — that's the case for indexes in one screenshot.

Surfaced one refinement to Q4: the GUID mismatch. ARD's URN is `urn:ard:episode:fdcf93eef8395b35`; fyyd indexes the same episode under `/wdr_zeitzeichen_20250123_59f90c28.mp3` (a WDR media filename — the actual RSS GUID). Cross-platform GUID portability is therefore not guaranteed; title + show_name + published_at is the more reliable primary key, with GUID as a hint when present.

Re-asked Q5 (model deletion scope) since the user had redirected to ground the architecture. My recommendation remained (b) — full drop.

### User

> Let's go for (b). Where do we put the attempt to look up the episode's download url via a podcast index page in the "Fetch details" or on the "Download" step/agent?

### Assistant

(b) locked in for the model deletions. Answered the new question: **download.** Three reasons:

1. fetch-details has no signal about whether a URL works — it's HTML-to-data extraction; verification only happens when something tries to GET the URL, and that's download.
2. The index lookup is fundamentally a *fallback* in this design, not a primary source. Per Q1's option (b), fetch-details is allowed to finish with `audio_url` empty; download is *already* contractually responsible for that case. Adding "query index" is the natural way it discharges that responsibility — same code path that handles "URL was extracted but returns 404."
3. Clean separation: HTML extraction vs. file acquisition. Different concerns, different failure modes, different infra (BeautifulSoup vs. fyyd/podcastindex API clients).

Listed the resulting download agent toolset (`wget`, `lookup_podcast_index`, `find_audio_links`, `intercept_audio_requests`, click + screenshot tools, `download_file`). Flagged but recommended deferring the alternative: invoke indexes inside fetch-details *as a cheap path before the LLM* (skip LLM if index returns rich metadata). Defer because fetch-details is already cheap and the index miss rate is unknown — measure first, then decide.

### User

> Side question: is it possible to attach metadata to DBOS workflow steps and also add success or error details?

### Assistant

Web-searched DBOS docs (`docs.dbos.dev/python/tutorials/step-tutorial`, `docs.dbos.dev/python/reference/contexts`). Synthesized the answer: yes, but the idiom is different from what you might expect.

Per-step automatic recording: name, inputs, output (must be serializable), exception (class + message + traceback), step ID, attempt number, timing.

There is **no** `DBOS.add_step_attribute()` or `step.metadata = {...}` API. Two canonical patterns instead:

- **Pattern 1 — Return a structured result.** Whatever the step returns gets stored verbatim and is visible via `DBOS.list_workflow_steps()` / `dbos workflow steps <id>`. Showed example: `DownloadResult` dataclass with `success`, `source` (`wget` | `fyyd` | `podcastindex` | `agent`), `audio_url`, `bytes_downloaded`, `duration_seconds`, `candidates_tried`.
- **Pattern 2 — Raise a structured exception.** DBOS records the exception class + args. Custom exceptions with structured fields preserve the detail. Showed example: `DownloadFailed(error_type, http_status, sources_tried, message)`.

Adjacent APIs:

- `DBOS.set_event(key, value)` — workflow-scoped key/value channel; queryable via `get_event`. Useful for "current progress" state, not per-step records.
- `DBOS.write_stream(stream, value)` — append-only stream per workflow. Good for "log many progress entries during a long step."
- `DBOS.span` — current OpenTelemetry span; `span.set_attribute(...)` propagates to OTel collectors (Langfuse) but **not** to DBOS's own step record. Two stores, two query paths.

This strengthens the case for Q5(b): not only can DBOS replace the Django models, there's a clean idiom for attaching the structured detail those tables carried (success → return value, failure → custom exception). No information loss.

### User

> Let's do it then!

### Assistant

Pumped the brakes — this is a 4–5 PR effort that touches recovery, downloader, fetch-details, models, migrations, admin, env vars, and the DBOS workflow shape. Per `CLAUDE.md`, accepted plans go to `doc/plans/` and the planning session transcript goes to `doc/sessions/` before implementation starts; all work happens on a feature branch off `main`. Proposed a 5-PR sequence (`feature/episode-guid` → `feature/podcast-indexes` → `feature/download-agent` → `feature/remove-recovery-layer` → `feature/dbos-state-of-truth`), each independently reviewable.

### User

> Since I am a solo developer, I suggest you do 1 (save the accepted plan) and 2 (save the planning session). We will do the implementation in one issue and one PR with several commits since I am a solo developer.

### Assistant

Acknowledged — single PR with multiple commits. Found the session UUID by listing `~/.claude/projects/-Users-rafa-Develop-projects-ragtime/*.jsonl` modified in the last 2 hours and grepping for "fyyd / podcast index / recovery / grill" content; the unique match was `feb4fa49-bab7-41e3-bfdc-f9285276dc87.jsonl`. Confirmed `main` was clean and up-to-date, then created branch `feature/download-agent-and-recovery-removal`. Wrote `doc/plans/2026-04-28-download-agent-and-recovery-removal.md` and this session transcript. Implementation will follow as commits 2–8 on this same branch.
