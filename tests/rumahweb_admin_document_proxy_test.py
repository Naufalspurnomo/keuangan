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
from urllib.parse import parse_qs, urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "rumahweb-admin"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"
IDEMPOTENCY_KEY = "project-proxy-key-0001"
PDF_BYTES = b"%PDF-1.4\nsynthetic persisted pdf\n%%EOF\n"


class _UpstreamHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ProjectDocumentUpstream/1"

    def _handle(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.received.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        status, content_type, payload = self.server.responses.pop(0)  # type: ignore[attr-defined]
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle

    def log_message(self, format, *args):
        return


class RumahwebAdminProjectDocumentProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.username = "proxy-owner"
        cls.password = "synthetic-project-proxy-password"
        cls.password_hash = subprocess.check_output(
            ["php", "-r", f"echo password_hash('{cls.password}', PASSWORD_DEFAULT);"],
            text=True,
        )

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hollawall-project-proxy-")
        self.account_root = Path(self._tmp.name)
        self.web_root = self.account_root / "public_html"
        shutil.copytree(TEMPLATE, self.web_root / "admin")
        self.config = self.account_root / ".hollawall-admin.php"
        self.write_config(enabled=False)

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(
        self,
        *,
        enabled: bool,
        projects: str = "https://example.invalid/api/dashboard/v1/projects",
        documents: str = "https://example.invalid/api/dashboard/v1/documents",
        public_origin: str = "https://finance.example.test",
    ):
        self.config.write_text(
            "<?php return ["
            f"'username'=>'{self.username}',"
            f"'password_hash'=>'{self.password_hash}',"
            "'proxy_token'=>'synthetic-server-token-0001',"
            "'upstream_snapshot_url'=>'https://example.invalid/snapshot',"
            "'transaction_writes_enabled'=>false,"
            "'upstream_transactions_url'=>'https://example.invalid/transactions',"
            f"'project_document_writes_enabled'=>{'true' if enabled else 'false'},"
            f"'public_origin'=>'{public_origin}',"
            f"'upstream_projects_url'=>'{projects}',"
            f"'upstream_documents_url'=>'{documents}'];",
            encoding="utf-8",
        )

    @contextlib.contextmanager
    def php_server(self, *, ca_bundle=None):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "HOLLAWALL_ADMIN_CONFIG": str(self.config)}
        command = ["php"]
        if ca_bundle is not None:
            command += ["-d", f"curl.cainfo={ca_bundle}"]
        command += ["-S", f"127.0.0.1:{port}", "-t", str(self.web_root)]
        process = subprocess.Popen(
            command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
                self.fail("PHP server did not become ready")
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
            root = f"https://localhost:{server.server_port}/api/dashboard/v1"
            yield root, cert, server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @staticmethod
    def cookie(session_id):
        return {"Cookie": f"hollawall_admin={session_id}"}

    def login(self, base):
        first = requests.get(base, timeout=5)
        session_id = first.cookies.get("hollawall_admin")
        match = re.search(r'name="csrf" value="([^"]+)"', first.text)
        self.assertTrue(session_id and match)
        response = requests.post(
            base,
            headers=self.cookie(session_id),
            data={"username": self.username, "password": self.password, "csrf": match.group(1)},
            allow_redirects=False,
            timeout=5,
        )
        self.assertEqual(response.status_code, 303)
        authenticated_id = response.cookies.get("hollawall_admin")
        session_data = (
            self.account_root / ".hollawall-admin-sessions" / f"sess_{authenticated_id}"
        ).read_text(encoding="utf-8")
        csrf = re.search(r'csrf\|s:\d+:"([^"]+)";', session_data)
        self.assertIsNotNone(csrf)
        return authenticated_id, csrf.group(1)

    def test_proxy_timeout_covers_cold_backend_document_rendering(self):
        source = (TEMPLATE / "api" / "project-document-proxy.php").read_text(encoding="utf-8")
        timeout = re.search(r"CURLOPT_TIMEOUT\s*=>\s*(\d+)", source)
        connect_timeout = re.search(r"CURLOPT_CONNECTTIMEOUT\s*=>\s*(\d+)", source)
        self.assertIsNotNone(timeout)
        self.assertIsNotNone(connect_timeout)
        self.assertGreaterEqual(int(timeout.group(1)), 75)
        self.assertGreaterEqual(int(connect_timeout.group(1)), 10)
        self.assertLess(int(connect_timeout.group(1)), int(timeout.group(1)))

    @staticmethod
    def success(data):
        return {
            "api_version": "dashboard.v1",
            "data": data,
            "meta": {"capabilities": {
                "reads_enabled": True,
                "project_document_writes_enabled": True,
                "transaction_correction_reversal": False,
                "hard_delete": False,
            }},
        }

    def test_auth_default_gate_methods_no_store_and_allowlisted_actions(self):
        with self.php_server() as base:
            projects = base + "api/projects.php"
            documents = base + "api/documents.php"
            self.assertEqual(requests.put(projects, timeout=5).status_code, 405)
            self.assertEqual(requests.delete(documents, timeout=5).status_code, 405)
            unauth = requests.get(projects, params={"action": "list"}, timeout=5)
            self.assertEqual(unauth.status_code, 401)

            session_id, csrf = self.login(base)
            headers = {
                **self.cookie(session_id),
                "Origin": base.removesuffix("/admin/"),
                "Sec-Fetch-Site": "same-origin",
                "X-CSRF-Token": csrf,
                "Idempotency-Key": IDEMPOTENCY_KEY,
                "If-Match": "*",
            }
            invalid = requests.get(
                projects,
                headers=self.cookie(session_id),
                params={"action": "delete", "project_id": PROJECT_ID},
                timeout=5,
            )
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(invalid.json()["error"]["code"], "invalid_action")

            disabled = requests.post(
                projects,
                headers=headers,
                json={"action": "create", "idempotency_key": IDEMPOTENCY_KEY, "values": {}},
                timeout=5,
            )
            self.assertEqual(disabled.status_code, 503)
            self.assertEqual(disabled.json()["error"]["code"], "project_document_writes_disabled")
            self.assertIn("no-store", disabled.headers["Cache-Control"])

    def test_read_capabilities_intersect_upstream_with_local_write_gate(self):
        responses = [(200, "application/json", self.success({"items": []}))]
        with self.https_upstream(responses) as (root, cert, _server):
            with self.php_server(ca_bundle=cert) as base:
                self.write_config(
                    enabled=False,
                    projects=root + "/projects",
                    documents=root + "/documents",
                    public_origin=base.removesuffix("/admin/"),
                )
                session_id, _csrf = self.login(base)
                response = requests.get(
                    base + "api/projects.php",
                    headers=self.cookie(session_id),
                    params={"action": "list"},
                    timeout=5,
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertFalse(
                    response.json()["meta"]["capabilities"]
                    ["project_document_writes_enabled"]
                )

    def test_project_read_and_write_routes_are_exact_and_headers_sanitized(self):
        responses = [
            (200, "application/json", self.success({"items": [{"id": PROJECT_ID}]})),
            (200, "application/json", self.success({"id": PROJECT_ID, "lock_version": 3})),
            (201, "application/json", self.success({"project": {"id": PROJECT_ID}, "sales_order": {"id": DOCUMENT_ID}})),
            (200, "application/json", self.success({"id": PROJECT_ID, "lock_version": 4})),
            (200, "application/json", self.success({"id": PROJECT_ID, "status": "active", "lock_version": 4})),
            (200, "application/json", self.success({"id": PROJECT_ID, "status": "cancelled", "lock_version": 4})),
            (200, "application/json", self.success({"items": [{"event_type": "project.updated"}]})),
        ]
        with self.https_upstream(responses) as (root, cert, server):
            with self.php_server(ca_bundle=cert) as base:
                origin = base.removesuffix("/admin/")
                self.write_config(
                    enabled=True,
                    projects=root + "/projects",
                    documents=root + "/documents",
                    public_origin=origin,
                )
                session_id, csrf = self.login(base)
                endpoint = base + "api/projects.php"
                cookie = self.cookie(session_id)
                self.assertEqual(requests.get(endpoint, headers=cookie, params={"action": "list"}, timeout=5).status_code, 200)
                self.assertEqual(requests.get(endpoint, headers=cookie, params={"action": "get", "project_id": PROJECT_ID}, timeout=5).status_code, 200)

                write = {
                    **cookie,
                    "Origin": origin,
                    "Sec-Fetch-Site": "same-origin",
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": IDEMPOTENCY_KEY,
                }
                create_body = {"action": "create", "idempotency_key": IDEMPOTENCY_KEY, "values": {"name": "A"}}
                created = requests.post(endpoint, headers={**write, "If-Match": "*"}, json=create_body, timeout=5)
                self.assertEqual(created.status_code, 201, created.text)
                update_body = {"action": "update", "project_id": PROJECT_ID, "idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3, "changes": {"name": "B"}}
                self.assertEqual(requests.post(endpoint, headers={**write, "If-Match": '"3"'}, json=update_body, timeout=5).status_code, 200)
                status_body = {"action": "status", "project_id": PROJECT_ID, "idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3, "status": "active"}
                self.assertEqual(requests.post(endpoint, headers={**write, "If-Match": '"3"'}, json=status_body, timeout=5).status_code, 200)
                archive_body = {"action": "archive", "project_id": PROJECT_ID, "idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3}
                self.assertEqual(requests.post(endpoint, headers={**write, "If-Match": '"3"'}, json=archive_body, timeout=5).status_code, 200)
                self.assertEqual(requests.get(endpoint, headers=cookie, params={"action": "audit", "project_id": PROJECT_ID}, timeout=5).status_code, 200)

            self.assertEqual(
                [(item["method"], urlparse(item["path"]).path) for item in server.received],
                [
                    ("GET", "/api/dashboard/v1/projects"),
                    ("GET", f"/api/dashboard/v1/projects/{PROJECT_ID}"),
                    ("POST", "/api/dashboard/v1/projects"),
                    ("PATCH", f"/api/dashboard/v1/projects/{PROJECT_ID}"),
                    ("POST", f"/api/dashboard/v1/projects/{PROJECT_ID}/status"),
                    ("POST", f"/api/dashboard/v1/projects/{PROJECT_ID}/archive"),
                    ("GET", f"/api/dashboard/v1/projects/{PROJECT_ID}/audit"),
                ],
            )
            forwarded = server.received[2]
            self.assertNotIn("action", json.loads(forwarded["body"]))
            headers = {key.casefold(): value for key, value in forwarded["headers"].items()}
            self.assertEqual(headers["x-hollawall-proxy-token"], "synthetic-server-token-0001")
            self.assertEqual(headers["idempotency-key"], IDEMPOTENCY_KEY)
            self.assertNotIn("cookie", headers)
            self.assertNotIn("x-csrf-token", headers)

    def test_document_routes_pdf_binary_and_upstream_error_sanitization(self):
        responses = [
            (200, "application/json", self.success({"items": [{"id": DOCUMENT_ID}]})),
            (200, "application/json", self.success({"id": DOCUMENT_ID})),
            (201, "application/json", self.success({"id": DOCUMENT_ID, "document_type": "invoice"})),
            (201, "application/json", self.success({"id": DOCUMENT_ID, "document_type": "receipt"})),
            (200, "application/json", self.success({"id": DOCUMENT_ID, "lock_version": 5})),
            (200, "application/json", self.success({"id": DOCUMENT_ID, "status": "issued"})),
            (200, "application/json", self.success({"id": DOCUMENT_ID, "status": "void"})),
            (201, "application/json", self.success({"id": DOCUMENT_ID, "revision_of_id": DOCUMENT_ID})),
            (200, "application/json", self.success({"items": [{"event_type": "document.issued"}]})),
            (200, "application/pdf", PDF_BYTES),
            (409, "application/json", {"error": {"code": "project_document_conflict", "message": "Conflict", "trace": "secret"}, "debug": "secret"}),
        ]
        with self.https_upstream(responses) as (root, cert, server):
            with self.php_server(ca_bundle=cert) as base:
                origin = base.removesuffix("/admin/")
                self.write_config(enabled=True, projects=root + "/projects", documents=root + "/documents", public_origin=origin)
                session_id, csrf = self.login(base)
                endpoint = base + "api/documents.php"
                cookie = self.cookie(session_id)
                write = {**cookie, "Origin": origin, "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": csrf, "Idempotency-Key": IDEMPOTENCY_KEY}
                self.assertEqual(requests.get(endpoint, headers=cookie, params={"action": "list", "project_id": PROJECT_ID}, timeout=5).status_code, 200)
                self.assertEqual(requests.get(endpoint, headers=cookie, params={"action": "get", "document_id": DOCUMENT_ID}, timeout=5).status_code, 200)

                creates = [
                    {"action": "create_invoice", "project_id": PROJECT_ID, "idempotency_key": IDEMPOTENCY_KEY, "kind": "DP", "values": {}},
                    {"action": "create_receipt", "project_id": PROJECT_ID, "idempotency_key": IDEMPOTENCY_KEY, "allocations": [{"source_key": "sheet:1", "amount": 1000}], "values": {}},
                ]
                for body in creates:
                    response = requests.post(endpoint, headers={**write, "If-Match": "*"}, json=body, timeout=5)
                    self.assertEqual(response.status_code, 201, response.text)
                actions = [
                    ("update", {"changes": {"notes": "X"}}, 200),
                    ("issue", {}, 200),
                    ("void", {"reason": "Cancelled"}, 200),
                    ("revise", {}, 201),
                ]
                for action, extra, expected in actions:
                    body = {"action": action, "document_id": DOCUMENT_ID, "idempotency_key": IDEMPOTENCY_KEY, "expected_version": 4, **extra}
                    response = requests.post(endpoint, headers={**write, "If-Match": '"4"'}, json=body, timeout=5)
                    self.assertEqual(response.status_code, expected, response.text)
                self.assertEqual(requests.get(endpoint, headers=cookie, params={"action": "audit", "document_id": DOCUMENT_ID}, timeout=5).status_code, 200)
                pdf = requests.get(endpoint, headers=cookie, params={"action": "download", "document_id": DOCUMENT_ID}, timeout=5)
                self.assertEqual(pdf.status_code, 200)
                self.assertEqual(pdf.content, PDF_BYTES)
                self.assertEqual(pdf.headers["Content-Type"], "application/pdf")
                self.assertIn("attachment", pdf.headers["Content-Disposition"])
                self.assertIn("no-store", pdf.headers["Cache-Control"])

                conflict_body = {"action": "issue", "document_id": DOCUMENT_ID, "idempotency_key": IDEMPOTENCY_KEY, "expected_version": 4}
                conflict = requests.post(endpoint, headers={**write, "If-Match": '"4"'}, json=conflict_body, timeout=5)
                self.assertEqual(conflict.status_code, 409)
                self.assertEqual(conflict.json(), {"error": {"code": "project_document_conflict", "message": "Conflict"}})
                self.assertNotIn("secret", conflict.text)

    def test_same_origin_csrf_json_idempotency_if_match_and_limits_fail_closed(self):
        with self.php_server() as base:
            origin = base.removesuffix("/admin/")
            self.write_config(enabled=True, public_origin=origin)
            session_id, csrf = self.login(base)
            endpoint = base + "api/projects.php"
            cookie = self.cookie(session_id)
            body = {"action": "update", "project_id": PROJECT_ID, "idempotency_key": IDEMPOTENCY_KEY, "expected_version": 3, "changes": {"name": "B"}}
            valid = {**cookie, "Origin": origin, "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": csrf, "Idempotency-Key": IDEMPOTENCY_KEY, "If-Match": '"3"'}

            cases = [
                ({**valid, "Origin": "https://evil.example"}, body, 403, "same_origin_required"),
                ({k: v for k, v in valid.items() if k != "X-CSRF-Token"}, body, 403, "csrf_validation_failed"),
                ({k: v for k, v in valid.items() if k != "Idempotency-Key"}, body, 422, "idempotency_key_required"),
                ({k: v for k, v in valid.items() if k != "If-Match"}, body, 428, "if_match_required"),
                ({**valid, "If-Match": '"2"'}, body, 412, "if_match_failed"),
            ]
            for headers, payload, status, code in cases:
                response = requests.post(endpoint, headers=headers, json=payload, timeout=5)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)

            wrong_type = requests.post(endpoint, headers={**valid, "Content-Type": "text/plain"}, data="{}", timeout=5)
            self.assertEqual(wrong_type.status_code, 415)
            malformed = requests.post(endpoint, headers={**valid, "Content-Type": "application/json"}, data="{", timeout=5)
            self.assertEqual(malformed.status_code, 422)
            oversized = requests.post(endpoint, headers=valid, json={"padding": "x" * 300000}, timeout=5)
            self.assertEqual(oversized.status_code, 413)


class RumahwebAdminProjectDocumentStaticTests(unittest.TestCase):
    def test_config_exposes_independent_default_off_gate_and_explicit_upstreams(self):
        text = (TEMPLATE / "config.example.php").read_text(encoding="utf-8")
        self.assertRegex(text, r"'project_document_writes_enabled'\s*=>\s*false")
        self.assertIn("'upstream_projects_url'", text)
        self.assertIn("'upstream_documents_url'", text)
        self.assertIn("'public_origin'", text)

    def test_proxy_source_contains_no_hard_delete_or_cash_mutation_action(self):
        for name in ("projects.php", "documents.php"):
            text = (TEMPLATE / "api" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"['\"](?:delete|correct_transaction|reverse_transaction)['\"]\s*=>")
            self.assertIn("Cache-Control: no-store", text)


if __name__ == "__main__":
    unittest.main()
