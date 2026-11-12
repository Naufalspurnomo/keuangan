#!/usr/bin/env python3
"""Verify a Hollawall backup by restoring only into a disposable database.

There is deliberately no production restore mode. The default is non-mutating;
``--verify`` decrypts into a temporary directory, validates every byte, checks
Sheets and Presensi invariants, then invokes pg_restore against the disposable
DSN supplied through an environment variable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol

try:
    from scripts import hollawall_backup as backup
except ImportError:  # Direct execution: python scripts/hollawall_restore_verify.py
    import hollawall_backup as backup  # type: ignore[no-redef]


ARCHIVE_KEY_CHILD_ENV = "HOLLAWALL_ARCHIVE_KEY"
DISPOSABLE_CONFIRMATION = "VERIFY_DISPOSABLE_DATABASE"


class RestoreVerificationError(RuntimeError):
    """A fail-closed restore drill validation error."""


class CommandRunner(Protocol):
    def __call__(self, command: list[str], *, env: dict[str, str] | None = None) -> str | None: ...


@dataclass(frozen=True)
class RestoreVerifyConfig:
    archive: Path
    disposable_dsn_env: str = "HOLLAWALL_RESTORE_VERIFY_DATABASE_URL"
    archive_key_env: str | None = "HOLLAWALL_ARCHIVE_KEY"
    archive_key_path: Path | None = None
    openssl_command: str = "openssl"
    pg_restore_command: str = "pg_restore"
    psql_command: str = "psql"


def _postgres_contract(manifest: dict[str, object]) -> dict[str, object]:
    contract = manifest.get("postgresql")
    if not isinstance(contract, dict):
        raise RestoreVerificationError("manifest PostgreSQL contract is invalid")
    lsn = contract.get("lsn")
    cutoff = contract.get("cutoff")
    schema = contract.get("schema")
    migration = contract.get("migration_version")
    application = contract.get("application")
    if not isinstance(lsn, str) or not backup.LSN_PATTERN.fullmatch(lsn):
        raise RestoreVerificationError("manifest PostgreSQL LSN is invalid")
    if not isinstance(cutoff, str) or not cutoff.endswith("Z"):
        raise RestoreVerificationError("manifest PostgreSQL cutoff is invalid")
    if (
        not isinstance(schema, dict)
        or schema.get("name") != "public"
        or not isinstance(schema.get("sha256"), str)
        or len(str(schema["sha256"])) != 64
    ):
        raise RestoreVerificationError("manifest PostgreSQL schema contract is invalid")
    if not isinstance(migration, str) or not migration:
        raise RestoreVerificationError("manifest PostgreSQL migration version is invalid")
    schema_version = manifest.get("schema")
    if not isinstance(application, dict):
        raise RestoreVerificationError("manifest PostgreSQL application contract is invalid")
    tables = set(application)
    if schema_version == backup.LEGACY_SCHEMA_VERSION:
        valid_tables = tables == set(backup.POSTGRES_APPLICATION_TABLES)
    else:
        valid_tables = (
            bool(tables)
            and backup.CANONICAL_REQUIRED_TABLES.issubset(tables)
            and all(backup.TABLE_NAME_PATTERN.fullmatch(table) for table in tables)
        )
    if not valid_tables:
        raise RestoreVerificationError("manifest PostgreSQL application contract is invalid")
    for entry in application.values():
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("total"), int)
            or entry["total"] < 0
            or not isinstance(entry.get("sha256"), str)
            or len(str(entry["sha256"])) != 64
        ):
            raise RestoreVerificationError("manifest PostgreSQL application contract is invalid")
    return contract


def _restored_application_contract(
    runner: CommandRunner,
    config: RestoreVerifyConfig,
    dsn: str,
    tables: list[str],
) -> dict[str, dict[str, object]]:
    if not tables or len(tables) != len(set(tables)) or any(
        not backup.TABLE_NAME_PATTERN.fullmatch(table) for table in tables
    ):
        raise RestoreVerificationError("application table inventory is invalid")
    observed: dict[str, dict[str, object]] = {}
    for table in tables:
        output = runner(
            [
                config.psql_command,
                "--no-psqlrc",
                "--quiet",
                "--tuples-only",
                "--no-align",
                "--set=ON_ERROR_STOP=1",
                "--command",
                f"/* hollawall-contract:{table} */\n"
                f"SELECT to_jsonb(row_data)::text FROM public.{table} AS row_data "
                "ORDER BY to_jsonb(row_data)::text",
            ],
            env=backup.libpq_env(dsn),
        )
        if not isinstance(output, str):
            raise RestoreVerificationError("application totals/hashes readback failed")
        rows = [line for line in output.splitlines() if line]
        observed[table] = {"total": len(rows), "sha256": backup._rows_sha256(rows)}
    return observed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_runner(command: list[str], *, env: dict[str, str] | None = None) -> str:
    child_env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
        if os.environ.get(key)
    }
    if env:
        child_env.update(env)
    try:
        completed = subprocess.run(
            command,
            check=True,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout
    except FileNotFoundError as error:
        raise RestoreVerificationError(f"required command unavailable: {Path(command[0]).name}") from error
    except subprocess.CalledProcessError as error:
        raise RestoreVerificationError(f"command failed: {Path(command[0]).name}") from error


def _archive_key(config: RestoreVerifyConfig, environ: Mapping[str, str]) -> str:
    if config.archive_key_path is not None:
        path = config.archive_key_path.expanduser()
        if path.is_symlink() or not path.is_file():
            raise RestoreVerificationError("archive key file is unavailable")
        try:
            key = path.read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError) as error:
            raise RestoreVerificationError("archive key file cannot be read") from error
    elif config.archive_key_env:
        key = str(environ.get(config.archive_key_env, ""))
    else:
        key = ""
    if not key:
        raise RestoreVerificationError("archive key is not configured")
    return key


def _safe_member_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RestoreVerificationError("archive contains an unsafe member path")
    return path.as_posix()


def _extract_verified_tar(tar_path: Path, destination: Path) -> set[str]:
    try:
        with tarfile.open(tar_path, "r:") as bundle:
            names: set[str] = set()
            for member in bundle.getmembers():
                name = _safe_member_name(member.name)
                if not member.isfile() or name in names:
                    raise RestoreVerificationError("archive contains a non-file or duplicate member")
                names.add(name)
                target = destination.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise RestoreVerificationError("archive member cannot be read")
                with source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
            return names
    except RestoreVerificationError:
        raise
    except (tarfile.TarError, OSError) as error:
        raise RestoreVerificationError("archive decrypt/tar readback failed") from error


def _load_manifest(root: Path) -> dict[str, object]:
    path = root / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RestoreVerificationError("manifest is missing or invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schema") not in backup.SUPPORTED_SCHEMA_VERSIONS:
        raise RestoreVerificationError("manifest schema is unsupported")
    return manifest


def _manifest_rows(manifest: dict[str, object], component: str) -> list[dict[str, object]]:
    components = manifest.get("components")
    entry = components.get(component) if isinstance(components, dict) else None
    if not isinstance(entry, dict):
        raise RestoreVerificationError(f"manifest {component} inventory is invalid")
    rows = entry.get("files")
    if not isinstance(rows, list) or not rows:
        raise RestoreVerificationError(f"manifest {component} inventory is invalid")
    typed: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RestoreVerificationError(f"manifest {component} inventory is invalid")
        typed.append(row)
    if entry.get("file_count") != len(typed):
        raise RestoreVerificationError(f"manifest {component} file count mismatch")
    sizes = [row.get("size") for row in typed]
    if not all(isinstance(size, int) and size >= 0 for size in sizes):
        raise RestoreVerificationError(f"manifest {component} byte count mismatch")
    if entry.get("total_bytes") != sum(size for size in sizes if isinstance(size, int)):
        raise RestoreVerificationError(f"manifest {component} byte count mismatch")
    return typed


def _verify_component_inventory(
    root: Path,
    manifest: dict[str, object],
    component: str,
) -> list[dict[str, object]]:
    rows = _manifest_rows(manifest, component)
    expected_paths: set[str] = set()
    for row in rows:
        relative = row.get("path")
        size = row.get("size")
        digest = row.get("sha256")
        if not isinstance(relative, str) or not relative.startswith(component + "/"):
            raise RestoreVerificationError(f"manifest {component} path is invalid")
        normalized = _safe_member_name(relative)
        if normalized in expected_paths or not isinstance(size, int) or size < 0:
            raise RestoreVerificationError(f"manifest {component} inventory is invalid")
        if not isinstance(digest, str) or len(digest) != 64:
            raise RestoreVerificationError(f"manifest {component} hash is invalid")
        expected_paths.add(normalized)
        path = root.joinpath(*PurePosixPath(normalized).parts)
        if not path.is_file() or path.stat().st_size != size or sha256_file(path) != digest:
            raise RestoreVerificationError(f"{component} integrity hash mismatch")

    component_root = root / component
    observed = {
        path.relative_to(root).as_posix()
        for path in component_root.rglob("*")
        if path.is_file()
    }
    if observed != expected_paths:
        raise RestoreVerificationError(f"{component} inventory mismatch")
    return rows


def _is_jpeg(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 20 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        return False
    # Require a Start Of Frame and Start Of Scan, not merely JPEG edge markers.
    has_sof = any(marker in data for marker in (b"\xff\xc0", b"\xff\xc1", b"\xff\xc2", b"\xff\xc3"))
    return has_sof and b"\xff\xda" in data


def _verify_presensi(root: Path) -> tuple[int, int]:
    component = root / "presensi"
    events_path = component / "events.json"
    try:
        events = json.loads(events_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RestoreVerificationError("Presensi events.json is invalid") from error
    if not isinstance(events, list):
        raise RestoreVerificationError("Presensi events.json must contain a list")

    event_photos: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise RestoreVerificationError("Presensi event is invalid")
        photo_name = event.get("photo_name")
        if not isinstance(photo_name, str) or PurePosixPath(photo_name).name != photo_name:
            raise RestoreVerificationError("Presensi event photo name is invalid")
        if photo_name in event_photos or event.get("photo_mime") != "image/jpeg":
            raise RestoreVerificationError("Presensi event/photo bijection is invalid")
        event_photos.add(photo_name)

    photos_root = component / "photos"
    observed_photos = {
        path.name for path in photos_root.iterdir() if path.is_file()
    } if photos_root.is_dir() else set()
    if event_photos != observed_photos:
        raise RestoreVerificationError("Presensi event/photo bijection is invalid")
    for name in sorted(observed_photos):
        if Path(name).suffix.lower() not in {".jpg", ".jpeg"} or not _is_jpeg(photos_root / name):
            raise RestoreVerificationError("Presensi JPEG validation failed")
    return len(events), len(observed_photos)


def _source_database_fingerprint(manifest: dict[str, object]) -> str:
    sources = manifest.get("sources")
    postgres = sources.get("postgres") if isinstance(sources, dict) else None
    value = postgres.get("fingerprint_sha256") if isinstance(postgres, dict) else None
    if not isinstance(value, str) or len(value) != 64:
        raise RestoreVerificationError("manifest PostgreSQL source fingerprint is invalid")
    return value


def run_restore_verification(
    config: RestoreVerifyConfig,
    *,
    verify: bool = False,
    runner: CommandRunner | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Plan or execute an isolated restore verification drill."""
    if not verify:
        return {"action": "dry-run", "mutation": False, "target": "disposable-database-only"}

    selected_env = dict(os.environ if environ is None else environ)
    selected_runner = runner or _default_runner
    archive = config.archive.expanduser().resolve()
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size == 0:
        raise RestoreVerificationError("encrypted archive is unavailable")
    dsn = str(selected_env.get(config.disposable_dsn_env, ""))
    if not dsn:
        raise RestoreVerificationError("disposable database DSN is not configured")
    try:
        target_fingerprint = backup.database_fingerprint(dsn)
    except backup.BackupError as error:
        raise RestoreVerificationError(str(error)) from error
    key = _archive_key(config, selected_env)

    with tempfile.TemporaryDirectory(prefix="hollawall-restore-verify-") as temporary:
        work = Path(temporary)
        decrypted = work / "payload.tar"
        selected_runner(
            [
                config.openssl_command,
                "enc",
                "-d",
                "-aes-256-cbc",
                "-pbkdf2",
                "-in",
                str(archive),
                "-out",
                str(decrypted),
                "-pass",
                f"env:{ARCHIVE_KEY_CHILD_ENV}",
            ],
            env={ARCHIVE_KEY_CHILD_ENV: key},
        )
        if not decrypted.is_file() or decrypted.stat().st_size == 0:
            raise RestoreVerificationError("decryption did not produce an archive")

        extracted = work / "extracted"
        extracted.mkdir()
        members = _extract_verified_tar(decrypted, extracted)
        manifest = _load_manifest(extracted)
        postgres_contract = _postgres_contract(manifest)
        source_fingerprint = _source_database_fingerprint(manifest)
        if target_fingerprint == source_fingerprint:
            raise RestoreVerificationError("disposable database matches backup source")

        postgres_rows = _verify_component_inventory(extracted, manifest, "postgres")
        sheets_rows = _verify_component_inventory(extracted, manifest, "sheets")
        _verify_component_inventory(extracted, manifest, "presensi")
        expected_members = {
            str(row["path"])
            for component in ("postgres", "sheets", "presensi")
            for row in _manifest_rows(manifest, component)
        } | {"manifest.json"}
        if members != expected_members:
            raise RestoreVerificationError("archive member inventory mismatch")
        if len(postgres_rows) != 1 or postgres_rows[0].get("path") != "postgres/database.dump":
            raise RestoreVerificationError("PostgreSQL custom dump inventory is invalid")
        events, photos = _verify_presensi(extracted)

        dump_path = extracted / "postgres" / "database.dump"
        selected_runner([config.pg_restore_command, "--list", str(dump_path)], env={})
        selected_runner(
            [
                config.pg_restore_command,
                "--exit-on-error",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "--dbname=",
                str(dump_path),
            ],
            env=backup.libpq_env(dsn),
        )
        expected_application = postgres_contract["application"]
        assert isinstance(expected_application, dict)
        restored_application = _restored_application_contract(
            selected_runner,
            config,
            dsn,
            sorted(expected_application),
        )
        if restored_application != expected_application:
            raise RestoreVerificationError("application totals/hashes mismatch after restore")
        return {
            "action": "verify",
            "verified": True,
            "database_restored": True,
            "sheets_files_verified": len(sheets_rows),
            "presensi_events_verified": events,
            "presensi_photos_verified": photos,
            "backup_cutoff_verified": True,
            "application_totals_verified": sum(
                int(entry["total"]) for entry in restored_application.values()
            ),
            "application_hashes_verified": len(restored_application),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--disposable-dsn-env", default="HOLLAWALL_RESTORE_VERIFY_DATABASE_URL")
    key = parser.add_mutually_exclusive_group()
    key.add_argument("--archive-key-env", default="HOLLAWALL_ARCHIVE_KEY")
    key.add_argument("--archive-key-file", type=Path)
    parser.add_argument("--openssl-command", default="openssl")
    parser.add_argument("--pg-restore-command", default="pg_restore")
    parser.add_argument("--psql-command", default="psql")
    parser.add_argument("--verify", action="store_true", help="run the isolated restore drill")
    parser.add_argument(
        "--confirm-disposable-database",
        help=f"required with --verify; exact value: {DISPOSABLE_CONFIRMATION}",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.verify and args.confirm_disposable_database != DISPOSABLE_CONFIRMATION:
        print(json.dumps({"action": "verify", "error": "disposable_database_confirmation_required", "success": False}))
        raise SystemExit(2)
    config = RestoreVerifyConfig(
        archive=args.archive,
        disposable_dsn_env=args.disposable_dsn_env,
        archive_key_env=None if args.archive_key_file else args.archive_key_env,
        archive_key_path=args.archive_key_file,
        openssl_command=args.openssl_command,
        pg_restore_command=args.pg_restore_command,
        psql_command=args.psql_command,
    )
    try:
        result = run_restore_verification(config, verify=args.verify)
    except RestoreVerificationError as error:
        print(json.dumps({"action": "verify" if args.verify else "dry-run", "error": str(error), "success": False}))
        raise SystemExit(2) from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
