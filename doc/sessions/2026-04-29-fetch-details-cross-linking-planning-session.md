# Fetch Details Cross-Linking — Planning Session

**Date:** 2026-04-29

**Session ID:** 256b5081-68e8-481e-bcdc-1494317b8319

## Summary

Designed the next iteration of the Fetch Details pipeline step: expand it from a single structured-output LLM call into a true investigator agent that classifies the submitted URL (canonical vs aggregator), cross-links between publisher sites and aggregators when extraction from one source is insufficient, decides one of five distinct outcomes, and produces both a concise message and a detailed agent report. Drove down each architectural fork — tools, output schema, persistence model, status taxonomy, agent control flow, file layout, admin UI — in a `/grill-me`-style interview format. Deferred LLM evaluation infrastructure to a follow-up issue but locked the file/directory structure so the eval workflow's path filter will be clean. Renamed `podcast_indexes/` → `podcast_aggregators/` and added iTunes (keyless iTunes Search API) alongside fyyd.

## Detailed conversation

### User

`/grill-me`

### Assistant

Asked what plan or design to be grilled on, since the slash-command was invoked without prior context.

### User

> In a previous PR we re-implemented the "Fetch Details" pipeline ingestion step as an agent with Pydantic AI. Can you review the current implementation of that step so that we get to a common understanding?

### Assistant

Read `episodes/agents/fetch_details.py`, `episodes/fetch_details_step.py`, and `episodes/agents/_model.py`. Summarized the existing two-file split: pure agent module with module-purity rule (no Django/DBOS imports), single structured-output LLM call, `EpisodeDetails` schema with `field_validator`s for ISO date and ISO 639-1 language, `@lru_cache`-memoized agent factory, no tools yet. The orchestrator owns status transitions, HTML fetch + clean (BeautifulSoup, 30 KB cap), fast-path skip when required fields are pre-filled, empty-field-only merge, completeness check, and error/recovery hand-off. `_model.py` provides shared model factory with credential isolation (env-scoped fallback for providers whose Pydantic AI submodule import fails).

Posed Question 1 about an apparent gap: the system prompt instructs the LLM to leave relative URLs as-is, but no orchestrator code resolves them with `urllib.parse.urljoin`. Asked if this is a real gap.

### User

> Big picture
> The current issue we have is that users can use several types of episodes URLs and we need to 1) find out what the canonical episode URL for the episode is and 2) find enough information about the episode that helps the next step in the pipeline (namely "Download") to be able to download the episode.
>
> This are some things I have noticed (please, push back if you have a different opinion):

### Assistant

Acknowledged and waited for the user to finish their list.

### User

[Request interrupted by user]

### User

> - episode pages hosted by the original producers of the episode (named "canonical episode URL" above) do not offer an easy way of downloading the episode's audio file. Some of them are quite old from an implementation perspective. See this one https://www.rtve.es/play/audios/jazz-porque-si/jazz-porque-si-040215/2979898/ where the player is at the bottom and the download is behind a "three vertical dots" UI component. Nevertheless, this episode is also available in the Apple podcasts website at https://podcasts.apple.com/es/podcast/jazz-porque-s%C3%AD-django-reinhardt-04-02-15/id301721801?i=1000466079630 which includes a link back to the canonical episode URL.
> Another example is https://www.ardsounds.de/episode/urn:ard:episode:fdcf93eef8395b35/ which is also available at Apple Podcasts https://podcasts.apple.com/de/podcast/der-mann-der-europa-den-jazz-brachte-django-reinhardt/id206817194?i=1000685079301
> - Apple podcasts offers the audio directly in the episode HTML page but it has the ".m4a" format and not ".mp3"
>
> What I would like from the "Fetch details" step agent is:
> 1) visit the URL and decide whether it is actually an episode podcast page -> if not the error accordingly
> 2) find details about language, country, title, description, ...
> 3) the agent should attempt to find out if this URL is the canonical episode URL for this podcast or if the website is a podcast indexing website: Apple Podcasts, Spotify, ...
> 4) attempt to find out the audio URL, whether MP3 or some other format
> 5) generate a concise human-readable message about what it did whether succeful or not. Also generate a human/agent-readable report with the details about what it did and what it tried and whether it was succesful retrieving all the needed information or not. We will feed this report to the next steps agent as an intial help. We also want to surface this human-readable concise message and report in the Django UI (this PR) and eventually in the Scott user front-end (future PR).
> 6) we want to build actual tests that will use actual episode URLs and actually call LLMs in CI/CD so we sant the tests to NOT trigger after each change but only for changes related to this step. We may want to use DeepEval for this.

