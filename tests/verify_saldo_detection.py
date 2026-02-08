import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.groq_analyzer import is_saldo_update
from ai_helper import _is_wallet_update_context


class SaldoDetectionTests(unittest.TestCase):
    def test_project_expense_with_dompet_is_not_saldo_update(self):
        text = "pembelian alkali untuk wash di project Juanda alky dompet tx sby"
        self.assertFalse(is_saldo_update(text))
        self.assertFalse(_is_wallet_update_context(text))

    def test_explicit_update_still_detected(self):
        text = "update saldo dompet tx sby 10jt"
        self.assertTrue(is_saldo_update(text))
        self.assertTrue(_is_wallet_update_context(text))

    def test_short_dompet_amount_update_detected(self):
        text = "dompet tx sby 10jt"
        self.assertTrue(is_saldo_update(text))
        self.assertTrue(_is_wallet_update_context(text))


if __name__ == "__main__":
    unittest.main()
