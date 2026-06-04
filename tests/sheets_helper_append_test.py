import unittest

from config.constants import SPLIT_LAYOUT_DATA_START, SPLIT_PEMASUKAN, SPLIT_PENGELUARAN
from sheets_helper import _split_append_metadata


class SheetsHelperAppendTests(unittest.TestCase):
    def test_split_append_metadata_uses_first_empty_row_in_selected_block(self):
        rows = [
            ["1", "", "", "", "", "", "", "", "msg-in-1", "1", "", "", "", "", "", "", "", "msg-out-1"],
            ["", "", "", "", "", "", "", "", "", "2", "", "", "", "", "", "", "", "msg-out-2"],
            ["3", "", "", "", "", "", "", "", "msg-in-3"],
        ]

        next_row, entry_count, existing_ids = _split_append_metadata(
            rows,
            SPLIT_PEMASUKAN["NO"],
            SPLIT_PEMASUKAN["MESSAGE_ID"],
        )

        self.assertEqual(next_row, SPLIT_LAYOUT_DATA_START + 1)
        self.assertEqual(entry_count, 2)
        self.assertEqual(existing_ids, {"msg-in-1", "msg-in-3"})

    def test_split_append_metadata_is_scoped_to_selected_message_id_column(self):
        rows = [
            ["1", "", "", "", "", "", "", "", "msg-in-1", "1", "", "", "", "", "", "", "", "msg-out-1"],
        ]

        _, _, existing_ids = _split_append_metadata(
            rows,
            SPLIT_PENGELUARAN["NO"],
            SPLIT_PENGELUARAN["MESSAGE_ID"],
        )

        self.assertEqual(existing_ids, {"msg-out-1"})


if __name__ == "__main__":
    unittest.main()
