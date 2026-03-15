import django.db.models.deletion
from django.db import migrations, models


def delete_entity_mentions(apps, schema_editor):
    """Delete all existing EntityMention rows so chunk FK can be made non-nullable."""
    EntityMention = apps.get_model("episodes", "EntityMention")
    EntityMention.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("episodes", "0015_remove_resizing_status"),
    ]

    operations = [
        # 1. Add entities_json to Chunk
        migrations.AddField(
            model_name="chunk",
            name="entities_json",
            field=models.JSONField(blank=True, null=True),
        ),
        # 2. Add chunk FK to EntityMention (nullable initially)
        migrations.AddField(
            model_name="entitymention",
            name="chunk",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="entity_mentions",
                to="episodes.chunk",
            ),
        ),
        # 3. Data migration: delete all existing EntityMention rows
        migrations.RunPython(delete_entity_mentions, migrations.RunPython.noop),
        # 4. Make chunk non-nullable
        migrations.AlterField(
            model_name="entitymention",
            name="chunk",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="entity_mentions",
                to="episodes.chunk",
            ),
        ),
        # 5. Drop old unique constraint, add new one
        migrations.RemoveConstraint(
            model_name="entitymention",
            name="unique_entity_episode_context",
        ),
        migrations.AddConstraint(
            model_name="entitymention",
            constraint=models.UniqueConstraint(
                fields=["entity", "chunk"],
                name="unique_entity_chunk",
            ),
        ),
    ]
