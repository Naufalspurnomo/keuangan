import unittest
from unittest.mock import patch

from handlers.smart_handler import SmartHandler


class _DummyStateManager:
    def get_original_message_id(self, _reply_message_id):
        return None

    def has_pending_transaction(self, _key):
        return False

    def record_bot_interaction(self, _sender_number, _chat_jid, _intent):
        return None


class SmartHandlerHutangOverrideTests(unittest.TestCase):
    @patch("handlers.smart_handler.GroqContextAnalyzer")
    @patch("handlers.smart_handler.should_quick_filter", return_value="PROCESS")
    @patch("handlers.smart_handler.get_full_context", return_value={"addressed_score": 60})
    def test_hutang_payment_without_amount_forces_record_transaction(
        self, _mock_ctx, _mock_quick, mock_analyzer
    ):
        mock_analyzer.return_value.analyze_message.return_value = {
            "should_respond": False,
            "intent": "IGNORE",
            "category_scope": "OPERATIONAL",
            "confidence": 0.95,
            "reasoning": "classified as balance update",
        }

        handler = SmartHandler(_DummyStateManager())
        result = handler.process(
            text="Bayar hutang dompet tx bali dari cv hb",
            chat_jid="6281212042709@s.whatsapp.net",
            sender_number="6281212042709",
            has_media=False,
            sender_name="Naufal",
        )

        self.assertEqual(result.get("action"), "PROCESS")
        self.assertEqual(result.get("intent"), "RECORD_TRANSACTION")

    @patch("handlers.smart_handler.GroqContextAnalyzer")
    @patch("handlers.smart_handler.should_quick_filter", return_value="PROCESS")
    @patch("handlers.smart_handler.get_full_context", return_value={"addressed_score": 60})
    def test_project_hutang_text_not_forced_into_debt_payment_override(
        self, _mock_ctx, _mock_quick, mock_analyzer
    ):
        mock_analyzer.return_value.analyze_message.return_value = {
            "should_respond": False,
            "intent": "IGNORE",
            "category_scope": "PROJECT",
            "confidence": 0.95,
            "reasoning": "uncertain project context",
        }

        handler = SmartHandler(_DummyStateManager())
        result = handler.process(
            text="Hutang projek daria ke cv hb",
            chat_jid="6281212042709@s.whatsapp.net",
            sender_number="6281212042709",
            has_media=False,
            sender_name="Naufal",
        )

        self.assertEqual(result.get("action"), "IGNORE")


if __name__ == "__main__":
    unittest.main()
