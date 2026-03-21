# Wikidata Cache Persistence

**Date:** 2026-03-21

## Problem

Wikidata API responses were cached in memory (`locmem`), lost on every Django restart. Entity resolution for a single episode can trigger ~650 API requests. Reprocessing or restarting repeated all requests, risking IP rate-limiting by Wikidata.

## Changes

- **File-based cache default** — replaced `locmem` with `django.core.cache.backends.filebased.FileBasedCache` stored in `.cache/wikidata/` (already gitignored). Survives restarts with no setup required. The `db` backend remains as an alternative.
- **Token bucket rate limiter** — added a thread-safe `_TokenBucket` class in `episodes/wikidata.py` that limits API requests to 5/second sustained with bursts up to 10. Only applies to cache misses; cached responses are returned immediately.
- **Documentation** — added a Wikidata Cache section to `doc/README.md` with settings table, cache clearing instructions, and rate-limiting details.

## Key parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Rate limiter rate | 5 req/s | Conservative vs Wikidata's limits (~200 req/s for bots) |
| Rate limiter capacity | 10 | Allows short bursts without blocking |
| Cache TTL | 604800 (7 days) | Unchanged; Wikidata entities rarely change |
| Cache location | `.cache/wikidata/` | Project-local, already in `.gitignore` |

## Verification

```bash
uv run python manage.py test episodes
uv run python manage.py shell -c "from django.core.cache import caches; print(caches['wikidata'])"
```

## Files modified

| File | Change |
|------|--------|
| `ragtime/settings.py` | Replace `locmem` with `filebased` default, remove `locmem` option |
| `episodes/wikidata.py` | Add `_TokenBucket` rate limiter, call before HTTP requests |
| `.env.sample` | Update `RAGTIME_WIKIDATA_CACHE_BACKEND` comment |
| `core/management/commands/_configure_helpers.py` | Change default to `"filebased"` |
| `doc/README.md` | Add Wikidata Cache section with settings table and clearing instructions |
