import unittest
from unittest.mock import patch

from app.stores import meta_index


class TestGenreLimit(unittest.TestCase):
    def test_genre_limit_exceeded(self):
        # Create 33 mock genres
        mock_genres = [f"genre_{i}" for i in range(33)]

        with patch.object(meta_index.queries, "filter_vocabulary", return_value=(["en"], mock_genres)):
            with self.assertRaises(RuntimeError) as ctx:
                meta_index.load_index()

            self.assertIn("exceeding the 32-genre limit of uint32 bitmask", str(ctx.exception))
            self.assertIn("33 distinct genres", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
