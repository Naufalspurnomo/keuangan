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
DEFAULT_CANONICAL_URL = (
    "https://renewed-loreen-hollawalls-8d8f6f5c.koyeb.app"
    "/api/dashboard/v1/canonical-transactions"
)
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


def replace_php_value(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"('{re.escape(key)}'\s*=>\s*)(?:true|false|'(?:\\.|[^'])*')")
    replacement = rf"\g<1>{php_single_quoted(value)}"
    if len(pattern.findall(text)) != 1:
        raise RuntimeError(f"config key missing or duplicated: {key}")
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"config key update failed: {key}")
    return updated


def replace_php_bool(text: str, key: str, value: bool) -> str:
    pattern = re.compile(rf"('{re.escape(key)}'\s*=>\s*)(?:true|false|'(?:\\.|[^'])*')")
    if len(pattern.findall(text)) != 1:
        raise RuntimeError(f"config key missing or duplicated: {key}")
    updated, count = pattern.subn(rf"\g<1>{str(value).lower()}", text, count=1)
    if count != 1:
        raise RuntimeError(f"config key update failed: {key}")
    return updated


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


def exists(ftp: FTP_TLS, path: str) -> bool:
    try:
        ftp.size(path)
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--canonical-url", default=DEFAULT_CANONICAL_URL)
    parser.add_argument("--audience", default=DEFAULT_AUDIENCE)
    parser.add_argument("--port", type=int, default=21)
    parser.add_argument("--evidence")
    args = parser.parse_args()

    host = require_env("RW_FTP_HOST")
    user = require_env("RW_FTP_USER")
    password = require_env("RW_FTP_PASSWORD")
    secret = require_env("DASHBOARD_ACTOR_ASSERTION_SECRET")
    if len(secret) < 32:
        raise RuntimeError("dashboard actor assertion secret is too short")

    remote = safe_remote(args.remote)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    staging = f"{remote}.__next_{timestamp}"
    backup = f"{remote}.__prev_{timestamp}"
    evidence: dict[str, object] = {
        "remote": remote,
        "staging": staging,
        "backup": backup,
        "success": False,
        "rolled_back": False,
    }

    ftp = connect(host, user, password, args.port)
    try:
        original = download(ftp, remote)
        text = original.decode("utf-8")
        text = replace_php_value(text, "upstream_canonical_transactions_url", args.canonical_url)
        text = replace_php_value(text, "dashboard_actor_assertion_audience", args.audience)
        text = replace_php_value(text, "dashboard_actor_assertion_secret", secret)
        text = replace_php_bool(text, "canonical_finance_writes_enabled", True)
        updated = text.encode("utf-8")
        if secret.encode("utf-8") not in updated:
            raise RuntimeError("secret synchronization validation failed")
        if exists(ftp, staging) or exists(ftp, backup):
            raise RuntimeError("staging or backup collision")

        ftp.storbinary(f"STOR {staging}", io.BytesIO(updated))
        staged = download(ftp, staging)
        if staged != updated:
            raise RuntimeError("staged config readback mismatch")

        ftp.rename(remote, backup)
        try:
            ftp.rename(staging, remote)
            final = download(ftp, remote)
            if final != updated:
                raise RuntimeError("final config readback mismatch")
        except Exception:
            if exists(ftp, remote):
                ftp.delete(remote)
            ftp.rename(backup, remote)
            evidence["rolled_back"] = True
            raise

        evidence.update(
            {
                "success": True,
                "before_sha256": hashlib.sha256(original).hexdigest(),
                "after_sha256": hashlib.sha256(updated).hexdigest(),
                "staged_readback": True,
                "final_readback": True,
                "canonical_url_host": args.canonical_url.split("/", 3)[2],
                "audience": args.audience,
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
