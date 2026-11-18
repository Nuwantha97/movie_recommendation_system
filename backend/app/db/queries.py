from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from psycopg import sql
from app.db.pool import current_pool                                    # CHANGED

from psycopg.rows import dict_row

POST_FILTER_BATCH = 5000


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


def gate_ids(f: Filters, limit: int) -> list[int]:
    """Filtered ids, unordered. Caller passes EXACT_LIMIT + 1."""
    clauses, params = _where(f)
    sql = "SELECT id FROM movies"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " LIMIT %s"
    with current_pool().connection() as conn:                           # CHANGED
        rows = conn.execute(sql, [*params, limit]).fetchall()
    return [int(r["id"]) for r in rows]                                 # CHANGED


def filter_ids(ids: list[int], f: Filters) -> set[int]:
    """Subset of ids that satisfy the filters (same _where as the gate)."""
    if not ids:
        return set()
    clauses, params = _where(f)
    where = " AND ".join(["id = ANY(%s)", *clauses])
    keep: set[int] = set()
    with current_pool().connection() as conn:                           # CHANGED
        for i in range(0, len(ids), POST_FILTER_BATCH):
            chunk = ids[i:i + POST_FILTER_BATCH]
            rows = conn.execute(f"SELECT id FROM movies WHERE {where}",
                                [chunk, *params]).fetchall()
            keep.update(int(r["id"]) for r in rows)                     # CHANGED
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
    hits = {}
    with current_pool().connection() as conn:
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
    with current_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
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
