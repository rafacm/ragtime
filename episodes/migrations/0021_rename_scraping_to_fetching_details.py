"""Rename ``scraping`` status / step name to ``fetching_details``.

Part of the Fetch Details agent migration. Renames the status enum value on
``Episode``, then rewrites every persisted ``"scraping"`` literal in the
DB-side audit columns (``ProcessingStep.step_name``,
``PipelineEvent.step_name``, ``ProcessingRun.resumed_from_step``).
"""

from django.db import migrations, models


def rename_scraping_forward(apps, schema_editor):
    Episode = apps.get_model("episodes", "Episode")
    ProcessingStep = apps.get_model("episodes", "ProcessingStep")
    PipelineEvent = apps.get_model("episodes", "PipelineEvent")
    ProcessingRun = apps.get_model("episodes", "ProcessingRun")

    Episode.objects.filter(status="scraping").update(status="fetching_details")
    ProcessingStep.objects.filter(step_name="scraping").update(step_name="fetching_details")
    PipelineEvent.objects.filter(step_name="scraping").update(step_name="fetching_details")
    ProcessingRun.objects.filter(resumed_from_step="scraping").update(
        resumed_from_step="fetching_details"
    )


def rename_scraping_backward(apps, schema_editor):
    Episode = apps.get_model("episodes", "Episode")
    ProcessingStep = apps.get_model("episodes", "ProcessingStep")
    PipelineEvent = apps.get_model("episodes", "PipelineEvent")
    ProcessingRun = apps.get_model("episodes", "ProcessingRun")

    Episode.objects.filter(status="fetching_details").update(status="scraping")
    ProcessingStep.objects.filter(step_name="fetching_details").update(step_name="scraping")
    PipelineEvent.objects.filter(step_name="fetching_details").update(step_name="scraping")
    ProcessingRun.objects.filter(resumed_from_step="fetching_details").update(
        resumed_from_step="scraping"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("episodes", "0020_entity_musicbrainz_id_entity_wikidata_attempts_and_more"),
    ]

    operations = [
        migrations.RunPython(rename_scraping_forward, rename_scraping_backward),
        migrations.AlterField(
            model_name="episode",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("queued", "Queued"),
                    ("fetching_details", "Fetching Details"),
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
