# Make `StepFailed` pickles portable across processes — Planning Session

**Date:** 2026-05-04

**Session ID:** unavailable

## Summary

Reviewed issue #110 and commit `9ff6719` (which partially addressed it). Confirmed the remaining gap is cross-process portability: the standalone `dbos workflow steps` CLI runs outside Django, can't import `episodes.workflows`, and prints `Warning: exception object could not be deserialized … No module named 'episodes'`. Picked Option 3 from the issue (`__reduce__` returning a stdlib `RuntimeError`) because it preserves the typed exception hierarchy at raise time while making the on-the-wire pickle portable to any Python process. Verified no caller catches `StepFailed` subclasses by type, so collapsing them on the wire is safe.

## Detailed conversation

### User

(Task spec from the agent harness:) Issue #110 — replace typed StepFailed exceptions with serializable failure objects so the dbos CLI can render them. Step 1: confirm staleness — the issue is "partially addressed in 9ff6719", so check what's left. Step 2: pick the smallest viable option (Option 3 = `__reduce__` returning RuntimeError, recommended). Step 3: verify the full test suite still passes. Step 4: documentation. Step 5: PR.

### Assistant

Read `episodes/workflows.py` and confirmed the current `__reduce__` returns `(self.__class__, (self.episode_id, self.error_message))` — works in-process but the typed class is a Django-app-namespaced symbol the CLI can't resolve. Read commit `9ff6719` and the issue's top comment to confirm the partial-progress markers; the comment narrows the remaining acceptance criteria to "CLI renders the message", "in-process unpickle still works", "349+ tests passing".

Surveyed catch-by-type usage: `grep "except (StepFailed|FetchDetailsFailed|DownloadStepFailed|TranscribeStepFailed|SummarizeStepFailed|ChunkStepFailed|ExtractStepFailed|ResolveStepFailed|EmbedStepFailed)"` returned zero matches. The typed hierarchy is purely for log/debug readability, not control flow — so collapsing it at pickle time is safe.

Weighed three options:

1. **Inline `raise RuntimeError(json.dumps(...))`.** Loses intent-revealing raise sites. Rejected.
2. **Move classes to a stdlib-only module the CLI imports.** Too much scaffolding for 8-line classes; the CLI still has to know where to look. Rejected.
3. **`__reduce__` returns `(RuntimeError, (str(self),))`.** Worker-side typed hierarchy intact; on-the-wire pickle is stdlib-only, portable everywhere. Picked.

Also flagged that legacy rows pickled before `9ff6719` (typed-class wire format that the current process can no longer rehydrate) currently render as raw b64 in the admin via the silent fallback in `_decode_dbos_payload`. Decided to upgrade the fallback to `<could not deserialize: <80-char preview>>` so the admin shows context instead of a wall of base64.

Out of scope: DBOS Conductor end-to-end verification (no Conductor locally) and rewriting legacy admin rows post-hoc (too invasive — the readable fallback covers the UX).
