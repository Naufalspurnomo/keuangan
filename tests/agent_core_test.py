import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent_core.conversation_memory import get_recent, record_message, render_for_prompt
from agent_core.query_engine import execute, parse_ast
from agent_core.semantic_dedup import find_likely_duplicates
from services.finance_agent import plan_finance_message


class AgentCoreTests(unittest.TestCase):
    def test_query_engine_filters_and_sums_deterministically(self):
        ast = parse_ast({
            "metric": "sum",
            "filters": {
                "project": "villa",
                "tipe": "Pengeluaran",
                "date_from": "2026-07-01",
                "date_to": "2026-07-31",
            },
            "group_by": None,
        })
        rows = [
            {"tanggal": "2026-07-02", "nama_projek": "Villa Puncak", "tipe": "Pengeluaran", "jumlah": 100000},
            {"tanggal": "2026-07-03", "nama_projek": "Villa Puncak", "tipe": "Pemasukan", "jumlah": 50000},
            {"tanggal": "2026-06-30", "nama_projek": "Villa Puncak", "tipe": "Pengeluaran", "jumlah": 25000},
        ]

        result = execute(ast, rows)

        self.assertEqual(result["value"], 100000)
        self.assertEqual(result["row_count"], 1)

    def test_conversation_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "memory.jsonl")
            with patch.dict(os.environ, {"CONVERSATION_MEMORY_PATH": path, "CONVERSATION_MEMORY_ENABLED": "true"}):
                record_message("chat-1", "user-1", "user", "catat semen 50rb")
                record_message("chat-1", "user-1", "bot", "Disimpan")
                record_message("chat-2", "user-1", "user", "ignored")

                recent = get_recent("chat-1", "user-1", limit=6)
                rendered = render_for_prompt(recent)

        self.assertEqual([item["role"] for item in recent], ["user", "bot"])
        self.assertIn("user: catat semen 50rb", rendered)
        self.assertIn("bot: Disimpan", rendered)

    def test_semantic_dedup_matches_same_amount_similar_text(self):
        hits = find_likely_duplicates(
            {"jumlah": 50000, "keterangan": "beli semen", "nama_projek": "Villa"},
            [
                {"jumlah": 50000, "keterangan": "beli semen", "nama_projek": "Villa", "tanggal": "2026-07-01"},
                {"jumlah": 50000, "keterangan": "beli pasir", "nama_projek": "Villa", "tanggal": "2026-07-01"},
            ],
            threshold=0.75,
        )

        self.assertEqual(hits[0][1]["keterangan"], "beli semen")

    def test_finance_agent_includes_conversation_context(self):
        captured = {}

        class FakeMessage:
            content = json.dumps({
                "action": "PROCESS",
                "confidence": 0.9,
                "transactions": [{
                    "tanggal": "2026-07-04",
                    "kategori": "Bahan Alat",
                    "keterangan": "semen revisi",
                    "jumlah": 100000,
                    "tipe": "Pengeluaran",
                    "nama_projek": "Villa",
                }],
                "missing_fields": [],
                "question": "",
                "reasoning": "Uses recent context.",
            })

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        def fake_llm(messages):
            captured["messages"] = messages
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "memory.jsonl")
            with patch.dict(os.environ, {
                "CONVERSATION_MEMORY_PATH": path,
                "CONVERSATION_MEMORY_ENABLED": "true",
            }):
                record_message("chat-1", "user-1", "user", "catat semen 50rb project Villa")
                with patch("services.finance_agent._safe_sheet_context", return_value={
                    "wallets": [],
                    "known_projects": ["Villa"],
                    "sheet_context_available": True,
                }):
                    plan_finance_message(
                        "yang tadi jadi 100rb",
                        "Naufal",
                        llm_call=fake_llm,
                        chat_id="chat-1",
                        user_id="user-1",
                    )

        payload = json.loads(captured["messages"][1]["content"])
        self.assertIn("catat semen 50rb", payload["conversation_context"])


if __name__ == "__main__":
    unittest.main()
