import os
import sys
import unittest
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import state_manager as sm


class StateManagerPendingGuardsTests(unittest.TestCase):
    def setUp(self):
        self._original_pending = dict(sm._pending_transactions)
        sm._pending_transactions.clear()

    def tearDown(self):
        sm._pending_transactions.clear()
        sm._pending_transactions.update(self._original_pending)

    def test_set_pending_transaction_rejects_non_string_key(self):
        bad_key = lambda: None
        sm.set_pending_transaction(bad_key, {"transactions": []})
        self.assertEqual(sm._pending_transactions, {})

    def test_get_pending_transactions_rejects_invalid_key(self):
        self.assertIsNone(sm.get_pending_transactions(None))
        self.assertIsNone(sm.get_pending_transactions(""))

    def test_find_pending_by_bot_msg_skips_and_cleans_invalid_key(self):
        bad_key = lambda: None
        good_key = "123@g.us:628123"
        sm._pending_transactions[bad_key] = {
            "bot_msg_id": "bad-bot-msg",
            "created_at": datetime.now(),
        }
        sm._pending_transactions[good_key] = {
            "bot_msg_id": "good-bot-msg",
            "created_at": datetime.now(),
        }

        found_key, pending = sm.find_pending_by_bot_msg("123@g.us", "good-bot-msg")
        self.assertEqual(found_key, good_key)
        self.assertIsNotNone(pending)
        self.assertNotIn(bad_key, sm._pending_transactions)


if __name__ == "__main__":
    unittest.main()
