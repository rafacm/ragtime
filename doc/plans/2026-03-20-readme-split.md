# Plan: Split README into root overview + doc/README.md

**Date:** 2026-03-20

## Context

The root README.md is 276 lines — too long for a landing page. Detailed pipeline step descriptions, Langfuse setup, recovery layer docs, and "How Scott Works" make it hard to scan. The goal is a concise root README (~120 lines) that gives readers the essentials, with a `doc/README.md` for the deep-dive content. Additionally, `ragtime.svg` and `ragtime.png` live in the project root but belong in `doc/`.

## Steps

1. **Move image assets** — `git mv ragtime.svg doc/ragtime.svg` and `git mv ragtime.png doc/ragtime.png`
2. **Slim down root README** — keep hero image (update path), badges, What is RAGtime?, Features, Status, Getting Started, Tech Stack, License. Replace ~90-line pipeline section with compact table. Remove How Scott Works and Langfuse sections. Add Documentation section with links to doc/.
3. **Create doc/README.md** — detailed pipeline steps (verbatim), Recovery, How Scott Works, Langfuse observability, Feature Documentation section. Fix all relative links for doc/ location.
4. **Update CLAUDE.md** — update spec reference and pipeline sync instruction to mention both files.
5. **Update CHANGELOG.md** — add 2026-03-20 entry.
6. **Create documentation artifacts** — plan, feature doc, planning and implementation session transcripts.

## Expected result

- Root README: ~120 lines, scannable overview
- doc/README.md: all detailed content with working relative links
- No broken links, no content loss
