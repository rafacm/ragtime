from django.db import migrations, models


def migrate_resizing_episodes(apps, schema_editor):
    """Move any episodes stuck in 'resizing' to 'transcribing'."""
    Episode = apps.get_model("episodes", "Episode")
    Episode.objects.filter(status="resizing").update(status="transcribing")

    ProcessingStep = apps.get_model("episodes", "ProcessingStep")
    ProcessingStep.objects.filter(
        step_name="resizing",
        status__in=["pending", "running"],
    ).update(status="skipped")


class Migration(migrations.Migration):

    dependencies = [
        ("episodes", "0014_alter_episode_status_chunk"),
    ]

    operations = [
        migrations.RunPython(migrate_resizing_episodes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="episode",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("scraping", "Scraping"),
                    ("needs_review", "Needs Review"),
                    ("downloading", "Downloading"),
                    ("transcribing", "Transcribing"),
                    ("summarizing", "Summarizing"),
                    ("chunking", "Chunking"),
                    ("extracting", "Extracting"),
                    ("resolving", "Resolving"),
                    ("embedding", "Embedding"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
