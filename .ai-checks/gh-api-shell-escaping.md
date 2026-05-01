---
name: gh api Shell Escaping & Endpoints
description: gh api invocations must use heredocs for bodies with backticks/specials, and must hit the correct endpoints for PR comments and replies.
---

# gh api Shell Escaping & Endpoints

## Context

`gh api` is the standard way scripts and agents in this repo interact
with GitHub — replying to PR review comments, fetching review threads,
posting issue comments. AGENTS.md documents two recurring failure modes:

1. **Shell escaping.** zsh interprets backticks as command substitution.
   A `gh api ... -f body="see \`foo()\`"` will try to *execute* `foo()`
   on the local shell. The fix is `$(cat <<'EOF' ... EOF)` heredocs with
   the quoted `'EOF'` delimiter (which disables expansion entirely).

2. **Wrong endpoints.** GitHub's API has several confusable endpoints:
   - PR review comments (file-anchored): `repos/O/R/pulls/N/comments`
   - PR general comments (timeline): `repos/O/R/issues/N/comments`
   - PR reviews (the review objects, not their comments):
     `repos/O/R/pulls/N/reviews`
   - Replying to a review comment: POST to
     `repos/O/R/pulls/N/comments` with `-F in_reply_to=COMMENT_ID`.
     There is **no** `/replies` sub-endpoint on individual comments —
     that returns 404.

These are easy to get subtly wrong (the call succeeds against the wrong
resource, or the comment lands on the wrong thread). A linter cannot
catch them. This check is for that.

## What to Check

### 1. Bodies with backticks/specials must use heredocs

If a `gh api ... -f body="..."` invocation contains backticks, dollar
signs, double quotes, or `!`, it must be rewritten as a heredoc:

**BAD**

```bash
gh api repos/O/R/pulls/1/comments \
  -f body="See `process_episode()` for the fix"
```

**GOOD**

```bash
gh api repos/O/R/pulls/1/comments \
  -f body="$(cat <<'EOF'
See `process_episode()` for the fix
EOF
)" \
  -F in_reply_to=12345
```

Note the **quoted** `'EOF'` — without the quotes, `$VAR` and backticks
are still expanded inside the heredoc.

### 2. Reply endpoints

A "reply to a review comment" must POST to the pulls comments endpoint
with `-F in_reply_to=...`. Reject any URL containing
`/comments/<id>/replies` — that path does not exist.

**BAD**

```bash
gh api repos/O/R/pulls/1/comments/12345/replies -f body="thanks"
# 404
```

**GOOD**

```bash
gh api repos/O/R/pulls/1/comments \
  -f body="thanks" \
  -F in_reply_to=12345
```

### 3. Review-comment vs issue-comment confusion

Reading or posting to the wrong endpoint silently lands on the wrong
thread. Spot-check intent vs URL:

- Fetching the file-anchored review comments on a PR:
  `repos/O/R/pulls/N/comments` ✓
- Fetching the timeline conversation on a PR:
  `repos/O/R/issues/N/comments` ✓ (because PRs are issues for the
  comment timeline)
- Listing reviews (the review summaries themselves):
  `repos/O/R/pulls/N/reviews` ✓

If the script claims to "fetch all PR comments" but only hits
`/pulls/N/comments`, it's missing the issue timeline — flag it.

### 4. POST/PATCH/DELETE warrant extra care

Any non-GET `gh api` call (anything with `-f`, `-F`, `--method POST/PATCH/DELETE`,
or `-X`) is doing a side-effecting action against GitHub. Confirm:

- The body is escaped per rule (1).
- The endpoint is right per rules (2)–(3).
- For destructive actions (closing PRs, deleting branches, dismissing
  reviews) there is a clear reason in the surrounding context.

### 5. Don't paper over with `--no-verify`-style flags

If a `gh` call is failing and the proposed fix adds `-H` headers to
bypass validation, or skips `--method` checks, prefer fixing the URL
or body instead.

## Key Files

- Anywhere under `scripts/`, `core/management/commands/`,
  `.github/workflows/`, or shell snippets in `doc/` that invoke `gh`.
- Code blocks in markdown docs that show users `gh api` recipes — those
  get copied verbatim and need to be correct.

## Exclusions

- `gh pr view`, `gh pr create`, `gh issue view` and other high-level
  `gh` subcommands: those don't have the body-escaping problem because
  they read from `--body-file` or stdin, and they hit the right
  endpoints by construction.
- Read-only `gh api` GETs with no `-f`/`-F` body.
