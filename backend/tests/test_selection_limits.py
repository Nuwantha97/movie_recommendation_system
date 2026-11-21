import unittest

from pydantic import ValidationError

from app.schemas import RecommendRequest


class TestSelectionLimits(unittest.TestCase):
    def test_each_limit_is_inclusive_and_independent(self):
        data = {
            "movie_ids": list(range(1, 11)),
            "tags": [{"tag_type": "keywords", "name": f"tag {i}"} for i in range(20)],
            "genres": [f"genre {i}" for i in range(6)],
            "original_language": ["en", "fr", "de", "ja", "si", "ta", "it", "hi", "ko", "es"],
        }
        RecommendRequest.model_validate(data)
        for field, items in data.items():
            with self.subTest(field=field), self.assertRaises(ValidationError) as error:
                RecommendRequest.model_validate({**data, field: [*items, items[0]]})
            self.assertEqual(error.exception.errors()[0]["loc"], (field,))
