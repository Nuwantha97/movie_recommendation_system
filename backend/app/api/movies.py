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


@router.get("/search", response_model=list[MovieHit])
def search_movies(
    q: str = Query(..., max_length=100),
    limit: int = Query(20, ge=1, le=25),
    pool: ConnectionPool = Depends(get_pool),
):
    return queries.search_movies(pool, q, limit)


@router.get('/{movie_id}', response_model=dict)
def get_movie(movie_id: int = Path(..., ge=1)):
    movies = queries.get_movies([movie_id])
    if movie_id not in movies:
        raise HTTPException(status_code=404, detail='Movie not found')
    return movies[movie_id]
