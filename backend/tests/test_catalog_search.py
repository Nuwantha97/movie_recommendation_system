import unittest

from app.api.movies import search_movies
from app.db.pool import close_pool, open_pool
from app.schemas import RecommendRequest
from app.services.recommender import retrieve_and_rank


class TestCatalogSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = open_pool()
        cls.addClassCleanup(close_pool)

    def test_title_and_optional_year(self):
        cases = (
            ("Up", "Up", 2009), (" Up   2009 ", "Up", 2009),
            ("inception 2010", "Inception", 2010),
            ("AI 2001", "A.I. Artificial Intelligence", 2001),
            ("Blade Runner 2049", "Blade Runner 2049", 2017),
        )
        for query, title, year in cases:
            with self.subTest(query=query):
                rows = search_movies(q=query, limit=20, pool=self.pool)
                self.assertIn((title, year), [(r["title"], r["year"]) for r in rows])
                if query.strip().endswith(("2001", "2009", "2010")):
                    self.assertEqual((rows[0]["title"], rows[0]["year"]), (title, year))
                    self.assertTrue(all(r["year"] == year for r in rows))
        for query in ("U", " U 2009 "):
            self.assertEqual(search_movies(q=query, limit=20, pool=self.pool), [])

    def test_catalog_only_director_respects_filters(self):
        tag = {"tag_type": "director", "name": "강경화"}
        matches = retrieve_and_rank(RecommendRequest(tags=[tag]))["ranked"]
        movie = next(r for r in matches if r["movie_id"] == 1115566)
        self.assertEqual(movie["tag_score"], 1)
        self.assertIsNone(movie["plot_score"])
        filtered = RecommendRequest(tags=[tag], original_language=["en"])
        self.assertNotIn(1115566, [r["movie_id"] for r in retrieve_and_rank(filtered)["ranked"]])
