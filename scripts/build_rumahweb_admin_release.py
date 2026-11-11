#!/usr/bin/env python3
"""Build the path-isolated Rumahweb /admin release with immutable provenance."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from scripts import release_manifest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
TEMPLATE = ROOT / "deploy" / "rumahweb-admin"
OUTPUT = ROOT / "artifacts" / "rumahweb-admin-release"


def build_release(
    *,
    output: Path,
    provenance_path: Path,
    artifact_revision: str,
    dashboard_dist: Path | None = None,
    run_dashboard_build: bool = True,
) -> Path:
    dist = (dashboard_dist or DASHBOARD / "dist").resolve()
    if run_dashboard_build:
        env = os.environ.copy()
        env["VITE_PUBLIC_BASE"] = "/admin/"
        env["VITE_SNAPSHOT_URL"] = "/admin/api/snapshot.php"
        subprocess.run(["npm", "run", "build"], cwd=DASHBOARD, env=env, check=True)
    if not (dist / "index.html").is_file() or not (dist / "assets").is_dir():
        raise RuntimeError("dashboard build output is missing")

    if output.exists():
        shutil.rmtree(output)
    admin = output / "admin"
    shutil.copytree(TEMPLATE, admin)
    (admin / "config.example.php").unlink()
    shutil.copy2(ROOT / "deploy" / "rumahweb-presensi" / "api" / "presensi-common.php", admin / "api" / "presensi-common.php")
    shutil.copytree(dist / "assets", admin / "assets")
    brand = admin / "brand"
    brand.mkdir()
    for asset in ("hollawall-logo.png", "waves-background.svg"):
        shutil.copy2(DASHBOARD / "src" / "assets" / asset, brand / asset)

    shell = (dist / "index.html").read_text(encoding="utf-8")
    guarded = "<?php defined('HOLLAWALL_AUTHENTICATED') || exit; ?>\n" + shell
    (admin / "app-shell.php").write_text(guarded, encoding="utf-8")
    for token in ("/live-api/snapshot", 'src="/assets/', 'href="/assets/'):
        if token in guarded:
            raise RuntimeError(f"non-isolated build reference: {token}")

    manifest = release_manifest.build_manifest(
        component="rumahweb-admin",
        payload_root=admin,
        provenance=release_manifest.load_provenance(provenance_path),
        artifact_revision=artifact_revision,
    )
    release_manifest.write_manifest(output / "release-manifest.json", manifest)
    release_manifest.write_sha256sums(output / "SHA256SUMS", manifest)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--artifact-revision", required=True)
    args = parser.parse_args()
    print(build_release(output=args.output, provenance_path=args.provenance, artifact_revision=args.artifact_revision))


if __name__ == "__main__":
    main()
