#!/usr/bin/env python3
"""Validate the exact release baseline and emit source provenance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Sequence


REQUIRED_BASELINE_SHA = "0ee6a95e253bdb616382fca86a8c7285f7d02fd4"
SCHEMA = "hollawall.release-provenance/v1"
DEFAULT_LOCKFILES = ("requirements.txt", "dashboard/package-lock.json")


class ProvenanceError(RuntimeError):
    """Raised when source cannot be proven safe for a release build."""


def _git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ProvenanceError("git provenance command failed") from error


def _commit(repo: Path, revision: str, label: str) -> str:
    result = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")
    value = result.stdout.strip().lower()
    if len(value) != 40:
        raise ProvenanceError(f"{label} does not resolve to an exact commit")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def collect_provenance(
    *,
    repo: Path,
    candidate: str = "HEAD",
    required_baseline: str = REQUIRED_BASELINE_SHA,
    lockfiles: Sequence[str] = DEFAULT_LOCKFILES,
) -> dict[str, object]:
    """Return canonical evidence, failing closed on drift or an inexact baseline."""
    root = repo.resolve()
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout:
        raise ProvenanceError("working tree is dirty")
    baseline_sha = _commit(root, required_baseline, "required baseline")
    candidate_sha = _commit(root, candidate, "candidate")
    ancestry = _git(root, "merge-base", "--is-ancestor", baseline_sha, candidate_sha, check=False)
    if ancestry.returncode != 0:
        raise ProvenanceError("exact baseline is not an ancestor of candidate")

    parent = _git(root, "rev-parse", "--verify", f"{candidate_sha}^", check=False)
    parent_sha = parent.stdout.strip().lower() if parent.returncode == 0 else None
    submodule_output = _git(root, "submodule", "status", "--recursive").stdout
    submodules: list[dict[str, object]] = []
    for raw in submodule_output.splitlines():
        state = raw[:1]
        fields = raw[1:].strip().split()
        if len(fields) < 2 or state in {"-", "+", "U"}:
            raise ProvenanceError("submodule state is not release-safe")
        submodules.append({"path": fields[1], "sha": fields[0].lower()})

    dependency_lockfiles: dict[str, str] = {}
    for relative in lockfiles:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ProvenanceError(f"required dependency lockfile missing: {relative}")
        dependency_lockfiles[relative] = _sha256(path)

    return {
        "schema": SCHEMA,
        "required_baseline_sha": baseline_sha,
        "implementation_head_sha": candidate_sha,
        "parent_sha": parent_sha,
        "dirty": False,
        "submodules": submodules,
        "dependency_lockfiles": dependency_lockfiles,
        "candidate_diff": f"{baseline_sha}..{candidate_sha}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", default="HEAD")
    parser.add_argument("--required-baseline", default=REQUIRED_BASELINE_SHA)
    parser.add_argument("--lockfile", action="append", dest="lockfiles")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        evidence = collect_provenance(
            repo=args.repo,
            candidate=args.candidate,
            required_baseline=args.required_baseline,
            lockfiles=tuple(args.lockfiles or DEFAULT_LOCKFILES),
        )
    except ProvenanceError as error:
        print(json.dumps({"error": str(error), "valid": False}, sort_keys=True))
        raise SystemExit(2) from error
    rendered = json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
