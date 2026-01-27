
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from layers.layer_4_state_machine import handle_query_setup
from layers.layer_6_storage import process_query
from layers import Intent

class TestQueryFlow(unittest.TestCase):
    
    def setUp(self):
        self.ctx = MagicMock()
        self.ctx.intent = Intent.QUERY_STATUS
        self.ctx.text = ""
        self.ctx.query_params = {}
        
    def test_layer_4_parsing(self):
        """Test Layer 4 parsing of query text."""
        print("\n[Layer 4] Testing Query Parsing...")
        
        scenarios = [
            ("berapa pengeluaran hari ini", "today", "expense"),
            ("cek pemasukan kemarin", "yesterday", "income"),
            ("total profit bulan ini", "month", "profit"),
            ("laporan 30 hari", "30days", "summary"),
            ("rekap minggu ini", "week", "summary"),
            ("berapa saldo", "today", "balance"), 
        ]
        
        for text, exp_period, exp_type in scenarios:
            self.ctx.text = text
            ctx = handle_query_setup(self.ctx)
            
            print(f"Input: '{text}' -> Period: {ctx.query_params['period']}, Type: {ctx.query_params['type']}")
            
            self.assertEqual(ctx.current_state, 'READY_TO_QUERY')
            self.assertEqual(ctx.query_params['period'], exp_period)
            self.assertEqual(ctx.query_params['type'], exp_type)

    @patch('sheets_helper.get_all_data')
    def test_layer_6_execution(self, mock_get_data):
        """Test Layer 6 execution and formatting."""
        print("\n[Layer 6] Testing Query Execution...")
        
        # Setup Mock Data
        # 3 transactions: Today (Income), Today (Expense), Yesterday (Income)
        mock_get_data.return_value = [
            {'tanggal': datetime.now().strftime('%Y-%m-%d'), 'jumlah': 1000000, 'tipe': 'Pemasukan', 'keterangan': 'Gaji'},
            {'tanggal': datetime.now().strftime('%Y-%m-%d'), 'jumlah': 500000, 'tipe': 'Pengeluaran', 'keterangan': 'Makan'},
            {'tanggal': (datetime.now().replace(day=1) if datetime.now().day > 1 else datetime.now()).strftime('%Y-%m-%d'), 'jumlah': 200000, 'tipe': 'Pemasukan', 'keterangan': 'Old'}
        ]
        
        # Scenario 1: Today Summary
        self.ctx.query_params = {'period': 'today', 'type': 'summary'}
        self.ctx.current_state = 'READY_TO_QUERY'
        
        ctx = process_query(self.ctx)
        
        print(f"[Layer 6] Response (Today): {ctx.response_message.encode('ascii', 'ignore')}")
        self.assertEqual(ctx.current_state, 'QUERY_DONE')
        self.assertIn("Pemasukan: Rp 1.000.000", ctx.response_message)
        self.assertIn("Pengeluaran: Rp 500.000", ctx.response_message)
        self.assertIn("Profit/Loss: Rp 500.000", ctx.response_message)
        
        # Scenario 2: Today Expense
        self.ctx.query_params = {'period': 'today', 'type': 'expense'}
        ctx = process_query(self.ctx)
        print(f"[Layer 6] Response (Today Expense): {ctx.response_message.encode('ascii', 'ignore')}")
        self.assertNotIn("Pemasukan", ctx.response_message)
        self.assertIn("Pengeluaran: Rp 500.000", ctx.response_message)
        
        # Scenario 3: Empty Data
        mock_get_data.return_value = []
        ctx = process_query(self.ctx)
        print(f"[Layer 6] Response (Empty): {ctx.response_message.encode('ascii', 'ignore')}")
        self.assertIn("(Belum ada transaksi)", ctx.response_message)

if __name__ == '__main__':
    unittest.main()
