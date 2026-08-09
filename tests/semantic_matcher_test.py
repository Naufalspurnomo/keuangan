import unittest

from utils.semantic_matcher import find_matching_item


class SemanticMatcherTests(unittest.TestCase):
    def test_single_item_without_hint_is_selected(self):
        item = {"keterangan": "DP workshop", "jumlah": 500000}

        result = find_matching_item([item], None, None)

        self.assertEqual(result["matched_item"], item)
        self.assertEqual(result["method"], "single_item")

    def test_empty_items_returns_no_match(self):
        self.assertIsNone(find_matching_item([], "dp", 500000))

    def test_malformed_items_are_ignored(self):
        self.assertIsNone(find_matching_item([None, "bad", 42], "dp", 500000))


if __name__ == "__main__":
    unittest.main()
