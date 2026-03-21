# Wikidata Cache Persistence — Planning Session

**Date:** 2026-03-21

**Session ID:** 438617e8-2ff9-4481-abaf-6bed9198c9f8

## Summary

Planned switching the Wikidata API cache from in-memory (`locmem`) to file-based persistence, adding a token bucket rate limiter, and documenting cache management.

### User

Provided a detailed issue description for Wikidata cache persistence, including the problem (locmem loses cache on restart, ~650 requests per episode), current state of the code, and proposed changes (switch to filebased, add to .gitignore, update .env.sample and configure wizard, consider rate-limiting).

### Assistant

Explored the codebase to verify the current state: settings.py cache config (lines 189-201), wikidata.py _make_request() caching logic, .env.sample entries, configure wizard defaults, and .gitignore (`.cache` already listed). Confirmed no existing rate-limiting or backoff logic.

Wrote the plan: replace `locmem` with `filebased` as default, keep `db` as alternative, add a simple `time.sleep(0.1)` before HTTP requests.

### User

Regarding rate limiting, what about a Token bucket / rate limiter approach, we would need to know which responses are coming from the cache and which ones are not so the rate limiting only apply to them.

### Assistant

Updated the plan to use a token bucket rate limiter instead of a simple sleep. The `_make_request()` function already returns early on cache hits (line 34-35), so the rate limiter only fires on cache misses. Designed a `_TokenBucket` class with rate=5 req/s and capacity=10 (burst), thread-safe via `threading.Lock`.

### User

The default cache approach should be this new one we are implementing now and not the memory-based one. What are the cons or tradoffs of removing that one?

### Assistant

Analyzed tradeoffs: `locmem`'s only advantage is zero disk I/O, which doesn't matter for this project (SQLite + Django Q2 ORM broker, not high-throughput). Recommended removing `locmem` entirely, keeping just `filebased` (default) and `db` (alternative). Updated the plan accordingly.

### User

Let's make sure we update the user-facing documentation on how to clear the file-based cache.

### Assistant

Added a documentation step to the plan: add a Wikidata Cache section to `doc/README.md` with settings table, cache clearing instructions (`rm -rf .cache/wikidata/`), and rate-limiting details.
