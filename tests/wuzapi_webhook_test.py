import unittest
import json
from unittest.mock import patch

from flask import Flask, jsonify, request

from handlers.wuzapi_webhook import _extract_sender_number, handle_wuzapi_webhook


class WuzapiWebhookTests(unittest.TestCase):
    def test_sender_none_falls_back_to_sender_alt(self):
        self.assertEqual(
            _extract_sender_number({
                "Sender": None,
                "SenderAlt": "628123456789@s.whatsapp.net",
            }),
            "628123456789",
        )

    def test_missing_sender_values_are_safe(self):
        self.assertEqual(_extract_sender_number({"Sender": None, "SenderAlt": None}), "")

    def test_mixed_lid_and_phone_identity_authorizes_and_uses_phone(self):
        app = Flask(__name__)
        payload = {
            "type": "Message",
            "event": {
                "Info": {
                    "Type": "text",
                    "ID": "mixed-identity-1",
                    "Chat": "628123456789@s.whatsapp.net",
                    "Sender": "628123456789@s.whatsapp.net",
                    "SenderAlt": "123456789012345@lid",
                    "PushName": "Admin",
                    "IsFromMe": False,
                },
                "Message": {"conversation": "status"},
            },
        }
        processed = []

        def allowed(identifiers):
            self.assertIn("628123456789", identifiers)
            self.assertIn("123456789012345", identifiers)
            return "628123456789" in identifiers

        with app.test_request_context(
            "/webhook", method="POST", data={"jsonData": json.dumps(payload)}
        ), patch("handlers.wuzapi_webhook.is_sender_allowed", side_effect=allowed), \
             patch("handlers.wuzapi_webhook.is_message_duplicate", return_value=False), \
             patch("handlers.wuzapi_webhook.capture_event", return_value="event-key"), \
             patch("handlers.wuzapi_webhook.mark_event"):
            response, status_code = handle_wuzapi_webhook(
                flask_request=request,
                process_message=lambda *args: processed.append(args) or (jsonify({"status": "processed"}), 200),
                max_webhook_bytes=1024 * 1024,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "processed")
        self.assertEqual(processed[0][0], "628123456789")

    def test_direct_chat_identity_can_authorize_when_sender_ids_are_lid(self):
        app = Flask(__name__)
        payload = {
            "type": "Message",
            "event": {
                "Info": {
                    "Type": "text",
                    "ID": "direct-chat-identity-1",
                    "Chat": "628987654321@s.whatsapp.net",
                    "Sender": "111111111111111@lid",
                    "SenderAlt": "222222222222222@lid",
                    "PushName": "Admin",
                    "IsFromMe": False,
                },
                "Message": {"conversation": "status"},
            },
        }
        processed = []

        with app.test_request_context(
            "/webhook", method="POST", data={"jsonData": json.dumps(payload)}
        ), patch(
            "handlers.wuzapi_webhook.is_sender_allowed",
            side_effect=lambda identifiers: "628987654321" in identifiers,
        ), patch("handlers.wuzapi_webhook.is_message_duplicate", return_value=False), \
             patch("handlers.wuzapi_webhook.capture_event", return_value="event-key"), \
             patch("handlers.wuzapi_webhook.mark_event"):
            response, status_code = handle_wuzapi_webhook(
                flask_request=request,
                process_message=lambda *args: processed.append(args) or (jsonify({"status": "processed"}), 200),
                max_webhook_bytes=1024 * 1024,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "processed")
        self.assertEqual(processed[0][0], "628987654321")

    def test_unauthorized_identity_fails_closed_before_deduplication(self):
        app = Flask(__name__)
        payload = {
            "type": "Message",
            "event": {
                "Info": {
                    "Type": "text",
                    "ID": "forbidden-before-dedupe-1",
                    "Chat": "628000000000@s.whatsapp.net",
                    "Sender": "111111111111111@lid",
                    "SenderAlt": "222222222222222@lid",
                    "PushName": "Unknown",
                    "IsFromMe": False,
                },
                "Message": {"conversation": "status"},
            },
        }

        with app.test_request_context(
            "/webhook", method="POST", data={"jsonData": json.dumps(payload)}
        ), patch("handlers.wuzapi_webhook.is_sender_allowed", return_value=False), \
             patch("handlers.wuzapi_webhook.is_message_duplicate") as dedupe, \
             patch("handlers.wuzapi_webhook.send_wuzapi_reply"):
            response, status_code = handle_wuzapi_webhook(
                flask_request=request,
                process_message=lambda *_args: self.fail("unauthorized message was processed"),
                max_webhook_bytes=1024 * 1024,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "forbidden")
        dedupe.assert_not_called()

    def test_webhook_sender_none_is_processed_without_http_500(self):
        app = Flask(__name__)
        payload = {
            "type": "Message",
            "event": {
                "Info": {
                    "Type": "text",
                    "ID": "sender-none-1",
                    "Chat": "628123456789@s.whatsapp.net",
                    "Sender": None,
                    "SenderAlt": "628123456789@s.whatsapp.net",
                    "PushName": "Admin",
                    "IsFromMe": False,
                },
                "Message": {"conversation": "dp 100.000 project pak rina tx sby"},
            },
        }

        with app.test_request_context(
            "/webhook", method="POST", data={"jsonData": json.dumps(payload)}
        ), patch("handlers.wuzapi_webhook.is_sender_allowed", return_value=True), \
             patch("handlers.wuzapi_webhook.is_message_duplicate", return_value=False), \
             patch("handlers.wuzapi_webhook.capture_event", return_value="event-key"), \
             patch("handlers.wuzapi_webhook.mark_event"):
            response, status_code = handle_wuzapi_webhook(
                flask_request=request,
                process_message=lambda *_args: (jsonify({"status": "processed"}), 200),
                max_webhook_bytes=1024 * 1024,
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response.get_json()["status"], "processed")


if __name__ == "__main__":
    unittest.main()
