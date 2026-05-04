# Make `StepFailed` pickles portable across processes — Planning Session

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Reviewed issue #110 and commit `9ff6719` (which partially addressed it). Confirmed the remaining gap is cross-process portability: the standalone `dbos workflow steps` CLI runs outside Django, can't import `episodes.workflows`, and prints `Warning: exception object could not be deserialized … No module named 'episodes'`. Picked Option 3 from the issue (`__reduce__` returning a stdlib `RuntimeError`) because it preserves the typed exception hierarchy at raise time while making the on-the-wire pickle portable to any Python process. Verified no caller catches `StepFailed` subclasses by type, so collapsing them on the wire is safe.

## Detailed conversation

### User

> Let's review the currently open issues and prioritize them for implementation.

### Assistant

Pulled the open issue list (`gh issue list --state open`), read each issue body and recent comments, and grouped them into tiers by impact and blast radius. Tier 1 covered the issues with the highest user-facing impact and the smallest implementation surface — `#110` (StepFailed CLI rendering, partially addressed in `9ff6719`), `#113` (a download-step regression), `#124` (an admin/UX fix), and `#111` (a larger refactor that needs scoping). Tier 2 and Tier 3 covered nice-to-have polish and longer-running architectural threads. Reported the tiering with one-line justifications per issue and a recommendation to start with Tier 1.

### User

> Can any of the issues in Tier 1 be worked in parallel sessions?

### Assistant

Walked through each Tier 1 issue and identified the file footprints and likely conflict zones:

- `#110` touches `episodes/workflows.py` (StepFailed classes) and `episodes/admin.py` (`_decode_dbos_payload` fallback). No overlap with the other tickets.
- `#113` touches `episodes/downloader.py` and the download-step orchestration — independent.
- `#124` touches admin templates and the changelist — also independent.
- `#111` is the larger refactor; needs a planning conversation before any worktree work, and may collide with `#124` on the admin layer.

Concluded that `#110`, `#113`, and `#124` could safely run in parallel worktrees with isolated branches. `#111` should stay in the main session as a design discussion. Recommended launching three parallel agent sessions for the first three and continuing the `#111` discussion synchronously.

### User

> Start parallel sessions for #124, #113 and #110 and let's discuss how to address #111. Be advised that the issues may be stale in the sense that a PR may have already solved part or all of the issues described in the issue.

### Assistant

Launched three parallel Agent-tool sessions with `isolation: worktree`, one per issue. The `#110` session received a launching prompt instructing it to:

1. Read `CLAUDE.md`, `AGENTS.md`, and the issue + its top comment.
2. Inspect commit `9ff6719` to see what was already addressed.
3. Branch off `main` as `rafacm/stepfailed-portable`.
4. Verify staleness — check whether `__reduce__` is already in place and whether further work is needed.
5. If still incomplete, pick Option 3 (`__reduce__` returns `(RuntimeError, (str(self),))`) for minimal blast radius and typed-shape preservation; verify nothing catches `StepFailed` subclasses by type before collapsing them on the wire.
6. Add a graceful legacy-row fallback in the admin's pickle-decode path so pre-`9ff6719` blobs render an explanation instead of crashing.
7. Run the full test suite, write feature/session/changelog docs per `AGENTS.md`, and open a PR.

Within the planning thread itself, the assistant then read `episodes/workflows.py` and confirmed the current `__reduce__` returns `(self.__class__, (self.episode_id, self.error_message))` — works in-process but the typed class is a Django-app-namespaced symbol the CLI can't resolve. Read commit `9ff6719` and the issue's top comment to confirm the partial-progress markers; the comment narrows the remaining acceptance criteria to "CLI renders the message", "in-process unpickle still works", "349+ tests passing".

Surveyed catch-by-type usage: `grep "except (StepFailed|FetchDetailsFailed|DownloadStepFailed|TranscribeStepFailed|SummarizeStepFailed|ChunkStepFailed|ExtractStepFailed|ResolveStepFailed|EmbedStepFailed)"` returned zero matches. The typed hierarchy is purely for log/debug readability, not control flow — so collapsing it at pickle time is safe.

Weighed three options:

1. **Inline `raise RuntimeError(json.dumps(...))`.** Loses intent-revealing raise sites. Rejected.
2. **Move classes to a stdlib-only module the CLI imports.** Too much scaffolding for 8-line classes; the CLI still has to know where to look. Rejected.
3. **`__reduce__` returns `(RuntimeError, (str(self),))`.** Worker-side typed hierarchy intact; on-the-wire pickle is stdlib-only, portable everywhere. Picked.

Also flagged that legacy rows pickled before `9ff6719` (typed-class wire format that the current process can no longer rehydrate) currently render as raw b64 in the admin via the silent fallback in `_decode_dbos_payload`. Decided to upgrade the fallback to `<could not deserialize: <80-char preview>>` so the admin shows context instead of a wall of base64.

Out of scope: DBOS Conductor end-to-end verification (no Conductor locally) and rewriting legacy admin rows post-hoc (too invasive — the readable fallback covers the UX).
