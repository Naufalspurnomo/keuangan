import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from flask import Flask, request
from security import rate_limit_check, validate_media_url, validate_transaction_data
from security import verify_webhook_secret, verify_wuzapi_webhook_secret, webhook_secret_required


class SecurityHardeningTests(unittest.TestCase):
    def test_media_url_requires_exact_telegram_host(self):
        self.assertEqual(validate_media_url("https://api.telegram.org.evil.test/file"), (False, "Domain not allowed"))
        self.assertEqual(validate_media_url("https://api.telegram.org/file/bot/token/photo.jpg"), (True, None))

    def test_transaction_validation_handles_untrusted_types(self):
        ok, error, sanitized = validate_transaction_data({
            "tanggal": "2026-08-09",
            "kategori": {"unexpected": "value"},
            "keterangan": "beli alat",
            "jumlah": "150rb",
        })

        self.assertTrue(ok, error)
        self.assertEqual(sanitized["jumlah"], 150000)

    def test_transaction_validation_rejects_explicit_invalid_date(self):
        ok, error, _ = validate_transaction_data({
            "tanggal": "2026-02-31",
            "keterangan": "beli alat",
            "jumlah": 150000,
        })

        self.assertFalse(ok)
        self.assertEqual(error, "Invalid date")

    def test_rate_limit_is_atomic_across_threads(self):
        import security

        with patch.object(security, "_rate_limit_store", {}):
            with ThreadPoolExecutor(max_workers=24) as pool:
                results = list(pool.map(lambda _: rate_limit_check("same-user")[0], range(24)))

        self.assertEqual(sum(results), security.RATE_LIMIT_REQUESTS)

    def test_webhook_secret_is_required_in_production(self):
        app = Flask(__name__)
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "production",
                "FLASK_DEBUG": "0",
                "WEBHOOK_SECRET_REQUIRED": "1",
                "TELEGRAM_WEBHOOK_SECRET": "expected-secret",
            },
        ):
            with app.test_request_context(
                "/telegram", headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}
            ):
                self.assertFalse(
                    verify_webhook_secret(
                        request,
                        "TELEGRAM_WEBHOOK_SECRET",
                        ("X-Telegram-Bot-Api-Secret-Token",),
                    )
                )
            with app.test_request_context(
                "/telegram", headers={"X-Telegram-Bot-Api-Secret-Token": "expected-secret"}
            ):
                self.assertTrue(
                    verify_webhook_secret(
                        request,
                        "TELEGRAM_WEBHOOK_SECRET",
                        ("X-Telegram-Bot-Api-Secret-Token",),
                    )
                )

    def test_webhook_secret_is_required_with_durable_state_mode(self):
        with patch.dict(
            os.environ,
            {
                "FLASK_ENV": "development",
                "FLASK_DEBUG": "1",
                "STATE_STORE_REQUIRED": "1",
                "TELEGRAM_WEBHOOK_SECRET": "",
            },
            clear=True,
        ):
            self.assertTrue(webhook_secret_required())

    def test_wuzapi_native_form_token_is_accepted_with_existing_token_config(self):
        app = Flask(__name__)
        with patch.dict(
            os.environ,
            {
                "WEBHOOK_SECRET_REQUIRED": "1",
                "WUZAPI_WEBHOOK_SECRET": "",
                "WUZAPI_TOKEN": "wuzapi-token",
            },
        ):
            with app.test_request_context(
                "/webhook_wuzapi",
                method="POST",
                data={"token": "wuzapi-token", "jsonData": "{}"},
            ):
                self.assertTrue(verify_wuzapi_webhook_secret(request))

            with app.test_request_context(
                "/webhook_wuzapi",
                method="POST",
                data={"token": "wrong-token", "jsonData": "{}"},
            ):
                self.assertFalse(verify_wuzapi_webhook_secret(request))

    def test_wuzapi_json_token_is_accepted(self):
        app = Flask(__name__)
        with patch.dict(
            os.environ,
            {
                "WEBHOOK_SECRET_REQUIRED": "1",
                "WUZAPI_WEBHOOK_SECRET": "json-secret",
                "WUZAPI_TOKEN": "",
            },
        ):
            with app.test_request_context(
                "/webhook_wuzapi",
                method="POST",
                json={"token": "json-secret", "type": "Message"},
            ):
                self.assertTrue(verify_wuzapi_webhook_secret(request))

    def test_wuzapi_query_token_is_accepted(self):
        app = Flask(__name__)
        with patch.dict(
            os.environ,
            {
                "WEBHOOK_SECRET_REQUIRED": "1",
                "WUZAPI_WEBHOOK_SECRET": "different-header-secret",
                "WUZAPI_TOKEN": "query-token",
            },
        ):
            with app.test_request_context(
                "/webhook_wuzapi?token=query-token",
                method="POST",
                data={"jsonData": "{}"},
            ):
                self.assertTrue(verify_wuzapi_webhook_secret(request))

    def test_media_download_closes_response_and_removes_partial_file(self):
        import ai_helper

        class FakeResponse:
            headers = {"content-type": "image/jpeg"}
            closed = False

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=8192):
                yield b"first"
                yield b"second"

            def close(self):
                self.closed = True

        response = FakeResponse()
        with patch("ai_helper.requests.get", return_value=response) as get_media, \
             patch("ai_helper.validate_media_url", return_value=(True, None)):
            path = ai_helper.download_media("https://api.telegram.org/file/bot/token/photo.jpg")
        try:
            self.assertTrue(os.path.isfile(path))
            with open(path, "rb") as downloaded:
                self.assertEqual(downloaded.read(), b"firstsecond")
            self.assertTrue(response.closed)
            self.assertFalse(get_media.call_args.kwargs["allow_redirects"])
        finally:
            os.unlink(path)

    def test_groq_call_has_bounded_timeout(self):
        import ai_helper

        with patch.dict(os.environ, {"GROQ_TIMEOUT_SECONDS": "999"}), \
             patch.object(ai_helper.groq_client.chat.completions, "create", return_value="ok") as create:
            result = ai_helper.call_groq_api(messages=[])

        self.assertEqual(result, "ok")
        self.assertEqual(create.call_args.kwargs["timeout"], 120.0)


if __name__ == "__main__":
    unittest.main()
