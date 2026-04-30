---
name: Entity Creation Race Safety
description: All Entity row creation must go through get_or_create with a sorted advisory lock — never bare Entity.objects.create().
---

# Entity Creation Race Safety

## Context

Pipeline episodes run in parallel (default `RAGTIME_EPISODE_CONCURRENCY=4`).
The resolver was the source of a real production deadlock when parallel
episodes shared entity names across types — see commit `4b69d9e` ("Fix
resolver deadlock when parallel episodes share entity names across types").

The fix codified a single safe pattern, in `episodes/resolver.py`:

1. Acquire a deterministic Postgres advisory lock on
   `(entity_type, name)` — `pg_advisory_xact_lock(hashtextextended(key, 0))`.
2. **Sort the keys before locking** when taking multiple locks in the
   same transaction, to prevent inverse-order deadlocks.
3. Use `Entity.objects.get_or_create(...)`, with an `IntegrityError`
   fallback for the unlikely-but-possible race after the lock.

The wrapper that does this is `_get_or_create_entity(entity_type, name, mbid)`
in `episodes/resolver.py`. Bypassing it — even "just this once" — re-opens
the deadlock window.

## What to Check

### 1. No bare Entity.objects.create

Search the diff for `Entity.objects.create(`. Any new occurrence outside
tests is a fail. Use `_get_or_create_entity(...)` from
`episodes/resolver.py` instead, or extract a similar helper if the call
site genuinely can't import it.

**BAD**

```python
entity = Entity.objects.create(entity_type=etype, name=name)
```

**GOOD**

```python
from episodes.resolver import _get_or_create_entity
entity, _created = _get_or_create_entity(etype, name)
```

### 2. Multi-key locks must be sorted

If new code takes more than one advisory lock in a single transaction,
the keys must be sorted before iteration. Unsorted locks across parallel
workers cause classic A→B / B→A deadlocks.

**BAD**

```python
for key in entity_keys:                  # arbitrary order
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
```

**GOOD**

```python
for key in sorted(entity_keys):
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
```

### 3. Don't downgrade xact_lock to non-xact

`pg_advisory_xact_lock` releases automatically at transaction end.
`pg_advisory_lock` does not — forgetting an unlock leaks the lock for
the lifetime of the connection. Flag any switch from `xact` to non-`xact`.

### 4. Lock keys must include entity_type

The deadlock fix specifically broadened the key to `(entity_type, name)`
because two episodes resolving "Miles Davis" as both Person and Artist
would hold disjoint rows but contend on the same name string. Don't
narrow the key back to just `name`.

### 5. New entity-creating code paths

If the diff introduces a new place that creates `Entity` rows (e.g. a
new admin action, a backfill management command, a new resolver mode),
either:

- Route it through `_get_or_create_entity`, OR
- Document why this path is single-writer (e.g. "this command is run
  manually, never concurrently") in a comment, and confirm that's
  actually true.

## Key Files

- `episodes/resolver.py` — canonical pattern, `_get_or_create_entity`
- `episodes/models.py` — `Entity` model, unique constraint
- Any new file under `episodes/` that imports `Entity`

## Exclusions

- Tests using `Entity.objects.create` directly inside transactions
  scoped to a single test (no concurrency).
- Migrations using `RunPython` with a single-writer assumption.
