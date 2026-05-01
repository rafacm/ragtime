# Replace Continue AI with self-hosted AI checks GitHub Action

**Date:** 2026-05-01

## Problem

#117 introduced Continue.dev as the runner for `.continue/checks/`. The checks have been surfacing on PRs as `Agent encountered an error` rather than real verdicts — unreliable, opaque, and a third-party SaaS dependency we now want to retire. The rules themselves are valuable; the runner is the part to replace.

## Goals

- One PR check row per rule (matching the Continue UX), with the rule's `name:` field rendered in GitHub's status row.
- Self-hosted in our CI. No SaaS bot. BYO LLM API key.
- Provider-neutral: switch between OpenAI / Anthropic / Gemini by changing one repo variable, no driver edits.
- Migrate the 9 existing rules verbatim — same frontmatter, same body — only the directory name changes.

## Non-goals

- Promoting any of the new rows to required-merge status. That's a per-rule decision once false-positive rates are known.
- Posting a single sticky aggregate comment in addition to per-rule rows. Can come later.
- Extracting the driver into its own reusable Action repo. Iterate in-tree first.
- Any change to the rule format (`---` frontmatter + Markdown body stays as-is).

## Approach

A small GitHub Actions workflow with two jobs:

1. `list` — runs a Python script that scans `.ai-checks/*.md`, parses each frontmatter for `name:`, and writes a JSON matrix of `{name, path}` to `$GITHUB_OUTPUT`.
2. `check` — `strategy.matrix: ${{ fromJson(needs.list.outputs.matrix) }}`, `fail-fast: false`. Each matrix shard runs `run_ai_check.py` against one rule. The job's `name:` uses the rule's `name:` field, so the GitHub UI shows one status row per rule.

The driver script:

- Parses the rule file's frontmatter (YAML-ish: simple `key: value` pairs, no nested structures needed).
- Reads `git diff origin/<base>...HEAD` for changed files + diff content.
- If frontmatter has `paths:` (comma-separated globs) and no changed file matches, returns `skip` without calling the LLM.
- Calls the LLM via [LiteLLM](https://github.com/BerriAI/litellm) with a `report_verdict` function (verdict ∈ `pass`/`fail`/`skip`, summary, details). LiteLLM normalizes function calling across providers.
- Writes verdict + reasoning to `$GITHUB_STEP_SUMMARY`.
- Exits 1 on `fail`, 0 on `pass`/`skip`.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Rules directory | `.ai-checks/` (repo root) | Mirrors `.continue/`'s position. Top-level signals "first-class config", not nested under `.github/`. |
| Driver location | `.github/scripts/` | Matches GH Actions convention for workflow-only Python helpers. |
| Provider routing | LiteLLM | Industry-standard router. Model string carries the provider (`<provider>/<model>`); LiteLLM auto-reads each provider's canonical env var. Lightweight enough for a CI driver. |
| Default model | `openai/gpt-4o-mini` | Fast, cheap, sufficient for code-review judgment. Per-rule override via `model:` frontmatter; workflow-wide override via repo variable `AI_CHECK_MODEL`. |
| API key env vars | Provider-canonical (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) | Every SDK auto-reads its canonical name. Generalizing to `AI_CHECK_PROVIDER_API_KEY` would break copy-pasted snippets and force users to re-do their repo secrets. |
| Structured output | LiteLLM's normalized function-calling (`tools` + `tool_choice`) | Maps to native function-calling on every major provider. More robust across providers than `response_format: json_schema`. |
| Per-rule path scoping | Frontmatter `paths:` (comma-separated `fnmatch` globs) | None of the 9 migrated rules need it yet. Available so token cost can be controlled per-rule when wanted. |
| Workflow trigger | `pull_request` only | Push events have no diff context that's useful here; PR diff is the unit of review. |
| Failure handling | `fail-fast: false` on the matrix | One slow / failing model call must not abort the others. |
| Branch protection | Off by default | Each row appears as `AI Check: <name>`; mark required individually once trust is built. |
| Diff truncation | 200 KB hard cap | Large refactors should not balloon the prompt. Soft truncation with a `[...diff truncated...]` marker. |

## Implementation steps

1. Create branch `feature/ai-checks-action` off `main`.
2. `git mv .continue/checks/*.md .ai-checks/` and `rm -rf .continue/`.
3. Add `.github/scripts/list_ai_checks.py` (matrix emitter — reads `.ai-checks/*.md`, parses `name:`, writes `matrix={"include": [...]}` to `$GITHUB_OUTPUT`).
4. Add `.github/scripts/run_ai_check.py` (driver — frontmatter parser, diff fetcher, path-glob filter, LiteLLM call with `report_verdict` tool, step-summary writer, exit-code mapper).
5. Add `.github/workflows/ai-checks.yml` (`list` + `check` jobs as above; env block exposes `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` from secrets so any can route via LiteLLM).
6. Smoke-test parser locally (`uv run --with litellm`).
7. Add `OPENAI_API_KEY` to repo secrets *(manual; user action)*.
8. Open PR, observe one `AI Check: <name>` row per rule on the PR's Checks tab.

## Documentation deliverables

The implementation PR commit must include:

- This plan: `doc/plans/2026-05-01-ai-checks-action.md`
- Feature doc: `doc/features/2026-05-01-ai-checks-action.md`
- Planning session transcript: `doc/sessions/2026-05-01-ai-checks-action-planning-session.md`
- Implementation session transcript: `doc/sessions/2026-05-01-ai-checks-action-implementation-session.md`
- `CHANGELOG.md` entry under `## 2026-05-01` (`### Added` for the workflow + `.ai-checks/`; `### Removed` for `.continue/`).

Branch name: `feature/ai-checks-action`.

## Out of scope

- Issue #117's promotion of any check to a required merge gate stays an open per-rule decision.
- Aggregate sticky-comment surface — per-rule rows already cover the Continue UX.
- Migration of the rule format itself — body and frontmatter are unchanged across the move.
