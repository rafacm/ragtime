# Session: CI — GitHub Actions Workflow + README Badges

**Date:** 2026-03-10
**Session ID:** 2b9f6484-833b-46af-8583-5caa2a8b3e13

## Summary

Implemented a GitHub Actions CI workflow to run the Django test suite on every PR and push to main. Added README badges for build status, Python version, Django version, and license.

## Conversation

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/README.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Switch to the main branch

### Assistant

Switched to `main`.

### User

Let's implement a GitHub action to run the tests for every PR and for changes to the main branch. Additionally add Python, Django, License and GitHub CI build status badges to the README.md file.

### Assistant

Let me check the README header and test file directly.

I need to know the GitHub repo info for the badges.

Now I have everything I need. Let me write the plan.

Let me implement the plan.

Now let me verify tests pass locally.

All 40 tests pass. Here's what was done:

1. **Created** [.github/workflows/ci.yml](.github/workflows/ci.yml) — runs tests on PRs to `main` and pushes to `main`, using `astral-sh/setup-uv@v6` for dependency management.

2. **Added badges** to [README.md](README.md) (lines 9-15) — CI build status, Python 3.13, Django 5.2, and MIT License.

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/.github/workflows/ci.yml in the IDE. This may or may not be related to the current task.</ide_opened_file>
Document this as a feature as per the AGENTS.md instructions.

### Assistant

Let me check the existing docs and README Features & Fixes section for the right format.

Now I have the format. Let me read the README around line 111 to see the full table structure.

Now I have everything I need. Let me create the feature doc and update the README table. No plan doc is needed since this was a straightforward feature (no upfront design).

Done. Created:

- [doc/features/ci-github-actions.md](doc/features/ci-github-actions.md) — feature doc with Problem, Changes, Key Parameters, Verification, and Files Modified sections
- Added a new row to the **Features & Fixes** table in [README.md](README.md) (line 119) linking to the feature doc

Note: I skipped the plan doc (this was a straightforward feature, no upfront design needed) and the session transcript (that would be an export of this conversation).

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/doc/features/ci-github-actions.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
Commit changes and create a PR

### Assistant

PR created: https://github.com/rafacm/ragtime/pull/4

The CI workflow should trigger automatically on this PR, which will also validate that the workflow itself works correctly.

### User

<ide_opened_file>The user opened the file /Users/rafa/Develop/projects/ragtime/README.md in the IDE. This may or may not be related to the current task.</ide_opened_file>
The session file is missing. Please generate it, amend the commit and force push the amended to the PR.

### Assistant

Now I have the format. Let me create the session file, update the README entry to include the session link, amend the commit, and force push.

Done. Added [doc/sessions/2026-03-10-ci-github-actions.md](doc/sessions/2026-03-10-ci-github-actions.md), updated the README table entry with the session link, amended the commit, and force pushed to the PR.

### User

We need to add space here:

### Assistant

The badges need more vertical spacing from the attribution text. Let me fix that.

Added a `<br>` between the attribution and the badges div. Want me to amend the commit and force push?

### User

Update the session transcript file to include the full session, ammend the commit with all the changes and force push it.

### Assistant

Done. Session transcript updated with the full conversation, commit amended, and force pushed to PR #4.
