import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_rumahweb_presensi_atomic.py"


class FakeFTP:
    def __init__(self, directories: set[str], fail_rename: tuple[str, str] | None = None):
        self.directories = set(directories)
        self.fail_rename = fail_rename
        self.renames: list[tuple[str, str]] = []

    def rename(self, source: str, target: str) -> None:
        if self.fail_rename == (source, target):
            raise RuntimeError("injected rename failure")
        if source not in self.directories:
            raise RuntimeError(f"missing source: {source}")
        self.directories.remove(source)
        self.directories.add(target)
        self.renames.append((source, target))


def load_module():
    spec = importlib.util.spec_from_file_location("presensi_deployer", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load deployer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PresensiAtomicDeployTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.admin = root / "admin"
        self.absen = root / "absen"
        self.admin.mkdir()
        self.absen.mkdir()
        (self.admin / "index.php").write_text("admin", encoding="utf-8")
        (self.absen / "index.php").write_text("absen", encoding="utf-8")
        self.specs = [
            self.module.ReleaseSpec("admin", self.admin, "public_html/admin"),
            self.module.ReleaseSpec("absen", self.absen, "public_html/absen"),
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def patch_transport(self):
        def exists(ftp, path):
            return path in ftp.directories

        def prepare(ftp, prepared):
            ftp.directories.add(prepared.staging)
            return {"ok": True, "expected": len(prepared.manifest)}

        def readback(_ftp, _remote, manifest):
            return {"ok": True, "expected": len(manifest)}

        return patch.multiple(
            self.module,
            exists=exists,
            prepare_release=prepare,
            readback=readback,
            remove_tree=lambda ftp, path: ftp.directories.discard(path),
        )

    def test_success_activates_both_paths_and_preserves_both_backups(self) -> None:
        ftp = FakeFTP({"public_html/admin", "public_html/absen"})
        with self.patch_transport():
            result = self.module.deploy_pair(ftp, self.specs, "candidate", "20261031T170000Z")
        self.assertTrue(result["success"])
        self.assertEqual(result["activated"], ["admin", "absen"])
        self.assertIn("public_html/admin", ftp.directories)
        self.assertIn("public_html/absen", ftp.directories)
        self.assertIn("public_html/admin.__prev_20261031T170000Z", ftp.directories)
        self.assertIn("public_html/absen.__prev_20261031T170000Z", ftp.directories)

    def test_second_activation_failure_restores_both_live_paths(self) -> None:
        ftp = FakeFTP(
            {"public_html/admin", "public_html/absen"},
            fail_rename=("public_html/absen.__next_candidate", "public_html/absen"),
        )
        with self.patch_transport(), self.assertRaisesRegex(RuntimeError, "injected rename failure"):
            self.module.deploy_pair(ftp, self.specs, "candidate", "20261031T170000Z")
        self.assertIn("public_html/admin", ftp.directories)
        self.assertIn("public_html/absen", ftp.directories)
        self.assertNotIn("public_html/admin.__prev_20261031T170000Z", ftp.directories)
        self.assertNotIn("public_html/absen.__prev_20261031T170000Z", ftp.directories)
        self.assertIn("public_html/admin.__failed_20261031T170000Z", ftp.directories)

    def test_rejects_overlapping_or_unsafe_remote_paths(self) -> None:
        duplicate = [
            self.module.ReleaseSpec("a", self.admin, "public_html/admin"),
            self.module.ReleaseSpec("b", self.absen, "public_html/admin"),
        ]
        with self.assertRaisesRegex(ValueError, "unique"):
            self.module.prepare_specs(duplicate, "candidate", "20261031T170000Z")
        unsafe = [
            self.module.ReleaseSpec("a", self.admin, "public_html/../admin"),
            self.module.ReleaseSpec("b", self.absen, "public_html/absen"),
        ]
        with self.assertRaisesRegex(ValueError, "safe relative"):
            self.module.prepare_specs(unsafe, "candidate", "20261031T170000Z")


if __name__ == "__main__":
    unittest.main()
