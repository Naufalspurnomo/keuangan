#!/usr/bin/env python3
"""Build the path-isolated Hollawall /absen release with immutable provenance."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import release_manifest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "rumahweb-presensi"
OUTPUT = ROOT / "artifacts" / "rumahweb-presensi-release"
LOGO = ROOT / "dashboard" / "src" / "assets" / "hollawall-logo.png"


def build_release(*, output: Path, provenance_path: Path, artifact_revision: str) -> Path:
    if output.exists():
        shutil.rmtree(output)
    absen = output / "absen"
    shutil.copytree(TEMPLATE, absen)
    brand = absen / "brand"
    brand.mkdir()
    shutil.copy2(LOGO, brand / "hollawall-logo.png")
    required = {
        "api/login.php",
        "api/logout.php",
        "api/outbox-claim.php",
        "api/outbox-ack.php",
        "api/bootstrap.php",
        "api/status.php",
        "api/submit.php",
        "presensi/index.php",
        "assets/presensi.js",
        "assets/presensi.css",
    }
    missing = sorted(path for path in required if not (absen / path).is_file())
    if missing:
        raise RuntimeError(f"required presensi release files missing: {missing}")
    forbidden = {"events.json", "rate-limits.json", ".hollawall-presensi.php"}
    for path in absen.rglob("*"):
        if path.name in forbidden:
            raise RuntimeError(f"runtime data leaked into release: {path}")
    manifest = release_manifest.build_manifest(
        component="rumahweb-presensi",
        payload_root=absen,
        provenance=release_manifest.load_provenance(provenance_path),
        artifact_revision=artifact_revision,
    )
    release_manifest.write_manifest(absen / "release-manifest.json", manifest)
    release_manifest.write_sha256sums(absen / "SHA256SUMS", manifest)
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
