"""Tests for the MusicBrainz local-DB client.

The actual MusicBrainz database is huge and not assumed available in CI; we
mock the psycopg connection pool and assert query construction + result
shaping. The query SQL is exercised as a string via the cursor's
``execute(query, params)`` capture.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from episodes import musicbrainz


def _et(table, filter_=None):
    """Build a stand-in EntityType (the real model has many more fields)."""
    return SimpleNamespace(
        musicbrainz_table=table,
        musicbrainz_filter=filter_ or {},
    )


def _fake_pool(rows):
    """Return a MagicMock pool whose connection().cursor().fetchall/fetchone
    returns ``rows`` (or rows[0] for fetchone).
    """
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    pool = MagicMock()

    @contextmanager
    def conn_cm():
        yield conn

    pool.connection = conn_cm
    pool._captured_cursor = cursor
    return pool


class FindCandidatesTests(SimpleTestCase):
    def setUp(self):
        # Reset the lazy pool between tests.
        musicbrainz._pool = None

    def test_returns_empty_for_unsupported_entity_type(self):
        result = musicbrainz.find_candidates("Miles Davis", _et(""))
        self.assertEqual(result, [])

    def test_returns_empty_for_unknown_table(self):
        result = musicbrainz.find_candidates("foo", _et("does_not_exist"))
        self.assertEqual(result, [])

    def test_artist_lookup_returns_candidates(self):
        rows = [
            (
                "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3",
                "Miles Davis",
                "Davis, Miles",
                "Jazz trumpeter",
                "Person",
                0,
            ),
            (
                "abcdef00-0000-0000-0000-000000000000",
                "Miles Davis Jr.",
                "Davis, Miles Jr.",
                "",
                "Person",
                1,
            ),
        ]
        pool = _fake_pool(rows)
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            result = musicbrainz.find_candidates(
                "Miles Davis",
                _et("artist", {"artist_type": "Person"}),
                limit=5,
            )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].mbid, "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3")
        self.assertEqual(result[0].name, "Miles Davis")
        self.assertEqual(result[0].type, "Person")
        self.assertEqual(result[0].disambiguation, "Jazz trumpeter")

        # The query should have passed the type filter through to params.
        call_args = pool._captured_cursor.execute.call_args
        params = call_args[0][1]
        self.assertEqual(params["name"], "Miles Davis")
        self.assertEqual(params["limit"], 5)
        self.assertEqual(params["types"], ["Person"])

    def test_artist_type_in_list_filter_expands(self):
        pool = _fake_pool([])
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            musicbrainz.find_candidates(
                "Weather Report",
                _et("artist", {"artist_type_in": ["Group", "Orchestra"]}),
            )
        params = pool._captured_cursor.execute.call_args[0][1]
        self.assertEqual(sorted(params["types"]), ["Group", "Orchestra"])

    def test_label_lookup_no_type_filter(self):
        rows = [("uuid-1", "Blue Note", "Blue Note", "jazz label", "", 0)]
        pool = _fake_pool(rows)
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            result = musicbrainz.find_candidates("Blue Note", _et("label"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].mbid, "uuid-1")
        self.assertEqual(result[0].type, "")

    def test_swallows_db_error_and_returns_empty(self):
        pool = MagicMock()
        pool.connection.side_effect = RuntimeError("connection refused")
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            result = musicbrainz.find_candidates("X", _et("artist"))
        self.assertEqual(result, [])


class GetWikidataQidTests(SimpleTestCase):
    def setUp(self):
        musicbrainz._pool = None

    def test_returns_qid_when_link_exists(self):
        pool = _fake_pool([("https://www.wikidata.org/wiki/Q93341",)])
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            qid = musicbrainz.get_wikidata_qid(
                "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3",
                _et("artist"),
            )
        self.assertEqual(qid, "Q93341")

    def test_returns_qid_for_entity_url_format(self):
        pool = _fake_pool([("http://wikidata.org/entity/Q482994",)])
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            qid = musicbrainz.get_wikidata_qid("uuid", _et("release_group"))
        self.assertEqual(qid, "Q482994")

    def test_none_when_no_row(self):
        pool = _fake_pool([])
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            qid = musicbrainz.get_wikidata_qid("uuid", _et("artist"))
        self.assertIsNone(qid)

    def test_none_for_unsupported_table(self):
        self.assertIsNone(musicbrainz.get_wikidata_qid("uuid", _et("")))

    def test_none_for_empty_mbid(self):
        self.assertIsNone(musicbrainz.get_wikidata_qid("", _et("artist")))

    def test_swallows_db_error(self):
        pool = MagicMock()
        pool.connection.side_effect = RuntimeError("boom")
        with patch.object(musicbrainz, "_get_pool", return_value=pool):
            qid = musicbrainz.get_wikidata_qid("uuid", _et("artist"))
        self.assertIsNone(qid)
