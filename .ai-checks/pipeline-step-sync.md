---
name: Pipeline Step Documentation Sync
description: When the 10-step ingestion pipeline changes, README.md, doc/README.md, and diagrams must be updated in lockstep.
paths: episodes/models.py, episodes/workflows.py, README.md, doc/README.md, doc/*.excalidraw
---

# Pipeline Step Documentation Sync

## Context

The ingestion pipeline is the spine of this project. Steps are declared in
`episodes/models.py` (`PIPELINE_STEPS`) and orchestrated by
`episodes/workflows.py`. Two human-facing surfaces document it:

- `README.md` — short summary table of the steps
- `doc/README.md` — detailed per-step descriptions

There are also Excalidraw diagrams under `doc/` that may visualise the flow.

When the pipeline changes (a step is added, removed, renamed, reordered,
re-scoped, or its terminal status semantics change) those surfaces drift
silently — there is no test that catches it. AGENTS.md explicitly calls this
out: "Keep in sync: When adding, removing, or changing a pipeline step,
update the summary table in README.md and the detailed step descriptions in
doc/README.md."

## What to Check

### 1. PIPELINE_STEPS edits must propagate to docs

If the diff touches `episodes/models.py` `PIPELINE_STEPS`, or adds/removes
a `@DBOS.step()` in `episodes/workflows.py`, both of these must also change:

- The pipeline summary table in `README.md`
- The detailed step section in `doc/README.md`

**BAD** — PR adds a new `verify` step between `embed` and `ready` in
`episodes/models.py` and `episodes/workflows.py`, but `README.md` and
`doc/README.md` still list 10 steps without it.

**GOOD** — same code change, plus README/doc updates that include `verify`,
its trigger, its terminal statuses, and any new error states.

### 2. Status name renames must propagate

`Episode.status` values (e.g. `queued`, `fetching_details`, `ready`,
`failed`) appear in admin views, templates, and prose docs. If a status is
renamed in `models.py`, search for it across `episodes/`, `chat/`,
`templates/`, and `doc/` and confirm all references update.

### 3. Diagrams must be flagged when stale

If pipeline structure changes, check whether any `.excalidraw` files in
`doc/` depict the pipeline. Diagrams cannot be auto-updated. Either:

- The PR also updates the diagram (PNG/SVG export plus the source file), OR
- The PR description explicitly notes the diagram is now stale and tracks
  follow-up.

Silently-stale diagrams are a fail.

### 4. DBOS queue / concurrency changes deserve a doc note

Changes to `RAGTIME_EPISODE_CONCURRENCY`, the `episode_pipeline` queue
config, or the deterministic workflow ID scheme (`episode-<id>-run-<n>`)
must be reflected in the "Pipeline parallelism" paragraph of
`AGENTS.md`/`CLAUDE.md` and the relevant section of `doc/README.md`.

## Key Files

- `episodes/models.py` — `PIPELINE_STEPS`, `Episode.status` choices
- `episodes/workflows.py` — DBOS workflow + steps
- `README.md` — summary table
- `doc/README.md` — detailed step descriptions
- `doc/*.excalidraw` — diagrams (manual update only)
- `AGENTS.md` / `CLAUDE.md` — architecture summary

## Exclusions

- Refactors that preserve step names, order, count, and terminal statuses
  (e.g. renaming an internal helper, extracting a sub-function inside a step).
- Pure bug fixes inside a step that don't change its contract.
- Tests-only PRs.
