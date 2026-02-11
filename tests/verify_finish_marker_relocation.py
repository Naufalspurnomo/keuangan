import unittest
from unittest.mock import patch

import sheets_helper
from config.constants import SPLIT_PEMASUKAN, SPLIT_PENGELUARAN


class _FakeSheet:
    def __init__(self, in_projects, out_projects):
        self._in_projects = in_projects
        self._out_projects = out_projects

    def col_values(self, col_idx):
        if col_idx == SPLIT_PEMASUKAN["PROJECT"]:
            return list(self._in_projects)
        if col_idx == SPLIT_PENGELUARAN["PROJECT"]:
            return list(self._out_projects)
        return []

    def update_cells(self, cell_list, value_input_option="USER_ENTERED"):
        for cell in cell_list:
            row_idx = int(cell.row) - 1
            if cell.col == SPLIT_PEMASUKAN["PROJECT"]:
                self._in_projects[row_idx] = cell.value
            elif cell.col == SPLIT_PENGELUARAN["PROJECT"]:
                self._out_projects[row_idx] = cell.value


class FinishMarkerRelocationTests(unittest.TestCase):
    def test_moves_old_finish_marker_to_latest_row(self):
        # Row 9 = old finish, Row 11 = latest finish (must stay)
        in_projects = [""] * 20
        out_projects = [""] * 20
        in_projects[8] = "Ancaksari Bali (Finish)"
        in_projects[10] = "Ancaksari Bali (Finish)"
        fake_sheet = _FakeSheet(in_projects, out_projects)

        with patch("sheets_helper.get_dompet_sheet", return_value=fake_sheet):
            updated = sheets_helper.move_finish_marker_to_latest(
                dompet_sheet="TX BALI(087)",
                project_name="Ancaksari Bali (Finish)",
                keep_row=11,
                keep_tipe="Pemasukan",
            )

        self.assertEqual(updated, 1)
        self.assertEqual(fake_sheet._in_projects[8], "Ancaksari Bali")
        self.assertEqual(fake_sheet._in_projects[10], "Ancaksari Bali (Finish)")

    def test_no_update_when_project_is_not_finish_marker(self):
        in_projects = [""] * 20
        out_projects = [""] * 20
        in_projects[8] = "Ancaksari Bali (Finish)"
        fake_sheet = _FakeSheet(in_projects, out_projects)

        with patch("sheets_helper.get_dompet_sheet", return_value=fake_sheet):
            updated = sheets_helper.move_finish_marker_to_latest(
                dompet_sheet="TX BALI(087)",
                project_name="Ancaksari Bali",
                keep_row=9,
                keep_tipe="Pemasukan",
            )

        self.assertEqual(updated, 0)
        self.assertEqual(fake_sheet._in_projects[8], "Ancaksari Bali (Finish)")


if __name__ == "__main__":
    unittest.main()
