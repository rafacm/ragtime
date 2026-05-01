"""Custom test runner that handles PostgreSQL lingering connections.

Some tests spawn async threads (e.g. asyncio.run for the recovery agent)
that create database connections which outlive the test. PostgreSQL
refuses to drop a database with active connections. This runner
patches the database backend to terminate lingering sessions immediately
before DROP DATABASE.

When the ``JUNIT_XML_OUTPUT=1`` environment variable is set, the runner
also emits a JUnit-compatible XML report to ``test-results/junit.xml``
for consumption by CI reporters. The flag is opt-in so local
``manage.py test`` invocations stay clean.
"""

import logging
import os
from pathlib import Path

from django.db import connections
from django.db.backends.postgresql.creation import DatabaseCreation
from django.test.runner import DiscoverRunner

logger = logging.getLogger(__name__)

_original_destroy = DatabaseCreation._destroy_test_db

JUNIT_OUTPUT_PATH = Path("test-results") / "junit.xml"


def _destroy_test_db_with_terminate(self, *args, **kwargs):
    """Terminate active connections then drop the test database."""
    test_database_name = args[0] if args else kwargs.get("test_database_name", "")
    connections.close_all()

    settings_dict = self.connection.settings_dict
    try:
        import psycopg

        with psycopg.connect(
            host=settings_dict["HOST"],
            port=settings_dict["PORT"],
            user=settings_dict["USER"],
            password=settings_dict["PASSWORD"],
            dbname="postgres",
            autocommit=True,
        ) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (test_database_name,),
            )
    except Exception:
        logger.warning(
            "Failed to terminate connections to %s", test_database_name,
            exc_info=True,
        )

    return _original_destroy(self, *args, **kwargs)


def _junit_enabled() -> bool:
    return os.environ.get("JUNIT_XML_OUTPUT") == "1"


class PostgresTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        DatabaseCreation._destroy_test_db = _destroy_test_db_with_terminate

    def teardown_test_environment(self, **kwargs):
        DatabaseCreation._destroy_test_db = _original_destroy
        super().teardown_test_environment(**kwargs)

    def run_suite(self, suite, **kwargs):
        if not _junit_enabled():
            return super().run_suite(suite, **kwargs)

        from xmlrunner import XMLTestRunner

        JUNIT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        runner_kwargs = self.get_test_runner_kwargs()
        # XMLTestRunner installs its own resultclass; the one Django supplies
        # (DebugSQLTextTestResult) is incompatible with the XML result.
        runner_kwargs.pop("resultclass", None)
        with JUNIT_OUTPUT_PATH.open("wb") as output_stream:
            runner = XMLTestRunner(output=output_stream, **runner_kwargs)
            return runner.run(suite)
