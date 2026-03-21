# README Split — Planning Session

**Session ID:** a9ed7a68-194f-46f8-a9f7-57acad62df15
**Date:** 2026-03-20

## Summary

Planned the split of the root README.md (276 lines) into a concise overview (~120 lines) and a detailed `doc/README.md`. Defined which sections to keep, replace, or move, and how to handle relative links and image assets.

## Detailed Conversation

### User

*(Automated `/pr-start` command)* Clear the current session and switch to the main branch and pull latest changes.

### Assistant

Checked the current branch (found `docs/cleanup-date-prefixes-session-ids`), switched to `main`, and ran `git pull --rebase`. The pull brought in commits `288e3fd..5109fea` with 81 files changed — mostly renaming doc files to add `YYYY-MM-DD-` date prefixes, adding Date lines to session files, and updating AGENTS.md rules.

Reported: On `main`, pulled latest changes. Ready for new work.

### User

Currently, the README is too long. Let's move the details to a README in the "doc" folder and leave a reduced README with the main points. Let's move also the ragtime.* files to the "doc" directory.

### Assistant

Began by exploring the current state of the project documentation using a sub-agent. The exploration covered:

1. **Read the full README.md** (276 lines) and identified its sections: hero image/badges, "What is RAGtime?", Features, Status, Processing Pipeline (detailed 10-step breakdown ~120 lines), How Scott Works, Getting Started, LLM Observability/Langfuse, Tech Stack, License.

2. **Listed doc/ directory** — found subdirectories: `architecture/`, `features/`, `plans/`, `sessions/`.

3. **Found ragtime.* files** — `ragtime.svg` and `ragtime.png` in the project root.

4. **Confirmed no `doc/README.md` exists yet.**

5. **Counted documentation** — 90 total markdown files across 4 directories (27 features, 20 plans, 43 sessions), plus 2 architecture files (Excalidraw + SVG).

After reading the README and doc/ structure, noted "Now I have a clear picture. Let me plan this."

Delegated to a planning sub-agent, which:

- Read the full README.md again to understand exact line ranges
- Listed the doc/ directory and architecture/ contents
- Listed ragtime.* files in root
- Searched for references to ragtime.svg/png across the codebase (found only in README.md line 3)
- Checked .gitignore for any relevant patterns (none found)

Produced a detailed implementation plan:

**Step 1: Move image assets** — `git mv ragtime.svg doc/ragtime.svg` and `git mv ragtime.png doc/ragtime.png`

**Step 2: Create `doc/README.md`** with detailed content moved from root: Processing Pipeline (full 10-step breakdown), Recovery section, How Scott Works, LLM Observability/Langfuse. All relative links adjusted (e.g., `episodes/signals.py` becomes `../episodes/signals.py`, `doc/features/...` becomes `features/...`).

**Step 3: Slim down root README.md** to ~120 lines. Keep: hero image (update path to `doc/ragtime.svg`), badges, "What is RAGtime?", Features, Status, Getting Started, Tech Stack, License. Replace the ~90-line Processing Pipeline section with a compact 10-row table. Remove "How Scott Works" and "LLM Observability" sections entirely (moved to doc/README.md). Add links to the detailed docs.

**Step 4: Update internal links** — table mapping old paths to new paths for doc/README.md context.

**Step 5: Documentation artifacts** — plan doc, feature doc, planning + implementation session transcripts, CHANGELOG entry.

**Step 6: Branch, commit, and PR.**

Line count estimate: root README drops from ~276 to ~120 lines (56% reduction).

Potential challenges identified: GitHub relative links across directories, AGENTS.md reference to "Processing Pipeline" section needing update, CLAUDE.md spec reference needing update.

Checked the CHANGELOG.md format (read first 40 lines) to ensure the planned entry follows existing conventions.

Wrote the plan and attempted to exit plan mode.

### User

In the root README, let's add a section called Documentation with an explicit mention of the Documentation available under the "doc" directory. In the "doc/README", let's add a section mentioning that features are documented with plans, feature doc, and session transcripts for both.

### Assistant

Acknowledged the feedback and updated the plan with two changes:

1. **Root README — new "Documentation" section** (replacing the simple "See also" links). Added after the pipeline table and before Getting Started:

```markdown
## Documentation

Detailed documentation lives in the [`doc/`](doc/) directory:

- [Full pipeline documentation](doc/README.md) — per-step details, entity types, recovery layer
- [How Scott works](doc/README.md#how-scott-works) — RAG architecture and query flow
- [LLM observability with Langfuse](doc/README.md#llm-observability-langfuse) — tracing setup and traced steps
- [Architecture diagrams](doc/architecture/) — processing pipeline diagram
- [Feature documentation](doc/features/) — per-feature docs with problem, changes, and verification
- [Plans](doc/plans/) — implementation plans
- [Session transcripts](doc/sessions/) — planning and implementation session logs

See [CHANGELOG.md](CHANGELOG.md) for the full history of changes.
```

The CHANGELOG link would be moved from the Status section into this new Documentation section to avoid duplication. Updated expected result to ~130 lines (from 276).

2. **doc/README.md — new "Feature Documentation" section** explaining the documentation pattern:

```markdown
## Feature Documentation

Each feature or significant change is documented with:

- **Plan** ([`plans/`](plans/)) — implementation strategy, written before coding begins
- **Feature doc** ([`features/`](features/)) — problem, changes, key parameters, verification, and files modified
- **Session transcripts** ([`sessions/`](sessions/)) — planning and implementation conversation logs with reasoning steps

All documents use a `YYYY-MM-DD-` date prefix. See the [CHANGELOG](../CHANGELOG.md) for a linked index of all features.
```

Edited the plan file twice to incorporate these additions, then exited plan mode for implementation.
