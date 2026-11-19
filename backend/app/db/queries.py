from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

POST_FILTER_BATCH = 5000


def _connection():
    # Standalone backend scripts can import queries without configuring the API.
    from app.db.pool import current_pool

    return current_pool().connection()


@contextmanager
def catalog_scan(name, statement, params=None):
    """Stream an offline catalog scan without changing the next pool client's timeout."""
    with _connection() as conn, conn.cursor(name=name) as cur:
        conn.execute("SET LOCAL statement_timeout = '120s'")
        cur.itersize = 50_000
        cur.execute(statement, params)
        yield cur


@dataclass(frozen=True)
class Filters:
    languages: tuple[str, ...] = field(default_factory=tuple)
    genres: tuple[str, ...] = field(default_factory=tuple)
    date_from: date | None = None
    date_to: date | None = None

    @property
    def active(self) -> bool:
        return bool(self.languages or self.genres or self.date_from or self.date_to)

    @classmethod
    def from_request(cls, req) -> "Filters":
        # request validation already lowercased these
        return cls(
            languages=tuple(req.original_language or ()),
            genres=tuple(req.genres or ()),
            date_from=req.date_from,
            date_to=req.date_to,
        )


def _where(f: Filters) -> tuple[list[str], list]:
    """THE single definition of the hard filters. Used by the gate and the post-filter."""
    clauses, params = [], []
    if f.languages:
        clauses.append("original_language = ANY(%s)")
        params.append(list(f.languages))
    if f.genres:
        clauses.append("genres && %s::text[]")        # any-of, served by the GIN index
        params.append(list(f.genres))
    if f.date_from:
        clauses.append("release_date >= %s")          # null release_date fails, by design
        params.append(f.date_from)
    if f.date_to:
        clauses.append("release_date <= %s")
        params.append(f.date_to)
    return clauses, params


def filtered_movie_query(statement: str, f: Filters) -> tuple[str, list]:
    """Append catalog filter predicates to a movie SELECT and return its bound values."""
    clauses, params = _where(f)
    if clauses:
        statement += " WHERE " + " AND ".join(clauses)
    return statement, params


def gate_ids(f: Filters, limit: int) -> list[int]:
    """Return up to limit matching movie IDs for recommendation candidate selection."""
    statement, params = filtered_movie_query("SELECT id FROM movies", f)
    with _connection() as conn:
        return [int(row["id"]) for row in conn.execute(statement + " LIMIT %s", [*params, limit])]


def filter_ids(ids: list[int], f: Filters) -> set[int]:
    """Subset of ids that satisfy the filters (same _where as the gate)."""
    if not ids:
        return set()
    clauses, params = _where(f)
    where = " AND ".join(["id = ANY(%s)", *clauses])
    keep: set[int] = set()
    with _connection() as conn:
        for i in range(0, len(ids), POST_FILTER_BATCH):
            chunk = ids[i:i + POST_FILTER_BATCH]
            rows = conn.execute(f"SELECT id FROM movies WHERE {where}",
                                [chunk, *params]).fetchall()
            keep.update(int(r["id"]) for r in rows)
    return keep


MOVIE_COLS = """
    id, title, original_language, release_date, genres, cast_members, director, writers, producers, music_composer,
    keywords, production_companies, production_countries, spoken_languages,
    overview, has_thin_overview, poster_path
"""

ARRAY_COLS = (
    "genres", "cast_members", "director", "writers", "producers",
    "music_composer", "keywords", "production_companies",
    "production_countries", "spoken_languages",
)


def exact_tag_hits(names_by_field: dict[str, set[str]]) -> dict[int, int]:
    """Count selected catalog tags absent from the fitted model, once per movie and tag."""
    from psycopg import sql

    hits = {}
    with _connection() as conn:
        for field, names in names_by_field.items():
            if field not in ARRAY_COLS:
                raise ValueError(f"Unknown movie tag field: {field}")
            # Use catalog spelling for the case-sensitive array index.
            rows = conn.execute(
                "SELECT name FROM tag_lookup WHERE tag_type = %s AND lower(name) = ANY(%s)",
                (field, list(names)),
            )
            canonical = [row["name"] for row in rows]
            if not canonical:
                continue
            count = sql.SQL("1")
            if len(names) > 1:
                count = sql.SQL(
                    "(SELECT count(DISTINCT lower(n)) FROM unnest({}) AS t(n) WHERE n = ANY(%(names)s))"
                ).format(sql.Identifier(field))
            statement = sql.SQL(
                "SELECT id, {} AS hits FROM movies WHERE {} && %(names)s::text[]"
            ).format(count, sql.Identifier(field))
            for row in conn.execute(statement, {"names": canonical}):
                mid = row["id"]
                hits[mid] = hits.get(mid, 0) + row["hits"]
    return hits


def get_movies(ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {MOVIE_COLS} FROM movies WHERE id = ANY(%s)",
            (list(ids),),
        )
        rows = cur.fetchall()

    out: dict[int, dict] = {}
    for row in rows:
        for col in ARRAY_COLS:
            row[col] = row[col] or []          # NULL -> [] so callers never branch
        out[int(row["id"])] = row

    return out


