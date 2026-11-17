from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "configure_rumahweb_admin_finance.py"


def load_module():
    spec = importlib.util.spec_from_file_location("finance_config", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finance_config_replaces_only_expected_values() -> None:
    module = load_module()
    original = """<?php
return [
  'upstream_canonical_transactions_url' => '',
  'canonical_finance_writes_enabled' => false,
  'dashboard_actor_assertion_audience' => '',
  'dashboard_actor_assertion_secret' => '',
  'owner_email' => 'owner@example.com',
];
"""
    updated = module.replace_php_value(
        original,
        "upstream_canonical_transactions_url",
        module.DEFAULT_CANONICAL_URL,
    )
    updated = module.replace_php_value(
        updated,
        "upstream_snapshot_url",
        module.DEFAULT_SNAPSHOT_URL,
    )
    updated = module.replace_php_value(
        updated,
        "dashboard_actor_assertion_audience",
        module.DEFAULT_AUDIENCE,
    )
    updated = module.replace_php_value(
        updated,
        "dashboard_actor_assertion_secret",
        "x" * 48,
    )
    updated = module.replace_php_bool(updated, "canonical_finance_writes_enabled", True)

    assert module.DEFAULT_CANONICAL_URL in updated
    assert module.DEFAULT_SNAPSHOT_URL in updated
    assert "'canonical_finance_writes_enabled' => true" in updated
    assert "'dashboard_actor_assertion_audience' => 'hollawall-finance-api'" in updated
    assert "'dashboard_actor_assertion_secret' => '" + ("x" * 48) + "'" in updated
    updated = module.replace_php_value(updated, "owner_email", "naufalspurnomo@gmail.com")
    assert "'owner_email' => 'naufalspurnomo@gmail.com'" in updated


def test_config_sync_requires_owner_scoped_proxy_token(monkeypatch):
    module = load_module()
    monkeypatch.delenv("HOLLAWALL_LIVE_API_PROXY_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="HOLLAWALL_LIVE_API_PROXY_TOKEN"):
        module.require_env("HOLLAWALL_LIVE_API_PROXY_TOKEN")


def test_finance_config_sets_presensi_canonical_project_catalog() -> None:
    module = load_module()
    source = "<?php\nreturn [\n  'employees' => [],\n];\n"
    updated = module.replace_php_value(source, "project_catalog_url", module.DEFAULT_PROJECT_CATALOG_URL)

    assert module.DEFAULT_PROJECT_CATALOG_URL in updated
    assert updated.count("project_catalog_url") == 1


class FakeFTP:
    def __init__(self, files: dict[str, bytes], fail_rename: tuple[str, str] | None = None):
        self.files = dict(files)
        self.fail_rename = fail_rename
        self.modes: dict[str, int] = {path: 0o600 for path in files}

    def size(self, path: str) -> int:
        if path not in self.files:
            raise FileNotFoundError(path)
        return len(self.files[path])

    def retrbinary(self, command: str, callback) -> None:
        callback(self.files[command.removeprefix("RETR ")])

    def storbinary(self, command: str, stream: io.BytesIO) -> None:
        path = command.removeprefix("STOR ")
        self.files[path] = stream.read()
        self.modes[path] = 0o644

    def sendcmd(self, command: str) -> str:
        prefix = "SITE CHMOD 600 "
        if not command.startswith(prefix):
            raise AssertionError(command)
        self.modes[command.removeprefix(prefix)] = 0o600
        return "200 Permissions changed"

    def rename(self, source: str, target: str) -> None:
        if self.fail_rename == (source, target):
            raise RuntimeError("synthetic activation failure")
        self.files[target] = self.files.pop(source)
        self.modes[target] = self.modes.pop(source)

    def delete(self, path: str) -> None:
        del self.files[path]
        self.modes.pop(path, None)


def test_finance_config_pair_activates_private_permissions() -> None:
    module = load_module()
    ftp = FakeFTP({"admin.php": b"admin-old", "presensi.php": b"presensi-old"})

    module.atomic_replace_many(
        ftp,
        [("admin.php", b"admin-new"), ("presensi.php", b"presensi-new")],
        "t0",
    )

    assert ftp.modes["admin.php"] == 0o600
    assert ftp.modes["presensi.php"] == 0o600


def test_finance_config_pair_rolls_back_first_target_when_second_activation_fails() -> None:
    module = load_module()
    ftp = FakeFTP(
        {"admin.php": b"admin-old", "presensi.php": b"presensi-old"},
        fail_rename=("presensi.php.__next_t1", "presensi.php"),
    )

    with pytest.raises(RuntimeError, match="synthetic activation failure"):
        module.atomic_replace_many(
            ftp,
            [("admin.php", b"admin-new"), ("presensi.php", b"presensi-new")],
            "t1",
        )

    assert ftp.files["admin.php"] == b"admin-old"
    assert ftp.files["presensi.php"] == b"presensi-old"
    assert not any(".__next_" in path for path in ftp.files)


def test_finance_config_adds_missing_keys_to_single_return_array() -> None:
    module = load_module()
    source = "<?php\nreturn [\n  'owner_email' => 'owner@example.com',\n];\n"
    updated = module.replace_php_value(source, "dashboard_actor_assertion_audience", module.DEFAULT_AUDIENCE)
    updated = module.replace_php_bool(updated, "canonical_finance_writes_enabled", True)

    assert updated.count("dashboard_actor_assertion_audience") == 1
    assert updated.count("canonical_finance_writes_enabled") == 1
    assert "'owner_email' => 'owner@example.com'" in updated
    assert updated.rstrip().endswith("];" )


def test_finance_config_accepts_legacy_bom_and_closing_tag_wrapper() -> None:
    module = load_module()
    source = "\ufeff<?php\nreturn [\n  'employees' => [['id' => 'pegawai-1']],\n];\n/* legacy provisioner */\n?>\n"

    updated = module.replace_php_value(source, "project_catalog_url", module.DEFAULT_PROJECT_CATALOG_URL)

    assert updated.startswith("\ufeff<?php")
    assert module.DEFAULT_PROJECT_CATALOG_URL in updated
    assert updated.rstrip().endswith("?>")


@pytest.mark.parametrize("source", [
    "<?php\nreturn array(\n  'employees' => array(array('id' => 'pegawai-1')),\n  'projects' => array(),\n);\n",
    "<?php\n$config = [\n  'employees' => [['id' => 'pegawai-1']],\n  'projects' => [],\n];\nreturn $config;\n",
])
def test_finance_config_accepts_supported_legacy_array_wrappers(source: str) -> None:
    module = load_module()

    updated = module.replace_php_value(source, "project_catalog_url", module.DEFAULT_PROJECT_CATALOG_URL)

    assert updated.count("project_catalog_url") == 1
    assert updated.index("project_catalog_url") < updated.index("employees")


def test_finance_config_fails_closed_for_duplicate_key_or_invalid_document() -> None:
    module = load_module()
    sources = (
        "'canonical_finance_writes_enabled' => false, 'canonical_finance_writes_enabled' => true,\n];",
        "<?php return [];",
    )
    for source in sources:
        try:
            module.replace_php_bool(source, "canonical_finance_writes_enabled", True)
        except RuntimeError:
            pass
        else:
            raise AssertionError("unsafe config must fail closed")
