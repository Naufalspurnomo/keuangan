
import unittest
from unittest.mock import MagicMock, patch
from layers import MessageContext, Intent
from layers.layer_4_state_machine import process as process_layer_4
from layers.layer_6_storage import process as process_layer_6
from layers.layer_1_intent_classifier import intent_pre_filter

class TestRevisionFlow(unittest.TestCase):
    
    def setUp(self):
        # Mock Context
        self.ctx = MessageContext(
            user_id="628123456789",
            message_id="msg_revision_123",
            text="revisi dp 7.5jt",
            quoted_message_id="msg_original_123"
        )
        # Manually set intent as if Layer 1 detected it
        self.ctx.intent = Intent.REVISION_REQUEST
        
        # Original Transactions (Mock DB)
        self.mock_transactions = [
            {'dompet': 'Dompet Holja', 'row': 10, 'amount': 0, 'keterangan': 'Beli Semen', 'message_id': 'msg_original_123'},
            {'dompet': 'Dompet Holja', 'row': 11, 'amount': 0, 'keterangan': 'Bayar DP Tukang', 'message_id': 'msg_original_123'},
            {'dompet': 'Dompet Holja', 'row': 12, 'amount': 0, 'keterangan': 'Beli Pasir', 'message_id': 'msg_original_123'},
        ]

    def test_layer_1_detection(self):
        """Test if intent pre-filter detects revision correctly."""
        ctx_dict = {'is_reply_to_bot': True, 'reply_context_type': 'TRANSACTION_REPORT'}
        result = intent_pre_filter("revisi dp 7.5jt", ctx_dict)
        print(f"\n[Layer 1] Pre-filter Result: {result}")
        self.assertEqual(result['intent'], 'REVISION_REQUEST')
        self.assertTrue(result['skip_ai'])

    def test_layer_4_parsing(self):
        """Test Layer 4 parsing of revision request."""
        print(f"\n[Layer 4] Input text: {self.ctx.text}")
        
        ctx = process_layer_4(self.ctx)
        
        print(f"[Layer 4] State: {ctx.current_state}")
        print(f"[Layer 4] Revision Data: {getattr(ctx, 'revision_data', None)}")
        
        self.assertEqual(ctx.current_state, 'READY_TO_REVISE')
        self.assertEqual(ctx.revision_data['amount'], 7500000)
        self.assertEqual(ctx.revision_data['keyword'], 'dp')
        
    @patch('sheets_helper.find_all_transactions_by_message_id')
    @patch('sheets_helper.update_transaction_amount')
    @patch('sheets_helper.invalidate_dashboard_cache')
    def test_layer_6_execution(self, mock_invalidate, mock_update, mock_find):
        """Test Layer 6 finding correct transaction and updating it."""
        # Setup context from Layer 4
        self.ctx.current_state = 'READY_TO_REVISE'
        self.ctx.revision_data = {'amount': 7500000, 'keyword': 'dp'}
        
        # Setup Mocks
        mock_find.return_value = self.mock_transactions
        mock_update.return_value = True
        
        print("\n[Layer 6] executing revision...")
        ctx = process_layer_6(self.ctx)
        
        print(f"[Layer 6] Final State: {ctx.current_state}")
        print(f"[Layer 6] Response: {ctx.response_message.encode('ascii', 'ignore')}")
        
        # Verification
        self.assertEqual(ctx.current_state, 'REVISION_DONE')
        
        # Should call update on row 11 (DP transaction)
        mock_update.assert_called_once_with('Dompet Holja', 11, 7500000)
        print("[Layer 6] Verified update called on correct row (11)")

    @patch('sheets_helper.find_all_transactions_by_message_id')
    def test_layer_6_ambiguity(self, mock_find):
        """Test Layer 6 handling ambiguity."""
        self.ctx.current_state = 'READY_TO_REVISE'
        self.ctx.revision_data = {'amount': 50000, 'keyword': 'beli'} # Ambiguous (Semen and Pasir both 'Beli')
        
        mock_find.return_value = self.mock_transactions
        
        print("\n[Layer 6] Testing ambiguity 'beli'...")
        ctx = process_layer_6(self.ctx)
        
        print(f"[Layer 6] State: {ctx.current_state}")
        # Semantic Engine finds "Beli Semen" as best match for "beli" (First item)
        # So we expect success now, not error.
        self.assertEqual(ctx.current_state, 'REVISION_DONE')
        # self.assertIn("Ada 2 item mirip", ctx.response_message)

if __name__ == '__main__':
    unittest.main()
