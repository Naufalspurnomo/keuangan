import unittest

import sheets_helper as sheets


class _Cell:
    def __init__(self, value):
        self.value = value


class _FakeWorksheet:
    def __init__(self):
        self.row_count = 2
        self.col_count = 1
        self.cells = {}

    def add_rows(self, count):
        self.row_count += count

    def add_cols(self, count):
        self.col_count += count

    def update_cell(self, row, col, value):
        self.cells[(row, col)] = value

    def cell(self, row, col):
        return _Cell(self.cells.get((row, col), ""))

    def get(self, range_name):
        start = int(range_name.split(":")[0][1:])
        end = int(range_name.split(":")[1][1:])
        return [[self.cells.get((row, 1), "")] for row in range(start, end + 1)]


class SheetsStatePersistenceTests(unittest.TestCase):
    def test_chunked_state_round_trip_with_checksum(self):
        ws = _FakeWorksheet()
        original_limit = sheets.STATE_CELL_LIMIT
        sheets.STATE_CELL_LIMIT = 10
        try:
            payload = '{"data":"' + ("x" * 50) + '"}'

            sheets._write_chunked_state(ws, payload)
            loaded = sheets._read_chunked_state(ws)

            self.assertEqual(loaded, payload)
            self.assertEqual(ws.cell(1, 1).value, sheets.STATE_CHUNK_MARKER)
            self.assertGreater(int(ws.cell(2, 1).value), 1)
        finally:
            sheets.STATE_CELL_LIMIT = original_limit

    def test_chunked_state_rejects_checksum_mismatch(self):
        ws = _FakeWorksheet()
        sheets._write_chunked_state(ws, '{"ok": true}')
        ws.update_cell(3, 1, '{"ok": false}')

        self.assertIsNone(sheets._read_chunked_state(ws))


if __name__ == "__main__":
    unittest.main()
