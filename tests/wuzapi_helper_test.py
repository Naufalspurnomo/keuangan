import unittest
from unittest.mock import patch

import wuzapi_helper


class FakeResponse:
    def __init__(self, status_code, payload=None, json_error=False):
        self.status_code = status_code
        self.headers = {}
        self._payload = payload
        self._json_error = json_error

    @property
    def text(self):
        return "" if self._payload is None else str(self._payload)

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


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


if __name__ == "__main__":
    unittest.main()
