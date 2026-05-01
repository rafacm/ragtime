# Replace Continue AI with self-hosted AI checks GitHub Action

**Date:** 2026-05-01

## Problem

#117 introduced Continue.dev as the runner for `.continue/checks/`. The checks rendered on PRs as `Agent encountered an error` rather than real verdicts — opaque, unreliable, and dependent on a third-party SaaS we want to retire. The 9 rule files themselves (well-shaped Markdown, capturing repo-specific invariants and past incidents) are valuable; only the runner needed to be replaced.

We surveyed the OSS GitHub Action ecosystem (PR-Agent, Claude Code Action, ChatGPT-CodeReview, freeedcom/ai-codereviewer, promptfoo). None offer the Continue UX of "directory of Markdown rules → one PR check row per rule, BYO LLM key, provider-neutral". The category is dominated by SaaS bots; OSS alternatives produce a single combined review, not per-rule rows. The 50-line custom workflow ends up being the standard answer when teams want self-hosted + per-rule checks.

## Changes

- **Rules directory.** Moved `.continue/checks/*.md` → `.ai-checks/*.md` verbatim (same frontmatter, same body). 9 rules. Deleted `.continue/`.
- **Matrix emitter** (`.github/scripts/list_ai_checks.py`). Scans `.ai-checks/*.md`, extracts each `name:` from frontmatter, writes `matrix={"include": [{"name": "<rule name>", "path": "<path>"}, ...]}` to `$GITHUB_OUTPUT`.
- **Driver** (`.github/scripts/run_ai_check.py`). Parses frontmatter, computes `git diff $BASE_REF...HEAD`, optionally short-circuits to `skip` via frontmatter `paths:` globs, calls LiteLLM with a `report_verdict` function (`pass`/`fail`/`skip` + summary + details), writes a Markdown summary to `$GITHUB_STEP_SUMMARY`, exits 1 on `fail`. Diff truncated at 200 KB. Conservative system prompt: returns `fail` only with concrete diff evidence.
- **Workflow** (`.github/workflows/ai-checks.yml`). Two jobs: `list` builds the matrix, `check` fans out via `strategy.matrix` with `fail-fast: false`. Each matrix shard's `name:` is `AI Check: <rule name>`, so each rule appears as its own PR status row. Env block exposes `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` from secrets — LiteLLM picks the one matching the chosen model. Triggered on `pull_request: branches: [main]`.

LiteLLM provides the provider abstraction. The model string carries the provider as a prefix (`openai/gpt-4o-mini`, `anthropic/claude-sonnet-4-6`, `gemini/gemini-2.0-flash`). LiteLLM normalizes function-calling across providers, so the same `report_verdict` tool definition works against any of them. Switching providers is a one-line repo-variable change (`AI_CHECK_MODEL`) plus the matching API key secret — no driver edits.

We deliberately do **not** generalize the API key env var name to `AI_CHECK_PROVIDER_API_KEY`. Every SDK auto-reads its own canonical name; renaming would break copy-pasted snippets, force users to re-do their repo secrets, and add wiring code for nothing. The convention is "use each provider's canonical name verbatim" and LiteLLM follows it.

## Key parameters

| Parameter | Value | Why |
|---|---|---|
| `AI_CHECK_MODEL` (default) | `openai/gpt-4o-mini` | Fast, cheap, sufficient for code-review judgment. LiteLLM model string `<provider>/<model>`. Repo-variable override; per-rule override via frontmatter `model:`. |
| Required secret (default) | `OPENAI_API_KEY` | Matches the default model. Switching models swaps the required secret. |
| `MAX_DIFF_CHARS` | `200_000` | Large refactors should not balloon the prompt. Soft truncation with a marker. |
| `max_tokens` (LLM response) | `2048` | Verdict + summary + details fit comfortably; over-generation is wasted cost. |
| `tool_choice` | `{"type": "function", "function": {"name": "report_verdict"}}` | Forces structured output. LiteLLM maps to native function-calling on each provider. |
| Workflow trigger | `pull_request: branches: [main]` | Push events have no useful diff context; PR diff is the unit of review. |
| `strategy.fail-fast` | `false` | One failing model call must not abort the rest. |
| `git fetch --depth=200` | 200 commits | Enough history for any realistic PR base; cheaper than `fetch-depth: 0`. |

## Verification

**Locally** (parser + matrix emitter only — no API call):

```bash
uv run --with litellm python -c "
import sys; sys.path.insert(0, '.github/scripts')
from run_ai_check import parse_check
from pathlib import Path
for p in sorted(Path('.ai-checks').glob('*.md')):
    fm, body = parse_check(p)
    print(p.name, '->', fm.get('name'), 'body:', len(body), 'chars')"

python3 .github/scripts/list_ai_checks.py
```

Expected: all 9 rules parse with non-empty `name:` and body; matrix emitter prints a single `matrix={...}` line with 9 `include` entries.

**In CI** (after adding `OPENAI_API_KEY` to repo secrets):

1. Open a PR against `main`.
2. Confirm 9 rows of the form `AI Check: <rule name>` appear in the PR's Checks tab.
3. Confirm each row's job page shows a Markdown summary with verdict + reasoning.
4. Switch providers: change repo variable `AI_CHECK_MODEL` to `anthropic/claude-sonnet-4-6`, ensure `ANTHROPIC_API_KEY` secret exists, rerun. No driver edits required.

## Files modified

- `.continue/checks/*.md` → `.ai-checks/*.md` — 9 rule files, moved verbatim. `.continue/` directory removed.
- `.github/scripts/list_ai_checks.py` — new. Matrix emitter, prints `matrix={...}` to `$GITHUB_OUTPUT`.
- `.github/scripts/run_ai_check.py` — new. Frontmatter parser + diff fetcher + path-glob filter + LiteLLM call + step-summary writer + exit-code mapper.
- `.github/workflows/ai-checks.yml` — new. `list` job builds the matrix, `check` job fans out.
- `doc/plans/2026-05-01-ai-checks-action.md` — plan for this work.
- `doc/features/2026-05-01-ai-checks-action.md` — this feature doc.
- `doc/sessions/2026-05-01-ai-checks-action-planning-session.md` — planning session transcript.
- `doc/sessions/2026-05-01-ai-checks-action-implementation-session.md` — implementation session transcript.
- `CHANGELOG.md` — entry under `## 2026-05-01`.

## Out of scope

- Promoting any of the new rows to required-merge status — per-rule decision once false-positive rates are known.
- Aggregate sticky-comment surface in addition to per-rule rows.
- Extracting the driver into its own reusable Action repo — iterate in-tree first.
