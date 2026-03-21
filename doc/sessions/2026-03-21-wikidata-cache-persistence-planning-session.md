# Wikidata Cache Persistence — Planning Session

**Date:** 2026-03-21

**Session ID:** 438617e8-2ff9-4481-abaf-6bed9198c9f8

## Summary

Planned switching the Wikidata API cache from in-memory (`locmem`) to file-based persistence, adding a token bucket rate limiter, and documenting cache management.

### User

Wikidata Cache Persistence

Problem: The Wikidata cache defaults to locmem (in-memory), so all cached responses are lost on every Django restart. During entity resolution, each unique entity name triggers up to 11 Wikidata API requests (1 wbsearchentities + up to 10 get_entity calls for P31 verification). For an episode with ~60 entities, that's potentially ~650 requests. Without persistence, reprocessing an episode or restarting the server repeats all those requests, risking IP rate-limiting/blocking.

Current state:
- Cache backend configured in ragtime/settings.py:190-201 via RAGTIME_WIKIDATA_CACHE_BACKEND env var
- Two options exist: locmem (default) and db (requires manage.py createcachetable)
- TTL is 7 days (RAGTIME_WIKIDATA_CACHE_TTL=604800)
- Cache key is SHA256 of sorted query params (episodes/wikidata.py:28-48)
- find_candidates() in episodes/wikidata.py:128-158 is the hot path — called per unique entity name per entity type during resolution

Proposed changes:
1. Switch default cache backend from locmem to filebased (django.core.cache.backends.filebased.FileBasedCache) — no extra setup needed, survives restarts
2. Add filebased as a third option in settings.py with a configurable LOCATION (e.g., .cache/wikidata/)
3. Add .cache/ to .gitignore
4. Update .env.sample and the configure wizard with the new option
5. Consider adding request rate-limiting/backoff in _make_request() to be a good Wikidata API citizen

Files involved:
- ragtime/settings.py — add filebased backend option, change default
- .env.sample — document new default
- core/management/commands/_configure_helpers.py — update wizard
- .gitignore — add .cache/
- episodes/wikidata.py — optionally add rate-limiting

Quick workaround (now): Set RAGTIME_WIKIDATA_CACHE_BACKEND=db in .env and run uv run python manage.py createcachetable.

### Assistant

Explored the codebase to verify the current state: settings.py cache config (lines 189-201), wikidata.py _make_request() caching logic, .env.sample entries, configure wizard defaults, and .gitignore (`.cache` already listed). Confirmed no existing rate-limiting or backoff logic.

Wrote the plan: replace `locmem` with `filebased` as default, keep `db` as alternative, add a simple `time.sleep(0.1)` before HTTP requests.

### User

Regarding rate limiting, what about a Token bucket / rate limiter approach, we would need to know which responses are coming from the cache and which ones are not so the rate limiting only apply to them.

### Assistant

Updated the plan to use a token bucket rate limiter instead of a simple sleep. The `_make_request()` function already returns early on cache hits (line 34-35), so the rate limiter only fires on cache misses. Designed a `_TokenBucket` class with rate=5 req/s and capacity=10 (burst), thread-safe via `threading.Lock`.

### User

The default cache approach should be this new one we are implementing now and not the memory-based one. What are the cons or tradeoffs of removing that one?

### Assistant

Analyzed tradeoffs: `locmem`'s only advantage is zero disk I/O, which doesn't matter for this project (SQLite + Django Q2 ORM broker, not high-throughput). Recommended removing `locmem` entirely, keeping just `filebased` (default) and `db` (alternative). Updated the plan accordingly.

### User

Let's make sure we update the user-facing documentation on how to clear the file-based cache.

### Assistant

Added a documentation step to the plan: add a Wikidata Cache section to `doc/README.md` with settings table, cache clearing instructions (`rm -rf .cache/wikidata/`), and rate-limiting details.
