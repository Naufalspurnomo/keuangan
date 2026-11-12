from __future__ import annotations

import json
import hashlib
import shutil
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import hollawall_backup, hollawall_restore_verify


FIXED_NOW = datetime(2026, 11, 9, 1, 15, 30, tzinfo=UTC)
SOURCE_DSN = "postgresql://owner:database-secret@db.internal:5432/hollawall?sslmode=require"
DISPOSABLE_DSN = "postgresql://tester:other-secret@127.0.0.1:55432/hollawall_restore"
ARCHIVE_SECRET = "owner-scoped-archive-secret"


CONTRACT_ROWS = {
    "financial_ledger": [
        '{"amount":"1000.00","id":1}',
        '{"amount":"2500.00","id":2}',
    ],
    "transaction_inbox": ['{"event_key":"evt-1","status":"processed"}'],
    "transaction_inbox_review_audit": ['{"action":"approve","id":1}'],
    "projects": ['{"id":"project-1","name":"Alpha"}'],
}


def rows_sha256(rows: list[str]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def jpeg_bytes() -> bytes:
    # Structurally complete one-pixel JPEG marker stream. The verifier does not decode pixels.
    return (
        b"\xff\xd8"
        b"\xff\xe0\x00\x10" + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        b"\xff\xda\x00\x0c\x03\x01\x00\x02\x00\x03\x00\x00\x3f\x00\x00"
        b"\xff\xd9"
    )


class FakeTools:
    """Deterministic pg/openssl/rclone substitutes used through dependency injection."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.remote: dict[str, bytes] = {}
        self.corrupt_download = False

    def __call__(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        selected_env = dict(env or {})
        self.calls.append((list(command), selected_env))
        tool = Path(command[0]).name
        if tool == "pg_dump":
            output = Path(command[command.index("--file") + 1])
            output.write_bytes(b"PGDMP\x01fake-custom-format")
            return
        if tool == "psql":
            sql = command[command.index("--command") + 1]
            if "hollawall-contract:metadata" in sql:
                return json.dumps({
                    "lsn": "0/16B6C50",
                    "cutoff": "2026-11-09T01:15:29Z",
                    "schema": "public",
                }) + "\n"
            if "hollawall-contract:schema" in sql:
                return "\n".join([
                    '{"column_name":"id","data_type":"bigint","table_name":"financial_ledger"}',
                    '{"column_name":"event_key","data_type":"text","table_name":"transaction_inbox"}',
                ]) + "\n"
            for table, rows in CONTRACT_ROWS.items():
                if f"hollawall-contract:{table} */" in sql:
                    return "\n".join(rows) + "\n"
            raise AssertionError(f"unexpected contract query: {sql}")
        if tool == "openssl":
            source = Path(command[command.index("-in") + 1])
            destination = Path(command[command.index("-out") + 1])
            shutil.copyfile(source, destination)
            return
        if tool == "rclone":
            copy_index = command.index("copyto")
            source, destination = command[copy_index + 1 : copy_index + 3]
            if ":" in destination:
                self.remote[destination] = Path(source).read_bytes()
            else:
                payload = self.remote[source]
                if self.corrupt_download:
                    payload += b"corrupt"
                Path(destination).write_bytes(payload)
            return
        if tool == "pg_restore":
            return
        raise AssertionError(f"unexpected fake tool: {tool}")


def source_tree(tmp_path: Path) -> tuple[Path, Path]:
    sheets = tmp_path / "sheets-export"
    sheets.mkdir()
    (sheets / "ledger.csv").write_text("date,amount\n2026-11-09,1000\n", encoding="utf-8")
    (sheets / "projects.csv").write_text("id,name\np-1,Alpha\n", encoding="utf-8")

    presensi = tmp_path / ".hollawall-presensi"
    photos = presensi / "photos"
    photos.mkdir(parents=True)
    photo_name = "evt-0123456789abcdef01234567.jpg"
    (photos / photo_name).write_bytes(jpeg_bytes())
    (presensi / "events.json").write_text(
        json.dumps([
            {
                "id": "evt-0123456789abcdef01234567",
                "photo_name": photo_name,
                "photo_mime": "image/jpeg",
            }
        ]),
        encoding="utf-8",
    )
    (presensi / "events.lock").write_bytes(b"")
    return sheets, presensi


def backup_config(tmp_path: Path, sheets: Path, presensi: Path, **overrides: object) -> hollawall_backup.BackupConfig:
    values: dict[str, object] = {
        "output_dir": tmp_path / "backups",
        "sheets_source": sheets,
        "presensi_source": presensi,
        "postgres_dsn_env": "TEST_SOURCE_DSN",
        "archive_key_env": "TEST_ARCHIVE_KEY",
    }
    values.update(overrides)
    return hollawall_backup.BackupConfig(**values)


def backup_env() -> dict[str, str]:
    return {"TEST_SOURCE_DSN": SOURCE_DSN, "TEST_ARCHIVE_KEY": ARCHIVE_SECRET}


def archive_manifest(archive: Path) -> dict[str, object]:
    with tarfile.open(archive, "r:") as bundle:
        member = bundle.getmember("manifest.json")
        handle = bundle.extractfile(member)
        assert handle is not None
        return json.loads(handle.read())


def test_backup_runner_does_not_leak_unrelated_parent_secrets(monkeypatch) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs["env"])

    monkeypatch.setenv("UNRELATED_SECRET", "must-not-leak")
    monkeypatch.setattr(hollawall_backup.subprocess, "run", fake_run)
    hollawall_backup._default_runner(["true"], env={"PGDATABASE": SOURCE_DSN})
    assert captured["PGDATABASE"] == SOURCE_DSN
    assert "UNRELATED_SECRET" not in captured


def test_backup_defaults_to_non_mutating_dry_run(tmp_path: Path) -> None:
    sheets, presensi = source_tree(tmp_path)
    tools = FakeTools()
    config = backup_config(tmp_path, sheets, presensi)

    result = hollawall_backup.run_backup(config, apply=False, runner=tools, environ={})

    assert result == {
        "action": "dry-run",
        "components": ["postgres", "sheets", "presensi"],
        "mutation": False,
        "offsite_upload": False,
    }
    assert tools.calls == []
    assert not config.output_dir.exists()


def test_apply_builds_custom_dump_redacted_manifest_and_verified_archive(tmp_path: Path) -> None:
    sheets, presensi = source_tree(tmp_path)
    tools = FakeTools()

    result = hollawall_backup.run_backup(
        backup_config(tmp_path, sheets, presensi),
        apply=True,
        runner=tools,
        environ=backup_env(),
        now=lambda: FIXED_NOW,
    )

    archive = Path(result["archive"])
    assert archive.is_file()
    assert result["verified"] is True
    assert result["uploaded"] is False
    dump_call, dump_env = next(call for call in tools.calls if Path(call[0][0]).name == "pg_dump")
    assert "--format=custom" in dump_call
    assert dump_env["PGDATABASE"] == SOURCE_DSN
    assert "TEST_ARCHIVE_KEY" not in dump_env
    assert SOURCE_DSN not in " ".join(dump_call)

    manifest = archive_manifest(archive)
    rendered = json.dumps(manifest, sort_keys=True)
    assert manifest["created_at"] == "2026-11-09T01:15:30Z"
    assert set(manifest["components"]) == {"postgres", "sheets", "presensi"}
    assert manifest["components"]["postgres"]["files"][0]["path"] == "postgres/database.dump"
    assert manifest["components"]["sheets"]["file_count"] == 2
    assert manifest["components"]["presensi"]["file_count"] == 3
    assert manifest["sources"]["postgres"]["identifier"] == "[REDACTED]"
    assert len(manifest["sources"]["postgres"]["fingerprint_sha256"]) == 64
    assert "database-secret" not in rendered
    assert ARCHIVE_SECRET not in rendered
    assert str(sheets) not in rendered
    assert str(presensi) not in rendered
    assert all(ARCHIVE_SECRET not in " ".join(command) for command, _env in tools.calls)


def test_backup_manifest_records_cutoff_schema_migration_and_application_hashes(tmp_path: Path) -> None:
    sheets, presensi = source_tree(tmp_path)
    tools = FakeTools()

    result = hollawall_backup.run_backup(
        backup_config(tmp_path, sheets, presensi),
        apply=True,
        runner=tools,
        environ=backup_env(),
        now=lambda: FIXED_NOW,
    )

    contract = archive_manifest(Path(result["archive"]))["postgresql"]
    assert contract["lsn"] == "0/16B6C50"
    assert contract["cutoff"] == "2026-11-09T01:15:29Z"
    assert contract["schema"] == {
        "name": "public",
        "sha256": rows_sha256([
            '{"column_name":"id","data_type":"bigint","table_name":"financial_ledger"}',
            '{"column_name":"event_key","data_type":"text","table_name":"transaction_inbox"}',
        ]),
    }
    assert contract["migration_version"] == "016_financial_export_delivery"
    assert contract["application"] == {
        table: {"total": len(rows), "sha256": rows_sha256(rows)}
        for table, rows in CONTRACT_ROWS.items()
    }
    dump_call = next(command for command, _env in tools.calls if Path(command[0]).name == "pg_dump")
    assert "--serializable-deferrable" in dump_call


def test_optional_rclone_upload_uses_explicit_config_and_downloaded_byte_readback(tmp_path: Path) -> None:
    sheets, presensi = source_tree(tmp_path)
    rclone_config = tmp_path / "rclone.conf"
    rclone_config.write_text("[offsite]\ntype = local\n", encoding="utf-8")
    tools = FakeTools()
    config = backup_config(
        tmp_path,
        sheets,
        presensi,
        rclone_config=rclone_config,
        rclone_destination="offsite:hollawall/backups",
    )

    result = hollawall_backup.run_backup(
        config,
        apply=True,
        runner=tools,
        environ=backup_env(),
        now=lambda: FIXED_NOW,
    )

    assert result["uploaded"] is True
    assert result["downloaded_byte_verified"] is True
    rclone_calls = [command for command, _env in tools.calls if Path(command[0]).name == "rclone"]
    assert len(rclone_calls) == 2
    assert all(command[1:3] == ["--config", str(rclone_config)] for command in rclone_calls)
    assert rclone_calls[0][3] == "copyto"
    assert rclone_calls[1][3] == "copyto"
    assert rclone_calls[0][-1].startswith("offsite:hollawall/backups/")


def test_upload_fails_if_downloaded_encrypted_bytes_differ(tmp_path: Path) -> None:
    sheets, presensi = source_tree(tmp_path)
    rclone_config = tmp_path / "rclone.conf"
    rclone_config.write_text("[offsite]\ntype = local\n", encoding="utf-8")
    tools = FakeTools()
    tools.corrupt_download = True

    with pytest.raises(hollawall_backup.BackupError, match="downloaded encrypted archive hash mismatch"):
        hollawall_backup.run_backup(
            backup_config(
                tmp_path,
                sheets,
                presensi,
                rclone_config=rclone_config,
                rclone_destination="offsite:hollawall/backups",
            ),
            apply=True,
            runner=tools,
            environ=backup_env(),
            now=lambda: FIXED_NOW,
        )


def make_archive(tmp_path: Path, tools: FakeTools) -> Path:
    sheets, presensi = source_tree(tmp_path)
    result = hollawall_backup.run_backup(
        backup_config(tmp_path, sheets, presensi),
        apply=True,
        runner=tools,
        environ=backup_env(),
        now=lambda: FIXED_NOW,
    )
    return Path(result["archive"])


def restore_config(archive: Path) -> hollawall_restore_verify.RestoreVerifyConfig:
    return hollawall_restore_verify.RestoreVerifyConfig(
        archive=archive,
        disposable_dsn_env="TEST_DISPOSABLE_DSN",
        archive_key_env="TEST_ARCHIVE_KEY",
    )


def test_restore_verification_defaults_to_non_mutating_plan(tmp_path: Path) -> None:
    tools = FakeTools()
    archive = make_archive(tmp_path, tools)
    tools.calls.clear()

    result = hollawall_restore_verify.run_restore_verification(
        restore_config(archive),
        verify=False,
        runner=tools,
        environ={},
    )

    assert result == {"action": "dry-run", "mutation": False, "target": "disposable-database-only"}
    assert tools.calls == []


def test_restore_refuses_database_matching_manifest_source_before_pg_restore(tmp_path: Path) -> None:
    tools = FakeTools()
    archive = make_archive(tmp_path, tools)
    tools.calls.clear()
    env = {"TEST_ARCHIVE_KEY": ARCHIVE_SECRET, "TEST_DISPOSABLE_DSN": SOURCE_DSN}

    with pytest.raises(hollawall_restore_verify.RestoreVerificationError, match="matches backup source"):
        hollawall_restore_verify.run_restore_verification(
            restore_config(archive),
            verify=True,
            runner=tools,
            environ=env,
        )

    assert not any(Path(command[0]).name == "pg_restore" for command, _env in tools.calls)


def test_restore_verifies_manifest_sheets_presensi_and_disposable_pg_restore(tmp_path: Path) -> None:
    tools = FakeTools()
    archive = make_archive(tmp_path, tools)
    tools.calls.clear()
    env = {"TEST_ARCHIVE_KEY": ARCHIVE_SECRET, "TEST_DISPOSABLE_DSN": DISPOSABLE_DSN}

    result = hollawall_restore_verify.run_restore_verification(
        restore_config(archive),
        verify=True,
        runner=tools,
        environ=env,
    )

    assert result["verified"] is True
    assert result["database_restored"] is True
    assert result["sheets_files_verified"] == 2
    assert result["presensi_events_verified"] == 1
    assert result["presensi_photos_verified"] == 1
    assert result["backup_cutoff_verified"] is True
    assert result["application_totals_verified"] == sum(len(rows) for rows in CONTRACT_ROWS.values())
    assert result["application_hashes_verified"] == len(CONTRACT_ROWS)
    restore_calls = [(command, child_env) for command, child_env in tools.calls if Path(command[0]).name == "pg_restore"]
    assert len(restore_calls) == 2
    assert "--list" in restore_calls[0][0]
    assert "--exit-on-error" in restore_calls[1][0]
    assert "--clean" in restore_calls[1][0]
    assert "--dbname=" in restore_calls[1][0]
    assert restore_calls[1][1]["PGDATABASE"] == DISPOSABLE_DSN
    assert DISPOSABLE_DSN not in " ".join(restore_calls[1][0])


def rewrite_archive_manifest(archive: Path, tmp_path: Path, mutate) -> None:
    unpacked = tmp_path / "manifest-rewrite"
    unpacked.mkdir()
    with tarfile.open(archive, "r:") as source:
        source.extractall(unpacked, filter="data")
    manifest_path = unpacked / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with tarfile.open(archive, "w") as destination:
        for path in sorted(unpacked.rglob("*")):
            if path.is_file():
                destination.add(path, arcname=path.relative_to(unpacked).as_posix())


def test_restore_rejects_missing_postgresql_cutoff_before_pg_restore(tmp_path: Path) -> None:
    tools = FakeTools()
    archive = make_archive(tmp_path, tools)
    tools.calls.clear()
    rewrite_archive_manifest(archive, tmp_path, lambda manifest: manifest["postgresql"].pop("cutoff"))

    with pytest.raises(hollawall_restore_verify.RestoreVerificationError, match="cutoff"):
        hollawall_restore_verify.run_restore_verification(
            restore_config(archive),
            verify=True,
            runner=tools,
            environ={"TEST_ARCHIVE_KEY": ARCHIVE_SECRET, "TEST_DISPOSABLE_DSN": DISPOSABLE_DSN},
        )

    assert not any(Path(command[0]).name == "pg_restore" for command, _env in tools.calls)


def test_restore_rejects_application_hash_mismatch_after_restore(tmp_path: Path) -> None:
    tools = FakeTools()
    archive = make_archive(tmp_path, tools)
    tools.calls.clear()

    def corrupt_hash(manifest) -> None:
        manifest["postgresql"]["application"]["financial_ledger"]["sha256"] = "0" * 64

    rewrite_archive_manifest(archive, tmp_path, corrupt_hash)

    with pytest.raises(hollawall_restore_verify.RestoreVerificationError, match="application totals/hashes"):
        hollawall_restore_verify.run_restore_verification(
            restore_config(archive),
            verify=True,
            runner=tools,
            environ={"TEST_ARCHIVE_KEY": ARCHIVE_SECRET, "TEST_DISPOSABLE_DSN": DISPOSABLE_DSN},
        )

    assert any(Path(command[0]).name == "pg_restore" for command, _env in tools.calls)


def test_restore_rejects_presensi_photo_event_non_bijection_before_pg_restore(tmp_path: Path) -> None:
    tools = FakeTools()
    archive = make_archive(tmp_path, tools)
    tools.calls.clear()

    # The fake encryption is a byte copy, allowing deterministic corruption fixture creation.
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    with tarfile.open(archive, "r:") as source:
        source.extractall(unpacked, filter="data")
    (unpacked / "presensi" / "photos" / "orphan.jpg").write_bytes(jpeg_bytes())
    manifest = json.loads((unpacked / "manifest.json").read_text(encoding="utf-8"))
    hollawall_backup.refresh_component_manifest(manifest, "presensi", unpacked / "presensi")
    (unpacked / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with tarfile.open(archive, "w") as destination:
        for path in sorted(unpacked.rglob("*")):
            if path.is_file():
                destination.add(path, arcname=path.relative_to(unpacked).as_posix())

    with pytest.raises(hollawall_restore_verify.RestoreVerificationError, match="event/photo bijection"):
        hollawall_restore_verify.run_restore_verification(
            restore_config(archive),
            verify=True,
            runner=tools,
            environ={"TEST_ARCHIVE_KEY": ARCHIVE_SECRET, "TEST_DISPOSABLE_DSN": DISPOSABLE_DSN},
        )

    assert not any(Path(command[0]).name == "pg_restore" for command, _env in tools.calls)


def test_backup_cli_default_does_not_require_secrets_or_create_output(tmp_path: Path, monkeypatch, capsys) -> None:
    sheets, presensi = source_tree(tmp_path)
    output = tmp_path / "cli-output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hollawall_backup.py",
            "--output-dir", str(output),
            "--sheets-source", str(sheets),
            "--presensi-source", str(presensi),
        ],
    )

    hollawall_backup.main()

    assert json.loads(capsys.readouterr().out)["action"] == "dry-run"
    assert not output.exists()
