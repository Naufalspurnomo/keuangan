import contextlib
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "artifacts" / "rumahweb-admin-release" / "admin"
SESSION_LIFETIME = 2_592_000


class RumahwebAdminSessionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["python3", "scripts/build_rumahweb_admin_release.py"], cwd=ROOT, check=True)
        cls.username = "session-proof"
        cls.password = "synthetic-proof-only"
        cls.password_hash = subprocess.check_output(
            ["php", "-r", f"echo password_hash('{cls.password}', PASSWORD_DEFAULT);"], text=True
        )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="hollawall-session-test-")
        self.account_root = Path(self._tmp.name)
        self.web_root = self.account_root / "public_html"
        shutil.copytree(RELEASE, self.web_root / "admin")
        self.config = self.account_root / ".hollawall-admin.php"
        self.config.write_text(
            "<?php return ["
            f"'username'=>'{self.username}',"
            f"'password_hash'=>'{self.password_hash}',"
            "'proxy_token'=>'synthetic-proof-token',"
            "'upstream_snapshot_url'=>'https://example.invalid/snapshot'];",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @contextlib.contextmanager
    def server(self):
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
    def cookie_header(session_id: str) -> dict[str, str]:
        return {"Cookie": f"hollawall_admin={session_id}"}

    @staticmethod
    def csrf_from(html: str) -> str:
        match = re.search(r'name="csrf" value="([^"]+)"', html)
        if not match:
            raise AssertionError("CSRF token missing")
        return match.group(1)

    def login(self, base: str) -> tuple[str, str]:
        first = requests.get(base, timeout=5)
        prelogin_id = first.cookies.get("hollawall_admin")
        self.assertTrue(prelogin_id)
        assert prelogin_id is not None
        response = requests.post(
            base,
            headers=self.cookie_header(prelogin_id),
            data={"username": self.username, "password": self.password, "csrf": self.csrf_from(first.text)},
            allow_redirects=False,
            timeout=5,
        )
        self.assertEqual(response.status_code, 303)
        authenticated_id = response.cookies.get("hollawall_admin")
        self.assertTrue(authenticated_id)
        assert authenticated_id is not None
        self.assertNotEqual(prelogin_id, authenticated_id, "login must regenerate the session ID")
        cookie = response.headers.get("Set-Cookie", "").lower()
        self.assertIn("max-age=2592000", cookie)
        self.assertIn("secure", cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        return prelogin_id, authenticated_id

    def session_file(self, session_id: str) -> Path:
        path = self.account_root / ".hollawall-admin-sessions" / f"sess_{session_id}"
        self.assertTrue(path.is_file(), path)
        return path

    def session_csrf(self, session_id: str) -> str:
        data = self.session_file(session_id).read_text(encoding="utf-8")
        match = re.search(r'csrf\|s:\d+:"([^"]+)";', data)
        if not match:
            raise AssertionError("CSRF missing from PHP session")
        return match.group(1)

    @staticmethod
    def replace_session_int(path: Path, key: str, value: int) -> None:
        data = path.read_text(encoding="utf-8")
        replaced, count = re.subn(rf"{re.escape(key)}\|i:\d+;", f"{key}|i:{value};", data)
        if count != 1:
            raise AssertionError(f"Could not replace {key} in PHP session")
        path.write_text(replaced, encoding="utf-8")

    def test_persistent_session_renewal_restart_expiry_and_logout_replay(self) -> None:
        with self.server() as base:
            _, session_id = self.login(base)
            app = requests.get(base, headers=self.cookie_header(session_id), timeout=5)
            self.assertNotIn("Masuk ke dashboard", app.text)
            session_dir = self.account_root / ".hollawall-admin-sessions"
            self.assertEqual(stat.S_IMODE(session_dir.stat().st_mode), 0o700)
            session_path = self.session_file(session_id)
            self.replace_session_int(session_path, "cookie_renewed_at", int(time.time()) - 172_800)
            renewed = requests.get(base, headers=self.cookie_header(session_id), timeout=5)
            self.assertEqual(renewed.cookies.get("hollawall_admin"), session_id)
            self.assertIn("max-age=2592000", renewed.headers.get("Set-Cookie", "").lower())

        with self.server() as base:
            survived = requests.get(base, headers=self.cookie_header(session_id), timeout=5)
            self.assertNotIn("Masuk ke dashboard", survived.text, "session must survive a PHP process restart")
            csrf = self.session_csrf(session_id)
            logged_out = requests.post(
                base,
                headers=self.cookie_header(session_id),
                data={"logout": "1", "csrf": csrf},
                allow_redirects=False,
                timeout=5,
            )
            self.assertEqual(logged_out.status_code, 303)
            expired_cookie = logged_out.headers.get("Set-Cookie", "").lower()
            self.assertTrue("max-age=0" in expired_cookie or "expires=thu, 01 jan 1970" in expired_cookie)
            replay = requests.get(base, headers=self.cookie_header(session_id), timeout=5)
            self.assertIn("Masuk ke dashboard", replay.text, "logged-out session ID must not authenticate")

        with self.server() as base:
            _, expiring_id = self.login(base)
            expiring_path = self.session_file(expiring_id)
            self.replace_session_int(expiring_path, "last_seen", int(time.time()) - SESSION_LIFETIME - 1)
            expired = requests.get(base, headers=self.cookie_header(expiring_id), timeout=5)
            self.assertIn("Masuk ke dashboard", expired.text)
            replay = requests.get(base, headers=self.cookie_header(expiring_id), timeout=5)
            self.assertIn("Masuk ke dashboard", replay.text, "expired session ID must not be revived")

    def test_login_throttle_survives_cookie_reset_and_process_restart(self) -> None:
        def attempt(base: str, password: str):
            first = requests.get(base, timeout=5)
            session_id = first.cookies.get("hollawall_admin")
            self.assertTrue(session_id)
            return requests.post(
                base,
                headers=self.cookie_header(str(session_id)),
                data={"username": self.username, "password": password, "csrf": self.csrf_from(first.text)},
                allow_redirects=False,
                timeout=5,
            )

        with self.server() as base:
            for _ in range(3):
                response = attempt(base, "wrong-password")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Username atau password tidak cocok", response.text)

        with self.server() as base:
            for _ in range(2):
                response = attempt(base, "wrong-password")
                self.assertEqual(response.status_code, 200)

        with self.server() as base:
            blocked = attempt(base, self.password)
            self.assertEqual(blocked.status_code, 200)
            self.assertIn("Terlalu banyak percobaan", blocked.text)

        rate_file = self.account_root / ".hollawall-admin-login-rate.json"
        self.assertTrue(rate_file.is_file())
        self.assertEqual(stat.S_IMODE(rate_file.stat().st_mode), 0o600)

    def test_session_storage_is_private_and_fails_closed_for_unsafe_paths(self) -> None:
        session_dir = self.account_root / ".hollawall-admin-sessions"
        session_dir.mkdir(mode=0o777)
        session_dir.chmod(0o777)
        forged_id = "forgedsharedhostingsession"
        (session_dir / f"sess_{forged_id}").write_text(
            'hollawall_admin_user|s:5:"admin";last_seen|i:2000000000;', encoding="utf-8"
        )
        with self.server() as base:
            response = requests.get(base, headers=self.cookie_header(forged_id), timeout=5)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(stat.S_IMODE(session_dir.stat().st_mode), 0o777)
            self.assertNotIn("AUTHENTICATED_APP", response.text)

        shutil.rmtree(session_dir)
        outside = self.account_root / "outside-sessions"
        outside.mkdir()
        session_dir.symlink_to(outside, target_is_directory=True)
        with self.server() as base:
            response = requests.get(base, timeout=5)
            self.assertEqual(response.status_code, 503)

        session_dir.unlink()
        session_dir.write_text("not a directory", encoding="utf-8")
        with self.server() as base:
            response = requests.get(base, timeout=5)
            self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
