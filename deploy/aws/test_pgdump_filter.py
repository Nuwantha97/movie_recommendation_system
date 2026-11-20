import io
import unittest
from pgdump_filter import filter_lines


class FilterTests(unittest.TestCase):
    def pipe(self, lines: bytes):
        dest = io.BytesIO()
        filter_lines(io.BytesIO(lines), dest)
        return dest.getvalue()

    def test_removes_roles_but_not_copy_data(self):
        original = (b'-- PostgreSQL database dump\n'
                    b'ALTER TABLE public.movies OWNER TO postgres;\n'
                    b'GRANT SELECT ON TABLE public.movies TO old_user;\n'
                    b'COPY public.movies (title) FROM stdin;\n'
                    b'GRANT is a film title\n'
                    b'\\.\n'
                    b'SELECT 1;\n')
        filtered = self.pipe(original)
        self.assertNotIn(b'OWNER TO postgres', filtered)
        self.assertNotIn(b'TO old_user', filtered)
        self.assertIn(b'GRANT is a film title', filtered)
        self.assertIn(b'SELECT 1', filtered)

    def test_disallows_cross_database_restore(self):
        with self.assertRaises(ValueError):
            self.pipe(b'CREATE DATABASE other;\n')
        with self.assertRaises(ValueError):
            self.pipe(b'\\connect other\n')

    def test_allows_postgres_18_restrict(self):
        self.assertEqual(self.pipe(b'\\restrict abcd\nSELECT 1;\n\\unrestrict abcd\n'),
                         b'\\restrict abcd\nSELECT 1;\n\\unrestrict abcd\n')


if __name__ == '__main__':
    unittest.main()
