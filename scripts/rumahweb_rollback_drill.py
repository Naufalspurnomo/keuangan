#!/usr/bin/env python3
"""Exercise atomic rollback against isolated Rumahweb canary directories."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tempfile
import time
import urllib.request
from ftplib import FTP_TLS  # nosec B402 -- cast only; TLS session created by deployer
from pathlib import Path
from typing import Any, cast

from deploy_rumahweb_presensi_atomic import (
    ReleaseSpec,
    connect,
    deploy_pair,
    ensure_dir,
    exists,
    remove_tree,
)


def public_digest(url: str) -> str:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310 -- fixed HTTPS URLs
        return hashlib.sha256(response.read()).hexdigest()


def read_file(ftp: Any, path: str) -> bytes:
    sink = io.BytesIO()
    ftp.retrbinary(f"RETR {path}", sink.write)
    return sink.getvalue()


class FailingRenameProxy:
    def __init__(self, ftp: Any, source: str, target: str) -> None:
        self._ftp = ftp
        self._source = source
        self._target = target
        self.injected = False

    def rename(self, source: str, target: str) -> Any:
        if not self.injected and source == self._source and target == self._target:
            self.injected = True
            raise RuntimeError("injected isolated activation failure")
        return self._ftp.rename(source, target)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ftp, name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()

    host = os.environ["RW_FTP_HOST"]
    user = os.environ["RW_FTP_USER"]
    password = os.environ["RW_FTP_PASSWORD"]
    tag = f"drill{int(time.time())}"
    root = f"public_html/.hollawall-rollback-{tag}"
    live_a = f"{root}/a"
    live_b = f"{root}/b"
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    before_public = {
        "admin": public_digest("https://hollawall.com/admin/release-manifest.json"),
        "absen": public_digest("https://hollawall.com/absen/release-manifest.json"),
    }
    result: dict[str, Any] = {
        "isolated_root": root,
        "failure_injected": False,
        "rollback_verified": False,
        "production_unchanged": False,
        "cleanup_verified": False,
    }

    ftp = connect(host, user, password, int(os.getenv("RW_FTP_PORT", "21")))
    try:
        ensure_dir(ftp, live_a)
        ensure_dir(ftp, live_b)
        ftp.storbinary(f"STOR {live_a}/sentinel.txt", io.BytesIO(b"old-a"))
        ftp.storbinary(f"STOR {live_b}/sentinel.txt", io.BytesIO(b"old-b"))
        with tempfile.TemporaryDirectory(prefix="hollawall-rollback-") as tmp:
            temp = Path(tmp)
            release_a = temp / "a"
            release_b = temp / "b"
            release_a.mkdir()
            release_b.mkdir()
            (release_a / "sentinel.txt").write_bytes(b"new-a")
            (release_b / "sentinel.txt").write_bytes(b"new-b")
            fail_source = f"{live_b}.__next_{tag}"
            proxy = FailingRenameProxy(ftp, fail_source, live_b)
            try:
                deploy_pair(
                    cast(FTP_TLS, proxy),
                    [
                        ReleaseSpec("a", release_a, live_a),
                        ReleaseSpec("b", release_b, live_b),
                    ],
                    tag,
                    timestamp,
                )
            except RuntimeError as exc:
                if "injected isolated activation failure" not in str(exc):
                    raise
            else:
                raise RuntimeError("rollback drill did not inject the expected failure")
            result["failure_injected"] = proxy.injected

        result["rollback_verified"] = (
            read_file(ftp, f"{live_a}/sentinel.txt") == b"old-a"
            and read_file(ftp, f"{live_b}/sentinel.txt") == b"old-b"
        )
        after_public = {
            "admin": public_digest("https://hollawall.com/admin/release-manifest.json"),
            "absen": public_digest("https://hollawall.com/absen/release-manifest.json"),
        }
        result["production_unchanged"] = before_public == after_public
    finally:
        if exists(ftp, root):
            remove_tree(ftp, root)
        result["cleanup_verified"] = not exists(ftp, root)
        try:
            ftp.quit()
        except Exception:
            ftp.close()
        for name in ("RW_FTP_HOST", "RW_FTP_USER", "RW_FTP_PASSWORD"):
            os.environ.pop(name, None)

    result["ok"] = all(
        result[key]
        for key in (
            "failure_injected",
            "rollback_verified",
            "production_unchanged",
            "cleanup_verified",
        )
    )
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "isolated": True}, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
