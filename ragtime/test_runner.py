"""Custom test runner that handles PostgreSQL lingering connections.

Some tests spawn async threads (e.g. asyncio.run for the recovery agent)
that create database connections which outlive the test. PostgreSQL
refuses to drop a database with active connections. This runner
patches the database backend to terminate lingering sessions immediately
before DROP DATABASE.
"""

import logging

from django.db import connections
from django.db.backends.postgresql.creation import DatabaseCreation
from django.test.runner import DiscoverRunner

logger = logging.getLogger(__name__)

_original_destroy = DatabaseCreation._destroy_test_db


def _destroy_test_db_with_terminate(self, test_database_name, verbosity):
    """Terminate active connections then drop the test database."""
    connections.close_all()

    settings_dict = self.connection.settings_dict
    try:
        import psycopg

        conn = psycopg.connect(
            host=settings_dict["HOST"],
            port=settings_dict["PORT"],
            user=settings_dict["USER"],
            password=settings_dict["PASSWORD"],
            dbname="postgres",
            autocommit=True,
        )
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (test_database_name,),
        )
        conn.close()
    except Exception:
        logger.warning(
            "Failed to terminate connections to %s", test_database_name,
            exc_info=True,
        )

    return _original_destroy(self, test_database_name, verbosity)


class PostgresTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        DatabaseCreation._destroy_test_db = _destroy_test_db_with_terminate

    def teardown_test_environment(self, **kwargs):
        DatabaseCreation._destroy_test_db = _original_destroy
        super().teardown_test_environment(**kwargs)
