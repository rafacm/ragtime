# Make `StepFailed` pickles portable across processes

**Date:** 2026-05-04

## Goal

Resolve issue #110: replace the typed `StepFailed` exception hierarchy on the DBOS wire so the standalone `dbos workflow steps` CLI (and Conductor) can render step errors instead of printing `Warning: exception object could not be deserialized … No module named 'episodes'`.

## Context

Commit `9ff6719` partially addressed the issue by adding `StepFailed.__reduce__` returning `(self.__class__, (episode_id, error_message))`, which fixed the in-process Episode admin view but kept the wire format tied to a Django module the CLI can't import. The issue's top comment narrows the remaining acceptance criteria to:

- [ ] `dbos workflow steps <id>` renders the step error as a readable message (no "could not be deserialized" warning).
- [ ] Existing in-process unpickle (Episode admin) keeps working.
- [ ] 349+ tests passing.

## Options considered

| Option | Sketch | Decision |
|---|---|---|
| **1. Inline raise** | Step wrappers raise `RuntimeError(json.dumps({...}))` directly, drop the typed hierarchy. | Loses intent-revealing code at raise sites. Rejected. |
| **2. Move classes to a stdlib-only module** | New `episodes_dbos/exceptions.py` (no Django imports), import path the CLI can resolve. | Overkill — these classes are 8 lines each, and the CLI still has to know where to find them. Rejected. |
| **3. `__reduce__` returns `RuntimeError`** | Worker-side typed hierarchy intact; the on-the-wire pickle collapses to a stdlib `RuntimeError`. | Smallest blast radius, preserves typed shape inside the raise process, portable everywhere. **Picked.** |

Verified with `grep` that no caller does `except FetchDetailsFailed` etc. — the typed hierarchy exists for log readability, not control flow, so collapsing on the wire is safe.

## Plan

1. **`episodes/workflows.py`** — change `StepFailed.__reduce__` to return `(RuntimeError, (str(self),))`. Update the docstring with the cross-process-portability rationale.
2. **`episodes/admin.py`** — when `_decode_dbos_payload()` can't unpickle a value that *looks* like a pickle blob (legacy rows pickled with the typed class), return `<could not deserialize: <80-char preview>>` instead of the raw b64 string. Improves the admin UX for legacy rows whose typed wire format the current process can no longer rehydrate.
3. **Tests** — new pickle round-trip test confirming `pickle.loads(pickle.dumps(DownloadStepFailed(...)))` returns a plain `RuntimeError`; update the existing legacy-row test to expect the new fallback message.
4. **Run the full test suite** — must stay at the 349+ baseline from `9ff6719`.
5. **Documentation** — feature doc + planning + implementation session transcripts + changelog entry per CLAUDE.md.

## Out of scope

- DBOS Conductor end-to-end verification (no Conductor running locally).
- Re-raising legacy admin rows as RuntimeError post-hoc — too invasive; they fall through to the readable fallback message.
