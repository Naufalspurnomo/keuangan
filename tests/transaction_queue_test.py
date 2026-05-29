import unittest

from services.transaction_queue import (
    first_missing_amount_tx,
    merge_transaction_queue,
    normalize_amount,
)


class TransactionQueueTest(unittest.TestCase):
    def test_merge_drops_exact_duplicate(self):
        tx = {
            "tipe": "Pengeluaran",
            "keterangan": "Beli semen",
            "nama_projek": "Project A",
            "kategori": "Material",
            "jumlah": 150000,
        }

        merged, meta = merge_transaction_queue([tx], [dict(tx)])

        self.assertEqual(len(merged), 1)
        self.assertEqual(meta["duplicates"], 1)
        self.assertEqual(meta["added"], 0)

    def test_merge_upgrades_missing_amount_for_same_content(self):
        existing = {
            "tipe": "Pengeluaran",
            "keterangan": "Beli semen",
            "nama_projek": "Project A",
            "kategori": "Material",
            "jumlah": 0,
        }
        incoming = dict(existing, jumlah=175000)

        merged, meta = merge_transaction_queue([existing], [incoming])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["jumlah"], 175000)
        self.assertEqual(meta["upgraded"], 1)

    def test_first_missing_amount_detects_flag_or_zero(self):
        txs = [
            {"keterangan": "valid", "jumlah": 1000},
            {"keterangan": "missing", "jumlah": 0},
        ]

        self.assertEqual(first_missing_amount_tx(txs)["keterangan"], "missing")

    def test_normalize_amount_accepts_rupiah_text(self):
        self.assertEqual(normalize_amount("Rp 1.250.000"), 1250000)


if __name__ == "__main__":
    unittest.main()
