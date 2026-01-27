
import unittest
from layers import MessageContext, Intent
from layers.layer_4_state_machine import process as process_layer_4

class TestConversationalFlow(unittest.TestCase):
    
    def test_conversational_help(self):
        """Test 'gimana cara' triggers help message."""
        ctx = MessageContext(
            user_id="123",
            message_id="msg1",
            text="gimana cara pakai bot"
        )
        ctx.intent = Intent.CONVERSATIONAL_QUERY
        
        ctx = process_layer_4(ctx)
        
        print(f"State: {ctx.current_state}")
        print(f"Response: {ctx.response_message}")
        
        self.assertEqual(ctx.current_state, 'HELP_RESPONDED')
        self.assertIn("Bantuan Bot Keuangan", ctx.response_message)
        self.assertIn("Contoh Perintah", ctx.response_message)

if __name__ == '__main__':
    unittest.main()
