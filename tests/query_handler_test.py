import unittest
import os
from unittest.mock import patch

from handlers import query_handler
from handlers import nl_query_handler


def _project_row(
    *,
    tanggal="2026-08-02",
    project="Holla - Yes Dental Perbaikan (Start)",
    amount=500000,
    tipe="Pengeluaran",
    wallet="CV HB(101)",
):
    return {
        "tanggal": tanggal,
        "nama_projek": project,
        "jumlah": amount,
        "tipe": tipe,
        "company_sheet": wallet,
        "keterangan": "Pembayaran vendor",
        "kategori": "Bahan Alat",
    }


class QueryHandlerTests(unittest.TestCase):
    def setUp(self):
        self._agent_env = patch.dict(os.environ, {"QUERY_AGENT_ENABLED": "false"})
        self._agent_env.start()

    def tearDown(self):
        self._agent_env.stop()

    def test_project_activity_phrase_is_not_treated_as_project_name(self):
        with patch.object(
            query_handler,
            "_handle_project_activity_query",
            return_value="jawaban aktivitas",
        ) as activity:
            answer = query_handler.handle_query_command(
                "project yang dikerjakan",
                "628100",
                "chat-1",
            )

        self.assertEqual(answer, "jawaban aktivitas")
        activity.assert_called_once()

    def test_project_activity_response_uses_transaction_evidence(self):
        rows = [_project_row()]
        with patch.object(query_handler, "get_all_data", return_value=rows):
            answer = query_handler.handle_query_command(
                "project yang dikerjakan",
                "628100",
                "chat-1",
            )

        self.assertIn("Yes Dental Perbaikan", answer)
        self.assertIn("Keluar Rp 500.000", answer)
        self.assertIn("1 transaksi", answer)
        self.assertNotIn("/tanya projek paling untung", answer)

    def test_project_detail_does_not_report_period_zero_when_history_exists(self):
        historical = [_project_row(tanggal="2026-06-01", amount=750000)]
        summary = {
            "by_projek": {
                "yes dental perbaikan": {
                    "name": "Yes Dental Perbaikan (Start)",
                    "income": 0,
                    "expense": 750000,
                    "profit_loss": -750000,
                }
            }
        }
        with patch.object(query_handler, "get_summary", return_value=summary), \
             patch.object(query_handler, "get_all_data", side_effect=[[], historical]):
            answer = query_handler._handle_project_query(
                "rincian project yes dental perbaikan",
                "rincian project yes dental perbaikan",
                30,
                "30 hari terakhir",
            )

        self.assertIn("Belum ada transaksi", answer)
        self.assertIn("Sepanjang riwayat", answer)
        self.assertIn("Rp 750.000", answer)
        self.assertNotIn("📤 Pengeluaran: Rp 0", answer)

    def test_query_agent_plans_retrieves_then_answers_from_facts(self):
        rows = [_project_row(), _project_row(project="Project Beta", amount=125000)]
        captured = {}

        def answer_from_facts(question, facts):
            captured["question"] = question
            captured["facts"] = facts
            return "jawaban dari fakta"

        with patch.object(nl_query_handler, "_ask_llm_for_plan", return_value={
            "intent": "project_activity",
            "metric": "count",
            "filters": {},
            "group_by": "project",
            "period_days": 30,
            "detail": False,
        }), patch.object(nl_query_handler, "get_all_data", return_value=rows), \
             patch.object(nl_query_handler, "_answer_from_facts", side_effect=answer_from_facts):
            answer = nl_query_handler.handle_nl_query(
                "project yang dikerjakan",
                default_days=30,
            )

        self.assertEqual(answer, "jawaban dari fakta")
        self.assertEqual(captured["facts"]["intent"], "project_activity")
        self.assertEqual(captured["facts"]["period_row_count"], 2)
        self.assertEqual(captured["facts"]["period_stats"]["row_count"], 2)
        self.assertEqual(len(captured["facts"]["evidence"]), 2)

    def test_query_command_uses_agent_before_legacy_formatter(self):
        with patch.dict(os.environ, {"QUERY_AGENT_ENABLED": "true"}), \
             patch(
                 "handlers.nl_query_handler.handle_nl_query",
                 return_value="jawaban agent",
             ) as agent:
            answer = query_handler.handle_query_command(
                "project yang dikerjakan",
                "628100",
                "chat-1",
            )

        self.assertEqual(answer, "jawaban agent")
        agent.assert_called_once_with("project yang dikerjakan", default_days=30)

    def test_query_agent_uses_authoritative_wallet_balance(self):
        captured = {}

        def answer_from_facts(question, facts):
            captured["facts"] = facts
            return "jawaban saldo"

        with patch.object(nl_query_handler, "_ask_llm_for_plan", return_value={
            "intent": "wallet",
            "metric": "sum",
            "filters": {"dompet": "CV HB(101)"},
            "group_by": None,
            "period_days": 30,
        }), patch.object(nl_query_handler, "get_all_data", return_value=[]), \
             patch.object(nl_query_handler, "get_wallet_balances", return_value={
                 "CV HB(101)": {
                     "saldo": 1250000,
                     "pemasukan": 2000000,
                     "pengeluaran": 500000,
                     "operational_debit": 250000,
                     "utang_open_in": 0,
                 }
             }), patch.object(nl_query_handler, "_answer_from_facts", side_effect=answer_from_facts):
            answer = nl_query_handler.handle_nl_query("saldo dompet CV HB", default_days=30)

        self.assertEqual(answer, "jawaban saldo")
        self.assertEqual(captured["facts"]["wallet_balances"]["CV HB(101)"]["saldo"], 1250000)

    def test_query_agent_uses_authoritative_debt_summary_and_position(self):
        captured = {}

        def answer_from_facts(question, facts):
            captured["facts"] = facts
            return "jawaban hutang"

        def open_debt(**filters):
            if filters.get("yang_hutang"):
                return [{"amount": 400000, "yang_hutang": "CV HB(101)", "yang_dihutangi": "TX SBY(216)"}]
            return [{"amount": 150000, "yang_hutang": "TX BALI(087)", "yang_dihutangi": "CV HB(101)"}]

        with patch.object(nl_query_handler, "_ask_llm_for_plan", return_value={
            "intent": "debt",
            "metric": "sum",
            "filters": {"dompet": "CV HB(101)"},
            "group_by": None,
            "period_days": None,
        }), patch.object(nl_query_handler, "get_hutang_summary", return_value={
             "open_count": 2, "open_total": 550000,
        }), patch.object(nl_query_handler, "find_open_hutang", side_effect=open_debt), \
             patch.object(nl_query_handler, "_answer_from_facts", side_effect=answer_from_facts):
            answer = nl_query_handler.handle_nl_query("hutang dompet CV HB", default_days=30)

        self.assertEqual(answer, "jawaban hutang")
        self.assertEqual(captured["facts"]["debt"]["summary"]["open_total"], 550000)
        self.assertEqual(captured["facts"]["debt"]["position"]["net"], -250000)


if __name__ == "__main__":
    unittest.main()
