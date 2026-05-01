# Replace Continue AI with self-hosted AI checks GitHub Action — Planning Session

**Date:** 2026-05-01

**Session ID:** 401925df-5642-48c2-ad82-9a09c252e1cd

## Summary

Planned a replacement for Continue.dev as the runner for `.continue/checks/`. Adopting Continue.dev before RAGtime had its own eval infrastructure was premature; the motivation for retiring the runner now is provider-account consolidation (the project already pays for OpenAI and Anthropic — adding a third billable account is overhead) rather than a product critique. Continue.dev is on the table to revisit once #115's eval infrastructure lands. The 9 rule files (capturing repo-specific invariants and past incidents from #117) are valuable and stay verbatim. Surveyed the OSS GitHub Action ecosystem and concluded no off-the-shelf tool offers the Continue UX (one PR check row per rule, BYO LLM key, prompts as Markdown). The category splits into SaaS bots (CodeRabbit, Greptile, Ellipsis) and OSS PR-review actions that emit a single combined review (PR-Agent, Claude Code Action). Closest mechanical fit is `promptfoo`, but it's off-label. Decision: build a small in-tree workflow — matrix-fanout with one job per rule, Python driver, LiteLLM for provider routing, default `openai/gpt-4o-mini`, default secret `OPENAI_API_KEY`. Directory renamed to `.ai-checks/`. Provider neutrality lives in the model string, not the API key env var.

## Detailed conversation

### User

In issue #117 we introduced Continue AI but it is giving us issues with failing checks and after thinking about it better we want to reduce dependency to third-party services for the time being. What solutions in the form of GitHub actions are out there that would allow us to reuse the existing prompts in ".continue/checks" against a remote LLM and report the results in the PR similar to how Continue AI does it: [screenshot of 9 failing `Continuous AI: <name>` checks, all "Agent encountered an error"]

### Assistant

Inspected `.continue/checks/` to confirm the format (frontmatter `name`/`description` + Markdown body, 9 files). Read one in full (`asgi-wsgi-scott.md`) to ground the discussion. Surveyed three categories of alternative:

1. **Roll-your-own** — small workflow + Anthropic/OpenAI SDK call. Matrix fan-out, one job per check file, each job posts via the GitHub Checks API. Matches Continue UX 1:1, ~50 lines of Python, zero third-party SaaS.
2. **`anthropics/claude-code-action`** — official action, runs Claude Code on PRs. Less control over per-check status rows; better suited to "one combined review".
3. **`qodo-ai/pr-agent`** — open-source, self-deployed with own API key. Has its own review-format/config schema, so the existing `.continue/checks/*.md` would have to be rewritten. Probably not worth the migration.

Recommended option 1 with the tradeoff: keeps the existing prompt format unchanged and gives one status row per rule, for the cost of one workflow file. Asked whether to draft it.

### User

I'm OK migrating the prompts/configuration currently in ".continue/checks/". We should actually do it since we will not be using Continue AI. I was asking in the more general view of whether such a GitHub Action already exists, i.e. run this prompt + configuration against a (configurable) LLM and report the results in the GitHub PR. This is a general high-level need for many projects.

### Assistant

Re-framed the answer for the more general question. The category as a polished off-the-shelf product does not exist:

- **SaaS PR-review bots with custom rules** — Continue itself, plus CodeRabbit, Greptile, Ellipsis, Bito, Korbit, Cursor BugBot, Diamond (Graphite). All third-party services.
- **Open-source GH Actions for AI PR review** — `qodo-ai/pr-agent`, `anc95/ChatGPT-CodeReview`, `freeedcom/ai-codereviewer`, `anthropics/claude-code-action`. Self-hosted, BYO key. But all produce a single combined review/comment, not one check per rule.
- **Surprise mechanical fit: `promptfoo`** — built for prompt regression testing, but its model is exactly "folder of prompt configs → run each → pass/fail per prompt → GH Action posts a check". Off-label use; would need a thin adapter to feed the diff and split into per-check rows.

The gap is real and recurring. The ecosystem hasn't filled it because the custom-workflow answer is small enough that teams keep writing their own and not extracting them. Offered to scaffold a generic-enough version.

### User

go ahead

### Assistant

Confirmed the plan before scaffolding:

