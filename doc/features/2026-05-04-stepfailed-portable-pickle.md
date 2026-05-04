# Make `StepFailed` pickles portable across processes

**Date:** 2026-05-04

## Problem

DBOS persists per-step `error` payloads as base64-encoded pickle bytes. The standalone `dbos workflow steps <id>` CLI (and DBOS Conductor) runs outside the Django process and can't import `episodes.workflows`, so unpickling a typed `StepFailed` subclass there raises `ModuleNotFoundError: No module named 'episodes'` and the CLI prints:

```
Warning: exception object could not be deserialized for workflow … : No module named 'episodes'
```

Issue #110. Commit `9ff6719` partially addressed the problem by adding `StepFailed.__reduce__` returning `(self.__class__, (episode_id, error_message))` — that fixed the in-process Episode admin "View workflow steps" page but kept the wire format tied to a Django module the CLI can't reach.

## Changes

1. **`StepFailed.__reduce__` now returns `(RuntimeError, (str(self),))`** (Option 3 from the issue). The pickle written to DBOS's system DB is a plain stdlib `RuntimeError` carrying the formatted message (`"<step> failed for episode <id>: <error_message>"`). Any Python process — CLI, Conductor, ad-hoc REPL — can deserialize it without importing project code. Worker-side semantics are unchanged: `raise DownloadStepFailed(...)` inside `process_episode` still matches `except StepFailed` / `except DownloadStepFailed` because `__reduce__` only kicks in at pickle time, after the typed exception has done its job.

   *Why Option 3 over Option 1 (`raise RuntimeError(json.dumps(...))`):* keeps the typed hierarchy at raise time so step wrappers still read as intent-revealing code (`raise DownloadStepFailed(...)` not `raise RuntimeError(...)`); one method on the base class is the smallest possible blast radius. Verified with `grep` that no caller catches by typed subclass — the typed shape is for log readability, not control flow.

2. **Admin legacy-row fallback upgraded.** `_decode_dbos_payload()` in `episodes/admin.py` previously returned the raw b64 blob when `pickle.loads` failed (e.g., for legacy rows pickled before `9ff6719` whose `__reduce__` representation can no longer round-trip). Now it returns `<could not deserialize: <preview>>` with the b64 preview truncated to 80 characters, so the admin "View workflow steps" page renders an explanation instead of a wall of base64.

3. **Tests** in `episodes/tests/test_admin.py`:
   - `test_step_failed_pickle_round_trip_yields_runtime_error` — new — confirms `pickle.loads(pickle.dumps(DownloadStepFailed(...)))` returns a plain `RuntimeError` carrying the formatted message, and that the typed instance is still a `StepFailed` before pickling.
   - `test_decode_dbos_payload_unpickles_step_output` — updated comment for the new RuntimeError-on-the-wire semantics; assertions unchanged because `str(RuntimeError(msg)) == msg` matches what the old typed unpickle produced.
   - `test_decode_dbos_payload_passthrough_for_plain_values` — updated to expect the new "could not deserialize" notice for the `gASnotpickle` legacy-row case.

## Key parameters

| Knob | Value | Why |
|---|---|---|
| Wire-format exception class | `RuntimeError` | Stdlib — no project imports needed at unpickle time |
| Legacy-row preview length | 80 chars (truncated to `<77 chars>...`) | Long enough to identify the row, short enough not to overflow the admin column |

## Verification

Full unit-test suite:

```bash
uv run python manage.py test
# Ran 372 tests in ~23s — OK
```

Pickle round-trip (smoke test, no DB needed):

```bash
uv run python -c "
import pickle, django; django.setup()
from episodes.workflows import DownloadStepFailed
err = DownloadStepFailed(episode_id=7, error_message='boom')
out = pickle.loads(pickle.dumps(err))
print(type(out).__name__, '->', out)
"
# RuntimeError -> downloading failed for episode 7: boom
```

End-to-end CLI verification (requires a DBOS-recorded failure):

```bash
uv run dbos workflow steps episode-<id>-run-<n> --sys-db-url "$RAGTIME_DB_URL"
# Expect: error column renders the formatted message; no "could not be deserialized" warning.
```

The CLI repro path was not exercised in this PR — the existing pickle round-trip test covers the same property the CLI relies on (deserializing without importing `episodes.workflows`).

## Files modified

- `episodes/workflows.py` — `StepFailed.__reduce__` now returns `(RuntimeError, (str(self),))`; comment rewritten to explain cross-process portability.
- `episodes/admin.py` — `_decode_dbos_payload()` failure branch now returns `<could not deserialize: <80-char preview>>` instead of the raw blob.
- `episodes/tests/test_admin.py` — new pickle round-trip test; existing tests updated for the RuntimeError-on-the-wire semantics and the new fallback message.
