# Wikidata Cache Persistence — Implementation Session

**Date:** 2026-03-21

**Session ID:** 438617e8-2ff9-4481-abaf-6bed9198c9f8

## Summary

Implemented file-based Wikidata cache persistence, token bucket rate limiter, and cache documentation. All 203 tests pass.

### Assistant

Implemented the approved plan:

1. **Settings** — changed default from `locmem` to `filebased` in `ragtime/settings.py`. Replaced `LocMemCache` with `FileBasedCache` pointing to `.cache/wikidata/`. Also used the already-defined `RAGTIME_WIKIDATA_CACHE_TTL` variable instead of re-reading the env var.

2. **Rate limiter** — added `_TokenBucket` class in `episodes/wikidata.py` with `rate=5` req/s and `capacity=10`. Thread-safe via `threading.Lock`. Called `_rate_limiter.acquire()` right before `httpx.get()` in `_make_request()`, which only runs on cache misses.

3. **Config updates** — changed `.env.sample` comment to document `filebased` as default. Changed configure wizard default from `"locmem"` to `"filebased"`.

4. **Documentation** — added Wikidata Cache section to `doc/README.md` with settings table, cache clearing command, and rate-limiting note. Added entry to table of contents.

5. Verified `FileBasedCache` is active via Django shell, confirmed `.cache/wikidata/` directory path. All 203 tests pass.
