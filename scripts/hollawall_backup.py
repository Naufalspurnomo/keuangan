#!/usr/bin/env python3
"""Create a coordinated, encrypted Hollawall backup.

The default mode is a non-mutating plan. ``--apply`` is required before the
script executes pg_dump, creates local files, or performs an optional rclone
upload. Credentials stay in environment variables or an owner-scoped key file;
they are never command-line arguments or result fields.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, MutableMapping, Protocol, cast
from urllib.parse import unquote, urlsplit


ARCHIVE_KEY_CHILD_ENV = "HOLLAWALL_ARCHIVE_KEY"
SCHEMA_VERSION = "hollawall.backup.v2"
ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "dashboard_api" / "migrations"
POSTGRES_APPLICATION_TABLES = (
    "financial_ledger",
    "transaction_inbox",
    "transaction_inbox_review_audit",
    "projects",
)
LSN_PATTERN = re.compile(r"^[0-9A-F]+/[0-9A-F]+$")


class BackupError(RuntimeError):
    """A fail-closed backup validation or orchestration error."""


class CommandRunner(Protocol):
    def __call__(self, command: list[str], *, env: dict[str, str] | None = None) -> str | None: ...


@dataclass(frozen=True)
class BackupConfig:
    output_dir: Path
    sheets_source: Path
    presensi_source: Path
    postgres_dsn_env: str = "HOLLAWALL_BACKUP_DATABASE_URL"
    archive_key_env: str | None = "HOLLAWALL_ARCHIVE_KEY"
    archive_key_path: Path | None = None
    rclone_config: Path | None = None
    rclone_destination: str | None = None
    pg_dump_command: str = "pg_dump"
    psql_command: str = "psql"
    openssl_command: str = "openssl"
    rclone_command: str = "rclone"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def database_identity(dsn: str) -> str:
    """Return a password-free canonical database endpoint identity.

    This identity is persisted only as a SHA-256 fingerprint. URI DSNs are
    required so restore verification can reliably reject its source database.
    """
    parsed = urlsplit(dsn)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise BackupError("PostgreSQL DSN must be a postgresql:// URI")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise BackupError("PostgreSQL DSN must name a database")
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port or 5432
    return f"postgresql://{host}:{port}/{database}"


def database_fingerprint(dsn: str) -> str:
    return fingerprint(database_identity(dsn))


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
        return completed.stdout if completed is not None else ""
    except FileNotFoundError as error:
        raise BackupError(f"required command unavailable: {Path(command[0]).name}") from error
    except subprocess.CalledProcessError as error:
        # Tool stderr can repeat connection strings or provider details. Keep the
        # operator-facing error intentionally bounded and secret-free.
        raise BackupError(f"command failed: {Path(command[0]).name}") from error


def _safe_relative(path: str) -> str:
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise BackupError("unsafe archive member path")
    return parsed.as_posix()


def _validate_source_tree(source: Path, label: str) -> Path:
    root = source.expanduser().resolve()
    if not root.is_dir():
        raise BackupError(f"{label} source directory is unavailable")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BackupError(f"{label} source contains a symlink")
        if not path.is_dir() and not path.is_file():
            raise BackupError(f"{label} source contains an unsupported entry")
    return root


def _copy_tree(source: Path, destination: Path, label: str) -> None:
    root = _validate_source_tree(source, label)
    shutil.copytree(root, destination, copy_function=shutil.copy2)


def _copy_presensi_locked(source: Path, destination: Path) -> None:
    root = _validate_source_tree(source, "Presensi")
    lock_path = root / "events.lock"
    if not lock_path.is_file() or lock_path.is_symlink():
        raise BackupError("Presensi events.lock is required for a coordinated snapshot")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            # Recheck after acquiring the same lock used by the PHP writer.
            _validate_source_tree(root, "Presensi")
            shutil.copytree(root, destination, copy_function=shutil.copy2)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def component_files(component: str, root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = _safe_relative(path.relative_to(root).as_posix())
        rows.append(
            {
                "path": f"{component}/{relative}",
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not rows:
        raise BackupError(f"{component} backup component contains no files")
    return rows


def refresh_component_manifest(manifest: MutableMapping[str, object], component: str, root: Path) -> None:
    """Refresh one component inventory. Public to support offline drill fixtures."""
    components = manifest.setdefault("components", {})
    if not isinstance(components, dict):
        raise BackupError("manifest components are invalid")
    rows = component_files(component, root)
    components[component] = {
        "file_count": len(rows),
        "total_bytes": sum(cast(int, row["size"]) for row in rows),
        "files": rows,
    }


def _rows_sha256(rows: list[str]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _query_rows(
    runner: CommandRunner,
    config: BackupConfig,
    dsn: str,
    marker: str,
    sql: str,
) -> list[str]:
    output = runner(
        [
            config.psql_command,
            "--no-psqlrc",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--set=ON_ERROR_STOP=1",
            "--command",
            f"/* hollawall-contract:{marker} */\n{sql}",
        ],
        env={"PGDATABASE": dsn},
    )
    if not isinstance(output, str):
        raise BackupError("psql contract query returned no output")
    return [line for line in output.splitlines() if line]


def _migration_version() -> str:
    migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if not migrations:
        raise BackupError("database migration version is unavailable")
    return migrations[-1].stem


def _postgres_contract(
    runner: CommandRunner,
    config: BackupConfig,
    dsn: str,
) -> dict[str, object]:
    metadata_rows = _query_rows(
        runner,
        config,
        dsn,
        "metadata",
        """
        SELECT jsonb_build_object(
            'lsn', pg_current_wal_lsn()::text,
            'cutoff', to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),
            'schema', current_schema()
        )::text
        """,
    )
    if len(metadata_rows) != 1:
        raise BackupError("PostgreSQL cutoff metadata is invalid")
    try:
        metadata = json.loads(metadata_rows[0])
    except json.JSONDecodeError as error:
        raise BackupError("PostgreSQL cutoff metadata is invalid") from error
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("lsn"), str)
        or not LSN_PATTERN.fullmatch(metadata["lsn"])
        or not isinstance(metadata.get("cutoff"), str)
        or not metadata["cutoff"].endswith("Z")
        or metadata.get("schema") != "public"
    ):
        raise BackupError("PostgreSQL cutoff metadata is invalid")

    schema_rows = _query_rows(
        runner,
        config,
        dsn,
        "schema",
        """
        SELECT jsonb_build_object(
            'table_name', table_name,
            'column_name', column_name,
            'data_type', data_type
        )::text
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """,
    )
    if not schema_rows:
        raise BackupError("PostgreSQL public schema inventory is empty")

    application: dict[str, dict[str, object]] = {}
    for table in POSTGRES_APPLICATION_TABLES:
        rows = _query_rows(
            runner,
            config,
            dsn,
            table,
            f"SELECT to_jsonb(row_data)::text FROM public.{table} AS row_data "
            "ORDER BY to_jsonb(row_data)::text",
        )
        application[table] = {"total": len(rows), "sha256": _rows_sha256(rows)}
    return {
        "lsn": metadata["lsn"],
        "cutoff": metadata["cutoff"],
        "schema": {"name": "public", "sha256": _rows_sha256(schema_rows)},
        "migration_version": _migration_version(),
        "application": application,
    }


def _source_record(kind: str, source_identity: str) -> dict[str, str]:
    return {
        "kind": kind,
        "identifier": "[REDACTED]",
        "fingerprint_sha256": fingerprint(source_identity),
    }


def _build_manifest(
    staging: Path,
    config: BackupConfig,
    dsn: str,
    created_at: str,
    postgres_contract: Mapping[str, object],
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "created_at": created_at,
        "archive": {"encryption": "openssl-aes-256-cbc-pbkdf2", "tar_format": "pax"},
        "sources": {
            "postgres": {
                "kind": "postgresql",
                "identifier": "[REDACTED]",
                "fingerprint_sha256": database_fingerprint(dsn),
            },
            "sheets": _source_record("google-sheets-export-or-copy", str(config.sheets_source.expanduser().resolve())),
            "presensi": _source_record("presensi-private-tree", str(config.presensi_source.expanduser().resolve())),
        },
        "components": {},
        "postgresql": dict(postgres_contract),
    }
    for component in ("postgres", "sheets", "presensi"):
        refresh_component_manifest(manifest, component, staging / component)
    return manifest


def _write_tar(staging: Path, destination: Path) -> None:
    files = [path for path in sorted(staging.rglob("*")) if path.is_file()]
    with tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as bundle:
        for path in files:
            bundle.add(path, arcname=path.relative_to(staging).as_posix(), recursive=False)


def _read_archive_members(path: Path) -> set[str]:
    try:
        with tarfile.open(path, "r:") as bundle:
            names: set[str] = set()
            for member in bundle.getmembers():
                normalized = _safe_relative(member.name)
                if not member.isfile() or normalized in names:
                    raise BackupError("archive contains an invalid member")
                names.add(normalized)
            if "manifest.json" not in names:
                raise BackupError("archive manifest is missing")
            return names
    except (tarfile.TarError, OSError) as error:
        raise BackupError("archive tar readback failed") from error


def _encrypt(
    source: Path,
    destination: Path,
    key: str,
    config: BackupConfig,
    runner: CommandRunner,
) -> None:
    runner(
        [
            config.openssl_command,
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-in",
            str(source),
            "-out",
            str(destination),
            "-pass",
            f"env:{ARCHIVE_KEY_CHILD_ENV}",
        ],
        env={ARCHIVE_KEY_CHILD_ENV: key},
    )


def _decrypt_and_readback(
    encrypted: Path,
    key: str,
    config: BackupConfig,
    runner: CommandRunner,
    work_dir: Path,
    expected_plain_sha256: str,
) -> set[str]:
    work_dir.mkdir(parents=True, exist_ok=True)
    decrypted = work_dir / "readback.tar"
    runner(
        [
            config.openssl_command,
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-in",
            str(encrypted),
            "-out",
            str(decrypted),
            "-pass",
            f"env:{ARCHIVE_KEY_CHILD_ENV}",
        ],
        env={ARCHIVE_KEY_CHILD_ENV: key},
    )
    if not decrypted.is_file() or sha256_file(decrypted) != expected_plain_sha256:
        raise BackupError("decrypted tar byte readback mismatch")
    return _read_archive_members(decrypted)


def _archive_key(config: BackupConfig, environ: Mapping[str, str]) -> str:
    if config.archive_key_path is not None:
        path = config.archive_key_path.expanduser()
        if path.is_symlink() or not path.is_file():
            raise BackupError("archive key file is unavailable")
        try:
            key = path.read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError) as error:
            raise BackupError("archive key file cannot be read") from error
    elif config.archive_key_env:
        key = str(environ.get(config.archive_key_env, ""))
    else:
        key = ""
    if not key:
        raise BackupError("archive key is not configured")
    return key


def _validate_rclone(config: BackupConfig) -> tuple[Path, str] | None:
    if config.rclone_config is None and config.rclone_destination is None:
        return None
    if config.rclone_config is None or not config.rclone_destination:
        raise BackupError("rclone config and destination must be supplied together")
    rclone_config = config.rclone_config.expanduser().resolve()
    if rclone_config.is_symlink() or not rclone_config.is_file():
        raise BackupError("explicit rclone config is unavailable")
    destination = config.rclone_destination.rstrip("/")
    if ":" not in destination or destination.startswith(":"):
        raise BackupError("rclone destination must include an explicit remote")
    return rclone_config, destination


def _timestamp(now: Callable[[], datetime]) -> tuple[str, str]:
    selected = now()
    if selected.tzinfo is None:
        raise BackupError("backup clock must be timezone-aware")
    utc = selected.astimezone(UTC).replace(microsecond=0)
    return utc.strftime("%Y%m%dT%H%M%SZ"), utc.isoformat().replace("+00:00", "Z")


def run_backup(
    config: BackupConfig,
    *,
    apply: bool = False,
    runner: CommandRunner | None = None,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Plan or execute one coordinated backup."""
    if not apply:
        return {
            "action": "dry-run",
            "components": ["postgres", "sheets", "presensi"],
            "mutation": False,
            "offsite_upload": bool(config.rclone_destination),
        }

    selected_env = dict(os.environ if environ is None else environ)
    selected_runner = runner or _default_runner
    selected_now = now or (lambda: datetime.now(UTC))
    dsn = str(selected_env.get(config.postgres_dsn_env, ""))
    if not dsn:
        raise BackupError("PostgreSQL backup DSN is not configured")
    database_identity(dsn)
    key = _archive_key(config, selected_env)
    rclone = _validate_rclone(config)
    sheets = _validate_source_tree(config.sheets_source, "Sheets")
    presensi = _validate_source_tree(config.presensi_source, "Presensi")
    output = config.output_dir.expanduser().resolve()
    if output == sheets or output == presensi or output.is_relative_to(sheets) or output.is_relative_to(presensi):
        raise BackupError("backup output must be outside source trees")

    stamp, created_at = _timestamp(selected_now)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = output / f"hollawall-backup-{stamp}.tar.enc"
    if archive.exists():
        raise BackupError("backup archive already exists")

    with tempfile.TemporaryDirectory(prefix=".hollawall-backup-", dir=output) as temporary:
        work = Path(temporary)
        staging = work / "payload"
        (staging / "postgres").mkdir(parents=True)
        dump_path = staging / "postgres" / "database.dump"
        postgres_contract = _postgres_contract(selected_runner, config, dsn)
        selected_runner(
            [
                config.pg_dump_command,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--serializable-deferrable",
                "--file",
                str(dump_path),
            ],
            env={"PGDATABASE": dsn},
        )
        if not dump_path.is_file() or dump_path.stat().st_size == 0:
            raise BackupError("pg_dump did not create a non-empty custom dump")

        _copy_tree(sheets, staging / "sheets", "Sheets")
        _copy_presensi_locked(presensi, staging / "presensi")
        manifest = _build_manifest(staging, config, dsn, created_at, postgres_contract)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        plain_tar = work / "payload.tar"
        candidate = work / archive.name
        _write_tar(staging, plain_tar)
        plain_tar_sha256 = sha256_file(plain_tar)
        expected_members = {
            path.relative_to(staging).as_posix()
            for path in staging.rglob("*")
            if path.is_file()
        }
        _encrypt(plain_tar, candidate, key, config, selected_runner)
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise BackupError("encryption did not create an archive")
        readback = _decrypt_and_readback(
            candidate,
            key,
            config,
            selected_runner,
            work / "local-readback",
            plain_tar_sha256,
        )
        if readback != expected_members:
            raise BackupError("encrypted archive member readback mismatch")
        candidate.replace(archive)
        archive.chmod(0o600)

        result: dict[str, object] = {
            "action": "apply",
            "archive": str(archive),
            "archive_sha256": sha256_file(archive),
            "verified": True,
            "uploaded": False,
            "downloaded_byte_verified": False,
        }

        if rclone is not None:
            rclone_config, destination = rclone
            remote = f"{destination}/{archive.name}"
            selected_runner(
                [config.rclone_command, "--config", str(rclone_config), "copyto", str(archive), remote],
                env={},
            )
            downloaded = work / "downloaded" / archive.name
            downloaded.parent.mkdir()
            selected_runner(
                [config.rclone_command, "--config", str(rclone_config), "copyto", remote, str(downloaded)],
                env={},
            )
            if not downloaded.is_file() or sha256_file(downloaded) != result["archive_sha256"]:
                raise BackupError("downloaded encrypted archive hash mismatch")
            downloaded_readback = _decrypt_and_readback(
                downloaded,
                key,
                config,
                selected_runner,
                work / "downloaded-readback",
                plain_tar_sha256,
            )
            if downloaded_readback != expected_members:
                raise BackupError("downloaded archive decrypt/tar readback mismatch")
            result["uploaded"] = True
            result["downloaded_byte_verified"] = True
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sheets-source", type=Path, required=True)
    parser.add_argument("--presensi-source", type=Path, required=True)
    parser.add_argument("--postgres-dsn-env", default="HOLLAWALL_BACKUP_DATABASE_URL")
    key = parser.add_mutually_exclusive_group()
    key.add_argument("--archive-key-env", default="HOLLAWALL_ARCHIVE_KEY")
    key.add_argument("--archive-key-file", type=Path)
    parser.add_argument("--rclone-config", type=Path)
    parser.add_argument("--rclone-destination")
    parser.add_argument("--pg-dump-command", default="pg_dump")
    parser.add_argument("--psql-command", default="psql")
    parser.add_argument("--openssl-command", default="openssl")
    parser.add_argument("--rclone-command", default="rclone")
    parser.add_argument("--apply", action="store_true", help="execute backup mutations")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = BackupConfig(
        output_dir=args.output_dir,
        sheets_source=args.sheets_source,
        presensi_source=args.presensi_source,
        postgres_dsn_env=args.postgres_dsn_env,
        archive_key_env=None if args.archive_key_file else args.archive_key_env,
        archive_key_path=args.archive_key_file,
        rclone_config=args.rclone_config,
        rclone_destination=args.rclone_destination,
        pg_dump_command=args.pg_dump_command,
        psql_command=args.psql_command,
        openssl_command=args.openssl_command,
        rclone_command=args.rclone_command,
    )
    try:
        result = run_backup(config, apply=args.apply)
    except BackupError as error:
        print(json.dumps({"action": "apply" if args.apply else "dry-run", "error": str(error), "success": False}))
        raise SystemExit(2) from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
