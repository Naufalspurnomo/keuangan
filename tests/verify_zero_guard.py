
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from layers import MessageContext, Intent
from layers.layer_4_state_machine import process as process_layer_4

class TestZeroGuard(unittest.TestCase):
    
    def test_empty_extraction_guard(self):
        """Test empty extraction leads to NO_TRANSACTION."""
        ctx = MessageContext(user_id="123", message_id="msg1", text="noise")
        ctx.extracted_data = []  # Empty
        ctx.intent = Intent.RECORD_TRANSACTION # Even if intent was record
        
        ctx = process_layer_4(ctx)
        
        print(f"Empty Extraction State: {ctx.current_state}")
        self.assertEqual(ctx.current_state, 'NO_TRANSACTION')

    def test_zero_amount_guard(self):
        """Test zero total amount leads to NO_TRANSACTION."""
        ctx = MessageContext(user_id="123", message_id="msg2", text="beli nol")
        ctx.extracted_data = [{'keterangan': 'Item', 'jumlah': 0, 'tipe': 'Pengeluaran'}]
        ctx.intent = Intent.RECORD_TRANSACTION
        
        ctx = process_layer_4(ctx)
        
        print(f"Zero Amount State: {ctx.current_state}")
        self.assertEqual(ctx.current_state, 'NO_TRANSACTION')
        
    def test_cancel_intent(self):
        """Test CANCEL intent in INITIAL state."""
        ctx = MessageContext(user_id="123", message_id="msg3", text="/cancel")
        ctx.intent = Intent.CANCEL_TRANSACTION
        ctx.current_state = 'INITIAL'
        
        ctx = process_layer_4(ctx)
        
        print(f"Cancel State: {ctx.current_state}")
        self.assertEqual(ctx.current_state, 'CANCELLED')
        self.assertIn("standby", ctx.response_message.lower())

if __name__ == '__main__':
    unittest.main()
