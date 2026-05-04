import os

from django.apps import AppConfig
from django.conf import settings


class EpisodesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'episodes'

    def ready(self):
        import episodes.signals  # noqa: F401

        from .telemetry import setup as setup_telemetry

        setup_telemetry()

        self._init_dbos()
        self._init_qdrant()

    def _init_dbos(self):
        import sys

        # DBOS startup is split into two roles:
        #
        # * **Worker** entrypoints (uvicorn, runserver) launch a full DBOS
        #   instance that listens to every declared queue and dequeues
        #   workflows for execution.
        # * **Client** management commands (``submit_episode``,
        #   ``enrich_entities``) only need to write a row to
        #   ``dbos.workflow_status`` so a running worker picks the workflow
        #   up. They launch DBOS with ``listen_queues([])`` so no local
        #   dispatcher races with the worker (avoids the "Contention
        #   detected" warning) and so no workflow is ever submitted to the
        #   client's executor (avoids "cannot schedule new futures after
        #   shutdown" at process exit).
        #
        # Other commands (migrate, check, shell, …) don't need DBOS at all.
        _CLIENT_COMMANDS = {"submit_episode", "enrich_entities"}
        _WORKER_COMMANDS = {"runserver"}
        is_uvicorn = any("uvicorn" in arg for arg in sys.argv[:1])
        is_worker = is_uvicorn or bool(_WORKER_COMMANDS.intersection(sys.argv))
        is_client = bool(_CLIENT_COMMANDS.intersection(sys.argv))
        if not (is_worker or is_client):
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
        if is_client and not is_worker:
            # Listen to no application queues — this process only enqueues.
            # ``Queue.enqueue`` calls ``start_workflow(execute_workflow=False)``
            # which only writes to ``dbos.workflow_status``; the dispatcher is
            # not needed. Pure "don't call launch()" doesn't work because
            # ``DBOS._sys_db`` is created inside ``launch()``.
            DBOS.listen_queues([])
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
