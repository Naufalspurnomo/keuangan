import os
import subprocess
import unittest
from pathlib import Path

from tests.release_test_support import build_release


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "artifacts" / "rumahweb-admin-release" / "admin"


class RumahwebAdminReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build_release(ROOT, "build_rumahweb_admin_release.py")

    def test_release_is_path_isolated(self) -> None:
        shell = (RELEASE / "app-shell.php").read_text(encoding="utf-8")
        self.assertIn("/admin/assets/", shell)
        self.assertNotIn('src="/assets/', shell)
        self.assertNotIn('href="/assets/', shell)
        self.assertNotIn("/live-api/snapshot", shell)
        self.assertFalse((ROOT / "artifacts" / "rumahweb-admin-release" / "index.php").exists())

    def test_release_has_login_and_read_only_proxy(self) -> None:
        login = (RELEASE / "index.php").read_text(encoding="utf-8")
        proxy = (RELEASE / "api" / "snapshot.php").read_text(encoding="utf-8")
        self.assertIn("Masuk ke dashboard", login)
        self.assertIn("brand/hollawall-logo.png", login)
        self.assertIn("brand/waves-background.svg", login)
        self.assertNotIn('class="mark">H', login)
        self.assertIn("password_verify", login)
        self.assertIn("method_not_allowed", proxy)
        self.assertIn("X-Hollawall-Proxy-Token", proxy)
        self.assertIn("CURLOPT_CONNECTTIMEOUT => 12", proxy)
        self.assertIn("CURLOPT_TIMEOUT => 75", proxy)

    def test_release_has_fail_closed_transaction_proxy(self) -> None:
        proxy = (RELEASE / "api" / "transactions.php").read_text(encoding="utf-8")
        self.assertIn("transaction_writes_enabled", proxy)
        self.assertIn("transaction_writes_disabled", proxy)
        self.assertIn("X-CSRF-Token", proxy)
        self.assertIn("Idempotency-Key", proxy)

    def test_release_has_fail_closed_canonical_debt_proxy(self) -> None:
        proxy = (RELEASE / "api" / "debts.php").read_text(encoding="utf-8")
        self.assertIn("canonical_debt_writes_enabled", proxy)
        self.assertIn("upstream_debts_url", proxy)
        self.assertIn("Idempotency-Key", proxy)
        self.assertIn("X-Hollawall-Actor-Assertion", proxy)
        self.assertIn("csrf_validation_failed", proxy)
        self.assertIn("/repayments", proxy)
        self.assertNotIn("CURLOPT_FOLLOWLOCATION => true", proxy)
        self.assertIn("X-Hollawall-Proxy-Token", proxy)
        self.assertIn("CURLOPT_FOLLOWLOCATION => false", proxy)
        self.assertIn("CURLOPT_SSL_VERIFYPEER => true", proxy)
        self.assertIn("Cache-Control: no-store", proxy)
        self.assertLess(proxy.index("session_write_close();"), proxy.index("$curl = curl_init($upstream);"))

    def test_login_session_is_secure_persistent_and_rolling(self) -> None:
        login = (RELEASE / "index.php").read_text(encoding="utf-8")
        proxy = (RELEASE / "api" / "snapshot.php").read_text(encoding="utf-8")
        for source in (login, proxy):
            self.assertIn("2592000", source)
            self.assertIn("session.gc_maxlifetime", source)
            self.assertIn(".hollawall-admin-sessions", source)
            self.assertIn("session_save_path() !== $sessionPath", source)
            self.assertIn("!session_start()", source)
            self.assertIn("fileperms($realSessionPath)", source)
            self.assertNotIn("chmod($realSessionPath, 0700)", source)
            self.assertIn("httponly", source)
            self.assertIn("samesite", source)
            self.assertNotIn("'lifetime' => 0", source)
        self.assertIn("cookie_renewed_at", login)
        self.assertIn("cookie_renewed_at", proxy)

    def test_release_sets_transport_security_headers(self) -> None:
        htaccess = (RELEASE / ".htaccess").read_text(encoding="utf-8")
        self.assertIn("Strict-Transport-Security", htaccess)
        self.assertIn("RewriteCond %{HTTPS} !=on", htaccess)
        self.assertIn("RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=301,L]", htaccess)
        self.assertIn("RewriteRule ^login/?$ index.php [L]", htaccess)
        self.assertIn("X-Content-Type-Options", htaccess)
        self.assertIn("X-Robots-Tag", htaccess)

    def test_release_contains_no_live_secret_or_config(self) -> None:
        self.assertFalse((RELEASE / "config.example.php").exists())
        self.assertFalse((RELEASE / ".hollawall-admin.php").exists())
        token_path = Path(
            os.environ.get(
                "HOLLAWALL_PROXY_TOKEN_PATH",
                "/root/.hermes/profiles/naufal/vault/hollawall-live-api-proxy-token",
            )
        )
        try:
            token = token_path.read_text().strip().encode() if token_path.is_file() else None
        except (OSError, PermissionError):
            token = None
        for path in RELEASE.rglob("*"):
            if path.is_file() and token:
                self.assertNotIn(token, path.read_bytes(), str(path))


if __name__ == "__main__":
    unittest.main()
