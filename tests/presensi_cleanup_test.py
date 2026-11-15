from __future__ import annotations

import importlib.util
import io
import json
from ftplib import error_perm
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "cleanup_rumahweb_presensi_events.py"
    spec = importlib.util.spec_from_file_location("presensi_cleanup", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeFTP:
    def __init__(
        self,
        files: dict[str, bytes],
        *,
        fail_rename: tuple[str, str] | None = None,
        fail_delete_contains: str | None = None,
    ):
        self.files = dict(files)
        self.fail_rename = fail_rename
        self.fail_delete_contains = fail_delete_contains
        self.modes: dict[str, int] = {}

    def retrbinary(self, command: str, callback):
        callback(self.files[command.removeprefix("RETR ")])

    def storbinary(self, command: str, stream: io.BytesIO):
        path = command.removeprefix("STOR ")
        self.files[path] = stream.read()
        self.modes[path] = 0o644

    def sendcmd(self, command: str):
        prefix = "SITE CHMOD 600 "
        if not command.startswith(prefix):
            raise RuntimeError("unsupported")
        self.modes[command.removeprefix(prefix)] = 0o600
        return "200"

    def size(self, path: str):
        if path not in self.files:
            raise error_perm("550 missing")
        return len(self.files[path])

    def rename(self, source: str, target: str):
        if self.fail_rename == (source, target):
            raise RuntimeError("rename failed")
        self.files[target] = self.files.pop(source)
        if source in self.modes:
            self.modes[target] = self.modes.pop(source)

    def delete(self, path: str):
        if self.fail_delete_contains and self.fail_delete_contains in path:
            raise RuntimeError("delete failed")
        del self.files[path]
        self.modes.pop(path, None)



def fixture():
    events = [
        {"id": "evt-111111111111111111111111", "photo_name": "evt-111111111111111111111111.jpg", "whatsapp_delivery": {"status": "sent"}},
        {"id": "evt-222222222222222222222222", "photo_name": "evt-222222222222222222222222.jpg", "whatsapp_delivery": {"status": "sent"}},
        {"id": "evt-333333333333333333333333", "photo_name": "evt-333333333333333333333333.jpg", "whatsapp_delivery": {"status": "pending"}},
    ]
    return {
        ".hollawall-presensi/events.json": (json.dumps(events) + "\n").encode(),
        ".hollawall-presensi/photos/evt-111111111111111111111111.jpg": b"one",
        ".hollawall-presensi/photos/evt-222222222222222222222222.jpg": b"two",
        ".hollawall-presensi/photos/evt-333333333333333333333333.jpg": b"three",
    }


def test_cleanup_removes_only_exact_sent_events_and_photos():
    module = load_module()
    ftp = FakeFTP(fixture())
    targets = {"evt-111111111111111111111111", "evt-222222222222222222222222"}

    result = module.cleanup_events(ftp, targets)

    remaining = json.loads(ftp.files[".hollawall-presensi/events.json"])
    assert [row["id"] for row in remaining] == ["evt-333333333333333333333333"]
    assert ".hollawall-presensi/photos/evt-111111111111111111111111.jpg" not in ftp.files
    assert ".hollawall-presensi/photos/evt-222222222222222222222222.jpg" not in ftp.files
    assert ".hollawall-presensi/photos/evt-333333333333333333333333.jpg" in ftp.files
    assert ftp.modes[".hollawall-presensi/events.json"] == 0o600
    assert result["removed_events"] == result["removed_photos"] == 2
    assert result["readback_clean"] is True


def test_cleanup_refuses_pending_delivery_before_mutation():
    module = load_module()
    files = fixture()
    ftp = FakeFTP(files)

    with pytest.raises(RuntimeError, match="WhatsApp status sent"):
        module.cleanup_events(ftp, {"evt-333333333333333333333333"})

    assert ftp.files == files


def test_cleanup_rolls_back_events_and_photos_on_activation_failure(monkeypatch):
    module = load_module()
    files = fixture()
    ftp = FakeFTP(files)
    original_rename = ftp.rename
    activations = 0

    def fail_activation(source: str, target: str):
        nonlocal activations
        if target == ".hollawall-presensi/events.json" and ".cleanup-next-" in source:
            activations += 1
            raise RuntimeError("activation failed")
        original_rename(source, target)

    monkeypatch.setattr(ftp, "rename", fail_activation)
    with pytest.raises(RuntimeError, match="activation failed"):
        module.cleanup_events(ftp, {"evt-111111111111111111111111"})

    assert activations == 1
    assert ftp.files[".hollawall-presensi/events.json"] == files[".hollawall-presensi/events.json"]
    assert ftp.files[".hollawall-presensi/photos/evt-111111111111111111111111.jpg"] == b"one"


def test_cleanup_restores_all_photos_when_quarantine_delete_fails():
    module = load_module()
    files = fixture()
    ftp = FakeFTP(files, fail_delete_contains="222222222222222222222222")

    with pytest.raises(RuntimeError, match="delete failed"):
        module.cleanup_events(
            ftp,
            {"evt-111111111111111111111111", "evt-222222222222222222222222"},
        )

    assert ftp.files[".hollawall-presensi/events.json"] == files[".hollawall-presensi/events.json"]
    assert ftp.files[".hollawall-presensi/photos/evt-111111111111111111111111.jpg"] == b"one"
    assert ftp.files[".hollawall-presensi/photos/evt-222222222222222222222222.jpg"] == b"two"


def test_event_id_parser_is_exact_and_bounded():
    module = load_module()
    assert module.safe_event_ids("evt-111111111111111111111111") == {"evt-111111111111111111111111"}
    with pytest.raises(ValueError):
        module.safe_event_ids("evt-short")
    with pytest.raises(ValueError):
        module.safe_event_ids("evt-111111111111111111111111,evt-111111111111111111111111")
