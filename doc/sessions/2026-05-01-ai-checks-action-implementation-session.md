# Replace Continue AI with self-hosted AI checks GitHub Action — Implementation Session

**Date:** 2026-05-01

**Session ID:** 401925df-5642-48c2-ad82-9a09c252e1cd

## Summary

Implemented the design from the planning session. Migrated `.continue/checks/*.md` → `.ai-checks/*.md` (verbatim, 9 files). Wrote a matrix emitter (`list_ai_checks.py`), a single-rule driver (`run_ai_check.py`), and a workflow (`ai-checks.yml`) with a `list` job + `check` matrix-fanout job. First-pass driver used the Anthropic SDK; refactored mid-implementation to LiteLLM after a design discussion in the planning session shifted the provider model from "Anthropic-only" to "provider-neutral via model-string routing". Default model: `openai/gpt-4o-mini`. Smoke-tested the parser and matrix emitter locally. Updated GitHub issue #121 body to reflect the LiteLLM-based design. Wrote plan, feature doc, both session transcripts, and CHANGELOG entry. Ran the full test suite before committing (per project feedback memory).

## Detailed conversation

### User

go ahead

### Assistant

Started on `main`, pulled latest, created `feature/ai-checks-action`. Inspected the existing `.github/workflows/ci.yml` and one more `.continue/checks/` rule (`env-var-sync.md`) to confirm format consistency.

First-pass scaffold (Anthropic-based):

- `git mv .continue/checks/*.md .github/ai-checks/` and `rm -rf .continue/`. (Initial location was `.github/ai-checks/`; renamed below.)
- Wrote `.github/scripts/run_ai_check.py`:
  - Parses YAML-ish frontmatter with a regex (`^---\n(.*?)\n---\n(.*)$`).
  - Reads `git diff $BASE_REF...HEAD` for both content and changed file list.
  - Optional frontmatter `paths:` → `fnmatch` filter against changed files; returns `skip` early if none match.
  - Truncates diff at `MAX_DIFF_CHARS = 200_000` with a `[...diff truncated...]` marker.
  - Calls Anthropic with a `report_verdict` tool (`tool_choice` forced) — verdict ∈ `pass`/`fail`/`skip` + summary + details.
  - Writes a `[PASS]/[FAIL]/[SKIP] <name>` Markdown summary to `$GITHUB_STEP_SUMMARY`.
  - Exits 1 on `fail`, 0 on `pass`/`skip`.
  - Conservative system prompt: returns `fail` only with concrete diff evidence.
- Wrote `.github/scripts/list_ai_checks.py` — emits `matrix={"include": [{"name": <rule name>, "path": <path>}, ...]}` to `$GITHUB_OUTPUT`.
- Wrote `.github/workflows/ai-checks.yml`:
  - Trigger: `pull_request: branches: [main]`.
  - `permissions: contents: read, pull-requests: read`.
  - `list` job runs the matrix emitter and surfaces `matrix` as a job output.
  - `check` job: `needs: [list]`, `if: ${{ fromJson(needs.list.outputs.matrix).include[0] != null }}`, `strategy.matrix: ${{ fromJson(needs.list.outputs.matrix) }}`, `fail-fast: false`, `name: "AI Check: ${{ matrix.name }}"`.
  - Steps: checkout (`fetch-depth: 0`), `setup-uv@v6`, `git fetch --depth=200 origin <base>`, `uv run --with anthropic python .github/scripts/run_ai_check.py "${{ matrix.path }}"`.
  - Env: `ANTHROPIC_API_KEY` from secrets; `BASE_REF: origin/${{ github.event.pull_request.base.ref }}`; `AI_CHECK_MODEL: ${{ vars.AI_CHECK_MODEL || 'claude-sonnet-4-6' }}`.

### User

Which name can we give to the new directory instead of ".continue/checks"?

### Assistant

Discussed naming options (transcribed in the planning session).

### User

