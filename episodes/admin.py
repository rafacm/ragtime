from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django_q.tasks import async_task

from .models import Entity, EntityMention, Episode


class EntityMentionInlineForEpisode(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("entity", "context", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityMentionInlineForEntity(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("episode", "context", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("url", "title", "language", "status", "created_at")
    list_filter = ("status", "language")
    readonly_fields = (
        "created_at",
        "updated_at",
        "audio_file",
        "error_message",
        "transcript",
        "transcript_json",
        "summary_generated",
        "entities_json",
    )
    actions = ["reprocess"]
    inlines = [EntityMentionInlineForEpisode]

    METADATA_FIELDS = (
        "title",
        "description",
        "published_at",
        "image_url",
        "language",
        "audio_url",
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            # Creating a new episode — only url is editable
            readonly += list(self.METADATA_FIELDS) + ["status", "scraped_html"]
        elif obj.status == Episode.Status.NEEDS_REVIEW:
            # Needs review — metadata editable, status read-only
            readonly += ["status", "scraped_html"]
        else:
            # All other statuses — everything read-only except url
            readonly += list(self.METADATA_FIELDS) + ["status", "scraped_html"]
        return readonly

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return [(None, {"fields": ("url",)})]
        main_fields = ["url", "status"]
        if obj.status == Episode.Status.FAILED and obj.error_message:
            main_fields.append("error_message")
        fieldsets = [
            (None, {"fields": main_fields}),
            (
                "Metadata",
                {"fields": self.METADATA_FIELDS},
            ),
        ]
        if obj.audio_file:
            fieldsets.append(("Files", {"fields": ("audio_file",)}))
        if obj.transcript:
            fieldsets.append(("Transcript", {"fields": ("transcript",)}))
        if obj.summary_generated:
            fieldsets.append(("Summary", {"fields": ("summary_generated",)}))
        if obj.entities_json:
            fieldsets.append((
                "Entities",
                {
                    "classes": ("collapse",),
                    "fields": ("entities_json",),
                },
            ))
        if obj.transcript_json:
            fieldsets.append((
                "Transcript JSON",
                {
                    "classes": ("collapse",),
                    "fields": ("transcript_json",),
                },
            ))
        fieldsets += [
            (
                "Debug",
                {
                    "classes": ("collapse",),
                    "fields": ("scraped_html",),
                },
            ),
            (
                "Timestamps",
                {
                    "classes": ("collapse",),
                    "fields": ("created_at", "updated_at"),
                },
            ),
        ]
        return fieldsets

    @admin.action(description="Reprocess selected episodes")
    def reprocess(self, request, queryset):
        count = 0
        for episode in queryset:
            episode.status = Episode.Status.SCRAPING
            episode.save(update_fields=["status", "updated_at"])
            async_task("episodes.scraper.scrape_episode", episode.pk)
            count += 1
        self.message_user(request, f"Queued {count} episode(s) for reprocessing.")


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("name", "entity_type", "mention_count", "created_at")
    list_filter = ("entity_type",)
    search_fields = ("name",)
    readonly_fields = ("entity_type", "name", "created_at", "updated_at")
    inlines = [EntityMentionInlineForEntity]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_mention_count=Count("mentions"))

    @admin.display(description="Mentions", ordering="_mention_count")
    def mention_count(self, obj):
        return obj._mention_count

    def has_add_permission(self, request):
        return False


@admin.register(EntityMention)
class EntityMentionAdmin(admin.ModelAdmin):
    list_display = ("entity", "episode", "short_context", "created_at")
    list_filter = ("entity__entity_type",)
    search_fields = ("entity__name", "episode__title")
    readonly_fields = ("entity", "episode", "context", "created_at")

    @admin.display(description="Context")
    def short_context(self, obj):
        if len(obj.context) > 80:
            return format_html("{}&hellip;", obj.context[:80])
        return obj.context

    def has_add_permission(self, request):
        return False
