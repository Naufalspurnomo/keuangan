import unittest
from unittest.mock import patch

from services import state_store


class StateStoreConfigTests(unittest.TestCase):
    def tearDown(self):
        state_store.reset_state_store_cache_for_tests()

    def test_external_state_required_truthy_values(self):
        with patch.dict("os.environ", {"STATE_STORE_REQUIRED": "true"}):
            self.assertTrue(state_store.external_state_required())

        with patch.dict("os.environ", {"STATE_STORE_REQUIRED": "0"}):
            self.assertFalse(state_store.external_state_required())

    def test_no_backend_returns_none(self):
        with patch.dict("os.environ", {"STATE_STORE_BACKEND": "local"}, clear=True):
            state_store.reset_state_store_cache_for_tests()
            self.assertIsNone(state_store.get_configured_state_store())

    def test_unknown_backend_returns_none(self):
        with patch.dict("os.environ", {"STATE_STORE_BACKEND": "unknown"}, clear=True):
            state_store.reset_state_store_cache_for_tests()
            self.assertIsNone(state_store.get_configured_state_store())


if __name__ == "__main__":
    unittest.main()
