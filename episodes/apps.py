import os

from django.apps import AppConfig
from django.conf import settings


class EpisodesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'episodes'

    def ready(self):
        import episodes.signals  # noqa: F401

        from .recovery import handle_step_failure
        from .signals import step_failed
        from .telemetry import setup as setup_telemetry

        step_failed.connect(handle_step_failure, dispatch_uid="recovery_step_failed")
        setup_telemetry()

        self._init_dbos()
        self._init_qdrant()

    def _init_dbos(self):
        import sys

        # Only initialize DBOS for server/worker entrypoints, plus the
        # management commands that need to talk to the queue. Other commands
        # (migrate, check, shell, …) don't need a live DBOS connection.
        _DBOS_COMMANDS = {"runserver", "submit_episode", "enrich_entities"}
        is_uvicorn = any("uvicorn" in arg for arg in sys.argv[:1])
        if not is_uvicorn and not _DBOS_COMMANDS.intersection(sys.argv):
            return

        from dbos import DBOS, DBOSConfig

        from urllib.parse import quote_plus

        db = settings.DATABASES["default"]
        user = quote_plus(db["USER"])
        password = quote_plus(db["PASSWORD"])
        host = db["HOST"]
        port = db["PORT"]
        name = db["NAME"]
        system_db_url = os.getenv(
            "DBOS_SYSTEM_DATABASE_URL",
            f"postgresql://{user}:{password}@{host}:{port}/{name}",
        )

        # Import every module that registers DBOS workflows / queues so the
        # @DBOS.workflow / @DBOS.step / Queue() decorators run BEFORE
        # DBOS.launch(). Lazy imports from inside steps would otherwise
        # register against an already-launched DBOS, and enqueues against
        # those late-registered workflows silently fail.
        import episodes.workflows  # noqa: F401 — episode_pipeline queue + process_episode
        import episodes.enrichment  # noqa: F401 — wikidata_enrichment queue + enrich_entity_wikidata

        dbos_config: DBOSConfig = {
            "name": "ragtime",
            "system_database_url": system_db_url,
        }
        DBOS(config=dbos_config)
        DBOS.launch()

    def _init_qdrant(self):
        """Bootstrap the Qdrant collection once per process at startup.

        Previously, ``ensure_collection()`` ran inside every per-episode
        embed step, which races with itself when multiple episodes embed
        in parallel against an empty Qdrant. Doing it once here makes the
        embed step a no-op against a pre-existing collection.

        Skipped for management commands that don't touch Qdrant (migrate,
        check, makemigrations, …) — same gating as DBOS.
        """
        import sys

        _QDRANT_COMMANDS = {"runserver"}
        is_uvicorn = any("uvicorn" in arg for arg in sys.argv[:1])
        if not is_uvicorn and not _QDRANT_COMMANDS.intersection(sys.argv):
            return

        try:
            from .vector_store import get_vector_store

            get_vector_store().ensure_collection()
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Could not ensure Qdrant collection at startup; will retry per-embed."
            )
