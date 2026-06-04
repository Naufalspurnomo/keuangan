import unittest
from unittest.mock import patch

import sheets_helper as sheets


class _FakeWorksheet:
    def __init__(self):
        self.get_all_values_calls = 0
        self.col_values_calls = 0

    def get_all_values(self):
        self.get_all_values_calls += 1
        return []

    def col_values(self, _column):
        self.col_values_calls += 1
        return []


class _FailingWorksheet(_FakeWorksheet):
    def __init__(self, *, fail_get_all_values=False, fail_col_values=False):
        super().__init__()
        self.fail_get_all_values = fail_get_all_values
        self.fail_col_values = fail_col_values

    def get_all_values(self):
        self.get_all_values_calls += 1
        if self.fail_get_all_values:
            raise RuntimeError("read failed")
        return []

    def col_values(self, _column):
        self.col_values_calls += 1
        if self.fail_col_values:
            raise RuntimeError("read failed")
        return []


class _FakeSpreadsheet:
    def __init__(self):
        self.worksheets = {}

    def worksheet(self, name):
        worksheet = self.worksheets.get(name)
        if worksheet is None:
            worksheet = _FakeWorksheet()
            self.worksheets[name] = worksheet
        return worksheet


class SheetsCacheTests(unittest.TestCase):
    def setUp(self):
        self._old_all_data_cache = dict(sheets._all_data_cache)
        self._old_wallet_cache = sheets._wallet_balances_cache
        self._old_wallet_cache_at = sheets._wallet_balances_cache_at
        sheets._all_data_cache.clear()
        sheets._wallet_balances_cache = None
        sheets._wallet_balances_cache_at = 0

    def tearDown(self):
        sheets._all_data_cache.clear()
        sheets._all_data_cache.update(self._old_all_data_cache)
        sheets._wallet_balances_cache = self._old_wallet_cache
        sheets._wallet_balances_cache_at = self._old_wallet_cache_at

    def test_get_all_data_reuses_cache_until_invalidated(self):
        spreadsheet = _FakeSpreadsheet()

        with patch.object(sheets, "get_spreadsheet", lambda: spreadsheet):
            self.assertEqual(sheets.get_all_data(days=2), [])
            calls_after_first = sum(w.get_all_values_calls for w in spreadsheet.worksheets.values())

            self.assertEqual(sheets.get_all_data(days=2), [])
            calls_after_second = sum(w.get_all_values_calls for w in spreadsheet.worksheets.values())

            sheets.invalidate_dashboard_cache()
            self.assertEqual(sheets.get_all_data(days=2), [])
            calls_after_invalidate = sum(w.get_all_values_calls for w in spreadsheet.worksheets.values())

        self.assertGreater(calls_after_first, 0)
        self.assertEqual(calls_after_second, calls_after_first)
        self.assertGreater(calls_after_invalidate, calls_after_second)

    def test_get_all_data_does_not_cache_partial_reads(self):
        spreadsheet = _FakeSpreadsheet()
        failing_dompet = sheets.DOMPET_SHEETS[0]
        failing_sheet = _FailingWorksheet(fail_get_all_values=True)
        spreadsheet.worksheets[failing_dompet] = failing_sheet

        with patch.object(sheets, "get_spreadsheet", lambda: spreadsheet):
            self.assertEqual(sheets.get_all_data(days=2), [])
            self.assertEqual(sheets.get_all_data(days=2), [])

        self.assertEqual(failing_sheet.get_all_values_calls, 2)

    def test_get_wallet_balances_reuses_cache_until_invalidated(self):
        dompet_sheets = {dompet: _FakeWorksheet() for dompet in sheets.DOMPET_SHEETS}
        operational = _FakeWorksheet()
        hutang = _FakeWorksheet()

        with patch.object(sheets, "get_dompet_sheet", lambda dompet: dompet_sheets[dompet]), \
             patch.object(sheets, "get_or_create_operational_sheet", lambda: operational), \
             patch.object(sheets, "get_or_create_hutang_sheet", lambda: hutang):
            first = sheets.get_wallet_balances()
            calls_after_first = sum(w.col_values_calls for w in dompet_sheets.values())

            second = sheets.get_wallet_balances()
            calls_after_second = sum(w.col_values_calls for w in dompet_sheets.values())

            sheets.invalidate_dashboard_cache()
            third = sheets.get_wallet_balances()
            calls_after_invalidate = sum(w.col_values_calls for w in dompet_sheets.values())

        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertGreater(calls_after_first, 0)
        self.assertEqual(calls_after_second, calls_after_first)
        self.assertGreater(calls_after_invalidate, calls_after_second)

    def test_get_wallet_balances_does_not_cache_partial_reads(self):
        failing_dompet = sheets.DOMPET_SHEETS[0]
        dompet_sheets = {dompet: _FakeWorksheet() for dompet in sheets.DOMPET_SHEETS}
        dompet_sheets[failing_dompet] = _FailingWorksheet(fail_col_values=True)
        operational = _FakeWorksheet()
        hutang = _FakeWorksheet()

        with patch.object(sheets, "get_dompet_sheet", lambda dompet: dompet_sheets[dompet]), \
             patch.object(sheets, "get_or_create_operational_sheet", lambda: operational), \
             patch.object(sheets, "get_or_create_hutang_sheet", lambda: hutang):
            sheets.get_wallet_balances()
            sheets.get_wallet_balances()

        self.assertEqual(dompet_sheets[failing_dompet].col_values_calls, 2)


if __name__ == "__main__":
    unittest.main()
