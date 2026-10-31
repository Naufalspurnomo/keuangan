import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ABSEN = ROOT / "artifacts" / "rumahweb-presensi-release" / "absen"
ADMIN = ROOT / "artifacts" / "rumahweb-admin-release" / "admin"


class PresensiReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["python3", "scripts/build_rumahweb_presensi_release.py"], cwd=ROOT, check=True)
        subprocess.run(["python3", "scripts/build_rumahweb_admin_release.py"], cwd=ROOT, check=True)

    def test_employee_release_has_camera_location_and_no_gallery_fallback(self) -> None:
        page = (ABSEN / "presensi" / "index.php").read_text(encoding="utf-8")
        script = (ABSEN / "assets" / "presensi.js").read_text(encoding="utf-8")
        self.assertIn("Presensi Hollawall", page)
        self.assertIn("navigator.mediaDevices.getUserMedia", script)
        self.assertIn("facingMode", script)
        self.assertIn("navigator.geolocation.getCurrentPosition", script)
        self.assertIn("enableHighAccuracy: true", script)
        self.assertNotIn('type="file"', page)
        self.assertNotIn("webkitdirectory", page)
        self.assertNotIn("localStorage", script)

    def test_public_api_and_admin_api_share_private_store_contract(self) -> None:
        for path in (
            ABSEN / "api" / "bootstrap.php",
            ABSEN / "api" / "status.php",
            ABSEN / "api" / "submit.php",
            ABSEN / "api" / "presensi-common.php",
            ADMIN / "api" / "presensi.php",
            ADMIN / "api" / "presensi-photo.php",
            ADMIN / "api" / "presensi-common.php",
            ABSEN / "bin" / "purge.php",
        ):
            self.assertTrue(path.is_file(), path)
        submit = (ABSEN / "api" / "submit.php").read_text(encoding="utf-8")
        common = (ABSEN / "api" / "presensi-common.php").read_text(encoding="utf-8")
        photo = (ADMIN / "api" / "presensi-photo.php").read_text(encoding="utf-8")
        admin_common = (ADMIN / "api" / "presensi-common.php").read_text(encoding="utf-8")
        self.assertIn("hash_equals", submit)
        self.assertIn("haversine", common.lower())
        self.assertIn("flock", common)
        self.assertIn("finfo", common)
        self.assertIn("getimagesizefromstring", common)
        self.assertIn(".hollawall-presensi", common)
        self.assertNotIn("public_html/.hollawall-presensi", common)
        self.assertIn("presensi_admin_session", photo)
        self.assertIn("hollawall_admin_user", admin_common)
        self.assertIn("X-Content-Type-Options", photo)

    def test_release_manifests_cover_every_file(self) -> None:
        for root, payload in ((ABSEN.parent, ABSEN), (ADMIN.parent, ADMIN)):
            manifest = root / "SHA256SUMS"
            self.assertTrue(manifest.is_file(), manifest)
            rows = [line.split("  ", 1)[1] for line in manifest.read_text(encoding="utf-8").splitlines()]
            files = [path.relative_to(payload).as_posix() for path in sorted(payload.rglob("*")) if path.is_file()]
            self.assertEqual(rows, files)

    def test_employee_primary_actions_use_accessible_ink_on_orange(self) -> None:
        css = (ABSEN / "assets" / "presensi.css").read_text(encoding="utf-8")
        self.assertIn(".primary-button { color: var(--ink); background: var(--orange); }", css)
        submit = css.split(".submit-button {", 2)[2].split("}", 1)[0]
        self.assertIn("color: var(--ink);", submit)
        self.assertIn(".submit-button small { color: var(--ink);", css)
        self.assertIn("button:disabled { cursor: not-allowed; opacity: 1; }", css)
        self.assertIn(".submit-button:disabled { color: #4b5563; background: #dedbd5;", css)

    def test_release_contains_no_runtime_data_or_secret(self) -> None:
        forbidden_names = {"events.json", "rate-limits.json", ".hollawall-presensi.php"}
        for release in (ABSEN, ADMIN):
            self.assertFalse(any(path.name in forbidden_names for path in release.rglob("*")))
            for path in release.rglob("*"):
                if not path.is_file():
                    continue
                body = path.read_bytes()
                self.assertNotIn(b"synthetic-proof-token", body, str(path))
                self.assertNotIn(b"RW_FTP_PASSWORD", body, str(path))


if __name__ == "__main__":
    unittest.main()