- Move `.continue/checks/*.md` → new directory at repo root, retire `.continue/`.
- New `.github/scripts/list_ai_checks.py` that scans the rules dir and emits a JSON matrix to `$GITHUB_OUTPUT`.
- New `.github/scripts/run_ai_check.py` that parses one rule, computes `git diff origin/main...HEAD`, calls the LLM with a `report_verdict` tool (verdict ∈ `pass`/`fail`/`skip` + summary + details), exits 1 on `fail`.
- New `.github/workflows/ai-checks.yml` with a `list` job + a matrix-fanout `check` job (one matrix shard per rule, `fail-fast: false`, job name `AI Check: <rule name>`).
- First-pass driver uses the Anthropic SDK with `claude-sonnet-4-6` as the default; secret `ANTHROPIC_API_KEY`.

Switched to `main`, pulled latest, branched to `feature/ai-checks-action`. Began implementation (transcribed in the implementation session).

### User

Which name can we give to the new directory instead of ".continue/checks"?

### Assistant

Suggested options: `.ai-checks/` (mirrors `.continue/`'s top-level position; concise; vendor-neutral), `.github/ai-checks/` (lives next to the workflow that consumes it; less prominent), `prompts/checks/` (semantic; loses the "lives at the root config layer" signal).

### User

Ah! ".ai-checks" looks good!

### Assistant

`.ai-checks/` chosen. (Already mid-scaffold; renamed via `git mv .github/ai-checks .ai-checks` in the implementation session.)

### User

Can you create an issue for this?

### Assistant

Read existing issue #117 (the Continue.dev introduction) to mirror its tone and structure. Drafted issue #121 with sections: Background (motivation for the change — initially framed as a Continue.dev product critique; later rewritten to provider-account consolidation per user feedback), Proposal (layout table, behaviour, design principles), Migration, Out of scope, Closes/relates-to. Created via `gh issue create --label enhancement` → https://github.com/rafacm/ragtime/issues/121.

### User

I would actually like to use OpenAI instead of Anthropic for this? Are there any best practices to make environment keys NOT provider specific? Or does the code check whether ANTHROPIC_API_KEY or OPENAI_API_KEY is available? What about renaming it to "AI_CHECL_PROVIDER_API_KEY" to follow "AI_CHECK_MODEL"? What's the format of "AI_CHECK_MODEL" by the way?

### Assistant

Separated three things:

1. **What the code does today.** Driver uses the Anthropic SDK; `anthropic.Anthropic()` auto-reads `ANTHROPIC_API_KEY`; `AI_CHECK_MODEL` is a raw Anthropic model ID. To use OpenAI you'd swap SDK and env var.
2. **Convention for API key env vars.** Every provider's SDK auto-reads its own canonical name (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, …). Generalizing to `AI_CHECK_PROVIDER_API_KEY` is the *less* idiomatic choice — it loses auto-pickup, requires every user to re-do their repo secrets under a custom name, and breaks copy-pasted snippets from any provider's docs. The ecosystem has settled on "use each provider's canonical name verbatim".
3. **The actually-portable pattern.** Provider neutrality lives in the **model string**, not the API key. Use a router library (LiteLLM, Pydantic AI) and the model string carries the provider as a prefix:
    - `openai/gpt-4o-mini` → uses `OPENAI_API_KEY`
    - `anthropic/claude-sonnet-4-6` → uses `ANTHROPIC_API_KEY`
    - `gemini/gemini-2.0-flash` → uses `GEMINI_API_KEY`

   The router auto-reads each provider's canonical env var. Switching providers is a one-line repo-variable change plus the matching secret — no driver edits.

Recommended LiteLLM over Pydantic AI for this CI driver: it's purpose-built for the routing job, lighter dep, and Pydantic AI's value (agents, tools, type-safe outputs) is overkill for "ask LLM, get verdict, exit". Tradeoff noted: structured-output mechanic differs slightly across providers — OpenAI uses `response_format: json_schema`, Anthropic uses tool use; LiteLLM normalizes both via its `tools` parameter, so the driver switches from Anthropic-native tool use to LiteLLM's OpenAI-shaped function calling.

Proposed defaulting `AI_CHECK_MODEL` to `openai/gpt-4o-mini` (fast, cheap, sufficient for review judgment) and adding `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`GEMINI_API_KEY` to the workflow's env block so any can route via LiteLLM.

### User

yes

### Assistant

Approved. Refactored the driver and workflow (transcribed in the implementation session). Updated issue #121 body to reflect LiteLLM-based design, the provider table, and the explicit "we do not generalize the env var name" rationale.
