# Session: CI — GitHub Actions Workflow + README Badges

**Session ID:** 2b9f6484-833b-46af-8583-5caa2a8b3e13
**Date:** 2026-03-10

## Summary

Added a GitHub Actions CI workflow to run the Django test suite on every PR and push to `main`, plus README badges for build status, Python version, Django version, and license.

## Conversation

### User
Let's implement a GitHub action to run the tests for every PR and for changes to the main branch. Additionally add Python, Django, License and GitHub CI build status badges to the README.md file.

### Assistant
Explored the codebase: project structure, test setup (`python manage.py test`, 40 tests in `episodes/tests.py`), `pyproject.toml` (Python 3.13, Django 5.2, uv), no existing CI, MIT license, no badges in README.

Entered plan mode and wrote the implementation plan.

### Plan

1. Create `.github/workflows/ci.yml` — triggers on push to `main` and PRs targeting `main`, uses `astral-sh/setup-uv@v6` for dependency installation, runs `uv run python manage.py test`.
2. Add a centered badge row to `README.md` below the hero image with four shields: CI status, Python 3.13, Django 5.2, License MIT.

### User
Approved the plan.

### Assistant
Created `.github/workflows/ci.yml` with the workflow configuration. Added badge block to `README.md` between the hero image and the "What is RAGtime?" heading. Ran tests locally — all 40 passed.

### User
Document this as a feature as per the AGENTS.md instructions.

### Assistant
Created `doc/features/2026-03-10-ci-github-actions.md` with Problem, Changes, Key Parameters, Verification, and Files Modified sections. Added a row to the Features & Fixes table in `README.md`.

### User
Commit changes and create a PR.

### Assistant
Created branch `ci/github-actions-workflow`, committed all changes, pushed, and opened PR #4.

### User
The session file is missing. Please generate it, amend the commit and force push.

### Assistant
Created `doc/sessions/2026-03-10-ci-github-actions.md`, updated the README Features & Fixes entry to include the session link, amended the commit, and force pushed.

### User
(Shared screenshot showing badges too close to the attribution text)

We need to add space here.

### Assistant
Added a `<br>` between the attribution `</div>` and the badges `<div>` in `README.md` for vertical spacing.

### User
Update the session transcript file to include the full session, amend the commit with all the changes and force push it.

### Assistant
Updated session transcript with the full conversation, amended the commit, and force pushed.
