**Date:** 2026-03-20

# Feature: Split README into root overview + doc/README.md

## Problem

The root README.md was 276 lines — too long for a project landing page. Detailed pipeline step descriptions, Langfuse setup instructions, recovery layer documentation, and "How Scott Works" made it difficult to scan quickly. Image assets (`ragtime.svg`, `ragtime.png`) also lived in the project root instead of `doc/`.

## Changes

- **Moved image assets** to `doc/` and updated the hero image `src` in root README.
- **Replaced** the ~90-line Processing Pipeline section in root README with a compact 10-row summary table linking to detailed docs.
- **Removed** "How Scott Works" and "LLM Observability (Langfuse)" sections from root README (moved to doc/README.md).
- **Added** a "Documentation" section in root README with links to doc/ subdirectories.
- **Kept** the CHANGELOG.md link at the end of the Status section (not duplicated under Documentation).
- **Created** `doc/README.md` containing all detailed content: full pipeline step descriptions, Recovery section, How Scott Works, LLM Observability, and a new Feature Documentation section.
- **Fixed** all relative links in `doc/README.md` to account for its `doc/` location (e.g., `episodes/signals.py` → `../episodes/signals.py`).
- **Updated** CLAUDE.md to reference both `README.md` and `doc/README.md`, and updated the pipeline sync instruction.

## Key parameters

| Parameter | Value | Rationale |
|---|---|---|
| Target root README size | ~120 lines | Short enough to scan on a single GitHub page |

## Verification

1. `uv run python manage.py test` — ensure no tests break
2. Review root README on GitHub — confirm it's ~120 lines and scannable
3. Review `doc/README.md` on GitHub — confirm all detailed content present with working links
4. Check that all anchor links (e.g., `doc/README.md#recovery`, `doc/README.md#how-scott-works`) resolve correctly

## Files modified

| File | Change |
|---|---|
| `ragtime.svg` → `doc/ragtime.svg` | git mv |
| `ragtime.png` → `doc/ragtime.png` | git mv |
| `README.md` | Slimmed down: pipeline summary table, removed How Scott Works + Langfuse, added Documentation section |
| `doc/README.md` | **New** — detailed pipeline, Scott, Langfuse, recovery, feature documentation |
| `CLAUDE.md` | Updated spec reference and pipeline sync instruction |
| `CHANGELOG.md` | Added 2026-03-20 entry |
| `doc/plans/2026-03-20-readme-split.md` | **New** — plan document |
| `doc/features/2026-03-20-readme-split.md` | **New** — this file |
| `doc/sessions/2026-03-20-readme-split-planning-session.md` | **New** — planning session transcript |
| `doc/sessions/2026-03-20-readme-split-implementation-session.md` | **New** — implementation session transcript |
