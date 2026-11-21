from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from app.db import queries
from app.db.pool import get_pool

router = APIRouter(prefix="/tags", tags=["tags"])

VALID_TYPES = {
    "genres", "original_language", "cast_members", "director",
    "writers", "producers", "music_composer", "keywords",
    "production_countries", "spoken_languages",
}
STATIC_TYPES = {"genres", "original_language"}


class TagOut(BaseModel):
    tag_type: str
    name: str
    movie_count: int  # display only


def _parse_types(types: str) -> list[str]:
    parsed = [t.strip() for t in types.split(",") if t.strip()]
    bad = [t for t in parsed if t not in VALID_TYPES]
    if not parsed or bad:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid tag type(s): {bad or 'none given'}. Allowed: {sorted(VALID_TYPES)}",
        )
    return parsed


@router.get("/search", response_model=list[TagOut])
def search_tags(
    q: str = Query(..., max_length=100),
    types: str = Query(..., description="comma-separated tag types"),
    per_type: int = Query(4, ge=1, le=20),
    pool: ConnectionPool = Depends(get_pool),
):
    return queries.search_tags(pool, q, _parse_types(types), per_type)


_static_cache: dict[str, list[dict]] = {}


@router.get("/all", response_model=list[TagOut])
def all_tags(
    tag_type: str = Query(...),
    pool: ConnectionPool = Depends(get_pool),
):
    if tag_type not in STATIC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"'{tag_type}' is too large to list. Static types: {sorted(STATIC_TYPES)}",
        )
    if tag_type not in _static_cache:
        _static_cache[tag_type] = queries.list_tags(pool, tag_type)
    return _static_cache[tag_type]
