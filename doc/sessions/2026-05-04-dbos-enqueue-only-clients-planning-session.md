# DBOS Enqueue-Only Clients — Planning Session

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Triage of issue #113. Confirmed the bug from prior context (PR #109 / issue #108 work surfaced both the contention warning and the shutdown error). Three options laid out in the issue body. Selected Option 1 ("don't launch from clients") as the architectural fix, with a fall-back to Option 2 (brief drain loop) if `Queue.enqueue` turned out to require `launch()`. Investigation showed pure Option 1 doesn't work — `DBOS._sys_db` raises if not launched — so the implementation refines Option 1 by using `DBOS.listen_queues([])` to launch the client with zero application queues attached. Same posture, working knob.

The conversation captured below is a triage exercise across multiple open issues; this transcript records the slice relevant to #113 — specifically, the user messages that prioritized the work, asked about parallelization, and authorized the parallel session that produced this PR.

## Detailed conversation

### User

> Let's review the currently open issues and prioritize them for implementation.

### Assistant

Pulled the open issue list and bucketed each by impact, blast radius, and dependency. Flagged #113 (DBOS client/worker split — surfaces noisy `Contention detected in queue thread` warnings plus a `cannot schedule new futures after shutdown` race when running `manage.py enrich_entities` or `manage.py submit_episode` while uvicorn consumes the queue) as a small-scoped, well-bounded fix with a clear architectural recommendation in the issue body. Grouped it into Tier 1 alongside other independently-grabbable items.

### User

> Can any of the issues in Tier 1 be worked in parallel sessions?

### Assistant

Walked through the Tier 1 set and assessed dependency overlap. #113 touches only `episodes/apps.py:_init_dbos` and the two affected management commands; it does not overlap with #124 or #110 in either files or DBOS constructs. Concluded the three are safely parallelizable. Noted the standard caveat: the issues may be partially or wholly addressed by recent merges (e.g., the DBOS queue restructure in PR #109), so each parallel session should staleness-check first.

### User

> Start parallel sessions for #124, #113 and #110 and let's discuss how to address #111. Be advised that the issues may be stale in the sense that a PR may have already solved part or all of the issues described in the issue.

### Assistant

Acknowledged. Drafted a per-issue implementation brief for #113 covering: required reading (`CLAUDE.md`, `AGENTS.md`, `gh issue view 113`, issue #108 / PR #109 context), branching protocol off `main` with branch name `rafacm/dbos-enqueue-only`, an explicit Step 1 staleness check on `episodes/apps.py:_init_dbos` and the two management commands, the recommended Option 1 implementation path (with a fall-back to Option 2 if `Queue.enqueue` truly requires `launch()`), verification (`uv run python manage.py test`, `manage.py check`, manual no-warning smoke test), documentation per CLAUDE.md's implementation phase, and PR creation against `main` with `Closes #113`. Launched the parallel implementation agent for #113 with that brief; sibling sessions for #124 and #110 launched alongside. Discussion of #111 continued separately in the parent session.

For the design decision the parallel agent ultimately landed on — the `DBOS.listen_queues([])` refinement of Option 1 — see the implementation transcript. The summary above captures the option analysis and the DBOS-source investigation that informed it.
