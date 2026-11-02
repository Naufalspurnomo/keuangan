import contextlib
import http.server
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "rumahweb-admin"
IDEMPOTENCY_KEY = "proxy-test-key-0001"


class _UpstreamHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SyntheticUpstream/1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.received.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        status, payload = self.server.responses.pop(0)  # type: ignore[attr-defined]
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


class RumahwebAdminTransactionProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.username = "proxy-owner"
        cls.password = "synthetic-proxy-password"
        cls.password_hash = subprocess.check_output(
            ["php", "-r", f"echo password_hash('{cls.password}', PASSWORD_DEFAULT);"],
            text=True,
        )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="hollawall-proxy-test-")
        self.account_root = Path(self._tmp.name)
        self.web_root = self.account_root / "public_html"
        shutil.copytree(TEMPLATE, self.web_root / "admin")
        self.config = self.account_root / ".hollawall-admin.php"
        self.write_config(enabled=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_config(self, *, enabled: bool, upstream: str = "https://example.invalid/transactions") -> None:
        self.config.write_text(
            "<?php return ["
            f"'username'=>'{self.username}',"
            f"'password_hash'=>'{self.password_hash}',"
            "'proxy_token'=>'synthetic-server-token-0001',"
            "'upstream_snapshot_url'=>'https://example.invalid/snapshot',"
            f"'transaction_writes_enabled'=>{'true' if enabled else 'false'},"
            f"'upstream_transactions_url'=>'{upstream}'];",
            encoding="utf-8",
        )

    @contextlib.contextmanager
    def php_server(self, *, ca_bundle: Path | None = None):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "HOLLAWALL_ADMIN_CONFIG": str(self.config)}
        if ca_bundle is not None:
            env["CURL_CA_BUNDLE"] = str(ca_bundle)
        process = subprocess.Popen(
            ["php", *(["-d", f"curl.cainfo={ca_bundle}"] if ca_bundle is not None else []), "-S", f"127.0.0.1:{port}", "-t", str(self.web_root)],
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

    @contextlib.contextmanager
    def https_upstream(self, responses):
        cert = self.account_root / "localhost-cert.pem"
        key = self.account_root / "localhost-key.pem"
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "1",
                "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        server.responses = list(responses)
        server.received = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"https://localhost:{server.server_port}/api/dashboard/v1/transactions", cert, server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @staticmethod
    def cookie(session_id: str) -> dict[str, str]:
        return {"Cookie": f"hollawall_admin={session_id}"}

    def login(self, base: str) -> tuple[str, str]:
        first = requests.get(base, timeout=5)
        session_id = first.cookies.get("hollawall_admin")
        self.assertTrue(session_id)
        match = re.search(r'name="csrf" value="([^"]+)"', first.text)
        self.assertIsNotNone(match)
        response = requests.post(
            base,
            headers=self.cookie(str(session_id)),
            data={"username": self.username, "password": self.password, "csrf": match.group(1)},
            allow_redirects=False,
            timeout=5,
        )
        self.assertEqual(response.status_code, 303)
        authenticated_id = response.cookies.get("hollawall_admin")
        self.assertTrue(authenticated_id)
        session_data = (
            self.account_root / ".hollawall-admin-sessions" / f"sess_{authenticated_id}"
        ).read_text(encoding="utf-8")
        csrf = re.search(r'csrf\|s:\d+:"([^"]+)";', session_data)
        self.assertIsNotNone(csrf)
        return str(authenticated_id), csrf.group(1)

    @staticmethod
    def transaction_url(base: str) -> str:
        return base + "api/transactions.php"

    @staticmethod
    def payload(key: str = IDEMPOTENCY_KEY) -> dict:
        return {
            "idempotency_key": key,
            "date": "2026-11-02",
            "scope": "office",
            "direction": "Pengeluaran",
            "amount": 125000,
            "description": "Synthetic proxy test",
            "wallet": "BCA PT",
            "category": "Operasional",
            "company": "Hollawall",
            "project": None,
        }

    def test_post_owner_session_and_default_disabled_gate(self) -> None:
        with self.php_server() as base:
            endpoint = self.transaction_url(base)
            method = requests.get(endpoint, timeout=5)
            self.assertEqual(method.status_code, 405)
            self.assertEqual(method.headers.get("Allow"), "POST")
            unauthenticated = requests.post(endpoint, json=self.payload(), timeout=5)
            self.assertEqual(unauthenticated.status_code, 401)

            session_id, csrf = self.login(base)
            disabled = requests.post(
                endpoint,
                headers={
                    **self.cookie(session_id),
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": IDEMPOTENCY_KEY,
                },
                json=self.payload(),
                timeout=5,
            )
            self.assertEqual(disabled.status_code, 503)
            self.assertEqual(disabled.json()["error"]["code"], "transaction_writes_disabled")
            self.assertIn("no-store", disabled.headers["Cache-Control"])

    def test_csrf_json_idempotency_forwarding_and_sanitized_replies(self) -> None:
        success = {
            "api_version": "dashboard.v1",
            "data": {
                "recorded": True,
                "transaction_id": "sheet:Operasional:operasional:9",
                "sheet_name": "Operasional",
                "sheet_row": 9,
                "source_block": "operasional",
                "sheet_message_id": "dashboard:synthetic:hash",
                "internal_note": "must-not-leak",
            },
            "debug": {"proxy_token": "must-not-leak"},
        }
        failure = {
            "error": {
                "code": "invalid_transaction",
                "message": "Transaction request is invalid",
                "internal": "must-not-leak",
            },
            "trace": "must-not-leak",
        }
        with self.https_upstream([(201, success), (422, failure)]) as (upstream, cert, server):
            self.write_config(enabled=True, upstream=upstream)
            with self.php_server(ca_bundle=cert) as base:
                endpoint = self.transaction_url(base)
                session_id, csrf = self.login(base)
                cookie = self.cookie(session_id)

                missing_csrf = requests.post(
                    endpoint,
                    headers={**cookie, "Idempotency-Key": IDEMPOTENCY_KEY},
                    json=self.payload(),
                    timeout=5,
                )
                self.assertEqual(missing_csrf.status_code, 403)
                self.assertEqual(missing_csrf.json()["error"]["code"], "csrf_validation_failed")

                common = {
                    **cookie,
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": IDEMPOTENCY_KEY,
                }
                wrong_type = requests.post(endpoint, headers=common, data="{}", timeout=5)
                self.assertEqual(wrong_type.status_code, 422)
                self.assertEqual(wrong_type.json()["error"]["code"], "json_required")

                mismatch = requests.post(
                    endpoint,
                    headers=common,
                    json=self.payload("different-proxy-key-0002"),
                    timeout=5,
                )
                self.assertEqual(mismatch.status_code, 422)
                self.assertEqual(mismatch.json()["error"]["code"], "idempotency_key_mismatch")

                raw = json.dumps(self.payload(), separators=(",", ":")).encode()
                accepted = requests.post(
                    endpoint,
                    headers={**common, "Content-Type": "application/json"},
                    data=raw,
                    timeout=5,
                )
                self.assertEqual(accepted.status_code, 201, accepted.text)
                self.assertEqual(
                    accepted.json(),
                    {"api_version": "dashboard.v1", "data": {
                        "recorded": True,
                        "transaction_id": "sheet:Operasional:operasional:9",
                        "sheet_name": "Operasional",
                        "sheet_row": 9,
                        "source_block": "operasional",
                        "sheet_message_id": "dashboard:synthetic:hash",
                    }},
                )
                self.assertIn("no-store", accepted.headers["Cache-Control"])

                rejected = requests.post(
                    endpoint,
                    headers=common,
                    json=self.payload(),
                    timeout=5,
                )
                self.assertEqual(rejected.status_code, 422)
                self.assertEqual(
                    rejected.json(),
                    {"error": {"code": "invalid_transaction", "message": "Transaction request is invalid"}},
                )

            self.assertEqual(len(server.received), 2)
            first = server.received[0]
            self.assertEqual(first["path"], "/api/dashboard/v1/transactions")
            self.assertEqual(first["body"], raw)
            headers = {key.casefold(): value for key, value in first["headers"].items()}
            self.assertEqual(headers["idempotency-key"], IDEMPOTENCY_KEY)
            self.assertEqual(headers["x-hollawall-proxy-token"], "synthetic-server-token-0001")
            self.assertNotIn("x-csrf-token", headers)
            self.assertNotIn("cookie", headers)


if __name__ == "__main__":
    unittest.main()
