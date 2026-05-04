---
name: Feature PR Documentation Bundle
description: Non-trivial feature PRs must ship the plan, feature doc, both session transcripts, and a changelog entry — with correct metadata format.
---

# Feature PR Documentation Bundle

## Context

This repo treats documentation as part of the PR, not an afterthought.
AGENTS.md mandates that the commit for a feature contains:

- The plan, in `doc/plans/YYYY-MM-DD-my-feature.md`
- The feature doc, in `doc/features/YYYY-MM-DD-my-feature.md`
- The planning session transcript, ending in `-planning-session.md`
- The implementation session transcript, ending in `-implementation-session.md`
- A `CHANGELOG.md` entry (Keep a Changelog format, dated section headers)

There is also a strict metadata format: every doc starts with a
`# Title` on the first line; metadata lines (`**Date:**`,
`**Session ID:**`) come immediately after, separated by blank lines.
Session transcripts must use a real Claude Code session UUID, not
"current session" or worktree names.

A linter cannot judge whether a PR is "a feature" — that requires reading
the diff. This check exists for that judgment call.

## What to Check

### 1. Classify the PR

Read the PR title, description, and diff. Decide if this is a feature /
significant change, a bug fix, a refactor, or docs/chore. Only features
and significant changes need the full bundle. State your classification
explicitly so the author can push back.

Heuristics for "feature / significant change":
- Adds or removes a pipeline step, provider, model, or admin view
- Introduces a new `RAGTIME_*` env var that gates user-visible behaviour
- Adds a new external dependency or service integration
- Changes Scott's prompt, retrieval, or tool-calling contract
- New management command intended for routine use

Heuristics for "no bundle needed":
- Pure bug fix with a test
- Internal refactor with no behaviour change
- Dependency bumps
- Doc-only PRs

### 2. If feature: all four artefacts present

The PR must contain new files at:

- `doc/plans/YYYY-MM-DD-<slug>.md`
- `doc/features/YYYY-MM-DD-<slug>.md`
- `doc/sessions/YYYY-MM-DD-<slug>-planning-session.md`
- `doc/sessions/YYYY-MM-DD-<slug>-implementation-session.md`

…with **the same date prefix and slug** across all four. Mismatched
slugs make these impossible to find later.

### 3. Metadata format is correct

For every new doc file, verify:

- Line 1 is `# <Title>` — not frontmatter, not a blank line.
- Metadata lines (`**Date:** YYYY-MM-DD`, and for transcripts
  `**Session ID:** <uuid>`) come immediately after the title, before any
  `## Section`.
- A blank line separates each metadata line so they render as separate
  paragraphs.
- Session ID is a real UUID, not `current session`, `unavailable` (unless
  truly unrecoverable), or a worktree name.

**BAD**

```markdown
**Date:** 2026-04-30
# My Feature
**Session ID:** current session
## Summary
```

**GOOD**

```markdown
# My Feature

**Date:** 2026-04-30

**Session ID:** a150a5a3-218f-44b4-a02b-cf90912619d7

## Summary
```

### 4. Changelog entry

`CHANGELOG.md` must have a new bullet under a dated section
(`## YYYY-MM-DD`), grouped by category (`### Added`, `### Changed`, etc.),
with links to the plan, feature doc, and both session transcripts.
Newest dates go first; existing same-day sections get appended to, not
duplicated.

### 5. Implementation transcript covers PR review

AGENTS.md requires the implementation transcript to include all
interactions up to and including PR review feedback and follow-up
changes. If the PR has had review rounds, confirm those rounds appear
in the transcript — not just the initial implementation.

### 6. User / parent-agent messages are verbatim

Spot-check the transcript: `### User` sections should read like real,
unedited messages (typos, casual phrasing, context). If they read like
clean prose summaries, they have been paraphrased and need fixing.

AGENTS.md also recognizes **agent-orchestrated sessions** (parallel
implementation agents launched from a parent Claude Code session, e.g.
under Conductor). In that case the transcript may use
`### Parent agent (orchestrator)` headings *instead of* `### User`,
provided the parent-agent's launching prompt is reproduced verbatim
(same verbatim rule). The transcript must explicitly declare the
session as agent-orchestrated at the top of `## Detailed conversation`,
not silently substitute the heading. Either form (real verbatim user
messages, or honest agent-orchestrated declaration with verbatim parent
prompt) satisfies this check; summarized/paraphrased content does not.

## Key Files

- `doc/plans/`, `doc/features/`, `doc/sessions/`
- `CHANGELOG.md`
- The diff itself (to classify the PR)

## Exclusions

- Bug fixes, refactors, dependency bumps, doc-only PRs.
- Hot-fixes explicitly tagged as urgent in the PR description (note as
  follow-up debt, don't block).
