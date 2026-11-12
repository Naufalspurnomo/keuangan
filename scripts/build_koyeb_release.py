#!/usr/bin/env python3
"""Build a provenance-bound Koyeb container context without deploying it."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import release_manifest


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "koyeb-release"
EXCLUDED_PARTS = {".git", ".hermes", ".superpowers", "artifacts", "data", "runtime", "tmp", "node_modules"}
EXCLUDED_NAMES = {".env", "credentials.json", "token.json"}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in EXCLUDED_PARTS or name in EXCLUDED_NAMES or name.startswith(".env.")}
    return ignored


def build_release(*, source_root: Path, output: Path, provenance_path: Path, artifact_revision: str) -> Path:
    source = source_root.resolve()
    if output.resolve() == source or source in output.resolve().parents:
        raise RuntimeError("Koyeb release output must be outside its source context")
    if not (source / "Dockerfile").is_file():
        raise RuntimeError("Koyeb source context is missing Dockerfile")
    if output.exists():
        shutil.rmtree(output)
    context = output / "context"
    shutil.copytree(source, context, ignore=_ignore, symlinks=False)
    manifest = release_manifest.build_manifest(
        component="koyeb-backend",
        payload_root=context,
        provenance=release_manifest.load_provenance(provenance_path),
        artifact_revision=artifact_revision,
    )
    release_manifest.write_manifest(output / "release-manifest.json", manifest)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--artifact-revision", required=True)
    args = parser.parse_args()
    print(
        build_release(
            source_root=args.source_root,
            output=args.output,
            provenance_path=args.provenance,
            artifact_revision=args.artifact_revision,
        )
    )


if __name__ == "__main__":
    main()
