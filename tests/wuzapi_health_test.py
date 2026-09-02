import threading
import unittest
from unittest.mock import Mock, patch

import wuzapi_helper


class Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


class Session:
    def __init__(self, gets=(), posts=()):
        self.gets = list(gets)
        self.posts = list(posts)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.gets.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.posts.pop(0)


class WuzApiHealthTests(unittest.TestCase):
    def setUp(self):
        wuzapi_helper._reset_wuzapi_runtime_state_for_tests()

    def configured(self, session):
        return patch.multiple(
            wuzapi_helper,
            WUZAPI_DOMAIN="https://wuzapi.test/api",
            WUZAPI_TOKEN="secret-token",
            get_wuzapi_session=Mock(return_value=session),
        )

    def test_status_falls_back_sanitizes_and_caches(self):
        session = Session(gets=[
            Response(404, {}),
            Response(200, {"data": {
                "connected": True,
                "loggedIn": True,
                "state": "CONNECTED",
                "jid": "628123@s.whatsapp.net",
                "token": "leak",
                "webhook": "https://secret.test/hook",
            }}),
        ])
        with self.configured(session):
            first = wuzapi_helper.get_wuzapi_status(force=True)
            second = wuzapi_helper.get_wuzapi_status()

        self.assertEqual(first, second)
        self.assertEqual(set(first), {
            "configured", "reachable", "connected", "logged_in",
            "state", "error", "checked_at",
        })
        self.assertTrue(first["connected"])
        self.assertNotIn("628123", str(first))
        self.assertEqual([call[0] for call in session.calls], ["GET", "GET"])
        self.assertTrue(session.calls[0][1].endswith("/session/status"))
        self.assertTrue(session.calls[1][1].endswith("/api/session/status"))
        self.assertLessEqual(session.calls[0][2]["timeout"], 5)

    def test_ensure_reconnects_disconnected_session_and_polls(self):
        session = Session(
            gets=[
                Response(200, {"data": {"connected": False, "loggedIn": False}}),
                Response(200, {"data": {"connected": True, "loggedIn": True}}),
            ],
            posts=[Response(200, {"success": True})],
        )
        with self.configured(session), patch.object(wuzapi_helper.time, "sleep"):
            result = wuzapi_helper.ensure_wuzapi_connected(force=True)

        self.assertTrue(result["connected"])
        connect = next(call for call in session.calls if call[0] == "POST")
        self.assertTrue(connect[1].endswith("/session/connect"))
        self.assertEqual(connect[2]["json"], {"Subscribe": [], "Immediate": False})
        self.assertGreaterEqual(connect[2]["timeout"], 11)
        self.assertLessEqual(connect[2]["timeout"], 20)

    def test_reconnect_cooldown_prevents_second_connect(self):
        session = Session(
            gets=[Response(200, {"connected": False})] * 3,
            posts=[Response(200, {"success": True})],
        )
        with self.configured(session), patch.object(wuzapi_helper.time, "sleep"):
            wuzapi_helper.ensure_wuzapi_connected(force=True)
            wuzapi_helper.ensure_wuzapi_connected(force=False)

        self.assertEqual(sum(call[0] == "POST" for call in session.calls), 1)

    def test_forced_checks_do_not_create_reconnect_storms(self):
        session = Session(
            gets=[Response(200, {"connected": False})] * 3,
            posts=[Response(200, {"success": True})],
        )
        with self.configured(session), patch.object(wuzapi_helper.time, "sleep"):
            wuzapi_helper.ensure_wuzapi_connected(force=True)
            wuzapi_helper.ensure_wuzapi_connected(force=True)

        self.assertEqual(sum(call[0] == "POST" for call in session.calls), 1)

    def test_send_reconnects_and_retries_once_when_provider_says_not_started(self):
        session = Session(posts=[
            Response(503, text="errors/not-started"),
            Response(200, {"Details": "Sent", "Id": "msg-1"}),
        ])
        connected = {"connected": True}
        with self.configured(session), \
             patch.object(wuzapi_helper, "ensure_wuzapi_connected", side_effect=[connected, connected]) as ensure:
            result = wuzapi_helper.send_wuzapi_reply("6281", "hello")

        self.assertEqual(result["Id"], "msg-1")
        self.assertEqual(ensure.call_count, 2)
        self.assertTrue(ensure.call_args_list[1].kwargs["force"])
        self.assertEqual(len(session.calls), 2)

    def test_send_reconnects_on_explicit_disconnected_http_success(self):
        session = Session(posts=[
            Response(200, {"success": False, "error": "session not started"}),
            Response(200, {"Details": "Sent", "Id": "msg-2"}),
        ])
        connected = {"connected": True}
        with self.configured(session), \
             patch.object(wuzapi_helper, "ensure_wuzapi_connected", side_effect=[connected, connected]) as ensure:
            result = wuzapi_helper.send_wuzapi_reply("6281", "hello")

        self.assertIsNotNone(result)
        self.assertEqual((result or {})["Id"], "msg-2")
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(len(session.calls), 2)

    def test_send_never_retries_unknown_http_success(self):
        bad = Response(200, None)
        bad.json = Mock(side_effect=ValueError("bad json"))
        session = Session(posts=[bad])
        with self.configured(session), \
             patch.object(wuzapi_helper, "ensure_wuzapi_connected", return_value={"connected": True}) as ensure:
            result = wuzapi_helper.send_wuzapi_reply("6281", "hello")

        self.assertIsNone(result)
        ensure.assert_called_once_with()
        self.assertEqual(len(session.calls), 1)

    def test_monitor_honors_disabled_setting_without_network(self):
        stop = threading.Event()
        with patch.dict(wuzapi_helper.os.environ, {"WUZAPI_MONITOR_ENABLED": "false"}), \
             patch.object(wuzapi_helper, "ensure_wuzapi_connected") as ensure:
            wuzapi_helper.run_wuzapi_monitor(stop)
        ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()