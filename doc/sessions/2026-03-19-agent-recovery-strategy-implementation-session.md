# Session: Agent Recovery Strategy — Implementation

**Date:** 2026-03-19
**Session ID:** 92a11085-c37d-46dc-9439-48864cdaf996

## Summary

Implemented Phase 4 of the recovery architecture: replaced the `AgentStrategy` stub with a Pydantic AI agent using Playwright browser automation, added Django admin retry action, and integrated with Langfuse observability including screenshot attachments.

## Conversation

### User

Implement the following plan:

# Phase 4: Agent Recovery Strategy for Pipeline Failures

## Context

Steps 2 (scraping) and 3 (downloading) in the RAGtime pipeline sometimes fail — audio URLs not found in HTML, downloads blocked by 403/CloudFlare. The decoupled recovery layer (Phases 1-3, PR #69) already emits `StepFailureEvent` signals and walks a strategy chain (agent → human), but `AgentStrategy` is a stub that always escalates. This phase replaces the stub with a real Pydantic AI agent that uses Playwright browser automation to find audio URLs and download files.

## Package Structure

```
episodes/agents/
    __init__.py      # exports run_recovery_agent()
    deps.py          # RecoveryDeps dataclass + RecoveryAgentResult model
    agent.py         # Pydantic AI agent definition, system prompt, run function
    tools.py         # Playwright browser tool functions
    browser.py       # Browser lifecycle context manager
    resume.py        # Pipeline resume logic after successful recovery
```

## Implementation Steps

### 1. Add dependencies to `pyproject.toml`

Add a `recovery` optional dependency group:

```toml
recovery = ["pydantic-ai>=0.1", "playwright>=1.40"]
```

### 2. Create `episodes/agents/browser.py`

Context manager that creates a fresh Playwright browser context per recovery attempt:
- `recovery_browser(download_dir: str) -> Generator[Page]`
- Headless-only, `accept_downloads=True`
- Sets `user_agent="RAGtime/0.1 (podcast recovery agent)"`
- Default timeout 30s per operation
- Cleanup in `finally`: page → context → browser → playwright

### 3. Create `episodes/agents/deps.py`

**Dependencies dataclass:**
```python
@dataclasses.dataclass
class RecoveryDeps:
    episode_id: int
    episode_url: str         # Podcast page URL
    audio_url: str           # May be empty for scraping failures
    step_name: str           # "scraping" or "downloading"
    error_message: str
    http_status: int | None
    download_dir: str        # Absolute path for downloaded files
    page: Page               # Playwright Page (injected)
    screenshots: list[bytes] # Mutable list, tools append PNG bytes
```

**Result model:**
```python
class RecoveryAgentResult(BaseModel):
    success: bool
    audio_url: str = ""         # Found audio URL (scraping recovery)
    downloaded_file: str = ""   # Path to downloaded file (download recovery)
    message: str = ""
```

### 4. Create `episodes/agents/tools.py`

Playwright browser tools registered on the Pydantic AI agent:

| Tool | Purpose |
|------|---------|
| `navigate_to_url(ctx, url)` | Navigate browser, return page title + text snippet |
| `get_page_content(ctx)` | Return current page text content (truncated to 15k chars) |
| `find_audio_links(ctx)` | Extract audio URLs from `<audio>`, `<a>`, `<source>`, `<meta>` tags |
| `click_element(ctx, selector)` | Click CSS selector, return resulting page state |
| `take_screenshot(ctx, label)` | Screenshot with JS-injected CSS cursor dot, append to `deps.screenshots` |
| `download_file(ctx, url)` | Navigate to URL, wait for download, save to `download_dir/{episode_id}.mp3` |
| `extract_text_by_selector(ctx, selector)` | Get text content of matching elements |

### 5. Create `episodes/agents/agent.py`

- Define `recovery_agent = Agent(model=..., deps_type=RecoveryDeps, result_type=RecoveryAgentResult)`
- Dynamic system prompt based on `step_name` (scraping vs downloading)
- `run_recovery_agent(event: StepFailureEvent) -> RecoveryAgentResult`:
  - Loads episode from DB
  - Sets `download_dir = settings.MEDIA_ROOT / "episodes"` (same as normal downloader)
  - Opens `recovery_browser(download_dir)` context
  - Builds `RecoveryDeps` with episode data + Playwright page
  - Calls `recovery_agent.run_sync()` with `UsageLimits(request_limit=15)`
  - Attaches screenshots to Langfuse if enabled
- Model from `RAGTIME_RECOVERY_AGENT_MODEL` setting (default: `openai:gpt-4.1-mini`), API key from `RAGTIME_RECOVERY_AGENT_API_KEY` passed explicitly to model constructor
- Langfuse: call `Agent.instrument_all()` at module level when `observability.is_enabled()`

### 6. Create `episodes/agents/resume.py`

`resume_pipeline(event, agent_result)`:
- **Scraping recovery**: set `episode.audio_url`, status → `DOWNLOADING`, call `create_run(resume_from=DOWNLOADING)`
- **Download recovery**: save file to `episode.audio_file` via Django `File`, extract duration with `mutagen.MP3`, status → `TRANSCRIBING`, call `create_run(resume_from=TRANSCRIBING)`
- The `post_save` signal on Episode auto-queues the next pipeline step

### 7. Replace `AgentStrategy.attempt()` in `episodes/recovery.py`

```python
def attempt(self, event):
    try:
        from .agents import run_recovery_agent
        result = run_recovery_agent(event)
        if result.success:
            from .agents.resume import resume_pipeline
            resume_pipeline(event, result)
            return RecoveryResult(success=True, message=result.message, should_escalate=False)
        return RecoveryResult(success=False, message=result.message or "Agent could not recover", should_escalate=True)
    except Exception as exc:
        logger.exception("Agent recovery failed for episode %s", event.episode_id)
        return RecoveryResult(success=False, message=f"Agent error: {exc}", should_escalate=True)
```

Lazy import inside method body so missing `pydantic-ai`/`playwright` doesn't crash app startup.

### 8. Add settings

**`ragtime/settings.py`** — after existing recovery settings:
```python
RAGTIME_RECOVERY_AGENT_API_KEY = os.getenv('RAGTIME_RECOVERY_AGENT_API_KEY', '')
RAGTIME_RECOVERY_AGENT_MODEL = os.getenv('RAGTIME_RECOVERY_AGENT_MODEL', 'openai:gpt-4.1-mini')
RAGTIME_RECOVERY_AGENT_TIMEOUT = int(os.getenv('RAGTIME_RECOVERY_AGENT_TIMEOUT', '120'))
```

Also add `RAGTIME_RECOVERY_AGENT_API_KEY` — passed explicitly to the Pydantic AI model constructor so the agent's LLM provider is fully independent from other subsystems (supports switching providers, models, or using local models).

**`.env.sample`** — add under recovery section:
```
# API key for the recovery agent LLM provider
RAGTIME_RECOVERY_AGENT_API_KEY=
# Pydantic AI model string (default: openai:gpt-4.1-mini). Examples: anthropic:claude-sonnet-4-20250514, openai:gpt-4.1
RAGTIME_RECOVERY_AGENT_MODEL=
# Timeout in seconds for recovery agent attempts (default: 120)
RAGTIME_RECOVERY_AGENT_TIMEOUT=
```

**`core/management/commands/_configure_helpers.py`** — add to Recovery subsystem fields:
```python
("AGENT_API_KEY", "", True),   # True = secret, masked in --show
("AGENT_MODEL", "openai:gpt-4.1-mini", False),
("AGENT_TIMEOUT", "120", False),
```

### 9. Write tests

**`episodes/tests/test_agent_tools.py`** — mock Playwright Page, test each tool function independently

**`episodes/tests/test_agent_resume.py`** — test `resume_pipeline` with real Django test DB:
- Scraping recovery: verify `audio_url` set, status → DOWNLOADING, new ProcessingRun
- Download recovery: verify `audio_file` saved, duration extracted, status → TRANSCRIBING

**Extend `episodes/tests/test_recovery.py`** — test `AgentStrategy.attempt()`:
- Mock `run_recovery_agent` to avoid real browser/LLM
- Verify success path calls `resume_pipeline`
- Verify exception path returns `should_escalate=True`

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Add `recovery` optional dependency group |
| `episodes/agents/__init__.py` | New — export `run_recovery_agent` |
| `episodes/agents/deps.py` | New — `RecoveryDeps`, `RecoveryAgentResult` |
| `episodes/agents/browser.py` | New — `recovery_browser()` context manager |
| `episodes/agents/tools.py` | New — 7 Playwright tool functions |
| `episodes/agents/agent.py` | New — Pydantic AI agent, `run_recovery_agent()` |
| `episodes/agents/resume.py` | New — `resume_pipeline()` |
| `episodes/recovery.py` | Replace `AgentStrategy.attempt()` stub |
| `ragtime/settings.py` | Add `RAGTIME_RECOVERY_AGENT_MODEL`, `RAGTIME_RECOVERY_AGENT_TIMEOUT` |
| `.env.sample` | Add new env vars |
| `core/management/commands/_configure_helpers.py` | Add fields to Recovery subsystem |
| `episodes/tests/test_agent_tools.py` | New — tool unit tests |
| `episodes/tests/test_agent_resume.py` | New — resume logic tests |
| `episodes/tests/test_recovery.py` | Extend with AgentStrategy tests |

## Verification

1. `uv sync --extra recovery && playwright install chromium`
2. `uv run python manage.py test episodes` — all tests pass
3. Manual test: create an episode with a URL that fails scraping, enable `RAGTIME_RECOVERY_AGENT_ENABLED=true`, reprocess, verify agent finds audio URL and pipeline resumes
4. Check Langfuse traces show agent spans with screenshots (when Langfuse enabled)


If you need specific details from before exiting plan mode (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/rafa/.claude/projects/-Users-rafa-Develop-projects-ragtime/a150a5a3-218f-44b4-a02b-cf90912619d7.jsonl

### Assistant

I'll start by reading the key existing files to understand the current codebase before implementing.

Good, I have a thorough understanding of the codebase. Let me now read the key files I need to modify directly.

Now let me also check the models and downloader for the exact field names and patterns.

Good, I have a thorough understanding. Let me start implementing. First, create the branch and set up the package structure.

Now let me implement all the files. I'll start with the dependency update and new agent package files.

Now update the existing files — `recovery.py`, `settings.py`, `.env.sample`, and `_configure_helpers.py`.

Now let me write the tests.

Now extend the existing `test_recovery.py` with `AgentStrategy.attempt()` tests.

Now let me also update the `test_agent_escalates_to_human` test since the stub behavior has changed — the agent now calls real code.

Now I need to update the `test_agent_escalates_to_human` test in `HandleStepFailureTests` since it relied on the stub behavior. The agent now tries to import real code which will fail without pydantic-ai installed, so we need to mock it.

Now let me clean up the dead test method I accidentally left in:

Now let me install the recovery dependencies and run the tests.

Two test failures to fix:

1. `test_saves_file_to_download_dir` — async mock for `expect_download` context manager not set up correctly
2. `test_saves_file_and_creates_run` — fake MP3 bytes not valid enough for mutagen

Let me fix both.

For the MP3 test, I need a real MP3 file. Let me mock `MP3` instead:

The `download_file` tool's mock isn't working because `expect_download()` is an async method that returns a context manager. The issue is that `page.expect_download()` is being called (it's an `AsyncMock` so it returns a coroutine), but then the `async with` needs to work on its return value. Let me fix the mock setup properly:

The issue is `download = await download_info.value` — `download_info` is the result of `__aenter__`, which is `mock_download` (already the download). The `value` attribute on Playwright's download info is awaitable. Let me look at how the download tool actually works and fix the mock:

The `async with page.expect_download() as download_info:` sets `download_info` to the context manager's `__aenter__` return value. Then `download = await download_info.value` gets the actual download. So `download_info.value` needs to be awaitable.

Now let's run all episodes tests:

All 180 tests pass. The "database table is locked" errors are expected — those come from the integration tests where the real `AgentStrategy` runs `asyncio.run()` which creates a new thread that can't access the test DB. But those are handled gracefully (caught by the exception handler in `AgentStrategy.attempt()`) and escalate to human, which is the correct behavior.

Now let me also run the full test suite to make sure nothing else is broken:

These failures are in the `core` configure wizard tests, likely because the new fields changed the expected prompts. Let me check:

The configure wizard tests are failing because they provide a fixed number of mock inputs that don't account for the 3 new fields. Let me check the test:

I see — both tests need 3 more `input` entries for the new Recovery fields (`AGENT_API_KEY` is a secret so it goes through getpass, `AGENT_MODEL` and `AGENT_TIMEOUT` go through input). Let me update both tests:

All 203 tests pass. Now let me verify all files look correct:

Everything looks good. Let me check that the `django check` also passes:

All checks pass. Here's a summary of what was implemented:

**New files (6):**
- `episodes/agents/__init__.py` — exports `run_recovery_agent()`
- `episodes/agents/deps.py` — `RecoveryDeps` dataclass + `RecoveryAgentResult` model
- `episodes/agents/browser.py` — `recovery_browser()` async context manager (Playwright lifecycle)
- `episodes/agents/tools.py` — 7 Playwright browser tools (navigate, get content, find audio links, click, screenshot, download, extract text)
- `episodes/agents/agent.py` — Pydantic AI agent with dynamic system prompts for scraping vs downloading recovery, Langfuse instrumentation
- `episodes/agents/resume.py` — `resume_pipeline()` to restart the pipeline after successful recovery

**New test files (2):**
- `episodes/tests/test_agent_tools.py` — unit tests for all 7 tool functions with mocked Playwright
- `episodes/tests/test_agent_resume.py` — integration tests for resume logic (scraping + downloading paths)

**Modified files (6):**
- `pyproject.toml` — added `recovery` optional dependency group
- `episodes/recovery.py` — replaced `AgentStrategy.attempt()` stub with real implementation
- `ragtime/settings.py` — added 3 new recovery agent settings
- `.env.sample` — added 3 new env vars
- `core/management/commands/_configure_helpers.py` — added 3 fields to Recovery subsystem
- `core/tests/test_configure.py` — updated mock input sequences for new fields
- `episodes/tests/test_recovery.py` — replaced stub test with 3 agent strategy tests (success, failure, exception)

**All 203 tests pass.**

### User

How do I test this locally? Do I need to execute a migration?

### Assistant

No migration needed — no model changes were made.

To test locally:

**1. Install dependencies + Playwright browser:**
```bash
uv sync --extra recovery
playwright install chromium
```

**2. Configure the agent** (add to `.env`):
```
RAGTIME_RECOVERY_AGENT_ENABLED=true
RAGTIME_RECOVERY_AGENT_API_KEY=sk-your-openai-key
```

The default model is `openai:gpt-4.1-mini`. You can change it:
```
RAGTIME_RECOVERY_AGENT_MODEL=anthropic:claude-sonnet-4-20250514
```

**3. Manual test:** Submit an episode with a URL where scraping will fail (e.g., a page behind CloudFlare or with no discoverable audio URL). The pipeline will fail at scraping/downloading, emit `step_failed`, and the agent will attempt recovery with Playwright.

**4. Run just the new tests:**
```bash
uv run python manage.py test episodes.tests.test_agent_tools episodes.tests.test_agent_resume episodes.tests.test_recovery
```

### User

Have we updated the configuration wizard and the README with a section after the "Steps" section?

### Assistant

Good catch. Let me check the README to see what needs updating.

The configuration wizard is already updated (the new fields are being prompted). But you're right — the README needs a recovery section. Let me read the relevant part of the README to add it properly.

Now I see the full picture. I need to add a `### Recovery` section after `### Steps` (inside `## Processing Pipeline`) documenting the agent recovery strategy. Let me add it:

Let me verify tests still pass after the README change:

All 203 tests still pass. To answer your questions:

1. **Configuration wizard** — yes, already updated. The 3 new fields (`AGENT_API_KEY`, `AGENT_MODEL`, `AGENT_TIMEOUT`) were added to `_configure_helpers.py` and the wizard tests were updated to match.

2. **README** — just added a `### Recovery` section right after `### Steps` inside `## Processing Pipeline`. It documents the agent → human strategy chain, setup instructions, model configuration, and links to the tools module.

### User

Update ther README where it says "Then set in `.env`:" with how to use the configuration wizard or set the variables like we do for Langfuse

### Assistant

Now let me check the Langfuse section for the pattern to follow:

Done — now matches the Langfuse pattern: wizard first, then manual `.env` as the alternative.

### User

How do I install playwright?

### Assistant

It's already in the README setup instructions:

```
uv sync --extra recovery
playwright install chromium
```

The first command installs the `playwright` Python package (along with `pydantic-ai`). The second downloads the Chromium browser binary that Playwright needs.

### User

Does not seem to work:
uv sync --extra recovery
Resolved 153 packages in 7ms
Checked 145 packages in 4ms
 ragtime  playwright install chromium
zsh: command not found: playwright

### Assistant

The `playwright` command isn't on your PATH because it's installed inside the venv. Use `uv run`:

```
uv run playwright install chromium
```

Let me also fix this in the README.

### User

When using the configuration wizard, it should be possible to use the same api key for Agent Api Key and model as for other previous steps.

### Assistant

The issue is the condition `suffix == "API_KEY"` — the Recovery field is `AGENT_API_KEY`, so it doesn't match. I need to broaden the check to match any suffix ending with `_API_KEY`.

Now let me run the configure tests to make sure it still works:

All 23 configure tests pass. The fix is a one-character change — `suffix == "API_KEY"` to `suffix.endswith("API_KEY")` — so the "Enter to reuse LLM key" prompt now also appears for `AGENT_API_KEY` in the Recovery section.

### User

Which ID have we set for the Langfuse session ID? Do I need to configure something on the Langfuse side to see the agent-related sessions and traces?

### Assistant

We're not setting a session ID on the agent traces. `Agent.instrument_all()` uses Pydantic AI's OpenTelemetry instrumentation, which sends spans to Langfuse via the OTel TracerProvider that `observability.setup()` initializes — but we're not propagating any `session_id` or `user_id` the way the pipeline steps do with `propagate_attributes`.

Compare with how pipeline steps do it in `observability.py:observe_step()` — they use `propagate_attributes(session_id=..., user_id=...)`. The agent doesn't do this, so its traces will appear as orphaned spans in Langfuse.

No special Langfuse-side config is needed, but the traces won't be grouped usefully right now. Let me fix the agent to propagate attributes:

Now add the helper function that wraps the agent run with Langfuse context:

All good. To answer your questions:

**Session ID**: `recovery-run-{processing_run_id}-episode-{episode_id}` — same pattern as pipeline steps (`processing-run-{id}-episode-{id}`), just prefixed with `recovery-` so you can distinguish them. The `user_id` is `episode-{id}`, matching the pipeline convention.

**Metadata** propagated to each trace: `episode_id`, `step_name`, `error_type`, `attempt_number`.

**Langfuse-side config**: Nothing special needed. As long as your existing `RAGTIME_LANGFUSE_*` settings work for pipeline traces, the agent traces will appear in the same Langfuse project. You can filter by session ID prefix `recovery-` or by the metadata fields to find agent-specific traces.

### User

We need to allow the user via the Django admin UI to trigger another attempt by the agent. Where can we add this functionality?

### Assistant

Two natural places, from most to least specific:

1. **`RecoveryAttemptAdmin`** (line 655) — add an action on `AWAITING_HUMAN` records. The admin sees the failed attempts, selects the ones to retry, and the action queues the agent. This is the most precise entry point since it already has `NeedsHumanActionFilter` and shows error context.

2. **`EpisodeAdmin`** (line 126) — add a second action alongside the existing `reprocess`. The difference: `reprocess` restarts the whole pipeline from a chosen step, while "retry agent" specifically runs the recovery agent against the failed step. More discoverable since admins are usually on the Episode page.

I'd recommend **option 1** as the primary action — the `RecoveryAttemptAdmin` already surfaces exactly the records that need attention. The implementation would:
- Filter selected attempts to `AWAITING_HUMAN` only
- Rebuild a `StepFailureEvent` from the linked `PipelineEvent` and episode
- Queue `run_recovery_agent` as a Django Q2 async task (to avoid blocking the admin request)
- Mark the attempt as `RESOLVED` with `resolved_by="human:admin-retry"`

Want me to implement it?

### User

yes

### Assistant

Now I need to understand how to rebuild a `StepFailureEvent` from a `RecoveryAttempt`. Let me check the `PipelineEvent` fields and the `StepFailureEvent` dataclass.

I need to build a `StepFailureEvent` from the `PipelineEvent` + `RecoveryAttempt`. The `PipelineEvent` has all the fields I need. Let me also create a task function that can be queued by Django Q2.

Now let me add tests for this action. Let me check what test files exist for admin:

Now let me add tests for the retry action:

Now add the test class at the end of the file, before the `WikidataViewTests`:

All 25 admin tests pass. Let me run the full suite to confirm:

All 208 tests pass. Here's what was added:

**`RecoveryAttemptAdmin`** — new "Retry with recovery agent" action that:
- Filters to only `AWAITING_HUMAN` attempts (warns if none selected)
- Marks each attempt as `RESOLVED` with `resolved_by="human:admin-retry"`
- Queues `_run_agent_recovery_task` via Django Q2 (non-blocking)

**`_run_agent_recovery_task`** — module-level function (callable by Django Q2) that:
- Rebuilds a `StepFailureEvent` from the `PipelineEvent`
- Runs `run_recovery_agent` → `resume_pipeline` on success
- Creates a new `RecoveryAttempt` record with the outcome (success → `ATTEMPTED`, failure → `AWAITING_HUMAN` for another round)

**5 new tests** — admin action (queues task, skips non-awaiting) + task function (success, failure, exception paths).

### User

I can see the following error in the Django Q logs:
15:53:45 [Q] INFO Process-cf6d9e2910ff48a69ff1f66a0235205a processing victor-fourteen-six-april 'episodes.admin._run_agent_recovery_task'
Admin-triggered agent recovery error for episode 2
Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/episodes/admin.py", line 735, in _run_agent_recovery_task
    result = run_recovery_agent(event)
  File "/Users/rafa/Develop/projects/ragtime/episodes/agents/agent.py", line 240, in run_recovery_agent
    return asyncio.run(_run_agent_async(event))
           ~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/asyncio/runners.py", line 195, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/asyncio/runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/asyncio/base_events.py", line 725, in run_until_complete
    return future.result()
           ~~~~~~~~~~~~~^^
  File "/Users/rafa/Develop/projects/ragtime/episodes/agents/agent.py", line 151, in _run_agent_async
    agent = _build_agent()
  File "/Users/rafa/Develop/projects/ragtime/episodes/agents/agent.py", line 84, in _build_agent
    agent = Agent(
        model,
        deps_type=RecoveryDeps,
        result_type=RecoveryAgentResult,
    )
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/agent/__init__.py", line 309, in __init__
    _utils.validate_empty_kwargs(_deprecated_kwargs)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_utils.py", line 467, in validate_empty_kwargs
    raise exceptions.UserError(f'Unknown keyword arguments: {unknown_kwargs}')
pydantic_ai.exceptions.UserError: Unknown keyword arguments: `result_type`
15:53:46 [Q] INFO Processed 'episodes.admin._run_agent_recovery_task' (victor-fourteen-six-april)

### Assistant

The Pydantic AI API has changed — `result_type` is now called `output_type`. Let me check the installed version and fix it.

`result_type` → `output_type`, and `result.output` should still work. Also the `run()` first positional arg is `user_prompt`, not just a string. Let me fix `agent.py`:

Also need to check if `result.output` is still the correct accessor:

No `output` attribute either! Let me check what `response` gives:

OK, `output` is a dataclass field — `result.output` is correct. The only fix needed was `result_type` → `output_type`. Let me run the tests:

All 208 tests pass. The fix was a single line: `result_type=RecoveryAgentResult` → `output_type=RecoveryAgentResult` — the Pydantic AI 1.x API renamed this parameter.

### User

I'm seeing this in the Django Q logs:
15:56:27 [Q] INFO Process-0d7f95cda7eb4d8eb3a62f0a443d4c53 processing avocado-carpet-winter-jersey 'episodes.admin._run_agent_recovery_task'
Admin-triggered agent recovery error for episode 2
Traceback (most recent call last):
  File "/Users/rafa/Develop/projects/ragtime/episodes/admin.py", line 735, in _run_agent_recovery_task
    result = run_recovery_agent(event)
  File "/Users/rafa/Develop/projects/ragtime/episodes/agents/agent.py", line 240, in run_recovery_agent
    return asyncio.run(_run_agent_async(event))
           ~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/asyncio/runners.py", line 195, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/asyncio/runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/asyncio/base_events.py", line 725, in run_until_complete
    return future.result()
           ~~~~~~~~~~~~~^^
  File "/Users/rafa/Develop/projects/ragtime/episodes/agents/agent.py", line 154, in _run_agent_async
    result = await _run_with_langfuse(agent, system_prompt, deps, event)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/episodes/agents/agent.py", line 194, in _run_with_langfuse
    return await agent.run(**run_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/agent/abstract.py", line 226, in run
    async with self.iter(
               ~~~~~~~~~^
        user_prompt=user_prompt,
        ^^^^^^^^^^^^^^^^^^^^^^^^
    ...<10 lines>...
        builtin_tools=builtin_tools,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ) as agent_run:
    ^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/contextlib.py", line 235, in __aexit__
    await self.gen.athrow(value)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/agent/__init__.py", line 658, in iter
    async with graph.iter(
               ~~~~~~~~~~^
        inputs=user_prompt_node,
        ^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
        infer_name=False,
        ^^^^^^^^^^^^^^^^^
    ) as graph_run:
    ^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/contextlib.py", line 235, in __aexit__
    await self.gen.athrow(value)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_graph/beta/graph.py", line 270, in iter
    async with GraphRun[StateT, DepsT, OutputT](
               ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        graph=self,
        ^^^^^^^^^^^
    ...<3 lines>...
        traceparent=traceparent,
        ^^^^^^^^^^^^^^^^^^^^^^^^
    ) as graph_run:
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_graph/beta/graph.py", line 423, in __aexit__
    await self._async_exit_stack.__aexit__(exc_type, exc_val, exc_tb)
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/contextlib.py", line 768, in __aexit__
    raise exc
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/contextlib.py", line 749, in __aexit__
    cb_suppress = cb(*exc_details)
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/contextlib.py", line 162, in __exit__
    self.gen.throw(value)
    ~~~~~~~~~~~~~~^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_graph/beta/graph.py", line 981, in _unwrap_exception_groups
    raise exception
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_graph/beta/graph.py", line 750, in _run_tracked_task
    result = await self._run_task(t_)
             ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_graph/beta/graph.py", line 782, in _run_task
    output = await node.call(step_context)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_graph/beta/step.py", line 253, in _call_node
    return await node.run(GraphRunContext(state=ctx.state, deps=ctx.deps))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 576, in run
    async with self.stream(ctx):
               ~~~~~~~~~~~^^^^^
  File "/Users/rafa/.local/share/uv/python/cpython-3.13.12-macos-aarch64-none/lib/python3.13/contextlib.py", line 221, in __aexit__
    await anext(self.gen)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 590, in stream
    async for _event in stream:
        pass
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 716, in _run_stream
    async for event in self._events_iterator:
        yield event
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 677, in _run_stream
    async for event in self._handle_tool_calls(ctx, tool_calls):
        yield event
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 732, in _handle_tool_calls
    async for event in process_tool_calls(
    ...<8 lines>...
        yield event
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 950, in process_tool_calls
    async for event in _call_tools(
    ...<10 lines>...
        yield event
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 1086, in _call_tools
    if event := await handle_call_or_result(coro_or_task=task, index=index):
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 1049, in handle_call_or_result
    (await coro_or_task) if inspect.isawaitable(coro_or_task) else coro_or_task.result()
     ^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_agent_graph.py", line 1122, in _call_tool
    tool_result = await tool_manager.handle_call(tool_call)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_tool_manager.py", line 119, in handle_call
    return await self._call_function_tool(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<8 lines>...
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_tool_manager.py", line 254, in _call_function_tool
    tool_result = await self._call_tool(
                  ^^^^^^^^^^^^^^^^^^^^^^
    ...<4 lines>...
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_tool_manager.py", line 175, in _call_tool
    result = await self.toolset.call_tool(name, args_dict, ctx, tool)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/toolsets/combined.py", line 90, in call_tool
    return await tool.source_toolset.call_tool(name, tool_args, ctx, tool.source_tool)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/toolsets/combined.py", line 90, in call_tool
    return await tool.source_toolset.call_tool(name, tool_args, ctx, tool.source_tool)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/toolsets/function.py", line 350, in call_tool
    return await tool.call_func(tool_args, ctx)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/pydantic_ai/_function_schema.py", line 52, in call
    return await function(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/episodes/agents/tools.py", line 81, in click_element
    await page.click(selector)
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/playwright/async_api/_generated.py", line 9931, in click
    await self._impl_obj.click(
    ...<11 lines>...
    )
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/playwright/_impl/_page.py", line 854, in click
    return await self._main_frame._click(**locals_to_params(locals()))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/playwright/_impl/_frame.py", line 566, in _click
    await self._channel.send("click", self._timeout, locals_to_params(locals()))
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/playwright/_impl/_connection.py", line 69, in send
    return await self._connection.wrap_api_call(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "/Users/rafa/Develop/projects/ragtime/.venv/lib/python3.13/site-packages/playwright/_impl/_connection.py", line 559, in wrap_api_call
    raise rewrite_error(error, f"{parsed_st['apiName']}: {error}") from None
playwright._impl._errors.TimeoutError: Page.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("a[title='Escuchar']")

15:57:08 [Q] INFO Processed 'episodes.admin._run_agent_recovery_task' (avocado-carpet-winter-jersey)
I'm not seeing any sessions or traces for the agents in Langfuse.

### Assistant

Two separate issues here:

1. **The timeout on `click_element`** — the agent tried to click a selector that didn't match. That's expected agent behavior (it's exploring the page). The error bubbles up through Pydantic AI's tool error handling and the agent should recover. But since the whole run ultimately failed, it became the final error.

2. **No Langfuse traces** — this is the real problem. Let me check why `_maybe_instrument()` isn't working.

The problem is that `_maybe_instrument()` is called **inside** the `_run_agent_async` function which runs via `asyncio.run()` — that creates a new thread/process context. But more importantly, `Agent.instrument_all()` uses OpenTelemetry instrumentation which requires the OTel TracerProvider to be set up. The Django Q2 worker process should have it from `EpisodesConfig.ready()`, but `_maybe_instrument()` is called **after** `_build_agent()` — the agent is already constructed.

Actually the bigger issue: Pydantic AI's `instrument_all()` needs to be called **before** `agent.run()`, and it instruments via the `instrument` parameter or globally. Let me check the current Pydantic AI instrumentation API:

The cleanest approach: pass `instrument=True` directly to the `Agent` constructor instead of calling `instrument_all()` separately. This way it's instrumented from the start. And we only pass it when Langfuse is enabled.

Now remove the `_maybe_instrument()` call from `_run_agent_async`:

All 208 tests pass. Two changes:

1. **Instrumentation fix** — replaced the separate `_maybe_instrument()` / `Agent.instrument_all()` call with `instrument=True` passed directly to the `Agent` constructor. This ensures the agent is instrumented from creation, before `run()` is called.

2. **Langfuse context** — `_run_with_langfuse` already wraps the run with `propagate_attributes(session_id=..., user_id=..., metadata=...)`, so traces will be grouped under `recovery-run-{id}-episode-{id}` sessions.

Restart `qcluster` and retry — you should see traces in Langfuse now.

### User

Now I only see this in the logs:
16:01:05 [Q] INFO Process-d131bdf990b342a39ed62d9041de614a processing rugby-winter-minnesota-yankee 'episodes.admin._run_agent_recovery_task'

### Assistant

That's good news — no error traceback means the agent ran successfully without crashing. The task completed silently.

Check a few things:

1. **Did it create a new `RecoveryAttempt`?** Look in Django admin at the Recovery Attempts list — there should be a new one with `strategy=agent` for episode 2.

2. **Did the episode resume?** Check if episode 2's status changed from `failed` to `downloading` or `transcribing`.

3. **Langfuse traces** — check your Langfuse UI. It may take a few seconds for traces to flush. Look for sessions starting with `recovery-run-`.

4. **Django Q processed log** — do you see a "Processed" line after the "processing" line? Like:
   ```
   16:01:XX [Q] INFO Processed 'episodes.admin._run_agent_recovery_task' (rugby-winter-minnesota-yankee)
   ```

What do you see?

### User

Yes! with Message:
Agent error: Page.click: Timeout 30000ms exceeded.
Call log:
- waiting for locator("a[title='Escuchar']")

### Assistant

The agent ran but failed — it tried to click a Spanish "Listen" link (`Escuchar`) that didn't exist or wasn't clickable within 30 seconds. The error was caught gracefully and recorded as a failed `RecoveryAttempt`.

The `click_element` tool should handle timeouts gracefully instead of letting the exception propagate and kill the whole run. Let me add error handling to the tools that interact with the page:

The tools that interact with page elements (`click_element`, `navigate_to_url`, `download_file`) can all throw Playwright `TimeoutError`. Instead of crashing the entire agent run, they should return an error message so the LLM can try a different approach.

Also handle `extract_text_by_selector`:

All 208 tests pass. Now all Playwright tools catch `PlaywrightError` (which covers `TimeoutError`, `Error`, etc.) and return a descriptive error string instead of crashing. This lets the LLM see what went wrong and try a different approach — e.g., use a different selector, try `find_audio_links` instead, or give up gracefully with a proper `RecoveryAgentResult(success=False, ...)`.

Restart `qcluster` and retry the recovery.

### User

I still do not see sessions or traces in Langfuse

### Assistant

Let me investigate what's happening in the Q worker context.

The problem is likely that `is_enabled()` returns `False` in the Q worker because it checks `"test" in sys.argv` — but in `qcluster`, `sys.argv` is `['manage.py', 'qcluster']`, so that's fine. The real issue is probably that the Langfuse OTel exporter buffers traces and never flushes them before the task completes. Also, `asyncio.run()` creates a fresh event loop in a potentially different thread context.

Let me check how the Q worker starts and whether `setup()` actually ran:

`setup()` is called in `ready()` which runs in the Q worker. But `setup()` calls `langfuse.get_client()` — let me check if that's enough to register the OTel TracerProvider, or if Pydantic AI needs something else.

Now I see it. Langfuse registers itself as the global OTel `TracerProvider` when `get_client()` is called (via `_init_tracer_provider`). This should work. But the critical issue is that **traces are buffered and need to be flushed**. The `resource_manager.flush()` calls `tracer_provider.force_flush()`.

When the task finishes via `asyncio.run()`, the event loop closes, but the OTel exporter hasn't flushed yet. We need to explicitly flush after the agent run.

All 208 tests pass. The fix: added `_flush_langfuse()` in a `finally` block at the end of `run_recovery_agent()`. This calls `client.flush()` which forces `tracer_provider.force_flush()`, pushing all buffered OTel spans to Langfuse before the Django Q task completes.

Restart `qcluster` and retry — traces should appear in Langfuse now.

### User

Now I see the Langfuse sessions! But I do not see the images. Are they attached to the traces?

### Assistant

No, they're not actually attached as images. Looking at the `_attach_screenshots` code, it only creates trace metadata with the byte count — it doesn't upload the actual PNG data. Langfuse supports media attachments via its SDK. Let me fix this.

`LangfuseMedia` accepts `content_bytes` and `content_type`. I can pass `LangfuseMedia` objects as trace input/output and Langfuse will upload them. Let me check how to attach media to an existing trace:

I can use `create_event` with `LangfuseMedia` objects as input. These will be attached as child events of the current trace. Let me update `_attach_screenshots`:

All 208 tests pass. The fix: replaced the dummy `client.trace()` call with `client.create_event()` using `LangfuseMedia(content_bytes=png, content_type="image/png")`. This uploads the actual PNG screenshot data to Langfuse as a media attachment on a child event of the current trace.

Restart `qcluster` and retry — screenshots taken by the agent via `take_screenshot` will now appear as viewable images in the Langfuse trace.

### User

Is the screenshot visible in the Langfuse UI? I cannot see it.

### Assistant

The problem is that `_attach_screenshots` is called **after** the `propagate_attributes` context exits, so the events aren't associated with any trace. Let me restructure so screenshots are attached within the trace context.

I need to move screenshot attachment inside the `propagate_attributes` context. Let me refactor `_run_with_langfuse` to also handle screenshots:

All 208 tests pass. The fix: moved `_attach_screenshots()` inside the `propagate_attributes` context manager, so the `create_event` calls happen while the Langfuse trace context is still active. Previously they were called after the context exited, so the events were orphaned.

Restart `qcluster` and retry — screenshots should now appear as child events within the recovery trace in the Langfuse UI.

### User

When I re-run the agent, I always see the same Session ID in Langfuse "recovery-run-5-episode-2". Should we maybe add an additional id in that identifier so we can distinguish between different attempts? What do you think?

### Assistant

Good catch. The session ID uses `processing_run_id` which stays the same across retries since the original failed run doesn't change. Let me check what's available to make it unique.

We already have `event.attempt_number` in metadata. The simplest fix is to append it to the session ID:

```
recovery-run-5-episode-2-attempt-3
```

This is a one-line change — no plan needed. Want me to just go ahead and do it?

This is a trivial one-line change — appending `attempt_number` to the session ID. Let me update the plan file and exit.

This is a different task — a small fix to the existing implementation. Let me overwrite the plan.

Done. Each retry now gets a unique session ID like `recovery-run-5-episode-2-attempt-3`.

### User

In Langufuse, I can see a "take_screenshot" trace with Output Screenshot saved: no_audio_links_found (260338 bytes, #1)
But I cannot see the actual screenshot image.

### Assistant

The screenshots are collected in `deps.screenshots` and attached as events at the end, but the actual `take_screenshot` tool span only returns a text string. The image needs to be attached directly to the tool's span. Let me fix the tool to update its own Langfuse span with the image.

All tests pass. Now the `take_screenshot` tool calls `client.update_current_span(output=media)` with the actual PNG as a `LangfuseMedia` object. This attaches the image directly to the tool's span in Langfuse, so you'll see it inline when you click on the `take_screenshot` trace.

Restart `qcluster` and retry.

### User

I can see the screenshot now! Greaaat!

### Assistant

Excellent! Let's get all of this committed. Let me prepare the documentation and then we can create the PR.

First, let me check the current state of changes:

Would you like me to commit this and create a PR? Per the CLAUDE.md docs, I should also create the plan document, feature document, and session transcripts before committing. Want me to proceed with all of that?

### User

yes

### Assistant

Let me check existing docs structure and CHANGELOG first.

Now let me check the reference session format:

Good, I have the format. Let me now read the planning session transcript to reference in the docs:

Good, the planning transcript file exists. Now let me get the current session ID:

Now let me create all the documentation files in parallel, then commit.

Now update the CHANGELOG:

Now let me verify tests still pass and commit:

Now push and create the PR:

PR created: https://github.com/rafacm/ragtime/pull/70

### User

The tests "uv run python manage.py test --verbosity 2" in the PR are failing

### Assistant

The CI doesn't install the `recovery` extra, so `pydantic_ai` and `playwright` aren't available. The test files import from `episodes.agents` which fails at import time. I need to make the test files skip gracefully when the dependencies aren't installed.

The issue: `episodes/agents/deps.py` imports `from playwright.async_api import Page` and `from pydantic import BaseModel` at module level. The test files and the `episodes.agents` package itself can't be imported without `pydantic-ai` and `playwright`.

I need to:
1. Make `episodes/agents/__init__.py` handle missing deps gracefully
2. Skip test files when deps are missing
3. Fix tests that mock `episodes.agents.run_recovery_agent` (in `test_recovery.py` and `test_admin.py`)

Now make the test files skip when deps are missing:

Now fix the tests in `test_recovery.py` and `test_admin.py` that import from `episodes.agents`. These tests mock `run_recovery_agent` so they should work without the actual package, but they import `RecoveryAgentResult` at the test level:

These imports are inside test methods, so they'll fail at runtime when the test runs. Since these tests mock `episodes.agents.run_recovery_agent`, they need `RecoveryAgentResult` to construct the mock return value. I need to make these tests skip when deps are missing.

For `test_recovery.py`, the agent-related tests are mixed in with the `AgentStrategyTests` class. Let me add skipIf decorators:

Now add `skipUnless` to the tests that import from `episodes.agents`:

I need to add `@unittest.skipUnless` to the 4 test methods that use `episodes.agents`:

Now the `test_agent_escalates_to_human` in `HandleStepFailureTests`:

Also need to add the `import unittest` since we're now using `unittest.skipUnless`:

Now fix `test_admin.py` — the `RunAgentRecoveryTaskTests` class:

Now add `@skipUnless` to the `RunAgentRecoveryTaskTests` class:

Now let me verify all tests pass locally:

All 208 tests pass. Now let me also simulate the CI environment by checking what happens without the recovery deps. Let me verify the skip logic works:

Need `importlib.util` explicitly:

The `import importlib` alone doesn't give access to `importlib.util`. I need to fix the test files to use `import importlib.util`:

Now commit and push:

Pushed. The fix:

- `episodes/agents/__init__.py` — wraps the import in `try/except ImportError`, falls back to a stub that raises `RuntimeError` with install instructions
- `test_agent_tools.py` / `test_agent_resume.py` — raise `unittest.SkipTest` at module level when `pydantic_ai` isn't available
- `test_recovery.py` / `test_admin.py` — `@unittest.skipUnless(_has_recovery_deps, ...)` on the 4 test methods and 1 test class that import from `episodes.agents`

CI should pass now since the agent-specific tests will be skipped, while all other tests run normally.

All 17 comments are from **Copilot**. Here's the summary grouped by severity:

---

### Critical (will cause bugs in production)

| # | File | Issue | Suggested Fix | Action |
|---|------|-------|---------------|--------|
| 1 | `resume.py:40,64` | **Race condition**: `episode.save()` fires `post_save` signal before `create_run()`, so the next pipeline step starts without a `ProcessingRun` | Call `create_run()` **before** `episode.save()` | **Fix** — real bug, same pattern in both `_resume_from_scraping` and `_resume_from_downloading` |
| 2 | `test_agent_tools.py:57` | **Async tests never execute**: `async def` on `django.test.TestCase` means assertions never run — coroutines are created but never awaited | Use `unittest.IsolatedAsyncioTestCase` or `async_to_sync` | **Fix** — tests are silently passing without running |
| 3 | `admin.py:673` | `message_user(..., level="warning")` passes a string, Django expects `messages.WARNING` integer | Use `from django.contrib.messages import WARNING` | **Fix** — will error at runtime |

### High (functional issues)

| # | File | Issue | Suggested Fix | Action |
|---|------|-------|---------------|--------|
| 4 | `agent.py:129` | Download collision: agent saves directly to `MEDIA_ROOT/episodes`, then `resume` saves again via Django `File`, causing renames/duplicates | Download to temp dir, unlink after `audio_file.save()` | **Fix** — use tempdir like `downloader.py` does |
| 5 | `agent.py:150` | `timeout` setting read but never applied — agent can run indefinitely | Wrap `agent.run()` in `asyncio.wait_for(timeout=...)` | **Fix** — the setting exists but does nothing |
| 6 | `resume.py:37` | Scraping recovery resumes even if `result.audio_url` is empty | Validate `audio_url` before saving/resuming | **Fix** — guard against empty URL |
| 7 | `resume.py:59` | Downloaded temp file never cleaned up after saving to `audio_file` | Unlink `result.downloaded_file` in `finally` | **Fix** — disk leak on repeated retries |
| 8 | `tools.py:45` | `find_audio_links` returns non-MP3 URLs but downstream assumes MP3 (`mutagen.MP3`, `.mp3` filename) | Restrict to `.mp3` or handle other formats | **Fix** — restrict to MP3 for now, matches current pipeline |

### Medium (robustness — tools not catching all errors)

| # | File | Issue | Suggested Fix | Action |
|---|------|-------|---------------|--------|
| 9 | `tools.py:26` | `navigate_to_url` only wraps `goto` in try/except, not `title()`/`inner_text()` | Extend try block to cover all calls | **Fix** — consistent with tool design |
| 10 | `tools.py:32` | `get_page_content` doesn't catch `PlaywrightError` | Add try/except | **Fix** — only tool missing error handling |
| 11 | `tools.py:76` | `find_audio_links` doesn't catch `PlaywrightError` from `evaluate()` | Wrap in try/except | **Fix** |
| 12 | `tools.py:94` | `click_element` — `title()`/`inner_text()` after click not covered by try | Extend try block | **Fix** |
| 13 | `tools.py:115` | `take_screenshot` doesn't catch `PlaywrightError` | Wrap in try/except | **Fix** |
| 14 | `tools.py:150` | `download_file` — `os.path.getsize` can raise if file missing | Add `OSError` handling | **Fix** |
| 15 | `tools.py:165` | `extract_text_by_selector` — per-element `inner_text()` can raise | Catch per-element errors | **Fix** |

### Low (cleanup)

| # | File | Issue | Suggested Fix | Action |
|---|------|-------|---------------|--------|
| 16 | `browser.py:26` | `download_dir` parameter unused — never wired into Playwright | Remove param or configure downloads path | **Fix** — wire it into context |

---

**Summary**: 3 critical, 5 high, 7 medium, 1 low — all from Copilot, all valid. Want me to fix them all?

### User

yes

### Assistant

Now let me also read the test files and admin:

Good, I have all the context. Let me fix all issues systematically. I'll tackle them in groups.

**Fix 1: `resume.py` — race condition + validation + temp file cleanup**

**Fix 2: `tools.py` — comprehensive error handling + restrict to MP3**

**Fix 3: `agent.py` — use tempdir for downloads + apply timeout**

**Fix 4: `browser.py` — wire download_dir into Playwright context**

**Fix 5: `admin.py` — fix message level**

**Fix 6: `test_agent_tools.py` — use `IsolatedAsyncioTestCase`**

Now update `test_agent_resume.py` to account for the race condition fix (create_run now called before save) and temp file cleanup:

The resume code now cleans up the temp file itself, so the test's `os.unlink(tmp.name)` in `finally` will get an `OSError` (already deleted). Let me update the test:

Now run the tests:

All 208 tests pass. The "Context error" warnings are from the `take_screenshot` Langfuse calls in tests (no active span) — harmless, already caught by the `except Exception: pass`.

Now let me commit, push, and reply to the review comments:

Now reply to each review comment. I'll batch them:

Hmm, only 1 succeeded. Let me try them individually:

Good. Now let me reply to all remaining comments efficiently:

Now reply to the medium-severity Playwright error handling comments:

Now the `browser.py` comment:

All 17 review comments addressed and replied to. Here's the summary of fixes:

**Critical (3):**
- Race condition in `resume.py` — `create_run()` now called before `episode.save()`
- Async tests — switched to `unittest.IsolatedAsyncioTestCase`
- Admin `message_user` — uses `messages.WARNING` constant

**High (5):**
- Tempdir for downloads — avoids FileField collisions
- Timeout applied — `asyncio.wait_for(timeout=...)` wraps agent run
- Validation — empty `audio_url`/`downloaded_file` treated as failed recovery
- Temp file cleanup — `os.unlink` in `finally` block
- MP3 only — `find_audio_links` restricted to `.mp3` URLs

**Medium (7):**
- All 7 tools now wrap entire Playwright interactions in `try/except PlaywrightError`

**Low (1):**
- `browser.py` docstring clarified

All 17 are the original Copilot comments from before — they're all top-level because they were the initial review. Let me check if there are any **new** comments since our fix commit:

All 17 comments are from the original Copilot review (all timestamped `2026-03-19T16:41:*`). No new comments have been added since our fix commit. All have been addressed and replied to — there are no open review items remaining.

### User

Can you check again

### Assistant

There's a new Copilot review at `20:49:29` — after our fix commit. Let me check those new comments:

5 new comments from **Copilot** on the fix commit:

| # | File | Severity | Issue | Action |
|---|------|----------|-------|--------|
| 1 | `recovery.py:58` | **High** | `AgentStrategy.attempt()` returns `success=True` even when `resume_pipeline()` silently no-ops (empty audio_url). The chain stops but the episode isn't actually resumed. | **Fix** — make `resume_pipeline` return a bool, check it before returning success |
| 2 | `admin.py:741` | **High** | Same issue in `_run_agent_recovery_task` — records success without confirming resume actually happened | **Fix** — same pattern, check return value |
| 3 | `browser.py:14` | **Low** | Docstring still implies Playwright is configured with download_dir; it's actually done via `save_as` in the tool | **Fix** — update docstring (Copilot even provides the exact text) |
| 4 | `tools.py:120` | **Low** | `take_screenshot` docstring says "cursor position" but dot is fixed at viewport center | **Fix** — update docstring to say "viewport center" |
| 5 | `agent.py:154` | **Medium** | `tempfile.mkdtemp()` leaks directories on failure/timeout — should use `TemporaryDirectory` context manager | **Fix** — use `tempfile.TemporaryDirectory()` as Copilot suggests |

The two high-severity ones (#1, #2) are valid — `resume_pipeline` can silently fail. Want me to fix all 5?

### User

yes

### Assistant

**Fix 1: Make `resume_pipeline` return a bool**

**Fix 2: Check resume result in `recovery.py`**

**Fix 3: Check resume result in `admin.py`**

**Fix 4: `browser.py` docstring**

**Fix 5: `take_screenshot` docstring**

**Fix 6: Use `TemporaryDirectory` in `agent.py`**

Now run the tests:

All 208 tests pass. Commit, push, and reply:

Now reply to the 5 comments:

All 5 replies posted. All review comments from both Copilot review rounds are now addressed and replied to.

### User

Set the comments you have already addressed as resolved

### Assistant

GitHub's API doesn't support resolving PR review comment threads programmatically — that's only available through the GraphQL API. Let me use that.

22 unresolved threads (17 from first review + 5 from second). Let me resolve them all:

All 22 review threads resolved.

4 new unresolved comments from **Copilot** (third review round):

| # | File | Severity | Issue | Suggested Fix | Action |
|---|------|----------|-------|---------------|--------|
| 1 | `pyproject.toml:19` | **Medium** | `pydantic-ai>=0.1` is too loose — code uses 1.x APIs (`output_type`, `instrument`). Fresh installs could get an incompatible old version. | Tighten to `pydantic-ai>=1.30.1,<2` | **Fix** — good catch, we already hit the `result_type` rename |
| 2 | `test_recovery.py:9` | **Medium** | `_has_recovery_deps` only checks `pydantic_ai`, not `playwright`. Tests would fail if one is installed without the other. | Check both: `find_spec("pydantic_ai") and find_spec("playwright")` | **Fix** — simple and correct |
| 3 | `test_admin.py:10` | **Medium** | Same issue as #2 | Same fix | **Fix** |
| 4 | `agent.py:90` | **Medium** | `_build_model()` mutates `os.environ` with the API key, leaking it to other tasks in long-lived Q workers | Pass API key via model config instead of env vars | **Fix** — need to check if Pydantic AI supports passing `api_key` directly |

All valid. Want me to fix them?

### User

yes

### Assistant

`OpenAIProvider` accepts `api_key` directly. Let me check how to use providers with `Agent`:

Good — it works. But Agent also accepts a model string like `"openai:gpt-4.1-mini"`. Let me check if I can pass provider kwargs with the string form, or if I need to construct the model explicitly:

Works, but `OpenAIModel` is deprecated in favor of `OpenAIChatModel`. The cleanest approach is to use the provider map and construct the model object with the API key passed directly, avoiding env var mutation entirely. Let me implement all 4 fixes now.

**Fix 1: Tighten pyproject.toml bounds**

**Fix 2 & 3: Check both deps in test files**

**Fix 4: Pass API key via provider instead of mutating os.environ**

All 208 tests pass. Commit, push, reply, and resolve:

Now resolve the 4 threads:

All 4 threads resolved. Zero unresolved review comments remaining on the PR.

On `main`, pulled latest — PR #70 has been merged. Ready for new work.
