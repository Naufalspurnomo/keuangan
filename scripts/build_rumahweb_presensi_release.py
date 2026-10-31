#!/usr/bin/env python3
"""Build the path-isolated Hollawall /absen presensi release."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "rumahweb-presensi"
OUTPUT = ROOT / "artifacts" / "rumahweb-presensi-release"
LOGO = ROOT / "dashboard" / "src" / "assets" / "hollawall-logo.png"


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    absen = OUTPUT / "absen"
    shutil.copytree(TEMPLATE, absen)
    brand = absen / "brand"
    brand.mkdir()
    shutil.copy2(LOGO, brand / "hollawall-logo.png")
    forbidden = {"events.json", "rate-limits.json", ".hollawall-presensi.php"}
    for path in absen.rglob("*"):
        if path.name in forbidden:
            raise RuntimeError(f"runtime data leaked into release: {path}")
    files = sorted(path for path in absen.rglob("*") if path.is_file())
    manifest = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(absen).as_posix()}\n" for path in files)
    (OUTPUT / "SHA256SUMS").write_text(manifest, encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
