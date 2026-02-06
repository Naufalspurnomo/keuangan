import unittest

from utils.wallet_updates import (
    compute_balance_adjustment,
    is_absolute_balance_update,
    pick_wallet_target_amount,
)


class WalletUpdateHelperTests(unittest.TestCase):
    def test_detect_absolute_balance_update(self):
        self.assertTrue(is_absolute_balance_update("update saldo dompet tx sby 10jt"))
        self.assertTrue(is_absolute_balance_update("set saldo cv hb jadi 15jt"))
        self.assertTrue(is_absolute_balance_update("saldo awal dompet tx bali 8jt"))
        self.assertTrue(is_absolute_balance_update("samakan saldo dompet cv hb 5jt"))

    def test_detect_delta_update_is_not_absolute(self):
        self.assertFalse(is_absolute_balance_update("isi dompet tx sby 2jt"))
        self.assertFalse(is_absolute_balance_update("topup dompet cv hb 500rb"))
        self.assertFalse(is_absolute_balance_update("transfer ke dompet tx bali 1jt"))

    def test_pick_wallet_target_amount(self):
        txs = [
            {"jumlah": 2500},
            {"jumlah": 10000000},
            {"jumlah": 7500000},
        ]
        self.assertEqual(pick_wallet_target_amount(txs), 10000000)

    def test_compute_balance_adjustment_increase(self):
        adj = compute_balance_adjustment(current_balance=3000000, target_balance=10000000)
        self.assertEqual(adj["delta"], 7000000)
        self.assertEqual(adj["amount"], 7000000)
        self.assertEqual(adj["tipe"], "Pemasukan")

    def test_compute_balance_adjustment_decrease(self):
        adj = compute_balance_adjustment(current_balance=12000000, target_balance=10000000)
        self.assertEqual(adj["delta"], -2000000)
        self.assertEqual(adj["amount"], 2000000)
        self.assertEqual(adj["tipe"], "Pengeluaran")

    def test_compute_balance_adjustment_no_change(self):
        adj = compute_balance_adjustment(current_balance=5000000, target_balance=5000000)
        self.assertEqual(adj["delta"], 0)
        self.assertEqual(adj["amount"], 0)
        self.assertEqual(adj["tipe"], "")


if __name__ == "__main__":
    unittest.main()
