import unittest

from ai_helper import _enforce_transaction_type_semantics
from utils.lifecycle import apply_lifecycle_markers


class ProjectLifecycleSemanticsTests(unittest.TestCase):
    def test_existing_start_marker_is_not_reused(self):
        result = apply_lifecycle_markers(
            "Bu Mimin (Start)",
            {"tipe": "Pengeluaran", "keterangan": "material tambahan"},
            is_new_project=False,
        )

        self.assertEqual(result, "Bu Mimin")

    def test_project_pelunasan_is_income_and_can_finish(self):
        transaction = {
            "tipe": "Pengeluaran",
            "keterangan": "pelunasan 2 pilar 2.016.000 projek bu mimin",
        }

        _enforce_transaction_type_semantics(
            transaction,
            transaction["keterangan"],
        )

        self.assertEqual(transaction["tipe"], "Pemasukan")
        self.assertEqual(
            apply_lifecycle_markers(
                "Bu Mimin",
                transaction,
                is_new_project=False,
            ),
            "Bu Mimin (Selesai)",
        )

    def test_vendor_debt_payment_stays_expense(self):
        transaction = {
            "tipe": "Pengeluaran",
            "keterangan": "bayar pelunasan hutang ke vendor projek bu mimin",
        }

        _enforce_transaction_type_semantics(
            transaction,
            transaction["keterangan"],
        )

        self.assertEqual(transaction["tipe"], "Pengeluaran")


if __name__ == "__main__":
    unittest.main()
