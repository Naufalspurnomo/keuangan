import json
import os
import unittest
from unittest.mock import patch

from services.finance_agent import finance_agent_accepts, finance_agent_mode, plan_finance_message


STRUCTURED_MESSAGE = """/catat
Tanggal: 01/06/2026
Tipe: DB
Nominal: 480,000.00
Keterangan: TRSF E-BANKING DB 0106/FTSCYWS95051 fee workshop 29-31 RIZKI AGUSTINA
Catatan: projek workshop"""


class FinanceAgentTests(unittest.TestCase):
    def test_structured_bank_message_becomes_agent_transaction(self):
        decision = plan_finance_message(STRUCTURED_MESSAGE, "Naufal", llm_call=None)

        self.assertEqual(decision.action, "PROCESS")
        self.assertEqual(decision.source, "deterministic_structured")
        self.assertTrue(decision.accepted())
        self.assertEqual(len(decision.transactions), 1)
        tx = decision.transactions[0]
        self.assertEqual(tx.tanggal, "2026-06-01")
        self.assertEqual(tx.tipe, "Pengeluaran")
        self.assertEqual(tx.jumlah, 480000)
        self.assertEqual(tx.nama_projek, "workshop")

    def test_llm_agent_response_is_coerced_to_schema(self):
        class FakeMessage:
            content = json.dumps({
                "action": "PROCESS",
                "confidence": 0.88,
                "transactions": [{
                    "tanggal": "2026-06-01",
                    "kategori": "Gaji",
                    "keterangan": "fee workshop rizki",
                    "jumlah": "480,000.00",
                    "tipe": "Pengeluaran",
                    "nama_projek": "workshop",
                    "company": None,
                    "detected_dompet": None,
                }],
                "missing_fields": [],
                "question": "",
                "reasoning": "Structured transfer fee note.",
            })

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        def fake_llm(_messages):
            return FakeResponse()

        with patch("services.finance_agent._safe_sheet_context", return_value={
            "wallets": [],
            "known_projects": ["workshop"],
            "sheet_context_available": True,
        }):
            decision = plan_finance_message(
                "bayar fee workshop rizki nominal 480,000.00",
                "Naufal",
                llm_call=fake_llm,
            )

        self.assertEqual(decision.source, "llm_agent")
        self.assertTrue(decision.accepted())
        self.assertEqual(decision.transactions[0].jumlah, 480000)

    def test_missing_date_is_not_accepted_by_agent(self):
        text = """/catat
Tipe: DB
Nominal: 480,000.00
Keterangan: fee workshop
Catatan: projek workshop"""

        decision = plan_finance_message(text, "Naufal", llm_call=None)

        self.assertEqual(decision.action, "PROCESS")
        self.assertIn("tanggal", decision.missing_fields)
        self.assertFalse(decision.accepted())

    def test_shadow_mode_plans_but_does_not_accept_for_execution(self):
        with patch.dict(os.environ, {"FINANCE_AGENT_MODE": "shadow"}):
            decision = plan_finance_message(STRUCTURED_MESSAGE, "Naufal", llm_call=None)

            self.assertEqual(finance_agent_mode(), "shadow")
            self.assertTrue(decision.accepted())
            self.assertFalse(finance_agent_accepts())

    def test_deterministic_mode_does_not_call_llm_for_unstructured_text(self):
        def fail_if_called(_messages):
            raise AssertionError("LLM should not be called in deterministic mode")

        with patch.dict(os.environ, {"FINANCE_AGENT_MODE": "deterministic"}):
            decision = plan_finance_message(
                "bayar fee workshop rizki 480rb",
                "Naufal",
                llm_call=fail_if_called,
            )

        self.assertEqual(decision.action, "FALLBACK")
        self.assertFalse(decision.accepted())

    def test_llm_agent_rejects_partial_transaction_set(self):
        class FakeMessage:
            content = json.dumps({
                "action": "PROCESS",
                "confidence": 0.91,
                "transactions": [
                    {
                        "tanggal": "2026-06-01",
                        "kategori": "Gaji",
                        "keterangan": "fee workshop rizki",
                        "jumlah": "480,000.00",
                        "tipe": "Pengeluaran",
                        "nama_projek": "workshop",
                    },
                    {
                        "tanggal": "",
                        "kategori": "Gaji",
                        "keterangan": "fee tanpa tanggal",
                        "jumlah": "500,000.00",
                        "tipe": "Pengeluaran",
                        "nama_projek": "workshop",
                    },
                ],
                "missing_fields": [],
                "question": "",
                "reasoning": "One row is incomplete.",
            })

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        with patch("services.finance_agent._safe_sheet_context", return_value={
            "wallets": [],
            "known_projects": ["workshop"],
            "sheet_context_available": True,
        }):
            decision = plan_finance_message(
                "dua fee workshop",
                "Naufal",
                llm_call=lambda _messages: FakeResponse(),
            )

        self.assertEqual(decision.action, "PROCESS")
        self.assertFalse(decision.accepted())

    def test_llm_agent_rejects_amount_not_grounded_in_source(self):
        class FakeMessage:
            content = json.dumps({
                "action": "PROCESS",
                "confidence": 1.0,
                "transactions": [{
                    "tanggal": "2026-06-01",
                    "kategori": "Gaji",
                    "keterangan": "fee workshop",
                    "jumlah": 10600,
                    "tipe": "Pengeluaran",
                    "nama_projek": "workshop",
                }],
                "missing_fields": [],
                "question": "",
                "reasoning": "Incorrectly picked ref number.",
            })

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        text = "bayar fee workshop rizki 480,000.00 ref 0106 projek workshop"

        with patch("services.finance_agent._safe_sheet_context", return_value={
            "wallets": [],
            "known_projects": ["workshop"],
            "sheet_context_available": True,
        }):
            decision = plan_finance_message(
                text,
                "Naufal",
                llm_call=lambda _messages: FakeResponse(),
            )

        self.assertEqual(decision.source_amounts, [480000])
        self.assertFalse(decision.accepted())


if __name__ == "__main__":
    unittest.main()
