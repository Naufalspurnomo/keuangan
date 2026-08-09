import os
import tempfile
import unittest
from unittest.mock import patch

import wuzapi_helper


class FakeResponse:
    def __init__(self, status_code, payload=None, json_error=False):
        self.status_code = status_code
        self.headers = {}
        self._payload = payload
        self._json_error = json_error
        self.closed = False

    @property
    def text(self):
        return "" if self._payload is None else str(self._payload)

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class WuzApiSendAcknowledgementTests(unittest.TestCase):
    def _send(self, session):
        with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test"), \
             patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
             patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
            return wuzapi_helper.send_wuzapi_reply("group@g.us", "jawaban")

    def test_accepts_upstream_send_metadata(self):
        session = FakeSession([
            FakeResponse(200, {"Details": "Sent", "Timestamp": 123, "Id": "msg-1"}),
        ])

        result = self._send(session)

        self.assertEqual(result["Id"], "msg-1")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][1]["json"]["Phone"], "group@g.us")

    def test_provider_rejection_tries_supported_fallback_endpoint(self):
        session = FakeSession([
            FakeResponse(200, {"success": False, "error": "session not ready"}),
            FakeResponse(200, {"success": True, "data": {"Id": "msg-2"}}),
        ])

        result = self._send(session)

        self.assertEqual(result["data"]["Id"], "msg-2")
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.calls[1][0].endswith("/api/chat/send/text"))

    def test_unknown_http_success_is_not_reported_or_retried(self):
        session = FakeSession([
            FakeResponse(200, None, json_error=True),
        ])

        self.assertIsNone(self._send(session))
        self.assertEqual(len(session.calls), 1)

    def test_oversized_document_is_rejected_before_reading(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            session = FakeSession([])
            with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test"), \
                 patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
                 patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session), \
                 patch.object(wuzapi_helper.os.path, "getsize", return_value=10 * 1024 * 1024 + 1):
                self.assertIsNone(wuzapi_helper.send_wuzapi_document("123", path))
            self.assertEqual(session.calls, [])
        finally:
            os.unlink(path)

    def test_media_download_disables_redirects_and_closes_response(self):
        class MediaResponse:
            status_code = 200
            headers = {"content-type": "image/jpeg"}
            closed = False

            def iter_content(self, chunk_size=8192):
                yield b"image"

            def close(self):
                self.closed = True

        class MediaSession:
            def __init__(self, response):
                self.response = response
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return self.response

        response = MediaResponse()
        session = MediaSession(response)
        with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test"), \
             patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
            path = wuzapi_helper.download_wuzapi_media(
                "https://wuzapi.test/media/image.jpg"
            )
        try:
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(session.calls[0][1]["allow_redirects"])
            self.assertTrue(response.closed)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