### Assistant

Reframed Q1 around the foundational fork: when fetch_details detects an aggregator URL with a link to a canonical URL (or vice-versa), does the agent actively cross-link or just record what it found? Laid out three options — single-shot no cross-linking, active cross-linking inside fetch_details, or hybrid (cross-link only when primary extraction is incomplete). Recommended hybrid (option 3): keeps the common case cheap, puts the cross-linking logic where it's needed, naturally splits the report. Flagged scope creep risk: fetch_details takes audio-URL discovery from the download agent. Asked whether podcast-index lookup moves to fetch_details or stays in download.

### User

> Question 1: it actively cross-links, that's why it is an agent now! :) The step is called "Fetch details" and the fact that the provided URL is an aggregator URL and not the canonical URL is a detail of the Episode (which we may want to capture BTW).
> I like your hybrid option 3 proposal!
>
> What you say
> > the download agent currently owns ("download agent owns audio-URL discovery (cheap-path wget if   present, otherwise podcast-index lookup or Playwright browsing)"
> the problem is that this approach almost never works. We will refactor the "Download" step anyway in a subsequent PR after the current one we are working on.

### Assistant

Locked: hybrid cross-linking; capture canonical-vs-aggregator as Episode detail; download is being refactored next so we're not constrained by current download/fetch_details boundaries. Inspected the data model — `Episode` is flat, no per-step-run record exists, `error_message` is the only "what happened on the latest run" field, and `scraped_html` is overwritten on re-run.

Posed Q2 (output schema and where it lives). Three categories of output with different lifetimes: Episode-level facts (true regardless of which run produced them), per-run agent output (concise message + report), and status/error glue. Three options: all flat on Episode, split with `FetchDetailsRun` table, or generic `StepRun` model. Recommended split with dedicated `FetchDetailsRun` — recovery loops would otherwise overwrite diagnostic history. Resisted generalizing to `StepRun` — only one step needs this today. Sub-questions: are you OK adding the table, agree with the four new Episode columns, structured concise message with `outcome` enum + `summary`?

### User

> Let's add a FetchDetailsRun table this PR. Episode columns: agree with your proposal. We can add more in the future if needed. The concise human message: structured. Great suggestion!!

### Assistant

Locked: `FetchDetailsRun` + new Episode columns (`canonical_url`, `source_type`, `audio_format`, `country`) + structured concise message.

Posed Q3 (tool surface). Inventoried existing tools (the download agent has Playwright tools, `download_file`, `intercept_audio_requests`, `lookup_podcast_index`); flagged absence of an Apple/iTunes search tool. Recommended four-tool minimal set: `fetch_url` (httpx + BS4 as a tool), `browse_url` (Playwright), `search_apple_podcasts` (iTunes Search API — the key new tool), `lookup_podcast_index` (reuse existing). Excluded download_file/screenshots/intercept (download's job), web search (fragile), translate_text (not needed). Asked about the four-tool set and confirmed iTunes Search API as the keyless new tool.

### User

> One important point, I do not want to have to configure API keys for fyyd and podcastindex. If they are used by the agent in this step it should be via the browser and not via API.
> Regarding Playwright, are there lightweight alternatives we could use? Like https://agent-browser.dev/

### Assistant

Two-part response. (1) On podcast indexes via API — drop fyyd/podcastindex API access from fetch_details; iTunes Search API stays (no key). (2) On Playwright alternatives — was honest about not knowing `agent-browser.dev` enough to recommend. Pushed back on whether fetch_details needs a browser tool *at all* in this PR: walked through both example scenarios (rtve.es canonical, Apple Podcasts) and argued static httpx + iTunes search covers them — rtve.es metadata is in static HTML, Apple Podcasts is server-rendered for the relevant fields. Recommended zero browser tools in this PR: just `fetch_url` (static httpx) + `search_apple_podcasts` (iTunes). Trade-off: small minority of canonical pages will be empty without JS and get classified `partial`, picked up in download refactor.

### User

> Regarding what I said above about not needing API key: if it is possible to query their API without an API key then we can use that but API KEY related configuration should not be in the .env file.

### Assistant

Verified by reading `episodes/podcast_indexes/fyyd.py` and `episodes/podcast_indexes/podcastindex.py`. Confirmed: fyyd is keyless (optional key only raises rate limits, the existing code already supports `api_key=""`); podcastindex.org requires `api_key + api_secret` non-negotiably; iTunes Search API is keyless. Updated tool surface: `fetch_url` + `search_apple_podcasts` (iTunes) + `search_fyyd` (existing keyless mode). Dropped podcastindex from fetch_details. No browser tool.

Posed Q4 (outcome taxonomy). Five distinct outcomes worth being explicit about: `ok`, `partial`, `not_a_podcast_episode`, `unreachable`, `extraction_failed`. Sub-fork: does `partial` advance optimistically to `DOWNLOADING` (with the report) or stop at a new `NEEDS_REVIEW` status? Recommended advance optimistically — the whole point of report-as-input-to-next-agent is that downstream agents do more with partial state. Sub-question: keep `not_a_podcast_episode` and `extraction_failed` separate or collapse?

### User

> 1: confirmed
> 2: confirmed
> 3: keep separate so we can provide specific feedback to the user via the UI later

### Assistant

Locked: five-outcome taxonomy; partial advances; terminal outcomes separate.

Posed Q5 (report structure). Two consumers (agent + UI) want different things. Three shapes: free-form narrative, fully structured JSON, hybrid structured shell with prose fields. Recommended hybrid (option C): `narrative` + `attempted_sources` + `confidence` + `hints_for_next_step`. Stored alongside auto-captured tool-call trace from Pydantic AI (separate from agent self-narration — LLMs hallucinate their own histories). Asked about the four-field shape, separate vs. trace-only, and whether concise summary is its own LLM field.

### User

> Re: Question 5: agree with you. Let's go for C.

### Assistant

Locked Q5 partially. Then user added an additional constraint:

### User

> The big picture is that whereas in this PR we want to already introduce a CI/CD LLM evaluation test as mentioned before, in the future we will want to compare the "Fetch details" agent performance as we make changes to the tools and prompts.

### Assistant

Reshaped Q5's answer around eval-friendliness. Argued that structured fields are evaluable cheaply and deterministically (equality, fuzzy-match, HTTP HEAD), while prose requires LLM-as-judge (expensive, noisy, hard to set regression thresholds on). Pushed structure further: added `discovered_canonical_url`, `discovered_audio_url`, `cross_linked` flags, `extraction_confidence: Literal["high","medium","low"]`. Two layers of metrics: field-level (no LLM judge) for the regression signal; behavioral (from tool trace) for "did the agent cross-link when needed?"; prose quality (LLM judge, optional). Asked about dataset shape — hand-curated golden set, snapshot, or hybrid; recommended hand-curated for this PR. Asked about framework: pytest (cheap, no judge) vs DeepEval (judge for prose) vs both with sharp split. Asked about CI gating: path-based filter or manual workflow_dispatch. Asked about model + VCR cassettes.

### User

> Maybe it is too much to introduce the evaluation in this PR. We can extract this to an issue and tacke it right after this PR has been merged. What do you think?

### Assistant

Agreed with deferral. Reasoning: PR is already substantial; eval is its own subsystem (dataset, DeepEval wiring, CI workflow, VCR, model decisions); structured-heavy report still pays for itself for UI + downstream agent consumption. Two things to keep in this PR even with eval deferred: TestModel-based unit tests (correctness, not quality), and a few `@pytest.mark.live` opt-in smoke tests. Flagged risk: without eval, v0 quality is unmeasured and becomes the de facto baseline; mitigation is including absolute-fact cases in the follow-up. Suggested follow-up issue captures: dataset shape, framework split, CI path filter, VCR strategy, model decision.

### User

> But let's keep the "CI gating" for this PR since it will affet that test work.

### Assistant

Confirmed CI design captured for the follow-up. Read existing `.github/workflows/ci.yml` — single workflow runs `manage.py test` on push/PR with Postgres service, no path filtering. Posed Q7 with three sub-decisions: (a) separate workflow file vs job inside ci.yml, (b) what trigger paths gate the workflow, (c) does the workflow file land in this PR (with placeholder) or with the follow-up. Recommended separate file (native paths filter at workflow trigger), specific path list including `_model.py`, and (b) — design captured in follow-up issue, file lands with eval implementation.

### User

> What I meant is that we take that into account in this PR for the file/directory structuring and paths.

### Assistant

Re-interpreted: the user wants this PR's file layout to be path-filter-friendly so the follow-up doesn't need to refactor. Inspected `episodes/tests/` (flat layout, `test_fetch_details_step.py` already exists). Posed Q8 with the layout proposal:

- A. Under `episodes/agents/fetch_details*` glob: `fetch_details.py` (existing, expand), `fetch_details_tools.py` (new), `fetch_details_deps.py` (new).
- B. Caught by extra paths: `fetch_details_step.py`, `_model.py`, `itunes.py` (new top-level), `podcast_indexes/**`.
- C. Out of filter: `models.py`, `migrations/`, `admin.py`.
- D. Tests: flat under `episodes/tests/test_fetch_details*` glob.

Two real forks: iTunes API client at `episodes/itunes.py` (peer of `wikidata.py`, `musicbrainz.py`) vs inside `agents/fetch_details_tools.py`; reuse existing fyyd vs new keyless-only client. Recommended top-level `episodes/itunes.py` and existing fyyd reuse.

### User

> Isn't iTunes a podcast aggregator, i.e. a podcast index? I like the term "podcast aggregator" more than "podcast index". Or are they different things?

### Assistant

Walked through: they're functionally the same (catalogs of podcast metadata, queryable via API, returning episode candidates with audio URLs — same protocol shape `(title, show, guid) → list[EpisodeCandidate]`). Acknowledged a precision gap — "aggregator" colloquially carries two meanings (consumer-facing platform vs API-only catalog) — but for our purposes one bucket is right. Proposed renaming `episodes/podcast_indexes/` → `episodes/podcast_aggregators/`; iTunes inside (`podcast_aggregators/itunes.py`); rename `RAGTIME_PODCAST_INDEXES` → `RAGTIME_PODCAST_AGGREGATORS`. Flagged that MusicBrainz and Wikidata are NOT aggregators (different shape, different purpose) and stay where they are. Asked: rename or keep, and rename env var or keep.

### User

> 1: rename. 2: rename too since we are pre-prod

### Assistant

Locked: rename `podcast_indexes/` → `podcast_aggregators/`, iTunes inside, env var renamed cleanly, no fallback.

Posed Q9 (Episode.Status and recovery interaction). Given three failure outcomes, two ways to express the distinction: new Episode.Status values per outcome, or single FAILED + discriminator on FetchDetailsRun.outcome. Recommended single FAILED — pipeline has 10+ steps; per-step failure flavors would explode the global enum. Mapped each outcome to status + recovery treatment. Posed sub-question on recovery: today fail_step unconditionally fires recovery; for `not_a_podcast_episode`, retrying is pointless. Recommended adding `recoverable: bool` to fail_step.

### User

> 1: b. 2: we do we need to model the recovery? we removed the recovery logic in a previous PR. There's no recovery agent anymore. We subsumed the recovery agent into the "Download" pipeline step.

### Assistant

Verified by reading `episodes/processing.py` — confirmed it's now no-op stubs (`fail_step`, `complete_step`, `start_step` all `return None`), with a docstring saying "Future cleanup will inline the few remaining callers and delete this module." The "recovery runs synchronously via signal" comment in `fetch_details_step.py:131` is stale. Updated Q9 conclusions: single FAILED + discriminator confirmed; `recoverable` flag is moot; recovery treatment per outcome is moot. Two implications: (i) drop the no-op shim calls from the new step (don't touch processing.py — other steps still use it); (ii) without recovery, `unreachable` is now a hard fail. Three options for unreachable: accept it, light retry inside fetch_url, both. Recommended (c) — light retry — but asked.

### User

> 1: confirmed. 2: confirmed. 3: let's do (a) for now. We will revisit this in a future PR when we allow end users to paste a URL in the Scott chat and that triggers the ingestion directly.

### Assistant

Locked: drop processing.py shim calls; leave processing.py untouched; no retry on unreachable.

Posed Q10 (source_type taxonomy granularity). Three options: three buckets (canonical/aggregator/unknown), five buckets (per-provider Literal), or two-field split (`source_kind` + `aggregator_provider`). Recommended (c) two-field split — future providers will arrive (Spotify obvious next), enum-explosion is wrong shape, two genuinely different questions. Concrete schema: `source_kind` as TextChoices enum; `aggregator_provider` as free string with whitelist (`apple_podcasts | spotify | fyyd | overcast | pocketcasts`) + normalize helper at write time. Trade-off flagged: free string can drift; mitigated by tiny normalize helper; not worth a Literal that requires migration when adding providers.

### User

> 1: confirmed. 2: agreed.

### Assistant

Locked: two-field split, free-string `aggregator_provider` with whitelist normalize.

Posed Q11 (legacy behaviors of current step). Two things may not survive: (i) `Episode.scraped_html` (cached HTML on Episode), (ii) fast-path skip when required fields are pre-filled. Recommended dropping both: `scraped_html` is now misleading (multi-tool agent fetches 0–N URLs, not "the HTML"); fast-path's precondition (NEEDS_REVIEW flow) doesn't exist. Per-tool HTML snippets live in `tool_calls_json` on `FetchDetailsRun` (capped ~5 KB). Sub-decision: keep the empty-field-only merge in the orchestrator (so admin edits survive re-runs)? Recommended yes — costs nothing, preserves the right semantics by default.

### User

> 1. yes, drop. 2: yes, drop. 3: I dont' understand the issue. Can you expand?

### Assistant

Unpacked the merge strategy with an example: if Episode.title is already "X" and the agent extracts "Y", the existing value wins (current code, line 109-115). Explained when this matters — only when the step is run more than once on the same episode (admin manually edits a field, then pipeline is re-triggered). Three options: agent always wins, current empty-field-only, confidence-aware. Recommended keeping empty-field-only — preserves admin edits across re-runs as a permanent invariant. Counter-argument: with `extraction_confidence`, one could argue confidence-aware is "right" — but confidence calibration is itself a quality concern, premature.

### User

> You say:
> > When the agent finishes, the step copies extracted values onto Episode. The "only update empty fields" rule means: if Episode.title is already "Jazz Porque Sí — Django Reinhardt" and the agent extracts title="Django    Reinhardt special", the existing value wins. The agent's value only fills blanks.
>
> This was like this because we were scrapping first and did a first attempt at getting the information from the scrapped HTML. Whereas now (if my understanding is correct) the agent internally does the HTML "scrapping" and  interpretation.

### Assistant

Acknowledged the user's reframing. Re-read the code carefully: there isn't a separate heuristic-scrape stage in the current code — the LLM is the only producer of values. The empty-field-only merge guards against re-run clobber + the fast-path's "user pre-filled fields" precondition. With single-agent design, no fast-path, no re-run path, no recovery, the merge is guarding against precisely nothing in the codebase. Revised recommendation: drop the merge, agent's output is authoritative, overwrite directly. Flagged that this becomes a question again only if/when an admin "reprocess from fetch_details" feature is added later — and at that point the re-run feature designs its own merge semantics deliberately.

### User

> yes

### Assistant

Locked: drop empty-field-only merge.

Posed Q12 (full agent output schema). Consolidated everything previously agreed: wrapped `FetchDetailsOutput { details, report, concise }`; `EpisodeDetails` with all the new fields; `FetchDetailsReport` with structured-heavy fields; `ConciseMessage` with outcome + summary. Sub-decisions: (a) concise message separate LLM field vs derived (recommended separate); (b) country with ISO 3166-1 validator (yes); (c) audio_format Literal vs free string (recommended Literal — closed set is right when we know the values); (d) canonical_url as `str | None` with prefix validator vs HttpUrl (recommended str — strict HttpUrl risks breaking structured output on edge cases); (e) aggregator_provider free string with normalize helper (already agreed); (f) wrapping vs flattening (recommended wrapping — three concerns, three blocks).

### User

> a: keep it separate. b: yes. c: literal. d: your recommendation. e: agreed. f: wrapping

### Assistant

Locked agent output schema.

Posed Q13 (FetchDetailsRun storage shape). Schema with FK CASCADE, `run_index` per episode, `started_at`/`finished_at`, `model`, `outcome` enum (denormalized from output_json for filtering), `output_json` (single field), `tool_calls_json`, `usage_json` + extracted `tokens_in/out`, optional `cost_usd`, `error_message` only when no structured output, `unique_together(episode, run_index)`, indexes on `(episode, -run_index)`, `outcome`, `-started_at`. Sub-decisions on cost tracking: plumb now (price table) vs defer. Recommended deferring `cost_usd` — cost tracking is a real feature with its own design space.

### User

> 1: confirmed. 2: single. 3: keep usage_json we don't need to expose more for now. 4: keep run_index per episode. 5: no latest_run.
> Additionally: do we want to keep a reference to the DBOS workflow that ran the agent in each of the runs in case we want to query DBOS later for details?

### Assistant

Worth adding. Recommended `dbos_workflow_id` as `CharField(max_length=200, blank=True, default="", db_index=True)`. Reasoning: DBOS holds the infrastructure trail (step retries, checkpoints, recovery state); workflow IDs are deterministic per AGENTS.md (`episode-<id>-run-<n>`) but storing explicit ID is honest about what was run; indexed for reverse lookup. Flagged future-engine-swap concern: name it explicitly `dbos_workflow_id`, not generic `workflow_id`. Don't store step name or step index — workflow ID is enough.

### User

> yes

### Assistant

Locked dbos_workflow_id addition.

Posed Q14 (agent control flow + system prompt design). Two coupled decisions. (14a) Reasoning loop shape: single Pydantic AI agent loop, fixed sequence in orchestrator, or Pydantic AI Graph. Recommended single Pydantic AI agent loop — committed to "this is an agent now"; orchestrator-driven sequencing bypasses LLM reasoning; Graph is overkill for three tools and one output; eval cleaner with one run per FetchDetailsRun. (14b) System prompt prescriptiveness: minimal, heuristic-rich, or goal-stated + constraints. Recommended (III) goal-stated — calibrated confidence is a key eval signal that must be told directly; heuristics in (II) are exactly what we'd want to measure and improve, not bake in at v0. Provided strawman prompt with goal block, tools block, constraints block, outcome decision rules.

### User

> 1: confirmed. 2: confirmed. 3: let's go for your proposal for now. Once we've implemented in a subsequent PR where we focus on the "Fetch Details" step evaluation (as discussed before) we can focus on improving the prompt.

### Assistant

Locked single Pydantic AI loop + goal-stated prompt + v0 strawman.

Posed Q15 (DBOS step granularity). Read existing pattern in `episodes/workflows.py` (one `@DBOS.step()` per pipeline phase). Three options: one step wrapping orchestrator, decompose to per-tool steps, hybrid with Langfuse spans. Recommended (A) one step wrapping orchestrator — cost of replay is small (cents); (B) violates module purity rule (tools become DBOS-aware, violating the "no DBOS, bootable from bare interpreter" constraint); sync/async mismatches; (C) is the existing pattern. Implementation details: pass `dbos_workflow_id` as argument from `@DBOS.step()` wrapper into orchestrator (keeps orchestrator DBOS-import-free); preserve `_raise_if_failed(...)` typed-exception pattern.

### User

> 1: A. 2: confirmed. 3: keep.

### Assistant

Locked DBOS step shape.

Posed Q16 (admin UI). Inspected `admin.py` (779 lines, EpisodeAdmin already surfaces DBOS workflow runs/steps inline). Three sub-decisions: (16a) what to add on EpisodeAdmin — new "Source" fieldset for new columns + latest-run summary block at top + inline runs table; (16b) FetchDetailsRunAdmin detail page — collapsible Concise / Report / Details / Tool calls / Raw payloads sections; (16c) rendering strategy — admin-pattern with `mark_safe()` callables (matching existing DBOS surfaces) vs custom Jinja view. Recommended admin-pattern — established convention, operators audience, Scott UI is where to invest in real visual design later. Asked whether to add "re-run fetch_details" admin action.

### User

> 1-3: confirmed. 4: if I am not mistaken, we can re-run the fetch_details step for a given episode via the Django admin UI episodes list page.

### Assistant

Verified by grepping `admin.py`: confirmed existing `reprocess` admin action with `from_step` selector. New orchestrator behavior on reprocess from `fetching_details`: increments `run_index`, writes new `FetchDetailsRun`, overwrites Episode fields per agreed authoritative-output rule. No admin-side change needed.

Posed Q17 (versioning agent runs for cross-version eval comparison). Three options: no version field, auto-hashed agent config (`sha256(prompt + model + sorted_tool_names)[:16]`), manual version string. Recommended (b) auto-hash — automatic, sufficient for eval grouping, reproducible. Flagged that hashing tool *names* (not implementations) is a coarse signal — adding implementation hashes is overkill since their behavior is observable through eval anyway.

### User

> Let's keep this for the eval work later but add it to the issue you need to create about this and that I mentioned before in our conversation.

### Assistant

Deferred agent_config_hash to the eval follow-up issue.

Posed Q18 (housekeeping). (18a) Migration strategy: single migration file `0NNN_fetch_details_agent.py` covering all DB changes (atomic story, pre-prod means no fine-grained reversibility needed). (18b) Env vars: no new ones (iTunes + fyyd keyless), rename `RAGTIME_PODCAST_INDEXES` → `RAGTIME_PODCAST_AGGREGATORS` per CLAUDE.md (update `.env.sample` and `core/management/commands/configure.py`). (18c) Doc deliverables per CLAUDE.md: plan doc, feature doc, planning + implementation transcripts, CHANGELOG entry, README + doc/README pipeline-summary updates. (18d) Pipeline-summary updates worth a paragraph in `doc/README.md`. (18e) Open-ended: async/sync boundary stays (asyncio.run per step), Langfuse via `@trace_step` continues, reprocess with `not_a_podcast_episode` outcome — don't block, half-sentence hint in template if anything. Asked: anything I haven't asked about that you want to lock in?

### User

> 1-3: confirmed. 4: we're done. Thanks!

### Assistant

Produced final summary covering: architecture, data model, agent contract, file layout, admin UI, migrations/config, documentation, deferred-to-follow-up items. Offered to save the plan, draft the eval follow-up issue, or start implementation.

### User

> Save the plan. Create a branch for the implamentation and commit the plan and the session transcript. Create an issue for this work and the eval follow-up issue.

### Assistant

Verified on main and pulled latest. Located session UUID via session jsonl logs. Created branch `feature/fetch-details-cross-linking` (the natural name `feature/fetch-details-agent` already existed from the previous PR). Wrote `doc/plans/2026-04-29-fetch-details-cross-linking.md` and `doc/sessions/2026-04-29-fetch-details-cross-linking-planning-session.md`. Committed. Created GitHub issues for the implementation work and the eval follow-up.
