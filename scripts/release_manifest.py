#!/usr/bin/env python3
"""Build and verify deterministic, immutable Hollawall release manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping


SCHEMA = "hollawall.release-manifest/v1"
PROVENANCE_SCHEMA = "hollawall.release-provenance/v1"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class ManifestError(RuntimeError):
    """Raised when an artifact manifest is invalid or cannot remain immutable."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def manifest_digest(manifest: Mapping[str, object]) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest()


def load_provenance(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError("release provenance is missing or invalid") from error
    if not isinstance(value, dict):
        raise ManifestError("release provenance is missing or invalid")
    return value


def _validate_provenance(provenance: Mapping[str, object], artifact_revision: str) -> None:
    if provenance.get("schema") != PROVENANCE_SCHEMA or provenance.get("dirty") is not False:
        raise ManifestError("release manifest requires clean provenance")
    actual = provenance.get("implementation_head_sha")
    if not isinstance(actual, str) or not FULL_SHA.fullmatch(actual) or actual != artifact_revision:
        raise ManifestError("artifact revision does not match source provenance")
    baseline = provenance.get("required_baseline_sha")
    lockfiles = provenance.get("dependency_lockfiles")
    submodules = provenance.get("submodules")
    if not isinstance(baseline, str) or not FULL_SHA.fullmatch(baseline):
        raise ManifestError("release provenance baseline is invalid")
    if not isinstance(lockfiles, dict) or not lockfiles:
        raise ManifestError("release provenance lockfiles are invalid")
    if not isinstance(submodules, list):
        raise ManifestError("release provenance submodules are invalid")


def _payload_rows(root: Path) -> list[dict[str, object]]:
    if not root.is_dir() or root.is_symlink():
        raise ManifestError("release payload root is unavailable")
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ManifestError("release payload contains a symlink")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if relative == "release-manifest.json":
                raise ManifestError("release payload already contains a manifest")
            rows.append({"path": relative, "sha256": sha256_file(path), "size": path.stat().st_size})
    return rows


def build_manifest(
    *,
    component: str,
    payload_root: Path,
    provenance: Mapping[str, object],
    artifact_revision: str,
) -> dict[str, object]:
    revision = artifact_revision.strip().lower()
    if not component or not FULL_SHA.fullmatch(revision):
        raise ManifestError("component or artifact revision is invalid")
    _validate_provenance(provenance, revision)
    rows = _payload_rows(payload_root)
    manifest: dict[str, object] = {
        "schema": SCHEMA,
        "component": component,
        "artifact_revision": revision,
        "source": dict(provenance),
        "files": rows,
        "payload_sha256": hashlib.sha256(canonical_bytes({"files": rows})).hexdigest(),
    }
    manifest["manifest_sha256"] = manifest_digest(manifest)
    return manifest


def write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise ManifestError("immutable manifest already exists")
    if manifest.get("schema") != SCHEMA or manifest.get("manifest_sha256") != manifest_digest(manifest):
        raise ManifestError("release manifest self-digest is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(manifest))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_sha256sums(path: Path, manifest: Mapping[str, object]) -> None:
    """Write a compatibility checksum inventory from the signed payload rows."""
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise ManifestError("release manifest file inventory is invalid")
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
            raise ManifestError("release manifest file inventory is invalid")
        lines.append(f"{row['sha256']}  {row['path']}\n")
    if path.exists() or path.is_symlink():
        raise ManifestError("immutable checksum inventory already exists")
    path.write_text("".join(lines), encoding="utf-8")
    path.chmod(0o444)
