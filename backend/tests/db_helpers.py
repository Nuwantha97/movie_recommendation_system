"""Database queries used exclusively by backend tests and benchmarks."""

from app.db.queries import Filters, catalog_scan, filtered_movie_query


def matching_movie_ids(f: Filters) -> set[int]:
    statement, params = filtered_movie_query("SELECT id FROM movies", f)
    with catalog_scan("matching_ids", statement, params) as rows:
        return {int(row["id"]) for row in rows}


def count_matches(f: Filters) -> int:
    statement, params = filtered_movie_query("SELECT count(*) FROM movies", f)
    with catalog_scan("matching_count", statement, params) as rows:
        return rows.fetchone()["count"]


def stream_overviews():
    return catalog_scan("overview_stream", "SELECT id, overview, has_thin_overview FROM movies")


def chroma_segment_id(conn, collection: str) -> str | None:
    row = conn.execute(
        "SELECT s.id FROM segments s JOIN collections c ON s.collection = c.id "
        "WHERE c.name = ? AND s.type = 'urn:chroma:segment/vector/hnsw-local-persisted'",
        (collection,),
    ).fetchone()
    return row[0] if row else None


def chroma_collection_schemas(conn):
    return conn.execute("SELECT name, schema_str FROM collections").fetchall()


def chroma_collections(conn):
    return conn.execute("SELECT id, name FROM collections").fetchall()


def rename_chroma_collection(conn, old_name: str, new_name: str) -> None:
    conn.execute("UPDATE collections SET name = ? WHERE name = ?", (new_name, old_name))
