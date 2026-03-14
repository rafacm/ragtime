# Feature: Move Entity Types from YAML to Database

## Problem

Entity types (artist, band, album, etc.) were defined in a static YAML file (`episodes/entity_types.yaml`). Adding or modifying entity types required editing a source file and redeploying. There was no way for admin users to manage entity types through the Django admin interface.

## Changes

- **EntityType model** (`episodes/models.py`): New model with `key` (unique, max 30 chars), `name`, `description`, `examples` (JSONField storing a list of strings), `is_active` (boolean), and timestamps. Ordered by name. Used as FK target by Entity with `on_delete=PROTECT`.

- **Entity.entity_type FK** (`episodes/models.py`): Changed from `CharField` to `ForeignKey(EntityType)`. Provides referential integrity — renaming an EntityType key updates all related entities, deleting a type with existing entities is blocked.

- **3-step migration**: `0009_entitytype` creates the table. `0010_populate_entitytype_convert_fk` seeds from YAML, renames the old CharField to `entity_type_old`, adds a nullable FK `entity_type_new`, and populates it. `0011_finalize_entity_type_fk` drops the old field, renames the FK, makes it non-nullable, and re-adds the unique constraint.

- **YAML rename** (`episodes/initial_entity_types.yaml`): Renamed from `entity_types.yaml`. Examples converted from comma-separated strings to YAML lists for direct use as JSONField values.

- **Management command** (`episodes/management/commands/load_entity_types.py`): `load_entity_types` — idempotent seeding via `update_or_create` on key. Reports created/updated counts.

- **Extractor** (`episodes/extractor.py`): Removed module-level YAML loading. `build_system_prompt()` and `build_response_schema()` now query `EntityType.objects.filter(is_active=True)` on each call. Inactive types are excluded from extraction prompts and response schemas.

- **Resolver** (`episodes/resolver.py`): Looks up `EntityType` by key for each type in `entities_json`. Unknown types (not in DB) are skipped with a warning log. Entity creation and filtering use the FK instead of a string.

- **Admin** (`episodes/admin.py`): `EntityTypeAdmin` with entity count in list view, `key` field displayed first and read-only on edit, comma-separated examples input (custom `CommaSeparatedListField` form field that converts between text and JSON list), and a read-only entity inline with clickable change links. Updated `EntityAdmin` and `EntityMentionAdmin` list filters to use `entity_type__name`.

- **Tests** (`episodes/tests/test_extract.py`, `episodes/tests/test_resolve.py`): All tests seed EntityType rows from YAML in `setUp`. Entity creation uses FK. New tests: inactive types excluded from prompts, unknown entity types skipped during resolution.

- **README** (`README.md`): Replaced static entity type table with description of DB-backed management. Added `load_entity_types` to installation steps.

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| EntityType.key max_length | 30 | Matches existing Entity.entity_type length |
| EntityType.name max_length | 100 | Sufficient for descriptive type names |
| on_delete | `PROTECT` | Prevents accidental deletion of types with existing entities |
| is_active default | `True` | New types are immediately available for extraction |
| examples storage | JSONField | Clean list structure, matches YAML format, easy programmatic access |

## Verification

```bash
# Migrations apply cleanly
uv run python manage.py migrate

# No pending migrations
uv run python manage.py makemigrations --check

# Seed entity types (idempotent)
uv run python manage.py load_entity_types

# All tests pass (84 total)
uv run python manage.py test episodes

# Manual: Django admin — verify EntityType CRUD, comma-separated examples,
# entity inline with change links, Entity/EntityMention filters
```

## Files Modified

| File | Change |
|------|--------|
| `episodes/models.py` | Added EntityType model; changed Entity.entity_type from CharField to ForeignKey |
| `episodes/initial_entity_types.yaml` | Renamed from `entity_types.yaml`; examples converted to YAML lists |
| `episodes/migrations/0009_entitytype.py` | New — creates EntityType table |
| `episodes/migrations/0010_populate_entitytype_convert_fk.py` | New — seeds data, adds nullable FK, populates from old CharField |
| `episodes/migrations/0011_finalize_entity_type_fk.py` | New — drops old field, renames FK, makes non-nullable, re-adds constraint |
| `episodes/management/commands/load_entity_types.py` | New — idempotent seed command |
| `episodes/extractor.py` | Queries active EntityType from DB instead of loading YAML |
| `episodes/resolver.py` | Uses EntityType FK for entity creation/filtering; skips unknown types |
| `episodes/admin.py` | Added EntityTypeAdmin with comma-separated examples field and entity inline; updated filters |
| `episodes/tests/test_extract.py` | Seeds EntityType in setUp; added inactive type exclusion test |
| `episodes/tests/test_resolve.py` | Seeds EntityType in setUp; uses FK for Entity creation; added unknown type test |
| `README.md` | Updated Extracted Entities section and installation steps |
