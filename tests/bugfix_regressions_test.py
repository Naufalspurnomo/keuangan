import os
from unittest.mock import patch

import main
from handlers.revision_handler import handle_undo_command


DASHBOARD_ID = "dashboard:17:" + "a" * 64


def test_release_health_reports_configured_sha_without_runtime_dependencies():
    with patch.dict(os.environ, {"RELEASE_SHA": "abc123", "KOYEB_GIT_SHA": "ignored"}, clear=False), \
         patch.object(main, "inbox_health", side_effect=AssertionError("must not run")):
        response = main.app.test_client().get("/api/health/release")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "release_sha": "abc123"}


def test_release_health_falls_back_to_koyeb_sha():
    with patch.dict(os.environ, {"RELEASE_SHA": "", "KOYEB_GIT_SHA": "koyeb123"}, clear=False):
        response = main.app.test_client().get("/api/health/release")
    assert response.get_json() == {"status": "ok", "release_sha": "koyeb123"}


def test_explicit_dashboard_undo_uses_exact_message_id_and_confirmation():
    item = {"keterangan": "fixture", "amount": 1, "dompet": "Operasional Kantor", "row": 2}
    with patch("handlers.revision_handler.find_all_transactions_by_message_id", return_value=[item]) as find, \
         patch("handlers.revision_handler.set_pending_confirmation") as pending, \
         patch("handlers.revision_handler.get_last_tx_event", side_effect=AssertionError("must not use global/chat fallback")):
        result = handle_undo_command("6281", "6281", explicit_message_id=DASHBOARD_ID)
    find.assert_called_once_with(DASHBOARD_ID)
    assert "Hapus transaksi ini" in result["response"]
    assert pending.call_args.kwargs["data"]["original_message_id"] == DASHBOARD_ID


def test_explicit_dashboard_undo_rejects_malformed_id_without_lookup():
    with patch("handlers.revision_handler.find_all_transactions_by_message_id") as find:
        result = handle_undo_command("6281", "6281", explicit_message_id="dashboard:17:not-a-hash")
    assert "tidak valid" in result["response"]
    find.assert_not_called()
