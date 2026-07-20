import unittest
from unittest.mock import patch

from config.constants import (
    OPERASIONAL_COLS,
    SPLIT_LAYOUT_DATA_START,
    SPLIT_PEMASUKAN,
    SPLIT_PENGELUARAN,
)
from sheets_helper import _split_append_metadata, append_operational_transaction


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

    def test_operational_append_is_idempotent_by_message_id(self):
        class FakeSheet:
            def __init__(self):
                self.rows = []

            def col_values(self, column):
                if column == OPERASIONAL_COLS["MESSAGE_ID"]:
                    return ["MessageID"] + [row[OPERASIONAL_COLS["MESSAGE_ID"] - 1] for row in self.rows]
                return ["No"] + [str(index) for index, _row in enumerate(self.rows, start=1)]

            def append_row(self, row, value_input_option=None):
                self.rows.append(row)

        sheet = FakeSheet()
        transaction = {
            "jumlah": 450000,
            "keterangan": "Fee Rio sisanya",
            "message_id": "image-1|0",
        }
        with patch("sheets_helper.get_or_create_operational_sheet", return_value=sheet), \
             patch("sheets_helper.invalidate_dashboard_cache"), \
             patch("services.ledger_lock._database_url", return_value=""):
            first = append_operational_transaction(
                transaction, "Admin", "WhatsApp", "CV HB(101)", "Gaji"
            )
            second = append_operational_transaction(
                transaction, "Admin", "WhatsApp", "CV HB(101)", "Gaji"
            )

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(sheet.rows), 1)

    def test_operational_append_mirrors_only_after_sheet_write(self):
        class FakeSheet:
            def col_values(self, column):
                return ["header"]

            def append_row(self, row, value_input_option=None):
                self.row = row

        sheet = FakeSheet()
        transaction = {"jumlah": 450000, "keterangan": "Fee Rio", "message_id": "mirror-1"}
        with patch("sheets_helper.get_or_create_operational_sheet", return_value=sheet), \
             patch("sheets_helper.invalidate_dashboard_cache"), \
             patch("sheets_helper._mirror_financial_ledger") as mirror, \
             patch("services.ledger_lock._database_url", return_value=""):
            append_operational_transaction(transaction, "Admin", "WhatsApp", "CV HB(101)", "Gaji")

        mirror.assert_called_once()
        row = mirror.call_args.args[0]
        self.assertEqual(row["source_block"], "operasional")
        self.assertEqual(row["sheet_name"], "Operasional Kantor")
        self.assertEqual(row["message_id"], "mirror-1")

    def test_operational_failure_is_queued_and_never_reports_success(self):
        class FailingSheet:
            def col_values(self, column):
                return ["header"]

            def append_row(self, row, value_input_option=None):
                raise TimeoutError("sheets timeout")

        transaction = {
            "jumlah": 450000,
            "keterangan": "Fee Rio sisanya",
            "message_id": "image-fail|0",
        }
        with patch("sheets_helper.get_or_create_operational_sheet", return_value=FailingSheet()), \
             patch("sheets_helper.add_to_retry_queue", return_value="queue-1") as queue, \
             patch("services.ledger_lock._database_url", return_value=""):
            with self.assertRaises(TimeoutError):
                append_operational_transaction(
                    transaction, "Admin", "WhatsApp", "CV HB(101)", "Gaji"
                )

        queue.assert_called_once()
        self.assertEqual(queue.call_args.args[1]["write_kind"], "operational")


if __name__ == "__main__":
    unittest.main()
