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
