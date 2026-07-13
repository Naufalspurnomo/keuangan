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
