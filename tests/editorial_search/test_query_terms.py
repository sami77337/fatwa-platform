import unittest

from apps.editorial_search.query_terms import normalize_editorial_search
from apps.reference.normalization import normalize_title


class EditorialSearchAliasTests(unittest.TestCase):
    def test_without_paraphrase(self):
        self.assertEqual(normalize_editorial_search("بلا مقطع"), "بلا مقطع")
        self.assertEqual(normalize_editorial_search("بدون مقطع"), "بلا مقطع")
        self.assertEqual(normalize_editorial_search("نصّ بِدُون مقطع"), "نص بلا مقطع")

    def test_other_dun_is_not_silently_rewritten(self):
        self.assertEqual(normalize_editorial_search("عدد دون عشرين"), "عدد دون عشرين")
        self.assertEqual(normalize_editorial_search("تدوين مقطع"), "تدوين مقطع")

    def test_existing_catalog_title_normalization_stays_unchanged(self):
        self.assertEqual(normalize_title("بدون مقطع"), "بدون مقطع")


if __name__ == "__main__":
    unittest.main()
