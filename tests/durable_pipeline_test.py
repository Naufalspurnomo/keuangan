import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from handlers.wuzapi_webhook import handle_wuzapi_webhook
from services import durable_inbox, retry_service, state_manager
from services.durable_inbox import InboxUnavailable


class DurablePipelineTests(unittest.TestCase):
    def tearDown(self):
        state_manager.clear_visual_buffer("628100", "group@g.us")
        state_manager.clear_user_last_message("628100", "group@g.us")

    def test_visual_waiter_is_notified_by_concurrent_image(self):
        result = []

        def wait_for_image():
            result.extend(
                state_manager.wait_for_visual_buffer(
                    "628100", "group@g.us", timeout_seconds=1
                )
            )

        thread = threading.Thread(target=wait_for_image)
        thread.start()
        time.sleep(0.03)
        state_manager.store_visual_buffer(
            "628100",
            "group@g.us",
            "data:image/jpeg;base64,abc",
            "image-1",
        )
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["message_id"], "image-1")

    def test_durable_inbox_upgrades_duplicate_with_richer_media(self):
        durable_inbox._memory_events.clear()
        base = {
            "provider": "wuzapi",
            "message_id": "msg-1",
            "chat_id": "group@g.us",
            "sender_id": "628100",
            "event_type": "image",
            "payload_score": 0,
        }
        with patch.object(durable_inbox, "_ensure_db", return_value=False):
            key = durable_inbox.capture_event(base)
            upgraded_key = durable_inbox.capture_event(
                dict(base, media_data="data:image/jpeg;base64,abc", payload_score=1000)
            )

        self.assertEqual(key, upgraded_key)
        self.assertEqual(
            durable_inbox._memory_events[key]["media_data"],
            "data:image/jpeg;base64,abc",
        )

    def test_retry_fallback_deduplicates_same_source_transaction(self):
        with tempfile.TemporaryDirectory(dir=".") as temp_dir:
            queue_file = os.path.join(temp_dir, "retry.json")
            transaction = {"message_id": "msg-1", "jumlah": 450000}
            metadata = {"dompet_sheet": "CV HB(101)", "nama_projek": "Bu Astri"}
            with patch.object(retry_service, "QUEUE_FILE", queue_file), \
                 patch.object(retry_service, "_ensure_db", return_value=False):
                first = retry_service.add_to_retry_queue(transaction, metadata)
                second = retry_service.add_to_retry_queue(transaction, metadata)
                queue = retry_service.load_queue()

            self.assertEqual(first, second)
            self.assertEqual(len(queue), 1)

    def test_retry_queue_preserves_write_when_postgres_is_temporarily_unavailable(self):
        with tempfile.TemporaryDirectory(dir=".") as temp_dir:
            queue_file = os.path.join(temp_dir, "retry.json")
            transaction = {"message_id": "msg-db-down", "jumlah": 450000}
            metadata = {"dompet_sheet": "CV HB(101)", "nama_projek": "Bu Astri"}
            with patch.object(retry_service, "QUEUE_FILE", queue_file), \
                 patch.object(retry_service, "_database_url", return_value="postgresql://unavailable"), \
                 patch.object(retry_service, "_db_initialized", False), \
                 patch("psycopg.connect", side_effect=RuntimeError("db unavailable")):
                queue_id = retry_service.add_to_retry_queue(transaction, metadata)
                queue = retry_service.load_queue()

            self.assertTrue(queue_id)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["transaction"], transaction)

    def test_image_is_buffered_before_pipeline_callback(self):
        app = Flask(__name__)
        payload = {
            "type": "Message",
            "base64": "YWJj",
            "event": {
                "Info": {
                    "Type": "image",
                    "ID": "image-1",
                    "Chat": "group@g.us",
                    "Sender": "628100@s.whatsapp.net",
                    "SenderAlt": "628100@s.whatsapp.net",
                    "PushName": "Admin",
                    "IsFromMe": False,
                },
                "Message": {"imageMessage": {"caption": ""}},
            },
        }
        marked = []

        def process_message(*_args):
            buffered = state_manager.get_visual_buffer("628100", "group@g.us")
            self.assertEqual(buffered[0]["message_id"], "image-1")
            return jsonify({"status": "buffered_image_waiting_text"}), 200

        with app.test_request_context(
            "/webhook", method="POST", data={"jsonData": json.dumps(payload)}
        ), patch("handlers.wuzapi_webhook.is_sender_allowed", return_value=True), \
             patch("handlers.wuzapi_webhook.is_message_duplicate", return_value=False), \
             patch("handlers.wuzapi_webhook.capture_event", return_value="event-key"), \
             patch("handlers.wuzapi_webhook.mark_event", side_effect=lambda *a, **k: marked.append((a, k))):
            response, status_code = handle_wuzapi_webhook(
                flask_request=__import__("flask").request,
                process_message=process_message,
                max_webhook_bytes=1024 * 1024,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "buffered_image_waiting_text")
        self.assertEqual(marked[-2][0][1], "processing")
        self.assertEqual(marked[-1][0][1], "waiting_pair")

    def test_duplicate_image_is_rejected_before_provider_download(self):
        app = Flask(__name__)
        payload = {
            "type": "Message",
            "event": {
                "Info": {
                    "Type": "image",
                    "ID": "image-duplicate",
                    "Chat": "group@g.us",
                    "Sender": "628100@s.whatsapp.net",
                    "SenderAlt": "628100@s.whatsapp.net",
                    "PushName": "Admin",
                    "IsFromMe": False,
                },
                "Message": {"imageMessage": {"caption": ""}},
            },
        }

        with app.test_request_context(
            "/webhook", method="POST", data={"jsonData": json.dumps(payload)}
        ), patch("handlers.wuzapi_webhook.is_sender_allowed", return_value=True), \
             patch("handlers.wuzapi_webhook.is_message_duplicate", return_value=True), \
             patch("handlers.wuzapi_webhook.download_wuzapi_image") as download:
            response, status_code = handle_wuzapi_webhook(
                flask_request=__import__("flask").request,
                process_message=lambda *_args: None,
                max_webhook_bytes=1024 * 1024,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "duplicate")
        download.assert_not_called()

    def test_required_inbox_failure_clears_dedup_for_provider_retry(self):
        app = Flask(__name__)
        payload = {
            "type": "Message",
            "event": {
                "Info": {
                    "Type": "text",
                    "ID": "text-retry",
                    "Chat": "group@g.us",
                    "Sender": "628100@s.whatsapp.net",
                    "SenderAlt": "628100@s.whatsapp.net",
                    "PushName": "Admin",
                    "IsFromMe": False,
                },
                "Message": {"conversation": "Fee Rio 450rb projek Bu Astri"},
            },
        }

        with app.test_request_context(
            "/webhook", method="POST", data={"jsonData": json.dumps(payload)}
        ), patch("handlers.wuzapi_webhook.is_sender_allowed", return_value=True), \
             patch("handlers.wuzapi_webhook.is_message_duplicate", return_value=False), \
             patch("handlers.wuzapi_webhook.capture_event", side_effect=InboxUnavailable("db down")), \
             patch("handlers.wuzapi_webhook.clear_message_duplicate") as clear_dedup:
            response, status_code = handle_wuzapi_webhook(
                flask_request=__import__("flask").request,
                process_message=lambda *_args: None,
                max_webhook_bytes=1024 * 1024,
            )

        self.assertEqual(status_code, 503)
        self.assertEqual(response.get_json()["status"], "durable_inbox_unavailable")
        clear_dedup.assert_called_once_with("text-retry")

    def test_split_text_is_bound_as_media_before_smart_handler(self):
        import main

        state_manager.store_visual_buffer(
            "628100",
            "group@g.us",
            "data:image/jpeg;base64,YWJj",
            "image-1",
        )
        calls = []

        def smart_process(**kwargs):
            calls.append(kwargs)
            return {"action": "IGNORE", "intent": "IGNORE"}

        with main.app.test_request_context("/"), \
             patch.object(main, "rate_limit_check", return_value=(True, 0)), \
             patch.object(main.smart_handler, "process", side_effect=smart_process):
            response, status_code = main.process_incoming_message(
                sender_number="628100",
                sender_name="Admin",
                text="Fee rio sisanya, projek bu astri",
                input_type="text",
                message_id="text-1",
                is_group=True,
                chat_jid="group@g.us",
                sender_jid="628100@s.whatsapp.net",
                send_reply=lambda *_args, **_kwargs: {},
                source_label="WhatsApp",
                reply_to="group@g.us",
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "ignored")
        self.assertTrue(calls[0]["has_media"])
        self.assertEqual(calls[0]["text"], "Fee rio sisanya, projek bu astri")

    def test_clear_finance_input_acks_without_classifier_round_trip(self):
        import main

        events = []

        def smart_process(**_kwargs):
            events.append("classifier")
            raise AssertionError("clear finance input should use deterministic routing")

        with main.app.test_request_context("/"), \
             patch.object(main, "rate_limit_check", return_value=(True, 0)), \
             patch.object(main.smart_handler, "process", side_effect=smart_process), \
             patch.object(main, "extract_financial_data", return_value=[]):
            response, status_code = main.process_incoming_message(
                sender_number="628100999",
                sender_name="Admin",
                text="dp 100.000 project pak rina tx sby",
                input_type="text",
                message_id="ack-before-classifier-1",
                is_group=False,
                chat_jid="628100999@s.whatsapp.net",
                sender_jid="628100999@s.whatsapp.net",
                send_reply=lambda *_args, **_kwargs: events.append("ack"),
                source_label="WhatsApp",
                reply_to="628100999@s.whatsapp.net",
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "no_tx")
        self.assertEqual(events[0], "ack")
        self.assertNotIn("classifier", events)

    def test_fast_operational_flow_does_not_claim_saved_without_ack(self):
        import main

        events = []
        transaction = {
            "tanggal": "2026-08-09",
            "kategori": "Gaji",
            "keterangan": "gaji staff",
            "jumlah": 100000,
            "tipe": "Pengeluaran",
            "nama_projek": "",
            "detected_dompet": "CV HB(101)",
        }
        pkey = main.pending_key("628101", "628101@s.whatsapp.net")

        with main.app.test_request_context("/"), \
             patch.object(main, "FAST_MODE", True), \
             patch.object(main, "rate_limit_check", return_value=(True, 0)), \
             patch.object(main, "extract_financial_data", return_value=[transaction]), \
             patch.object(main, "detect_transaction_context", return_value={
                 "mode": "OPERATIONAL",
                 "needs_wallet": False,
                 "category": "Gaji",
             }), \
             patch.object(main, "append_operational_transaction", return_value={
                 "success": False,
                 "error": "Sheets timeout",
             }) as append:
            response, status_code = main.process_incoming_message(
                sender_number="628101",
                sender_name="Admin",
                text="gaji staff 100rb kantor dompet cv hb",
                input_type="text",
                message_id="operational-save-fail-1",
                is_group=False,
                chat_jid="628101@s.whatsapp.net",
                sender_jid="628101@s.whatsapp.net",
                send_reply=lambda body, **_kwargs: events.append(body) or {"id": "reply-1"},
                source_label="WhatsApp",
                reply_to="628101@s.whatsapp.net",
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "save_failed_operational")
        append.assert_called_once()
        self.assertTrue(any("Gagal menyimpan" in body for body in events))
        self.assertIn(pkey, main._pending_transactions)
        main._pending_transactions.pop(pkey, None)

    def test_split_text_waits_for_image_webhook_race(self):
        import main

        calls = []
        finished = []

        def smart_process(**kwargs):
            calls.append(kwargs)
            return {"action": "IGNORE", "intent": "IGNORE"}

        def process_text():
            with main.app.test_request_context("/"):
                result = main.process_incoming_message(
                    sender_number="628100",
                    sender_name="Admin",
                    text="Fee rio sisanya, projek bu astri",
                    input_type="text",
                    message_id="text-race",
                    is_group=True,
                    chat_jid="group@g.us",
                    sender_jid="628100@s.whatsapp.net",
                    send_reply=lambda *_args, **_kwargs: {},
                    source_label="WhatsApp",
                    reply_to="group@g.us",
                )
                finished.append(result)

        with patch.object(main, "rate_limit_check", return_value=(True, 0)), \
             patch.object(main.smart_handler, "process", side_effect=smart_process):
            thread = threading.Thread(target=process_text)
            thread.start()
            time.sleep(0.1)
            state_manager.store_visual_buffer(
                "628100",
                "group@g.us",
                "data:image/jpeg;base64,YWJj",
                "image-race",
            )
            thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        self.assertTrue(finished)
        self.assertTrue(calls[0]["has_media"])

    def test_health_reports_memory_inbox_as_degraded(self):
        import main

        with main.app.test_request_context("/health"), \
             patch.object(main, "inbox_health", return_value={"durable": False, "backend": "memory"}), \
             patch.object(main, "inbox_required", return_value=False):
            response, status_code = main.health_check()

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "degraded")
        self.assertTrue(response.get_json()["security"]["ready"])

    def test_health_fails_closed_when_production_security_is_missing(self):
        import main

        with main.app.test_request_context("/health"), \
             patch.object(main, "inbox_health", return_value={"durable": True, "backend": "postgres"}), \
             patch.object(main, "inbox_required", return_value=False), \
             patch.object(main, "allowlist_required", return_value=True), \
             patch.object(main, "webhook_secret_required", return_value=True), \
             patch.object(main, "ALLOWED_SENDER_IDS", set()), \
             patch.dict(os.environ, {
                 "WUZAPI_WEBHOOK_SECRET": "",
                 "TELEGRAM_WEBHOOK_SECRET": "",
             }):
            response, status_code = main.health_check()

        body = response.get_json()
        self.assertEqual(status_code, 503)
        self.assertEqual(body["status"], "unhealthy")
        self.assertEqual(
            body["security"]["missing"],
            [
                "ALLOWED_SENDER_IDS",
                "WUZAPI_WEBHOOK_SECRET",
                "TELEGRAM_WEBHOOK_SECRET",
            ],
        )

    def test_health_probe_exception_is_unhealthy_when_security_is_required(self):
        import main

        with main.app.test_request_context("/health"), \
             patch.object(main, "inbox_health", side_effect=RuntimeError("probe failed")), \
             patch.object(main, "inbox_required", return_value=False), \
             patch.object(main, "allowlist_required", return_value=True), \
             patch.object(main, "webhook_secret_required", return_value=False):
            response, status_code = main.health_check()

        self.assertEqual(status_code, 503)
        self.assertEqual(response.get_json()["status"], "unhealthy")

    def test_review_alert_reposts_image_evidence(self):
        import main

        event = {
            "chat_id": "group@g.us",
            "sender_id": "628100",
            "message_id": "image-1",
            "media_data": "data:image/jpeg;base64,YWJj",
        }
        with patch.object(main, "send_wuzapi_document", return_value={"status": "ok"}) as send_document, \
             patch.object(main, "send_wuzapi_reply") as send_text:
            main._notify_inbox_review(event, "", "keterangan belum ditemukan")

        send_document.assert_called_once()
        self.assertIn("TRANSAKSI TERTAHAN", send_document.call_args.kwargs["caption"])
        send_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
