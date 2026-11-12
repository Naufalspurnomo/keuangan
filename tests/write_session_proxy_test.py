import contextlib
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "rumahweb-admin"


class WriteSessionProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.username = "write-session-owner"
        cls.password = "synthetic-write-session-password"
        cls.password_hash = subprocess.check_output(
            ["php", "-r", f"echo password_hash('{cls.password}', PASSWORD_DEFAULT);"],
            text=True,
        )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="hollawall-write-session-test-")
        self.account_root = Path(self._tmp.name)
        self.web_root = self.account_root / "public_html"
        shutil.copytree(TEMPLATE, self.web_root / "admin")
        self.config = self.account_root / ".hollawall-admin.php"
        self.write_config()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_config(self, *, enabled: bool | None = None, username: str | None = None) -> None:
        enabled_config = (
            ""
            if enabled is None
            else f"'transaction_writes_enabled'=>{'true' if enabled else 'false'},"
        )
        self.config.write_text(
            "<?php return ["
            f"'username'=>'{username or self.username}',"
            f"'password_hash'=>'{self.password_hash}',"
            "'proxy_token'=>'synthetic-server-token-0001',"
            "'upstream_snapshot_url'=>'https://example.invalid/snapshot',"
            f"{enabled_config}"
            "'upstream_transactions_url'=>'https://example.invalid/transactions'];",
            encoding="utf-8",
        )

    @contextlib.contextmanager
    def php_server(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "HOLLAWALL_ADMIN_CONFIG": str(self.config)}
        process = subprocess.Popen(
            ["php", "-S", f"127.0.0.1:{port}", "-t", str(self.web_root)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}/admin/"
        try:
            for _ in range(50):
                try:
                    requests.get(base, timeout=0.25)
                    break
                except requests.RequestException:
                    time.sleep(0.05)
            else:
                self.fail("PHP test server did not become ready")
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    @staticmethod
    def cookie(session_id: str) -> dict[str, str]:
        return {"Cookie": f"hollawall_admin={session_id}"}

    def login(self, base: str) -> str:
        first = requests.get(base, timeout=5)
        session_id = first.cookies.get("hollawall_admin")
        self.assertTrue(session_id)
        match = re.search(r'name="csrf" value="([^"]+)"', first.text)
        self.assertIsNotNone(match)
        assert match is not None
        response = requests.post(
            base,
            headers=self.cookie(str(session_id)),
            data={
                "username": self.username,
                "password": self.password,
                "csrf": match.group(1),
            },
            allow_redirects=False,
            timeout=5,
        )
        self.assertEqual(response.status_code, 303)
        authenticated_id = response.cookies.get("hollawall_admin")
        self.assertTrue(authenticated_id)
        return str(authenticated_id)

    @staticmethod
    def endpoint(base: str) -> str:
        return base + "api/write-session.php"

    def test_get_owner_returns_default_disabled_contract(self) -> None:
        with self.php_server() as base:
            session_id = self.login(base)

            response = requests.get(
                self.endpoint(base),
                headers=self.cookie(session_id),
                timeout=5,
            )

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload["api_version"], "dashboard.v1")
            self.assertIsInstance(payload["data"]["csrf_token"], str)
            self.assertTrue(payload["data"]["csrf_token"])
            self.assertEqual(
                payload["data"]["capabilities"],
                {
                    "writes_enabled": False,
                    "canonical_finance_writes_enabled": False,
                    "canonical_debt_writes_enabled": False,
                },
            )
            self.assertIn("no-store", response.headers["Cache-Control"])

    def test_csrf_token_is_stable_for_the_same_session(self) -> None:
        with self.php_server() as base:
            session_id = self.login(base)
            headers = self.cookie(session_id)

            first = requests.get(self.endpoint(base), headers=headers, timeout=5)
            second = requests.get(self.endpoint(base), headers=headers, timeout=5)

            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(
                second.json()["data"]["csrf_token"],
                first.json()["data"]["csrf_token"],
            )

    def test_get_without_authenticated_session_returns_401(self) -> None:
        with self.php_server() as base:
            response = requests.get(self.endpoint(base), timeout=5)

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_get_rejects_authenticated_session_for_mismatched_owner(self) -> None:
        with self.php_server() as base:
            session_id = self.login(base)
            self.write_config(enabled=False, username="different-owner")

            response = requests.get(
                self.endpoint(base),
                headers=self.cookie(session_id),
                timeout=5,
            )

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "owner_required")

    def test_post_returns_405_and_allows_get(self) -> None:
        with self.php_server() as base:
            response = requests.post(self.endpoint(base), timeout=5)

            self.assertEqual(response.status_code, 405)
            self.assertEqual(response.headers.get("Allow"), "GET")
            self.assertEqual(response.json()["error"]["code"], "method_not_allowed")

    def test_get_reports_writes_enabled_when_config_is_true(self) -> None:
        self.write_config(enabled=True)
        with self.php_server() as base:
            session_id = self.login(base)

            response = requests.get(
                self.endpoint(base),
                headers=self.cookie(session_id),
                timeout=5,
            )

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                response.json()["data"]["capabilities"],
                {
                    "writes_enabled": True,
                    "canonical_finance_writes_enabled": False,
                    "canonical_debt_writes_enabled": False,
                },
            )


if __name__ == "__main__":
    unittest.main()