MOVIE_SEARCH_SQL = """
SELECT id, title, EXTRACT(YEAR FROM release_date)::int AS year, poster_path
FROM movies
WHERE {matches}
ORDER BY (lower(title) = %(full_query)s) DESC,
         (lower(title) = %(q)s) DESC,                 -- exact title match
         {initials_order}
         (lower(title) LIKE %(prefix)s) DESC,         -- starts with query
         (lower(title) LIKE %(word_prefix)s) DESC,    -- a word starts with query
         length(title),                               -- shorter = closer match
         title,
         id                                           -- stable tie-break
LIMIT %(limit)s
"""


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_movies(pool: ConnectionPool, q: str, limit: int) -> list[dict]:
    full_query = q.strip().lower()
    year_match = re.fullmatch(r"(.+?)\s+([1-9][0-9]{3})", full_query)
    title = year_match[1] if year_match else full_query
    if len(title) < 2:
        return []
    safe = _escape_like(title)
    params = {
        "q": title,
        "full_query": full_query,
        "prefix": safe + "%",
        "word_prefix": "% " + safe + "%",   # matches "the godfather" for q="god"
        "contains": "%" + safe + "%",
        "limit": limit,
    }
    # A two-letter contains search has no selective interior trigram.
    matches = "lower(title) LIKE %(prefix)s" if len(title) == 2 else "lower(title) LIKE %(contains)s"
    initials_order = ""
    if len(title) == 2 and title.isascii() and title.isalpha():
        matches += " OR lower(title) LIKE %(initials)s"
        params["initials"] = ".".join(title) + ".%"
        initials_order = "(lower(title) LIKE %(initials)s) DESC,"
    if year_match:
        year = int(year_match[2])
        params.update(start=date(year, 1, 1), end=date(year, 12, 31))
        # Keep literal titles ending in a number searchable (e.g. Blade Runner 2049).
        matches = f"lower(title) = %(full_query)s OR (({matches}) AND release_date BETWEEN %(start)s AND %(end)s)"
    with pool.connection() as conn:
        statement = MOVIE_SEARCH_SQL.format(matches=matches, initials_order=initials_order)
        return conn.execute(statement, params).fetchall()


SEARCH_SQL_FAST = """
SELECT t.tag_type, t.name, t.movie_count
FROM unnest(%(types)s::text[]) AS ty(tag_type)
CROSS JOIN LATERAL (
    SELECT tag_type, name, movie_count
    FROM tag_lookup
    WHERE tag_type = ty.tag_type
      AND length(name) BETWEEN 1 AND 100
      AND lower(name) LIKE %(contains)s
    ORDER BY (lower(name) LIKE %(prefix)s) DESC, length(name), name
    LIMIT %(per_type)s
) t
"""

SEARCH_SQL_FUZZY = """
SELECT t.tag_type, t.name, t.movie_count
FROM unnest(%(types)s::text[]) AS ty(tag_type)
CROSS JOIN LATERAL (
    SELECT tag_type, name, movie_count
    FROM tag_lookup
    WHERE tag_type = ty.tag_type
      AND length(name) BETWEEN 1 AND 100
      AND (lower(name) LIKE %(contains)s OR lower(name) %% %(q)s::text)
    ORDER BY (lower(name) LIKE %(prefix)s) DESC,
             similarity(lower(name), %(q)s::text) DESC,
             name
    LIMIT %(per_type)s
) t
"""


def search_tags(pool: ConnectionPool, q: str, type_list: list[str], per_type: int) -> list[dict]:
    q = q.strip().lower()
    if len(q) < 3 and "original_language" not in type_list:
        return []
    safe = _escape_like(q)
    params = {
        "q": q,
        "prefix": safe + "%",
        "contains": "%" + safe + "%",
        "types": type_list,
        "per_type": per_type,
    }
    sql = SEARCH_SQL_FUZZY if len(q) >= 5 else SEARCH_SQL_FAST
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def list_tags(pool: ConnectionPool, tag_type: str) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT tag_type, name, movie_count FROM tag_lookup WHERE tag_type = %s ORDER BY name",
            (tag_type,),
        ).fetchall()


def check_health(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute("SELECT 1")


def filter_vocabulary() -> tuple[list[str], list[str]]:
    with _connection() as conn:
        conn.execute("SET LOCAL statement_timeout = '60s'")
        languages = conn.execute("SELECT DISTINCT original_language FROM movies WHERE original_language IS NOT NULL")
        langs = sorted({r["original_language"].strip().lower() for r in languages if r["original_language"]})
        genres = conn.execute("SELECT DISTINCT unnest(genres) AS g FROM movies WHERE genres IS NOT NULL")
        return langs, sorted({r["g"].strip().lower() for r in genres if r["g"]})


def stream_movie_metadata():
    return catalog_scan(
        "meta_stream", "SELECT id, original_language, release_date, genres FROM movies ORDER BY id"
    )


@contextmanager
def stream_chroma_metadata(database_url: str):
    import psycopg

    with psycopg.connect(database_url) as conn, conn.cursor(name="meta_cur") as cur:
        cur.itersize = 10_000
        cur.execute("SELECT id, original_language, release_date FROM movies")
        yield cur


def thin_overview_ids() -> set[int]:
    with catalog_scan("thin_ids", "SELECT id FROM movies WHERE has_thin_overview") as rows:
        return {row["id"] for row in rows}
