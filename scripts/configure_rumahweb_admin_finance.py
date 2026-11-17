#!/usr/bin/env python3
"""Atomically synchronize private Rumahweb finance routing without exposing secrets."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import ssl
import time
from ftplib import FTP_TLS  # nosec B402 -- TLS-only deployer with certificate verification
from pathlib import PurePosixPath
from typing import cast

DEFAULT_REMOTE = ".hollawall-admin.php"
DEFAULT_PRESENSI_REMOTE = ".hollawall-presensi.php"
DEFAULT_BACKEND_ORIGIN = "https://renewed-loreen-hollawalls-8d8f6f5c.koyeb.app"
DEFAULT_PROJECT_CATALOG_URL = DEFAULT_BACKEND_ORIGIN + "/internal/presensi/projects"
DEFAULT_CANONICAL_URL = DEFAULT_BACKEND_ORIGIN + "/api/dashboard/v1/canonical-transactions"
DEFAULT_SNAPSHOT_URL = DEFAULT_BACKEND_ORIGIN + "/api/dashboard/v1/snapshot"
DEFAULT_AUDIENCE = "hollawall-finance-api"


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable missing: {name}")
    return value


def safe_remote(path: str) -> str:
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"unsafe remote path: {path!r}")
    return parsed.as_posix()


def php_single_quoted(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def upsert_php_literal(text: str, key: str, literal: str) -> str:
    pattern = re.compile(rf"('{re.escape(key)}'\s*=>\s*)(?:true|false|'(?:\\.|[^'])*')")
    matches = pattern.findall(text)
    if len(matches) > 1:
        raise RuntimeError(f"config key duplicated: {key}")
    if len(matches) == 1:
        updated, count = pattern.subn(rf"\g<1>{literal}", text, count=1)
        if count != 1:
            raise RuntimeError(f"config key update failed: {key}")
        return updated

    normalized = text.lstrip("\ufeff").lstrip()
    if not normalized.startswith("<?php") or re.search(r"\b(?:class|function|namespace)\b", normalized):
        raise RuntimeError("config is not a supported PHP config document")

    return_arrays = list(re.finditer(r"\breturn\s*\[", normalized))
    closing = re.search(
        r"(?P<tail>\]\s*;)(?P<suffix>\s*(?:(?://[^\r\n]*|/\*.*?\*/)\s*)*(?:\?>\s*)?)\Z",
        text,
        re.DOTALL,
    )
    if len(return_arrays) == 1 and closing is not None and "=>" in normalized[return_arrays[0].end() :]:
        insertion = f"\n    {php_single_quoted(key)} => {literal},"
        return text[: closing.start("tail")] + insertion + text[closing.start("tail") :]

    # Older production provisioners used either return array(...) or assigned
    # the array to $config before returning it. In both forms the unique
    # top-level employees key is a stable, syntax-preserving insertion anchor.
    employees = list(re.finditer(r"(?m)^(?P<indent>\s*)'employees'\s*=>", text))
    projects = list(re.finditer(r"(?m)^\s*'projects'\s*=>", text))
    legacy_wrapper = bool(
        re.search(r"\breturn\s+array\s*\(", normalized)
        or (re.search(r"\$config\s*=\s*(?:\[|array\s*\()", normalized) and re.search(r"\breturn\s+\$config\s*;", normalized))
    )
    if not legacy_wrapper or len(employees) != 1 or len(projects) != 1:
        raise RuntimeError("config is not a supported PHP config document")
    anchor = employees[0]
    insertion = f"{anchor.group('indent')}{php_single_quoted(key)} => {literal},\n"
    return text[: anchor.start()] + insertion + text[anchor.start() :]


def replace_php_value(text: str, key: str, value: str) -> str:
    return upsert_php_literal(text, key, php_single_quoted(value))


def replace_php_bool(text: str, key: str, value: bool) -> str:
    return upsert_php_literal(text, key, str(value).lower())


def connect(host: str, user: str, password: str, port: int) -> FTP_TLS:
    ftp = FTP_TLS(context=ssl.create_default_context(), timeout=60)
    ftp.connect(host, port)
    ftp.login(user, password)
    ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def download(ftp: FTP_TLS, path: str) -> bytes:
    buffer = io.BytesIO()
    ftp.retrbinary(f"RETR {path}", buffer.write)
    return buffer.getvalue()


def chmod_private(ftp: FTP_TLS, path: str) -> None:
    response = ftp.sendcmd(f"SITE CHMOD 600 {path}")
    if not str(response).startswith("2"):
        raise RuntimeError(f"private config chmod failed for {path}")


def prepare_replace(ftp: FTP_TLS, remote: str, updated: bytes, timestamp: str) -> dict[str, object]:
    staging = f"{remote}.__next_{timestamp}"
    backup = f"{remote}.__prev_{timestamp}"
    if exists(ftp, staging) or exists(ftp, backup):
        raise RuntimeError(f"staging or backup collision for {remote}")
    original = download(ftp, remote)
    ftp.storbinary(f"STOR {staging}", io.BytesIO(updated))
    chmod_private(ftp, staging)
    if download(ftp, staging) != updated:
        if exists(ftp, staging):
            ftp.delete(staging)
        raise RuntimeError(f"staged config readback mismatch for {remote}")
    return {
        "remote": remote,
        "staging": staging,
        "backup": backup,
        "original": original,
        "updated": updated,
    }


def restore_prepared(ftp: FTP_TLS, item: dict[str, object]) -> None:
    remote = cast(str, item["remote"])
    backup = cast(str, item["backup"])
    original = cast(bytes, item["original"])
    if exists(ftp, remote):
        ftp.delete(remote)
    if not exists(ftp, backup):
        raise RuntimeError(f"rollback backup missing for {remote}")
    ftp.rename(backup, remote)
    chmod_private(ftp, remote)
    if download(ftp, remote) != original:
        raise RuntimeError(f"rollback readback mismatch for {remote}")


def atomic_replace_many(
    ftp: FTP_TLS,
    updates: list[tuple[str, bytes]],
    timestamp: str,
) -> list[dict[str, object]]:
    prepared: list[dict[str, object]] = []
    activated: list[dict[str, object]] = []
    try:
        for remote, updated in updates:
            prepared.append(prepare_replace(ftp, remote, updated, timestamp))
        for item in prepared:
            remote = cast(str, item["remote"])
            staging = cast(str, item["staging"])
            backup = cast(str, item["backup"])
            ftp.rename(remote, backup)
            try:
                ftp.rename(staging, remote)
                chmod_private(ftp, remote)
                if download(ftp, remote) != cast(bytes, item["updated"]):
                    raise RuntimeError(f"final config readback mismatch for {remote}")
            except Exception:
                restore_prepared(ftp, item)
                raise
            activated.append(item)
    except Exception as activation_error:
        rollback_errors: list[str] = []
        for item in reversed(activated):
            try:
                restore_prepared(ftp, item)
            except Exception as rollback_error:  # pragma: no cover - catastrophic remote failure
                rollback_errors.append(str(rollback_error))
        for item in prepared:
            staging = cast(str, item["staging"])
            if exists(ftp, staging):
                ftp.delete(staging)
        if rollback_errors:
            raise RuntimeError("config activation failed and rollback was incomplete: " + "; ".join(rollback_errors)) from activation_error
        raise

    return [
        {
            "remote": item["remote"],
            "backup": item["backup"],
            "before_sha256": hashlib.sha256(cast(bytes, item["original"])).hexdigest(),
            "after_sha256": hashlib.sha256(cast(bytes, item["updated"])).hexdigest(),
            "staged_readback": True,
            "final_readback": True,
        }
        for item in prepared
    ]


def atomic_replace(ftp: FTP_TLS, remote: str, updated: bytes, timestamp: str) -> dict[str, object]:
    """Compatibility wrapper for one-file callers."""
    return atomic_replace_many(ftp, [(remote, updated)], timestamp)[0]


def exists(ftp: FTP_TLS, path: str) -> bool:
    try:
        ftp.size(path)
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--presensi-remote", default=DEFAULT_PRESENSI_REMOTE)
    parser.add_argument("--project-catalog-url", default=DEFAULT_PROJECT_CATALOG_URL)
    parser.add_argument("--canonical-url", default=DEFAULT_CANONICAL_URL)
    parser.add_argument("--snapshot-url", default=DEFAULT_SNAPSHOT_URL)
    parser.add_argument("--audience", default=DEFAULT_AUDIENCE)
    parser.add_argument("--port", type=int, default=21)
    parser.add_argument("--evidence")
    args = parser.parse_args()

    host = require_env("RW_FTP_HOST")
    user = require_env("RW_FTP_USER")
    password = require_env("RW_FTP_PASSWORD")
    secret = require_env("DASHBOARD_ACTOR_ASSERTION_SECRET")
    proxy_token = require_env("HOLLAWALL_LIVE_API_PROXY_TOKEN")
    owner_email = require_env("HOLLAWALL_OWNER_EMAIL").casefold()
    if len(secret) < 32:
        raise RuntimeError("dashboard actor assertion secret is too short")
    if not re.fullmatch(r"[^\x00-\x1F\x7F]{16,512}", proxy_token):
        raise RuntimeError("live API proxy token is invalid")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", owner_email):
        raise RuntimeError("owner email is invalid")

    remote = safe_remote(args.remote)
    presensi_remote = safe_remote(args.presensi_remote)
    project_catalog_url = str(args.project_catalog_url).strip()
    catalog_parts = project_catalog_url.split("/", 3)
    if len(catalog_parts) < 4 or catalog_parts[0] != "https:" or not catalog_parts[2]:
        raise RuntimeError("project catalog URL must be HTTPS")
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    evidence: dict[str, object] = {
        "remote": remote,
        "presensi_remote": presensi_remote,
        "success": False,
        "rolled_back": False,
    }

    ftp = connect(host, user, password, args.port)
    try:
        original = download(ftp, remote)
        text = original.decode("utf-8")
        text = replace_php_value(text, "upstream_canonical_transactions_url", args.canonical_url)
        text = replace_php_value(text, "upstream_snapshot_url", args.snapshot_url)
        text = replace_php_value(text, "dashboard_actor_assertion_audience", args.audience)
        text = replace_php_value(text, "dashboard_actor_assertion_secret", secret)
        text = replace_php_value(text, "proxy_token", proxy_token)
        text = replace_php_value(text, "owner_email", owner_email)
        text = replace_php_bool(text, "canonical_finance_writes_enabled", True)
        updated = text.encode("utf-8")
        if secret.encode("utf-8") not in updated:
            raise RuntimeError("secret synchronization validation failed")

        presensi_original = download(ftp, presensi_remote)
        presensi_text = replace_php_value(
            presensi_original.decode("utf-8"), "project_catalog_url", project_catalog_url
        )
        presensi_updated = presensi_text.encode("utf-8")

        admin_result, presensi_result = atomic_replace_many(
            ftp,
            [(remote, updated), (presensi_remote, presensi_updated)],
            timestamp,
        )
        evidence.update(
            {
                "success": True,
                "before_sha256": admin_result["before_sha256"],
                "after_sha256": admin_result["after_sha256"],
                "staged_readback": True,
                "final_readback": True,
                "canonical_url_host": args.canonical_url.split("/", 3)[2],
                "snapshot_url_host": args.snapshot_url.split("/", 3)[2],
                "snapshot_url_configured": True,
                "project_catalog_url_host": catalog_parts[2],
                "project_catalog_url_configured": True,
                "presensi_config_before_sha256": presensi_result["before_sha256"],
                "presensi_config_after_sha256": presensi_result["after_sha256"],
                "presensi_staged_readback": presensi_result["staged_readback"],
                "presensi_final_readback": presensi_result["final_readback"],
                "audience": args.audience,
                "owner_email_configured": True,
                "secret_present": True,
                "secret_exposed": False,
            }
        )
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()

    serialized = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        with open(args.evidence, "w", encoding="utf-8") as handle:
            handle.write(serialized)
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
