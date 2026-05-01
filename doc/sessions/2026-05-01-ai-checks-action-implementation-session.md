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

### User

Thanks! Tested the first run and since I did not define the OPENAI_API_KEY I see a Python exception. Can we improve the implementation to give a better user/dev-facing error?

### Assistant

Identified two complementary fixes — workflow-level preflight (one clear error, fast fail, no nine-runner fan-out) and driver-level defensive handling (for local runs and unexpected auth failures).

- New `.github/scripts/preflight_key.py`: maps `AI_CHECK_MODEL` prefix → required secret via a small table (`openai`/`anthropic`/`gemini`+`google`). When the secret is missing, writes a Markdown explanation to `$GITHUB_STEP_SUMMARY` (with "To fix" and "To switch providers" sections), emits a `::error::` annotation, exits 1. Unknown prefix → `::warning::` and exit 0 (LiteLLM validates at call time).
- Wired it into `ai-checks.yml` as the first step of the `list` job, so the matrix never fans out when the secret is missing.
- Driver: added `PROVIDER_TO_ENV_VAR` map + `required_env_var()` helper, defined a `ConfigError` exception, raised it from `evaluate()` when the required env var is unset, and caught `litellm.AuthenticationError` and re-raised as `ConfigError` with a "key likely invalid/expired/revoked" hint. Updated `main()` to catch `ConfigError`, emit a `[CONFIG ERROR]` line + `::error::` annotation + clean step-summary, and exit code `2` to distinguish from rule `fail` verdicts (exit 1).
- Smoke-tested all paths: preflight without key (exits 1 with `::error::`), preflight with key (exits 0), preflight with unknown provider (exits 0 with `::warning::`), driver without key (exits 2 with `[CONFIG ERROR]`).

Updated `doc/features/...` (Changes section + Files-modified list) and committed as a follow-up to the PR.

### User

Can you add a summary as end-user documentation to what is needed from a permissions perspective for the API KEY to the issue and the PR so we do not forget?

### Assistant

Drafted a 7-step least-privilege checklist for the OpenAI API key: dedicated Project, monthly budget cap, model allow-list restricted to `gpt-4o-mini`, Restricted secret key with only `Model capabilities → Chat completions (/v1/chat/completions) → Request` enabled (everything else `None`), descriptive key name, add as repository secret, rotate every ~90 days. Inserted as a new top-level section in issue #121 (between Proposal and Migration) and expanded the PR's "Required follow-up" section with the same checklist.

### User

Shall I add it [the secret] as a repository secret or as an environment secret?

### Assistant

Repository secret. Environment secrets buy approval gates and branch allow-lists you don't need here — the secret pays for LLM tokens (blast radius bounded by the OpenAI Project budget cap), the workflow trigger already restricts to PRs against `main`, and GitHub already withholds repository secrets from fork PRs by default. Migration to environment secret later is trivial if a deploy-style workflow ever needs the key.

### User

Yes [mirror the permissions section into the feature doc].

### Assistant

Added a new `## Setup` section to `doc/features/2026-05-01-ai-checks-action.md` with the 7-step checklist and a note about repository-vs-environment-secret choice. Doc home is the durable location — issue and PR can rot, the date-stamped feature doc is what `CHANGELOG.md` and future readers will navigate to. Committed as a follow-up to the PR.

### User

[Mirror the repository-secret choice into the runtime error messages too.]

### Assistant

Updated `.github/scripts/preflight_key.py` step-summary Markdown and the `::error::` annotation to specify "repository secret (not an environment secret)" and to point readers at the date-stamped feature doc for the full setup checklist. Mirrored the same wording into `run_ai_check.py`'s `ConfigError` message. Smoke-tested locally — the missing-key path now reads "Missing OPENAI_API_KEY repository secret … Add it under Settings → Secrets and variables → Actions → New repository secret (not an environment secret)".

### User

Last thing. Let's rephrase the text in the issue, PR description and CHANGELOG about the reasons for moving away from Continue.dev. It was my responsibility to introduce it too early and I do not want to have to add credits to yet another service if I already do that with OpenAI and Anthropic. I actually added credits to my Continue.dev account but somehow the error about the agent not having credits persisted. I may go back to Continue.dev once I've implemented Evals for the whole RAGtime app.

### Assistant

Rewrote the framing across all forward-looking artefacts: CHANGELOG `### Removed` entry, issue #121 Background section, PR #122 Summary section, plan doc Problem section, feature doc Problem section, and the Summary/notes lines in both session transcripts that previously characterised Continue.dev as "unreliable / opaque / a SaaS dependency we want to retire". New framing centres on: (a) adopting Continue.dev before RAGtime had its own eval infrastructure was premature sequencing; (b) the immediate motivation for moving off is provider-account consolidation (already paying OpenAI and Anthropic; a third billable account is overhead) rather than a product critique; (c) credits were added to the Continue.dev account during initial debugging but the GitHub checks still failed to run — the decision to move off a separately-billed runner stands regardless of root cause; (d) revisiting Continue.dev once #115's eval framework lands is explicitly on the table. The session-transcript user messages stay verbatim — the framing shift is documented in the assistant-summary lines and the forward-looking docs.

### User

Amend the commits accordingly and force push.

### Assistant

Authorised destructive operation. Amended HEAD to roll the framing rewrite into commit `4c4880c` (the existing repository-secret docs polish — both are documentation polish in the same family) with an updated commit message that mentions both changes.

### User

You can also add that I added credits to my Continue.dev account but still could not get the GitHub checks to work.

### Assistant

Strengthened the "added credits but still didn't work" point — it had been buried in a parenthetical aside. Updated the plan doc, feature doc, CHANGELOG `### Removed` entry, and this session transcript to state it explicitly: "credits were added to the Continue.dev account during initial debugging, but the GitHub checks still failed to run — moving off a separately-billed runner is the right call regardless of root cause." Re-amended the same HEAD commit to include the strengthening, then force-pushed with `--force-with-lease` and mirrored the same wording into issue #121 and PR #122 bodies.
