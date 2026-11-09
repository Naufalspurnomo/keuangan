from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "deploy" / "rumahweb-admin" / "api" / "inbox-reviews.php"
EVENT_KEY = "a" * 64
OWNER = "owner"
CSRF = "owner-csrf-token-0001"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(url: str, *, method: str = "GET", cookie: str = "", body: dict | None = None, headers: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    request_headers = dict(headers or {})
    if cookie:
        request_headers["Cookie"] = cookie
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    try:
        response = urllib.request.urlopen(request, timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    return response.status, json.loads(response.read())


@pytest.fixture
def proxy_server():
    if shutil.which("php") is None:
        pytest.skip("php CLI is unavailable")
    with tempfile.TemporaryDirectory() as temporary:
        account = Path(temporary)
        public = account / "public_html"
        api = public / "admin" / "api"
        api.mkdir(parents=True)
        shutil.copy2(PROXY, api / "inbox-reviews.php")
        session_path = account / ".hollawall-admin-sessions"
        session_path.mkdir(mode=0o700)
        config = account / ".hollawall-admin.php"
        config.write_text("""<?php return [
'username' => 'owner',
'proxy_token' => 'owner-proxy-token-0001',
'public_origin' => 'https://hollawall.test',
'inbox_review_writes_enabled' => false,
'upstream_inbox_reviews_url' => 'http://not-https.test/api/dashboard/v1/inbox/reviews',
];""")
        login = public / "admin" / "test-login.php"
        login.write_text(f"""<?php
ini_set('session.use_strict_mode', '1');
ini_set('session.use_only_cookies', '1');
session_name('hollawall_admin');
session_save_path({json.dumps(str(session_path))});
session_set_cookie_params(['path'=>'/admin/','secure'=>true,'httponly'=>true,'samesite'=>'Strict']);
session_start();
$_SESSION['hollawall_admin_user'] = {json.dumps(OWNER)};
$_SESSION['csrf'] = {json.dumps(CSRF)};
echo json_encode(['ok'=>true]);
""")
        port = _free_port()
        environment = os.environ | {"HOLLAWALL_ADMIN_CONFIG": str(config)}
        process = subprocess.Popen(
            ["php", "-S", f"127.0.0.1:{port}", "-t", str(public)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                response = urllib.request.urlopen(base + "/admin/test-login.php", timeout=0.2)
                cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                break
            except Exception:
                time.sleep(0.05)
        else:
            process.terminate()
            raise RuntimeError("PHP test server did not start")
        try:
            yield base, cookie, config
        finally:
            process.terminate()
            process.wait(timeout=3)


def test_proxy_requires_owner_session(proxy_server):
    base, _cookie, _config = proxy_server
    status, body = _request(base + "/admin/api/inbox-reviews.php?action=list")
    assert status == 401
    assert body["error"]["code"] == "authentication_required"


def test_proxy_validates_https_upstream_before_any_request(proxy_server):
    base, cookie, _config = proxy_server
    status, body = _request(base + "/admin/api/inbox-reviews.php?action=list", cookie=cookie)
    assert status == 503
    assert body["error"]["code"] == "configuration_invalid"


def test_proxy_fails_closed_for_writes_before_network(proxy_server):
    base, cookie, config = proxy_server
    config.write_text("""<?php return [
'username' => 'owner', 'proxy_token' => 'owner-proxy-token-0001',
'public_origin' => 'https://hollawall.test', 'inbox_review_writes_enabled' => false,
'upstream_inbox_reviews_url' => 'https://example.invalid/api/dashboard/v1/inbox/reviews',
];""")
    status, body = _request(
        base + f"/admin/api/inbox-reviews.php?event_key={EVENT_KEY}",
        method="POST",
        cookie=cookie,
        body={"action": "ignore", "reason": "not finance", "expected_status": "needs_review"},
        headers={
            "Origin": "https://hollawall.test",
            "Sec-Fetch-Site": "same-origin",
            "X-CSRF-Token": CSRF,
            "Idempotency-Key": "review-command-0001",
        },
    )
    assert status == 503
    assert body["error"]["code"] == "review_writes_disabled"


def test_proxy_rejects_invalid_routes_origin_csrf_and_command_fields_before_network(proxy_server):
    base, cookie, config = proxy_server
    config.write_text("""<?php return [
'username' => 'owner', 'proxy_token' => 'owner-proxy-token-0001',
'public_origin' => 'https://hollawall.test', 'inbox_review_writes_enabled' => true,
'upstream_inbox_reviews_url' => 'https://example.invalid/api/dashboard/v1/inbox/reviews',
];""")
    list_extra = _request(base + "/admin/api/inbox-reviews.php?action=list&extra=1", cookie=cookie)
    bad_key = _request(base + "/admin/api/inbox-reviews.php?action=detail&event_key=not-a-key", cookie=cookie)
    cross_site = _request(
        base + f"/admin/api/inbox-reviews.php?event_key={EVENT_KEY}", method="POST", cookie=cookie,
        body={"action": "ignore", "reason": "x", "expected_status": "needs_review"},
        headers={"Origin": "https://evil.test", "Sec-Fetch-Site": "cross-site", "X-CSRF-Token": CSRF, "Idempotency-Key": "review-command-0001"},
    )
    unknown_field = _request(
        base + f"/admin/api/inbox-reviews.php?event_key={EVENT_KEY}", method="POST", cookie=cookie,
        body={"action": "ignore", "reason": "x", "expected_status": "needs_review", "retry": True},
        headers={"Origin": "https://hollawall.test", "Sec-Fetch-Site": "same-origin", "X-CSRF-Token": CSRF, "Idempotency-Key": "review-command-0001"},
    )
    assert list_extra == (422, {"error": {"code": "unsupported_fields", "message": "Request contains unsupported fields."}})
    assert bad_key[0] == 422 and bad_key[1]["error"]["code"] == "invalid_event_key"
    assert cross_site[0] == 403 and cross_site[1]["error"]["code"] == "same_origin_required"
    assert unknown_field[0] == 422 and unknown_field[1]["error"]["code"] == "unsupported_fields"


def test_proxy_source_pins_transport_caps_and_token_injection():
    source = PROXY.read_text()
    assert "CURLOPT_FOLLOWLOCATION => false" in source
    assert "CURLOPT_SSL_VERIFYPEER => true" in source
    assert "CURLOPT_SSL_VERIFYHOST => 2" in source
    assert "X-Hollawall-Proxy-Token: " in source
    assert re.search(r"IR_MAX_REQUEST_BYTES\s*=\s*\d+", source)
    assert re.search(r"IR_MAX_RESPONSE_BYTES\s*=\s*\d+", source)
    assert "retry" not in re.sub(r"automatic retry[^\n]*", "", source, flags=re.I).lower()
