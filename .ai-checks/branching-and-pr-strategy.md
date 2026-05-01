---
name: Branching & PR Strategy
description: No direct commits to main. Feature branches off latest main. Rebase merge only — squash and merge-commit are forbidden on this repo.
---

# Branching & PR Strategy

## Context

AGENTS.md is unambiguous on the workflow:

> Before beginning any new work, always: verify we are on the `main`
> branch and switch to it if not, pull latest changes (`git pull --rebase`).
> All new features and fixes must be implemented in a dedicated branch
> off `main`. Never commit directly to `main`. When creating PRs, use
> the rebase strategy. Squash and merge-commit strategies are not
> allowed on this repository.

Why it matters:

- The session-transcript / plan / feature-doc bundle is per-PR; commits
  on `main` would smear that across history.
- Rebase merges keep the linear history that `git log` and `git blame`
  rely on. A squash would collapse the carefully-staged commits within
  a feature branch (often with their own session boundaries) into a
  single tombstone.

A linter cannot enforce branch discipline before push. This check is
the human-judgement gate.

## What to Check

### 1. PR is not from main

The PR must be from a feature branch (e.g. `feature/scott-citations`,
`fix/resolver-deadlock`) into `main`, never `main` → `main` and never
some long-lived `develop` branch into `main`. If the PR is from `main`
or the branch name is generic (`patch-1`, `update`, `tmp`), flag it
and request a rename.

### 2. Branch is up-to-date with main (rebased)

Confirm the branch has been rebased onto current `main`, not merged
from `main`. Tells:

- The PR commits show as a clean linear sequence on top of `main`'s
  tip, not interleaved with merge commits.
- No commits with messages like `Merge branch 'main' into feature/...`.

If `main` has moved, the author should `git rebase main` and
force-push, not `git merge main`.

### 3. No merge commits inside the branch

Inside the feature branch, every commit should be a real change. Merge
commits from `main`, or from an intermediate branch, will block a
clean rebase merge and pollute the linear history. Flag any merge
commit in the PR's commit list.

### 4. Commit messages aren't squash-shaped

Because the merge strategy is rebase, every individual commit lands on
`main` as-is. Commit messages should be self-contained and useful in
isolation, not titled "wip", "fix", "address review", or "more
changes" expecting a squash to clean them up. If the PR has those
shapes, ask the author to `git rebase -i` and tidy up before merge.

(Note: AGENTS.md forbids using `-i` flag on `git rebase` from inside
agent sessions — this is a request for the human author, not something
the agent runs.)

### 5. Documentation commit lives in the PR

AGENTS.md: "The commit for a given feature MUST contain the plan, the
feature documentation, and both session transcripts (planning and
implementation)." With rebase merge, those commits land on `main`
verbatim. Confirm the docs are in the same PR — not a separate
follow-up PR — so the rebased history pairs each feature commit with
its docs.

### 6. PR description anticipates rebase merge

Reviewers should see, somewhere in the PR description or template,
that the merge button used will be **Rebase and merge**. If the repo
settings somehow show squash/merge-commit options as the default, flag
that as a settings bug to fix at the repo level — but the PR itself
should not be merged any other way.

### 7. Don't commit to main from agent sessions

If a session transcript shows the agent committed directly to `main`
(no `git checkout -b`, just `git commit` while on `main`), that is a
process failure and must be called out. The fix is to move the commits
to a feature branch and reset `main` to its upstream tip — but this is
a destructive operation and the human must do it.

## Key Files

- `.git/` state (branch, log, config) — inspect via `git` rather than
  reading files
- `AGENTS.md` — the source of truth for these rules
- `.github/` — repo settings, PR templates, CODEOWNERS

## Exclusions

- Trivial typo fixes that GitHub's web UI made via "Edit on GitHub" —
  these still go through a PR but the branch may be auto-named. Just
  confirm it was rebase-merged.
- Initial repo bootstrap commits (before the rules existed). Use
  judgement on the date of the violation.
