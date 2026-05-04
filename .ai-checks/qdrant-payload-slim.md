---
name: Slim Qdrant Payload Discipline
description: Qdrant chunk points must carry only filter fields. All display data is hydrated from Postgres at search time.
paths: episodes/vector_store.py
---

# Slim Qdrant Payload Discipline

## Context

The repo has one source of truth per piece of data, and it is Postgres for
everything except vectors. Qdrant chunk points carry **only** the fields
needed for server-side filtering:

- `chunk_id`
- `episode_id`
- `language`
- `entity_ids`

Everything else — episode title, episode URLs, chunk text, entity names,
MusicBrainz IDs, Wikidata IDs — is hydrated from Postgres in
`vector_store.search_chunks()` via a single keyed query.

This is deliberate. It means title edits, MBID resolutions, and Wikidata
enrichment flow into Scott's results immediately, without re-embedding
or `client.set_payload(...)` calls. Adding a "convenience" field to the
Qdrant payload silently re-introduces the dual-source-of-truth bug this
design exists to prevent.

## What to Check

### 1. No new fields on PointStruct.payload

Look for changes that add keys to the dict passed as `payload=` when
building `qm.PointStruct(...)` in `episodes/vector_store.py` (or
anywhere chunks are upserted into Qdrant). The allowed set is exactly:
`chunk_id`, `episode_id`, `language`, `entity_ids`.

**BAD**

```python
qm.PointStruct(
    id=p.id,
    vector=p.vector,
    payload={
        "chunk_id": p.chunk_id,
        "episode_id": p.episode_id,
        "language": p.language,
        "entity_ids": p.entity_ids,
        "episode_title": p.episode_title,  # NO — hydrate from Postgres
    },
)
```

**GOOD** — keep the payload to the four allowed keys; surface the title
in `search_chunks()` by joining the returned `episode_id` against
`Episode.objects.in_bulk(...)`.

### 2. No `client.set_payload` / `client.update_vectors` mutations

Anything that calls `set_payload`, `overwrite_payload`, `update_vectors`,
or otherwise mutates Qdrant points after upsert is a smell. The only
legitimate mutation paths are: re-embedding (full point replace) and
deletes. Flag and ask why.

### 3. New display data must be hydrated, not stored

If a PR adds a new piece of data Scott needs to show users (e.g.
episode publication date, host name), the implementation should:

- Add/use the column on the Postgres model.
- Extend the keyed lookup in `vector_store.search_chunks()` to fetch it.
- **Not** add it to the Qdrant payload.

### 4. New filter fields are the only legitimate payload additions

If a new field genuinely needs to drive a Qdrant `Filter` (server-side
narrowing of results before scoring), then adding it to the payload is
correct. In that case, confirm:

- A `create_payload_index` call covers the new field, or there's a clear
  reason it's not indexed.
- The field is small and stable (IDs, enums, language codes) — not free
  text, not anything that changes via user edits.

## Key Files

- `episodes/vector_store.py` — upserts and `search_chunks()` hydration
- `episodes/embedder.py` (if present) — anywhere `PointStruct` is built
- `episodes/models.py` — Postgres source of truth for hydrated fields

## Exclusions

- Migrations that backfill existing points to remove a field (cleanup is
  fine, even encouraged).
- Tests that build fake `PointStruct`s for assertion purposes.
