import unittest

from sheets_helper import _parse_amount


class SheetsAmountParsingTests(unittest.TestCase):
    def test_suffix_amounts_are_supported(self):
        self.assertEqual(_parse_amount("100rb"), 100_000)
        self.assertEqual(_parse_amount("1,5jt"), 1_500_000)

    def test_locale_separators_are_not_concatenated_as_digits(self):
        self.assertEqual(_parse_amount("480,000.00"), 480_000)
        self.assertEqual(_parse_amount("480.000,00"), 480_000)

    def test_malformed_amount_is_rejected(self):
        self.assertEqual(_parse_amount("not-an-amount"), 0)


if __name__ == "__main__":
    unittest.main()