Ah! ".ai-checks" looks good!

### Assistant

`git mv .github/ai-checks .ai-checks` to move the rules to the repo root.

### Assistant (smoke test)

Ran the matrix emitter locally — printed a single-line `matrix={...}` with all 9 rules and their `name:` values. Ran the frontmatter parser via `uv run --with anthropic python -c "..."` against all 9 rules — all parsed cleanly with non-empty bodies (2,741–4,145 chars).

### User

Can you create an issue for this?

### Assistant

Inspected the repo (`rafacm/ragtime`) and read issue #117 to mirror its style. Drafted issue body covering Background / Proposal / Layout / Behaviour / Design principles / Migration / Out of scope / Closes-relates-to. Created via `gh issue create --title "Replace Continue AI with self-hosted GitHub Action for AI PR checks" --label enhancement --body <heredoc>`. Issue #121 created at https://github.com/rafacm/ragtime/issues/121.

### User

I would actually like to use OpenAI instead of Anthropic for this? Are there any best practices to make environment keys NOT provider specific? Or does the code check whether ANTHROPIC_API_KEY or OPENAI_API_KEY is available? What about renaming it to "AI_CHECL_PROVIDER_API_KEY" to follow "AI_CHECK_MODEL"? What's the format of "AI_CHECK_MODEL" by the way?

### Assistant

Discussed the design tradeoff (transcribed in the planning session). Offered to refactor to LiteLLM with `openai/gpt-4o-mini` as the new default.

### User

yes

### Assistant

Refactored the driver to use LiteLLM:

- Replaced `import anthropic` with `import litellm`.
- Reshaped `REPORT_TOOL` from Anthropic's `{"name", "description", "input_schema"}` shape to OpenAI's `{"type": "function", "function": {"name", "description", "parameters"}}` shape — LiteLLM's normalized form, which it maps to native function-calling on every provider.
- Replaced `anthropic.Anthropic().messages.create(...)` with `litellm.completion(...)`. Result extraction now reads `resp.choices[0].message.tool_calls[0].function.arguments` (JSON string) and `json.loads()`-es it.
- `DEFAULT_MODEL = "openai/gpt-4o-mini"`.
- Updated docstring and `--model` help text to say "LiteLLM model string".

Updated `.github/workflows/ai-checks.yml`:

- Env block now exposes `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` from secrets (only the one matching the chosen model needs to actually be set).
- Default `AI_CHECK_MODEL` changed to `openai/gpt-4o-mini`.
- Install line changed to `uv run --with litellm python ...`.

Smoke-tested: `uv run --with litellm python -c "import run_ai_check; ..."` — LiteLLM (and `openai` transitive) installed and imported cleanly; default model resolved to `openai/gpt-4o-mini`; parser still reads the rules.

Updated issue #121 body via `gh issue edit 121 --body <heredoc>` to reflect the LiteLLM design, add the provider/secret table, and add the explicit "we do not generalize the env var name to `AI_CHECK_PROVIDER_API_KEY`" rationale.

### User

Create a PR with this changes

### Assistant

Per CLAUDE.md the PR commit must include the plan, feature doc, both session transcripts, and a CHANGELOG entry. Wrote:

- `doc/plans/2026-05-01-ai-checks-action.md` — plan.
- `doc/features/2026-05-01-ai-checks-action.md` — feature doc.
- `doc/sessions/2026-05-01-ai-checks-action-planning-session.md` — planning session transcript.
- `doc/sessions/2026-05-01-ai-checks-action-implementation-session.md` — this transcript.
- `CHANGELOG.md` — entry under `## 2026-05-01`: `### Added` for `.ai-checks/` + workflow + driver + LiteLLM provider routing; `### Removed` for `.continue/`.

Ran the full test suite before committing per the project's feedback memory ("Run tests before committing"). Then staged the migration (`git mv` shows up as `R` rename entries), the new files, the docs, and the changelog. Committed and opened the PR.
