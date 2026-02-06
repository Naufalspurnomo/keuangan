import unittest
from unittest.mock import patch

from utils.lifecycle import apply_lifecycle_markers


class LifecycleMarkerTests(unittest.TestCase):
    @patch("utils.lifecycle.get_existing_projects", return_value=set())
    def test_new_project_pengeluaran_gets_start_marker(self, _mock_projects):
        result = apply_lifecycle_markers(
            project_name="Taman Indah",
            transaction={"tipe": "Pengeluaran", "keterangan": "Beli cat"},
            is_new_project=True,
            allow_finish=True,
        )
        self.assertEqual(result, "Taman Indah (Start)")

    @patch("utils.lifecycle.get_existing_projects", return_value={"Taman Indah"})
    def test_finish_marker_replaces_start_suffix(self, _mock_projects):
        result = apply_lifecycle_markers(
            project_name="Taman Indah (Start)",
            transaction={"tipe": "Pemasukan", "keterangan": "Pelunasan termin akhir"},
            is_new_project=False,
            allow_finish=True,
        )
        self.assertEqual(result, "Taman Indah (Finish)")

    @patch("utils.lifecycle.get_existing_projects", return_value={"Taman Indah"})
    def test_existing_project_without_finish_keeps_name(self, _mock_projects):
        result = apply_lifecycle_markers(
            project_name="Taman Indah",
            transaction={"tipe": "Pemasukan", "keterangan": "DP"},
            is_new_project=False,
            allow_finish=True,
        )
        self.assertEqual(result, "Taman Indah")


if __name__ == "__main__":
    unittest.main()
