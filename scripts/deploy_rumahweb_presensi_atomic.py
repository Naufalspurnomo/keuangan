#!/usr/bin/env python3
"""Coupled FTPS deployment for Hollawall /admin and /absen releases.

Both releases are uploaded and byte-verified before either live path changes.
Activation uses directory renames. Any activation/readback failure restores both
previous live paths in reverse order and preserves activated failed bytes.
Credentials are accepted only through environment variables and never logged.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import posixpath
import re
import ssl
import sys
import time
from ftplib import FTP_TLS, error_perm
from pathlib import Path, PurePosixPath
from typing import NamedTuple, cast


class ReleaseSpec(NamedTuple):
    name: str
    release: Path
    remote: str


class PreparedRelease(NamedTuple):
    spec: ReleaseSpec
    manifest: dict[str, dict[str, object]]
    staging: str
    backup: str
    failed: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_manifest(root: Path) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            rows[path.relative_to(root).as_posix()] = {
                "path": path,
                "size": len(data),
                "sha256": sha256(data),
            }
    if not rows:
        raise RuntimeError(f"release directory contains no files: {root}")
    return rows


def safe_remote(path: str) -> str:
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"remote path must be a safe relative path: {path!r}")
    normalized = parsed.as_posix()
    if normalized != path.rstrip("/"):
        raise ValueError(f"remote path must be a safe relative path: {path!r}")
    return normalized


def prepare_specs(specs: list[ReleaseSpec], tag: str, timestamp: str) -> list[PreparedRelease]:
    if len(specs) < 2:
        raise ValueError("at least two release paths are required")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
        raise ValueError("tag contains unsafe characters")
    remotes = [safe_remote(spec.remote) for spec in specs]
    if len(set(remotes)) != len(remotes):
        raise ValueError("remote paths must be unique")
    for index, left in enumerate(remotes):
        for right in remotes[index + 1 :]:
            if left.startswith(right + "/") or right.startswith(left + "/"):
                raise ValueError("remote paths must not overlap")
    prepared: list[PreparedRelease] = []
    for spec, remote in zip(specs, remotes, strict=True):
        root = spec.release.resolve()
        if not root.is_dir():
            raise RuntimeError(f"release directory not found: {root}")
        normalized = ReleaseSpec(spec.name, root, remote)
        prepared.append(PreparedRelease(
            normalized,
            local_manifest(root),
            f"{remote}.__next_{tag}",
            f"{remote}.__prev_{timestamp}",
            f"{remote}.__failed_{timestamp}",
        ))
    return prepared


def connect(host: str, user: str, password: str, port: int) -> FTP_TLS:
    ftp = FTP_TLS(context=ssl.create_default_context(), timeout=60)
    ftp.connect(host, port)
    ftp.login(user, password)
    ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def exists(ftp: FTP_TLS, path: str) -> bool:
    cwd = ftp.pwd()
    try:
        ftp.cwd(path)
        return True
    except error_perm:
        return False
    finally:
        try:
            ftp.cwd(cwd)
        except Exception:
            pass


def ensure_dir(ftp: FTP_TLS, path: str) -> None:
    current = ftp.pwd()
    try:
        ftp.cwd("/")
        for part in [item for item in path.split("/") if item]:
            try:
                ftp.cwd(part)
            except error_perm:
                ftp.mkd(part)
                ftp.cwd(part)
    finally:
        ftp.cwd(current)


def parse_mlsd(line: str) -> tuple[str, dict[str, str]]:
    facts_raw, name = line.split(" ", 1)
    facts: dict[str, str] = {}
    for item in facts_raw.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            facts[key.lower()] = value
    return name.strip(), facts


def list_tree(ftp: FTP_TLS, root: str) -> tuple[list[str], list[str]]:
    files: list[str] = []
    dirs: list[str] = []

    def walk(path: str) -> None:
        entries: list[tuple[str, dict[str, str]]] = []
        ftp.retrlines(f"MLSD {path}", lambda line: entries.append(parse_mlsd(line)))
        for name, facts in entries:
            if name in {".", ".."}:
                continue
            child = posixpath.join(path, name)
            if facts.get("type") == "dir":
                dirs.append(child)
                walk(child)
            elif facts.get("type") == "file":
                files.append(child)

    walk(root)
    return files, dirs


def remove_tree(ftp: FTP_TLS, root: str) -> None:
    if not exists(ftp, root):
        return
    files, dirs = list_tree(ftp, root)
    for path in files:
        ftp.delete(path)
    for path in sorted(dirs, key=lambda item: item.count("/"), reverse=True):
        ftp.rmd(path)
    ftp.rmd(root)


def readback(ftp: FTP_TLS, remote_root: str, manifest: dict[str, dict[str, object]]) -> dict[str, object]:
    observed: dict[str, dict[str, object]] = {}
    for rel in manifest:
        sink = io.BytesIO()
        ftp.retrbinary(f"RETR {posixpath.join(remote_root, rel)}", sink.write)
        data = sink.getvalue()
        observed[rel] = {"size": len(data), "sha256": sha256(data)}
    remote_files, _ = list_tree(ftp, remote_root)
    remote_rel = sorted(posixpath.relpath(path, remote_root) for path in remote_files)
    expected_rel = sorted(manifest)
    mismatches = [
        rel for rel, expected in manifest.items()
        if observed.get(rel, {}).get("size") != expected["size"]
        or observed.get(rel, {}).get("sha256") != expected["sha256"]
    ]
    unexpected = sorted(set(remote_rel) - set(expected_rel))
    missing = sorted(set(expected_rel) - set(remote_rel))
    return {
        "matched": len(expected_rel) - len(mismatches) - len(missing),
        "expected": len(expected_rel),
        "mismatches": mismatches,
        "unexpected": unexpected,
        "missing": missing,
        "ok": not mismatches and not unexpected and not missing,
    }


def prepare_release(ftp: FTP_TLS, prepared: PreparedRelease) -> dict[str, object]:
    ensure_dir(ftp, posixpath.dirname(prepared.spec.remote))
    remove_tree(ftp, prepared.staging)
    ensure_dir(ftp, prepared.staging)
    for rel, item in prepared.manifest.items():
        remote_path = posixpath.join(prepared.staging, rel)
        ensure_dir(ftp, posixpath.dirname(remote_path))
        with cast(Path, item["path"]).open("rb") as handle:
            ftp.storbinary(f"STOR {remote_path}", handle)
    staged = readback(ftp, prepared.staging, prepared.manifest)
    if not staged["ok"]:
        raise RuntimeError(f"staging readback failed for {prepared.spec.name}")
    return staged


def deploy_pair(
    ftp: FTP_TLS,
    specs: list[ReleaseSpec],
    tag: str,
    timestamp: str | None = None,
) -> dict[str, object]:
    timestamp = timestamp or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prepared = prepare_specs(specs, tag, timestamp)
    result: dict[str, object] = {
        "tag": tag,
        "timestamp": timestamp,
        "success": False,
        "activated": [],
        "rolled_back": False,
        "releases": {},
    }
    releases = result["releases"]
    assert isinstance(releases, dict)

    for item in prepared:
        staged = prepare_release(ftp, item)
        releases[item.spec.name] = {
            "remote": item.spec.remote,
            "staging": item.staging,
            "backup": item.backup,
            "failed": item.failed,
            "expected_files": len(item.manifest),
            "staged_readback": staged,
        }

    live_before = {item.spec.name: exists(ftp, item.spec.remote) for item in prepared}
    for item in prepared:
        if exists(ftp, item.backup) or exists(ftp, item.failed):
            raise RuntimeError(f"rollback target already exists for {item.spec.name}")

    activated: list[PreparedRelease] = []
    try:
        for item in prepared:
            if live_before[item.spec.name]:
                ftp.rename(item.spec.remote, item.backup)
        for item in prepared:
            ftp.rename(item.staging, item.spec.remote)
            activated.append(item)
            cast_activated = result["activated"]
            assert isinstance(cast_activated, list)
            cast_activated.append(item.spec.name)
        for item in prepared:
            final = readback(ftp, item.spec.remote, item.manifest)
            releases[item.spec.name]["final_readback"] = final
            if not final["ok"]:
                raise RuntimeError(f"final readback failed for {item.spec.name}")
    except Exception as original:
        rollback_errors: list[str] = []
        activated_names = {item.spec.name for item in activated}
        for item in reversed(prepared):
            try:
                if item.spec.name in activated_names and exists(ftp, item.spec.remote):
                    ftp.rename(item.spec.remote, item.failed)
                if exists(ftp, item.backup):
                    ftp.rename(item.backup, item.spec.remote)
                elif not live_before[item.spec.name] and exists(ftp, item.spec.remote):
                    remove_tree(ftp, item.spec.remote)
            except Exception as rollback_error:
                rollback_errors.append(f"{item.spec.name}: {rollback_error}")
        result["rolled_back"] = not rollback_errors
        if rollback_errors:
            raise RuntimeError(f"{original}; rollback errors: {'; '.join(rollback_errors)}") from original
        raise

    result["success"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-release", required=True, type=Path)
    parser.add_argument("--absen-release", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--admin-remote", default="public_html/admin")
    parser.add_argument("--absen-remote", default="public_html/absen")
    parser.add_argument("--port", type=int, default=int(os.getenv("RW_FTP_PORT", "21")))
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()

    host = os.environ.get("RW_FTP_HOST")
    user = os.environ.get("RW_FTP_USER")
    password = os.environ.get("RW_FTP_PASSWORD")
    if not all((host, user, password)):
        raise RuntimeError("RW_FTP_HOST, RW_FTP_USER, and RW_FTP_PASSWORD are required")

    specs = [
        ReleaseSpec("admin", args.admin_release, args.admin_remote),
        ReleaseSpec("absen", args.absen_release, args.absen_remote),
    ]
    ftp = connect(cast(str, host), cast(str, user), cast(str, password), args.port)
    try:
        result = deploy_pair(ftp, specs, args.tag)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
        for name in ("RW_FTP_HOST", "RW_FTP_USER", "RW_FTP_PASSWORD"):
            os.environ.pop(name, None)

    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "success": result["success"],
        "tag": result["tag"],
        "activated": result["activated"],
        "rolled_back": result["rolled_back"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        raise
