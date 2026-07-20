import unittest

from services.ledger_store import build_source_key, normalize_row


class LedgerStoreNormalizationTests(unittest.TestCase):
    def test_message_id_is_idempotent_per_sheet_block(self):
        base = {"sheet_name": "CV HB(101)", "message_id": "event-1|0"}
        incoming = build_source_key({**base, "source_block": "pemasukan"})
        outgoing = build_source_key({**base, "source_block": "pengeluaran"})

        self.assertNotEqual(incoming, outgoing)
        self.assertEqual(incoming, build_source_key({**base, "source_block": "pemasukan"}))

    def test_historical_row_without_message_id_stays_distinct_by_source_position(self):
        base = {
            "sheet_name": "TX SBY(216)",
            "source_block": "pengeluaran",
            "tanggal": "2026-07-20",
            "jumlah": "480.000",
            "keterangan": "Material",
            "nama_projek": "Rumah A",
        }
        self.assertNotEqual(
            build_source_key({**base, "sheet_row": 10}),
            build_source_key({**base, "sheet_row": 11}),
        )

    def test_normalize_preserves_invalid_historical_row_for_audit(self):
        normalized = normalize_row({
            "sheet_name": "CV HB(101)",
            "sheet_row": 9,
            "source_block": "pengeluaran",
            "tanggal": "manual edit",
            "jumlah": "not-a-number",
            "tipe": "Pengeluaran",
        })

        self.assertFalse(normalized["is_valid"])
        self.assertIsNone(normalized["amount"])
        self.assertIsNone(normalized["transaction_date"])


if __name__ == "__main__":
    unittest.main()
