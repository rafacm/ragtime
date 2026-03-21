# Wikidata Cache Persistence

**Date:** 2026-03-21

## Context

The Wikidata cache defaults to `locmem` (in-memory), losing all cached responses on every Django restart. During entity resolution, each unique entity name triggers up to 11 API requests. For ~60 entities per episode, that's ~650 requests repeated on each restart, risking IP rate-limiting.

## Changes

| # | Change | File |
|---|--------|------|
| 1 | Replace `locmem` with `filebased` as default cache backend, remove `locmem` option | `ragtime/settings.py` |
| 2 | Add token bucket rate limiter (5 req/s, burst 10) for cache-miss HTTP requests | `episodes/wikidata.py` |
| 3 | Update env sample and configure wizard defaults | `.env.sample`, `_configure_helpers.py` |
| 4 | Add Wikidata Cache section to documentation | `doc/README.md` |
