from __future__ import annotations

import json
from pathlib import Path

from scripts import build_koyeb_release, build_rumahweb_admin_release, build_rumahweb_presensi_release


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
BASELINE = "b" * 40


def write_provenance(tmp_path: Path) -> Path:
    path = tmp_path / "provenance.json"
    path.write_text(
        json.dumps(
            {
                "schema": "hollawall.release-provenance/v1",
                "required_baseline_sha": BASELINE,
                "implementation_head_sha": SHA,
                "parent_sha": "c" * 40,
                "dirty": False,
                "submodules": [],
                "dependency_lockfiles": {"requirements.txt": "d" * 64},
                "candidate_diff": f"{BASELINE}..{SHA}",
            }
        ),
        encoding="utf-8",
    )
    return path


def assert_release_manifest(output: Path, component: str) -> None:
    manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "hollawall.release-manifest/v1"
    assert manifest["component"] == component
    assert manifest["artifact_revision"] == SHA
    assert manifest["source"]["implementation_head_sha"] == SHA
    assert len(manifest["manifest_sha256"]) == 64


def test_presensi_builder_requires_and_consumes_provenance(tmp_path: Path) -> None:
    output = tmp_path / "presensi-release"
    build_rumahweb_presensi_release.build_release(
        output=output,
        provenance_path=write_provenance(tmp_path),
        artifact_revision=SHA,
    )
    assert_release_manifest(output, "rumahweb-presensi")
    sums = (output / "SHA256SUMS").read_text(encoding="utf-8")
    assert "release-manifest.json" not in sums


def test_admin_builder_consumes_provenance_without_running_node(tmp_path: Path) -> None:
    dashboard_dist = tmp_path / "dist"
    (dashboard_dist / "assets").mkdir(parents=True)
    (dashboard_dist / "assets" / "app.js").write_text("console.log('ok');", encoding="utf-8")
    (dashboard_dist / "index.html").write_text(
        '<html><script src="/admin/assets/app.js"></script></html>',
        encoding="utf-8",
    )
    output = tmp_path / "admin-release"

    build_rumahweb_admin_release.build_release(
        output=output,
        provenance_path=write_provenance(tmp_path),
        artifact_revision=SHA,
        dashboard_dist=dashboard_dist,
        run_dashboard_build=False,
    )

    assert_release_manifest(output, "rumahweb-admin")


def test_koyeb_builder_emits_release_manifest_for_container_context(tmp_path: Path) -> None:
    context = tmp_path / "context"
    output = tmp_path / "koyeb-release"
    (context / "app").mkdir(parents=True)
    (context / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    build_koyeb_release.build_release(
        source_root=context,
        output=output,
        provenance_path=write_provenance(tmp_path),
        artifact_revision=SHA,
    )

    assert (output / "context" / "app" / "main.py").is_file()
    assert_release_manifest(output, "koyeb-backend")
