import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("episodes", "0010_populate_entitytype_convert_fk"),
    ]

    operations = [
        # Remove old unique constraint (references old entity_type CharField)
        migrations.RemoveConstraint(
            model_name="entity",
            name="unique_entity_type_name",
        ),
        # Remove old CharField
        migrations.RemoveField(
            model_name="entity",
            name="entity_type_old",
        ),
        # Rename FK to entity_type
        migrations.RenameField(
            model_name="entity",
            old_name="entity_type_new",
            new_name="entity_type",
        ),
        # Make non-nullable
        migrations.AlterField(
            model_name="entity",
            name="entity_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="entities",
                to="episodes.entitytype",
            ),
        ),
        # Add new unique constraint
        migrations.AddConstraint(
            model_name="entity",
            constraint=models.UniqueConstraint(
                fields=["entity_type", "name"],
                name="unique_entity_type_name",
            ),
        ),
    ]
