# Fix pipeline bugs — Implementation session

**Date:** 2026-03-23

**Session ID:** 87080f37-fafd-4e80-9ce2-cb27c8dc0bb8

## Summary

Implemented fixes for two pipeline bugs: scraper save overwriting recovery status, and resolver crashing on malformed LLM wikidata_id values.

### User

Approved plan to split the shared `episode.save()` into success/failure branches.

### Assistant

Edited `episodes/scraper.py`: extracted the `update_fields` list, then split the single `episode.save()` into two calls — one in the success branch (after `complete_step`) and one in the failure branch (before `fail_step`). Added a comment explaining why the order matters.

Added regression test `test_incomplete_metadata_does_not_overwrite_recovery_status` in `episodes/tests/test_scraper.py`. The test connects a fake recovery handler to the `step_failed` signal that sets `status=TRANSCRIBING`, runs the scraper with incomplete LLM output, then asserts the episode status is `TRANSCRIBING` (not `FAILED`).

Ran `uv run python manage.py test episodes` — all 14 scraper tests pass. Ran full test suite — all 250 tests pass.

Created branch `fix/scraper-recovery-status-overwrite`, prepared documentation, committed, and opened PR #85.

### User

In the "resolving" step I am seeing "value too long for type character varying(20)"

### Assistant

Investigated the `Entity.wikidata_id` field (`max_length=20`) and the resolver code. Found that the LLM-returned `wikidata_id` is saved directly to the DB without sanitization. The `Entity.wikidata_id` field is `varchar(20)` which is fine for valid Q-IDs, but the LLM can return noisy values that exceed the limit.

Added `_sanitize_qid()` to `episodes/resolver.py` — a regex (`Q\d+`) that extracts the bare Q-ID from any format. Applied it at both points where `wikidata_id` is read from LLM output (line 256 for the no-existing-entities path and line 331 for the existing-entities path).

### User

Yes, I checked the logs and I can see the LLM returning "Q172}]} Explanation: ". Does the _sanitize_qid method handle this case?

### Assistant

Confirmed `_sanitize_qid` handles this correctly — the regex `Q\d+` matches `Q172` from the noisy string. Verified with a quick Python test covering bare IDs, full URLs, trailing garbage, and empty strings.

### User

Update the PR and the documentation as per AGENTS.md

### Assistant

Updated all documentation files (plan, feature doc, both session transcripts, changelog) to cover both fixes. Committed the resolver fix and updated PR #85.
