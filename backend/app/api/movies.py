import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from app.db import queries
from app.db.pool import get_pool

router = APIRouter(prefix="/movies", tags=["movies"])


class MovieHit(BaseModel):
    id: int
    title: str
    year: int | None = None
    poster_path: str | None = None


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


@router.get("/search", response_model=list[MovieHit])
def search_movies(
    q: str = Query(..., max_length=100),
    limit: int = Query(20, ge=1, le=25),
    pool: ConnectionPool = Depends(get_pool),
):
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

@router.get('/{movie_id}', response_model=dict)
def get_movie(movie_id: int = Path(..., ge=1)):
    movies = queries.get_movies([movie_id])
    if movie_id not in movies:
        raise HTTPException(status_code=404, detail='Movie not found')
    return movies[movie_id]
