"""Read-only MusicBrainz database client for foreground entity resolution.

Loaded into Postgres via https://github.com/rafacm/musicbrainz-database-setup
into the database named ``RAGTIME_MUSICBRAINZ_DB_NAME`` (default ``musicbrainz``)
under schema ``RAGTIME_MUSICBRAINZ_SCHEMA`` (default ``musicbrainz``).

Bypasses Django ORM — the MB schema is huge and read-only, building Django
models for it is invasive without giving us anything we need. A small psycopg
connection pool is enough.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    """A MusicBrainz candidate row, normalized across entity tables."""

    mbid: str          # entity gid (UUID, dashed string form)
    name: str          # primary or alias name that matched
    disambiguation: str
    type: str          # e.g. "Person" / "Group" / "Album" / "City". "" if no type table.


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        # ``make_conninfo`` properly escapes credentials / db names that
        # contain whitespace or special characters; building the DSN by
        # f-string interpolation breaks for passwords with quotes,
        # backslashes, or spaces.
        conninfo = make_conninfo(
            host=settings.RAGTIME_MUSICBRAINZ_DB_HOST,
            port=settings.RAGTIME_MUSICBRAINZ_DB_PORT,
            dbname=settings.RAGTIME_MUSICBRAINZ_DB_NAME,
            user=settings.RAGTIME_MUSICBRAINZ_DB_USER,
            password=settings.RAGTIME_MUSICBRAINZ_DB_PASSWORD,
        )
        _pool = ConnectionPool(
            conninfo=conninfo,
            min_size=1,
            max_size=8,
            kwargs={"autocommit": True, "options": f"-c search_path={settings.RAGTIME_MUSICBRAINZ_SCHEMA},public"},
        )
        return _pool


# Per-table query config. Keyed by EntityType.musicbrainz_table.
#
# MusicBrainz names its entity-relationship tables ``l_<a>_<b>`` with
# the two entity types in **alphabetical order**. The ``entity0`` /
# ``entity1`` columns follow that same alphabetical order. For most
# entity types ``<entity> < url`` (e.g. ``artist`` < ``url``), so the
# table is ``l_<entity>_url`` with ``entity0=<entity>``, ``entity1=url``.
# But ``url < work`` — so MB stores work-URL links in ``l_url_work``
# with ``entity0=url``, ``entity1=work``. ``link_main_col`` and
# ``link_url_col`` make the join direction explicit per type.
_TABLE_CONFIG: dict[str, dict[str, Any]] = {
    "artist": {
        "main": "artist",
        "alias": "artist_alias",
        "type_table": "artist_type",
        "type_fk": "type",
        "link_table": "l_artist_url",
        "link_main_col": "entity0",
        "link_url_col": "entity1",
    },
    "release_group": {
        "main": "release_group",
        "alias": "release_group_alias",
        "type_table": "release_group_primary_type",
        "type_fk": "type",
        "link_table": "l_release_group_url",
        "link_main_col": "entity0",
        "link_url_col": "entity1",
    },
    "label": {
        "main": "label",
        "alias": "label_alias",
        "type_table": "label_type",
        "type_fk": "type",
        "link_table": "l_label_url",
        "link_main_col": "entity0",
        "link_url_col": "entity1",
    },
    "place": {
        "main": "place",
        "alias": "place_alias",
        "type_table": "place_type",
        "type_fk": "type",
        "link_table": "l_place_url",
        "link_main_col": "entity0",
        "link_url_col": "entity1",
    },
    "work": {
        "main": "work",
        "alias": "work_alias",
        "type_table": "work_type",
        "type_fk": "type",
        # url < work alphabetically — MB names this ``l_url_work`` and
        # puts the work id in ``entity1``, the url id in ``entity0``.
        "link_table": "l_url_work",
        "link_main_col": "entity1",
        "link_url_col": "entity0",
    },
    "area": {
        "main": "area",
        "alias": "area_alias",
        "type_table": "area_type",
        "type_fk": "type",
        "link_table": "l_area_url",
        "link_main_col": "entity0",
        "link_url_col": "entity1",
    },
}

_WIKIDATA_QID_RE = re.compile(r"https?://(?:www\.)?wikidata\.org/(?:wiki|entity)/(Q\d+)")


def _filter_keys_for(table: str) -> set[str]:
    """Filter keys we accept in EntityType.musicbrainz_filter for this table."""
    return {
        "artist": {"artist_type", "artist_type_in"},
        "release_group": {"primary_type"},
        "label": set(),
        "place": set(),
        "work": set(),
        "area": {"area_type"},
    }.get(table, set())


def find_candidates(name: str, entity_type, *, limit: int = 10) -> list[Candidate]:
    """Return MusicBrainz candidates whose primary name or alias matches ``name``.

    ``entity_type`` is an episodes.models.EntityType instance. Reads its
    ``musicbrainz_table`` and ``musicbrainz_filter`` to build the query.
    Returns an empty list if the type isn't backed by an MB table or no
    candidates were found.
    """
    table = (entity_type.musicbrainz_table or "").strip()
    if not table:
        return []
    cfg = _TABLE_CONFIG.get(table)
    if cfg is None:
        logger.warning("Unknown musicbrainz_table %r for entity_type %s", table, entity_type)
        return []

    raw_filter = entity_type.musicbrainz_filter or {}
    accepted = _filter_keys_for(table)
    type_filter_values: list[str] = []
    for key, value in raw_filter.items():
        if key not in accepted:
            continue
        if isinstance(value, list):
            type_filter_values.extend(str(v) for v in value)
        else:
            type_filter_values.append(str(value))

    main_t = sql.Identifier(cfg["main"])
    main_fk = sql.Identifier(cfg["main"])  # alias FK column shares the main table name
    alias_t = sql.Identifier(cfg["alias"])

    common_cte = sql.SQL(
        """
        WITH name_matches AS (
            SELECT m.id, 0 AS rank
            FROM {main} m
            WHERE lower(m.name) = lower(%(name)s)
            UNION
            SELECT a.{main_fk} AS id, 1 AS rank
            FROM {alias} a
            WHERE lower(a.name) = lower(%(name)s)
        )
        """
    ).format(main=main_t, main_fk=main_fk, alias=alias_t)

    if cfg.get("type_table"):
        type_t = sql.Identifier(cfg["type_table"])
        type_fk = sql.Identifier(cfg["type_fk"])
        type_filter_sql = (
            sql.SQL("WHERE t.name = ANY(%(types)s) OR m.{fk} IS NULL").format(fk=type_fk)
            if type_filter_values
            else sql.SQL("")
        )
        body = sql.SQL(
            """
            SELECT m.gid::text, m.name, COALESCE(m.comment, ''),
                   COALESCE(t.name, '') AS type_name,
                   MIN(nm.rank) AS rank
            FROM name_matches nm
            JOIN {main} m ON m.id = nm.id
            LEFT JOIN {t} t ON t.id = m.{fk}
            {filter}
            GROUP BY m.id, m.gid, m.name, m.comment, t.name
            ORDER BY MIN(nm.rank), m.name
            LIMIT %(limit)s
            """
        ).format(main=main_t, t=type_t, fk=type_fk, filter=type_filter_sql)
    else:
        if type_filter_values:
            logger.debug(
                "Ignoring musicbrainz_filter for table %s — no type table available",
                table,
            )
        body = sql.SQL(
            """
            SELECT m.gid::text, m.name, COALESCE(m.comment, ''),
                   '' AS type_name,
                   MIN(nm.rank) AS rank
            FROM name_matches nm
            JOIN {main} m ON m.id = nm.id
            GROUP BY m.id, m.gid, m.name, m.comment
            ORDER BY MIN(nm.rank), m.name
            LIMIT %(limit)s
            """
        ).format(main=main_t)

    query = common_cte + body
    params = {"name": name, "limit": limit, "types": type_filter_values}

    pool = _get_pool()
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
    except Exception:
        logger.exception("MusicBrainz lookup failed for %r (%s)", name, table)
        return []

    return [
        Candidate(
            mbid=row[0],
            name=row[1],
            disambiguation=row[2],
            type=row[3],
        )
        for row in rows
    ]


def get_wikidata_qid(mbid: str, entity_type) -> str | None:
    """Resolve a MusicBrainz gid to a Wikidata Q-ID via external links.

    Returns the Q-ID string (e.g. ``"Q93341"``) or ``None`` if the entity has
    no Wikidata link in MB or the table isn't supported.
    """
    table = (entity_type.musicbrainz_table or "").strip()
    cfg = _TABLE_CONFIG.get(table)
    if cfg is None or not mbid:
        return None

    main_t = sql.Identifier(cfg["main"])
    link_t = sql.Identifier(cfg["link_table"])
    link_main = sql.Identifier(cfg.get("link_main_col", "entity0"))
    link_url = sql.Identifier(cfg.get("link_url_col", "entity1"))

    query = sql.SQL(
        """
        SELECT u.url
        FROM {main} m
        JOIN {link} lau ON lau.{main_col} = m.id
        JOIN url u ON u.id = lau.{url_col}
        WHERE m.gid = %s::uuid
          AND u.url ~ '^https?://(www\\.)?wikidata\\.org/(wiki|entity)/Q[0-9]+'
        LIMIT 1
        """
    ).format(main=main_t, link=link_t, main_col=link_main, url_col=link_url)

    pool = _get_pool()
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (mbid,))
                row = cur.fetchone()
    except Exception:
        logger.exception("MB → Wikidata link lookup failed for %s/%s", table, mbid)
        return None

    if not row:
        return None
    match = _WIKIDATA_QID_RE.search(row[0])
    return match.group(1) if match else None
