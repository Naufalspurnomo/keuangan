import unittest

from utils.lifecycle import (
    apply_lifecycle_markers,
    has_finish_marker,
    select_start_marker_indexes,
)


class LifecycleTests(unittest.TestCase):
    def test_existing_project_income_does_not_auto_start(self):
        result = apply_lifecycle_markers(
            "Project Lama",
            {"tipe": "Pemasukan", "keterangan": "DP tahap dua"},
            is_new_project=False,
        )

        self.assertEqual(result, "Project Lama")

    def test_confirmed_new_project_gets_single_start_per_batch(self):
        transactions = [
            {"nama_projek": "Project Baru", "tipe": "Pengeluaran"},
            {"nama_projek": "Project Baru", "tipe": "Pemasukan"},
        ]
        start_indexes = select_start_marker_indexes(transactions)

        names = [
            apply_lifecycle_markers(
                tx["nama_projek"],
                tx,
                is_new_project=True,
                allow_start=idx in start_indexes,
            )
            for idx, tx in enumerate(transactions)
        ]

        self.assertEqual(start_indexes, {1})
        self.assertEqual(names, ["Project Baru", "Project Baru (Start)"])

    def test_finish_marker_uses_selesai_and_supports_legacy_finish(self):
        result = apply_lifecycle_markers(
            "Project Lama (Start)",
            {"tipe": "Pemasukan", "keterangan": "pelunasan client"},
        )

        self.assertEqual(result, "Project Lama (Selesai)")
        self.assertTrue(has_finish_marker(result))
        self.assertTrue(has_finish_marker("Project Lama (Finish)"))


if __name__ == "__main__":
    unittest.main()