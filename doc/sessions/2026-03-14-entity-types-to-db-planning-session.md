# Session: Entity Types to DB — Planning

**Session ID:** `66a82ba2-f434-43d3-ad62-6aa697eb6421`

**Date:** 2026-03-14

## Summary

Planned the migration of entity types from a static YAML file to a database-backed model with Django admin UI. Covered model design, migration strategy, deletion semantics, and admin UX.

## Conversation

### User

Asked to plan moving entity types from the YAML file to the database so they can be managed via Django admin.

### Assistant

Entered plan mode. Read the current codebase: `episodes/models.py` (Entity model with CharField entity_type), `episodes/entity_types.yaml` (14 entity types), `episodes/extractor.py` (module-level YAML loading), `episodes/resolver.py` (string-based entity_type usage), `episodes/admin.py`, and both test files.

Considered key design questions:

1. **CharField vs ForeignKey** for `Entity.entity_type`: FK gives referential integrity and automatic cascade on rename. CharField would be simpler but loses DB-level consistency. Chose FK.

2. **Deletion strategy**: Considered CASCADE (too destructive — deletes all entities), SET_NULL (orphans entities), and PROTECT (safest). Chose PROTECT + `is_active` boolean so types can be disabled without deleting historical data.

3. **examples field type**: Considered TextField with comma-separated values, JSONField, and ArrayField. Chose JSONField — matches YAML structure, clean for programmatic use, and works on SQLite.

4. **Migration approach**: A direct field swap would lose data. Designed a 3-step migration: create table, rename old field + add nullable FK + populate, then finalize (drop old field, rename FK, make non-nullable).

Wrote the full implementation plan with 11 steps covering model creation, YAML rename, migrations, management command, extractor/resolver updates, admin registration, test updates, and README changes.

### User

Accepted the plan and asked to implement it.
