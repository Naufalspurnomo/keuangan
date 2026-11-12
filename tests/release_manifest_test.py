from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import release_manifest


SHA = "a" * 40
BASELINE = "b" * 40


def provenance() -> dict[str, object]:
    return {
        "schema": "hollawall.release-provenance/v1",
        "required_baseline_sha": BASELINE,
        "implementation_head_sha": SHA,
        "parent_sha": "c" * 40,
        "dirty": False,
        "submodules": [],
        "dependency_lockfiles": {"requirements.txt": "d" * 64},
        "candidate_diff": f"{BASELINE}..{SHA}",
    }


def test_build_release_manifest_hashes_exact_payload_and_is_deterministic(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")
    assets = payload / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok');\n", encoding="utf-8")

    first = release_manifest.build_manifest(
        component="rumahweb-admin",
        payload_root=payload,
        provenance=provenance(),
        artifact_revision=SHA,
    )
    second = release_manifest.build_manifest(
        component="rumahweb-admin",
        payload_root=payload,
        provenance=provenance(),
        artifact_revision=SHA,
    )

    assert first == second
    assert first["schema"] == "hollawall.release-manifest/v1"
    assert first["artifact_revision"] == SHA
    assert first["source"] == provenance()
    assert first["files"] == [
        {
            "path": "assets/app.js",
            "sha256": hashlib.sha256((assets / "app.js").read_bytes()).hexdigest(),
            "size": (assets / "app.js").stat().st_size,
        },
        {
            "path": "index.php",
            "sha256": hashlib.sha256((payload / "index.php").read_bytes()).hexdigest(),
            "size": (payload / "index.php").stat().st_size,
        },
    ]
    assert len(first["payload_sha256"]) == 64
    assert first["manifest_sha256"] == release_manifest.manifest_digest(first)


def test_write_manifest_refuses_overwrite_even_when_content_matches(tmp_path: Path) -> None:
    path = tmp_path / "release-manifest.json"
    manifest = {
        "schema": "hollawall.release-manifest/v1",
        "component": "koyeb-backend",
        "artifact_revision": SHA,
        "source": provenance(),
        "files": [],
        "payload_sha256": hashlib.sha256(b"").hexdigest(),
    }
    manifest["manifest_sha256"] = release_manifest.manifest_digest(manifest)

    release_manifest.write_manifest(path, manifest)
    assert json.loads(path.read_text(encoding="utf-8")) == manifest
    with pytest.raises(release_manifest.ManifestError, match="immutable manifest already exists"):
        release_manifest.write_manifest(path, manifest)


def test_build_manifest_rejects_dirty_or_mismatched_provenance(tmp_path: Path) -> None:
    dirty = provenance()
    dirty["dirty"] = True
    with pytest.raises(release_manifest.ManifestError, match="clean provenance"):
        release_manifest.build_manifest(
            component="rumahweb-presensi",
            payload_root=tmp_path,
            provenance=dirty,
            artifact_revision=SHA,
        )

    with pytest.raises(release_manifest.ManifestError, match="artifact revision"):
        release_manifest.build_manifest(
            component="rumahweb-presensi",
            payload_root=tmp_path,
            provenance=provenance(),
            artifact_revision="e" * 40,
        )
