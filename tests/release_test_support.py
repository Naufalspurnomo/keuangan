from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


REQUIRED_BASELINE = "0ee6a95e253bdb616382fca86a8c7285f7d02fd4"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_release(root: Path, script: str) -> None:
    """Run a fail-closed release builder with explicit synthetic test provenance."""
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    parent = subprocess.check_output(
        ["git", "rev-parse", "HEAD^"], cwd=root, text=True
    ).strip()
    evidence = {
        "schema": "hollawall.release-provenance/v1",
        "required_baseline_sha": REQUIRED_BASELINE,
        "implementation_head_sha": revision,
        "parent_sha": parent,
        "dirty": False,
        "submodules": [],
        "dependency_lockfiles": {
            "requirements.txt": _sha256(root / "requirements.txt"),
            "dashboard/package-lock.json": _sha256(root / "dashboard/package-lock.json"),
        },
        "candidate_diff": f"{REQUIRED_BASELINE}..{revision}",
    }
    with tempfile.TemporaryDirectory(prefix="hollawall-release-test-") as directory:
        provenance = Path(directory) / "provenance.json"
        provenance.write_text(json.dumps(evidence), encoding="utf-8")
        subprocess.run(
            [
                "python3",
                f"scripts/{script}",
                "--provenance",
                str(provenance),
                "--artifact-revision",
                revision,
            ],
            cwd=root,
            check=True,
        )