import asyncio
import unittest
from collections import defaultdict
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class TestExplanationPages(unittest.TestCase):
    def test_allowed_origin_can_read_overlapping_custom_pages(self):
        entry = {
            "ranked": [{"movie_id": i} for i in range(12)],
            "explanations": {}, "locks": defaultdict(asyncio.Lock),
            "query": None, "req": None,
        }
        url = "/api/recommend/custom-test/explanations"
        client = TestClient(app, base_url="http://localhost")
        self.addCleanup(client.close)
        preflight = client.options(url, headers={
            "Origin": settings.cors_origins[0],
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "cache-control,pragma",
        })
        self.assertEqual(preflight.status_code, 200)

        def explain(rows, *_):
            return {r["movie_id"]: str(r["movie_id"]) for r in rows}

        with (
            patch("app.api.recommend.paging.get", return_value=entry),
            patch("app.api.recommend.queries.get_movies", side_effect=lambda ids: dict.fromkeys(ids)),
            patch("app.api.recommend.explain.explain", new_callable=AsyncMock, side_effect=explain) as llm,
        ):
            for offset in (5, 7):
                response = client.get(url, params={"offset": offset, "limit": 5})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["explanations"], {str(i): str(i) for i in range(offset, offset + 5)})
            self.assertEqual([len(call.args[0]) for call in llm.await_args_list], [5, 2])
