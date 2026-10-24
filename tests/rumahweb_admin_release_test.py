import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "artifacts" / "rumahweb-admin-release" / "admin"


class RumahwebAdminReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["python3", "scripts/build_rumahweb_admin_release.py"], cwd=ROOT, check=True)

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

    def test_release_contains_no_live_secret_or_config(self) -> None:
        self.assertFalse((RELEASE / "config.example.php").exists())
        self.assertFalse((RELEASE / ".hollawall-admin.php").exists())
        token_path = Path("/root/.hermes/profiles/naufal/vault/hollawall-live-api-proxy-token")
        token = token_path.read_text().strip().encode() if token_path.exists() else None
        for path in RELEASE.rglob("*"):
            if path.is_file() and token:
                self.assertNotIn(token, path.read_bytes(), str(path))


if __name__ == "__main__":
    unittest.main()