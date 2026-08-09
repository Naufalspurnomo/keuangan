import os
import unittest
from unittest.mock import patch

from config import allowlist


class AllowlistSecurityTests(unittest.TestCase):
    def test_empty_allowlist_fails_closed_when_required(self):
        with patch.object(allowlist, "ALLOWED_SENDER_IDS", set()), patch.dict(
            os.environ, {"ALLOWLIST_REQUIRED": "1"}
        ):
            self.assertFalse(allowlist.is_sender_allowed(["628123456789"]))

    def test_empty_allowlist_remains_open_for_local_development(self):
        with patch.object(allowlist, "ALLOWED_SENDER_IDS", set()), patch.dict(
            os.environ,
            {"ALLOWLIST_REQUIRED": "0", "FLASK_ENV": "development", "FLASK_DEBUG": "1"},
        ):
            self.assertTrue(allowlist.is_sender_allowed(["628123456789"]))

    def test_durable_state_mode_also_fails_closed_by_default(self):
        with patch.object(allowlist, "ALLOWED_SENDER_IDS", set()), patch.dict(
            os.environ,
            {"FLASK_ENV": "development", "FLASK_DEBUG": "1", "STATE_STORE_REQUIRED": "1"},
            clear=True,
        ):
            self.assertFalse(allowlist.is_sender_allowed(["628123456789"]))


if __name__ == "__main__":
    unittest.main()
