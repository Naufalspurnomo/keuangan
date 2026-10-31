#!/usr/bin/env python3
"""Build the path-isolated Rumahweb /admin release without touching WordPress root."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
TEMPLATE = ROOT / "deploy" / "rumahweb-admin"
OUTPUT = ROOT / "artifacts" / "rumahweb-admin-release"


def main() -> None:
    env = os.environ.copy()
    env["VITE_PUBLIC_BASE"] = "/admin/"
    env["VITE_SNAPSHOT_URL"] = "/admin/api/snapshot.php"
    subprocess.run(["npm", "run", "build"], cwd=DASHBOARD, env=env, check=True)

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    admin = OUTPUT / "admin"
    shutil.copytree(TEMPLATE, admin)
    (admin / "config.example.php").unlink()
    shutil.copy2(ROOT / "deploy" / "rumahweb-presensi" / "api" / "presensi-common.php", admin / "api" / "presensi-common.php")
    shutil.copytree(DASHBOARD / "dist" / "assets", admin / "assets")
    brand = admin / "brand"
    brand.mkdir()
    for asset in ("hollawall-logo.png", "waves-background.svg"):
        shutil.copy2(DASHBOARD / "src" / "assets" / asset, brand / asset)

    shell = (DASHBOARD / "dist" / "index.html").read_text(encoding="utf-8")
    guarded = "<?php defined('HOLLAWALL_AUTHENTICATED') || exit; ?>\n" + shell
    (admin / "app-shell.php").write_text(guarded, encoding="utf-8")

    forbidden = ["/live-api/snapshot", 'src="/assets/', 'href="/assets/']
    for token in forbidden:
        if token in guarded:
            raise RuntimeError(f"non-isolated build reference: {token}")
    files = sorted(path for path in admin.rglob("*") if path.is_file())
    manifest = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(admin).as_posix()}\n" for path in files)
    (OUTPUT / "SHA256SUMS").write_text(manifest, encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()