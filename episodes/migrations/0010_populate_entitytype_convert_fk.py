from pathlib import Path

import yaml
from django.db import migrations, models
import django.db.models.deletion


def seed_entity_types_and_populate_fk(apps, schema_editor):
    EntityType = apps.get_model("episodes", "EntityType")
    Entity = apps.get_model("episodes", "Entity")

    # Load seed data
    yaml_path = Path(__file__).resolve().parent.parent / "initial_entity_types.yaml"
    with open(yaml_path) as f:
        entity_types = yaml.safe_load(f)

    type_by_key = {}
    for et in entity_types:
        obj, _ = EntityType.objects.update_or_create(
            key=et["key"],
            defaults={
                "name": et["name"],
                "description": et.get("description", ""),
                "examples": et.get("examples", []),
            },
        )
        type_by_key[et["key"]] = obj

    # Populate FK for existing Entity rows
    for entity in Entity.objects.all():
        et_obj = type_by_key.get(entity.entity_type_old)
        if et_obj is None:
            # Unknown type — create as inactive
            et_obj, _ = EntityType.objects.get_or_create(
                key=entity.entity_type_old,
                defaults={
                    "name": entity.entity_type_old,
                    "is_active": False,
                },
            )
            type_by_key[entity.entity_type_old] = et_obj
        entity.entity_type_new_id = et_obj.pk
        entity.save(update_fields=["entity_type_new_id"])


def reverse_populate(apps, schema_editor):
    Entity = apps.get_model("episodes", "Entity")
    EntityType = apps.get_model("episodes", "EntityType")

    for entity in Entity.objects.select_related("entity_type_new").all():
        if entity.entity_type_new:
            entity.entity_type_old = entity.entity_type_new.key
            entity.save(update_fields=["entity_type_old"])


class Migration(migrations.Migration):

    dependencies = [
        ("episodes", "0009_entitytype"),
    ]

    operations = [
        # Rename old CharField to entity_type_old
        migrations.RenameField(
            model_name="entity",
            old_name="entity_type",
            new_name="entity_type_old",
        ),
        # Add nullable FK
        migrations.AddField(
            model_name="entity",
            name="entity_type_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="episodes.entitytype",
            ),
        ),
        # Populate FK from old CharField
        migrations.RunPython(
            seed_entity_types_and_populate_fk,
            reverse_populate,
        ),
    ]
