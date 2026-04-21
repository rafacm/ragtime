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

    def _init_dbos(self):
        import sys

        # Only initialize DBOS for server/worker entrypoints — other commands
        # (migrate, check, shell, …) don't need a live DBOS connection.
        _DBOS_COMMANDS = {"runserver"}
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

        import episodes.workflows  # noqa: F401 — register workflows

        dbos_config: DBOSConfig = {
            "name": "ragtime",
            "system_database_url": system_db_url,
        }
        DBOS(config=dbos_config)
        DBOS.launch()
