# CI: GitHub Actions Workflow + README Badges

## Problem

The project had no automated testing. PRs and pushes to `main` could introduce regressions without anyone noticing until manual testing. The README also lacked quick-glance project metadata (build status, Python/Django versions, license).

## Changes

- **GitHub Actions workflow** (`.github/workflows/ci.yml`): Runs the full Django test suite on every push to `main` and on every pull request targeting `main`. Uses `astral-sh/setup-uv@v6` to install dependencies via `uv sync`, matching the project's package management convention. Python version is resolved automatically from `pyproject.toml`.

- **README badges**: Added a centered badge row below the hero image with four shields:
  - **CI** — live build status from the GitHub Actions workflow
  - **Python 3.13** — language version from `pyproject.toml`
  - **Django 5.2** — framework version from dependencies
  - **License: MIT** — links to the LICENSE file

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Runner | `ubuntu-latest` | Standard GitHub-hosted runner, sufficient for Django tests |
| uv action | `astral-sh/setup-uv@v6` | Official uv setup action; project uses uv exclusively |
| Triggers | `push: main`, `pull_request: main` | Catch regressions before merge and after |

## Verification

```bash
# Run tests locally
uv run python manage.py test

# Push branch and open PR → verify CI workflow triggers and passes
# Check README renders badges correctly on GitHub
```

## Files Modified

| File | Change |
|------|--------|
| `.github/workflows/ci.yml` | New — GitHub Actions workflow running `uv sync` + `manage.py test` |
| `README.md` | Added badge row (CI, Python, Django, License) below hero image; added Features & Fixes entry |
