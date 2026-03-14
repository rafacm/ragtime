# Plan: Move Entity Types from YAML to Database

## Context

Entity types (artist, band, album, etc.) are currently defined in a static YAML file (`episodes/entity_types.yaml`). The user wants them persisted in the database and editable via Django admin, so new entity types can be added without touching code. The YAML file becomes seed data renamed to `initial_entity_types.yaml`.

Key design question: what happens when a user modifies/deletes an entity type that already has extracted entities?

## Design Decisions

### Entity.entity_type: CharField to ForeignKey

Change `Entity.entity_type` from a CharField to a FK pointing to `EntityType`. This gives us referential integrity and means renaming an EntityType's key automatically updates all related entities. Requires a 3-step migration (create table, data migration, swap fields).

### Deletion strategy: PROTECT + is_active

- `PROTECT` on delete: prevents deleting an EntityType that has Entity records
- `is_active` boolean: lets admins disable a type so it's excluded from future extractions without destroying historical data
- Admin shows entity count to help users understand impact

### examples field: JSONField

Store examples as a JSON list of strings (not comma-separated text). Matches the YAML structure and is cleaner for programmatic use. Admin form uses a custom `CommaSeparatedListField` to present a user-friendly text input that converts to/from JSON.

## Implementation Steps

### Step 1: Create EntityType model

Add before `Entity` in `episodes/models.py`: `key` (unique CharField), `name`, `description`, `examples` (JSONField), `is_active` (BooleanField), timestamps.

### Step 2: Rename YAML file

`episodes/entity_types.yaml` to `episodes/initial_entity_types.yaml`. Convert examples from comma-separated strings to YAML lists.

### Step 3: Schema migration for EntityType

`0009_entitytype.py` — creates EntityType table.

### Step 4: Data migration — seed EntityType + add FK on Entity

`0010_populate_entitytype_convert_fk.py`:
1. Rename `entity_type` CharField to `entity_type_old`
2. Add nullable `entity_type_new` FK
3. `RunPython`: Load YAML, create EntityType rows via `update_or_create`, populate FK for existing Entity rows

### Step 5: Final schema migration — swap fields

`0011_finalize_entity_type_fk.py`:
1. Remove old unique constraint
2. Remove old CharField
3. Rename FK field
4. Make non-nullable
5. Re-add unique constraint

### Step 6: Management command `load_entity_types`

Idempotent `update_or_create` from YAML seed file.

### Step 7: Update extractor.py

Query `EntityType.objects.filter(is_active=True)` instead of loading YAML at module level.

### Step 8: Update resolver.py

Look up EntityType by key, create Entity with FK. Skip unknown entity types with a warning.

### Step 9: Update admin.py

- Register `EntityTypeAdmin` with entity count, key readonly on edit, comma-separated examples input, entity inline with change links
- Update `EntityAdmin` and `EntityMentionAdmin` filters to use FK lookups

### Step 10: Update tests

Seed EntityType in setUp, use FK for Entity creation. Add tests for inactive types and unknown entity types.

### Step 11: Update README

Replace static entity type table with description of DB-backed types. Add `load_entity_types` to installation steps.

## Files to Modify

| File | Change |
|------|--------|
| `episodes/models.py` | Add EntityType model, change Entity.entity_type to FK |
| `episodes/entity_types.yaml` | Rename to `initial_entity_types.yaml`, convert examples to lists |
| `episodes/extractor.py` | Query DB instead of YAML |
| `episodes/resolver.py` | Use EntityType FK for Entity creation/filtering |
| `episodes/admin.py` | Add EntityTypeAdmin, update filters |
| `episodes/management/commands/load_entity_types.py` | New management command |
| `episodes/tests/test_extract.py` | Adapt to DB-backed entity types |
| `episodes/tests/test_resolve.py` | Adapt to FK-based Entity model |
| `README.md` | Update "Extracted Entities" section and installation steps |
| 3 new migration files | Schema + data + finalize |
