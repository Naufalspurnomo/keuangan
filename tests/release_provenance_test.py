from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import release_provenance


BASELINE = "0ee6a95e253bdb616382fca86a8c7285f7d02fd4"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "release-test@example.invalid")
    git(repo, "config", "user.name", "Release Test")
    (repo / "requirements.txt").write_text("flask==3.1.3\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "baseline")
    baseline = git(repo, "rev-parse", "HEAD")
    (repo / "app.py").write_text("print('release')\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "candidate")
    return repo, baseline, git(repo, "rev-parse", "HEAD")


def test_provenance_requires_exact_baseline_ancestor_and_records_clean_source(tmp_path: Path) -> None:
    repo, baseline, candidate = make_repo(tmp_path)

    evidence = release_provenance.collect_provenance(
        repo=repo,
        candidate=candidate,
        required_baseline=baseline,
        lockfiles=("requirements.txt",),
    )

    assert evidence["schema"] == "hollawall.release-provenance/v1"
    assert evidence["required_baseline_sha"] == baseline
    assert evidence["implementation_head_sha"] == candidate
    assert evidence["parent_sha"] == git(repo, "rev-parse", f"{candidate}^")
    assert evidence["dirty"] is False
    assert evidence["submodules"] == []
    assert evidence["dependency_lockfiles"] == {
        "requirements.txt": hashlib.sha256((repo / "requirements.txt").read_bytes()).hexdigest()
    }
    assert evidence["candidate_diff"] == f"{baseline}..{candidate}"


def test_provenance_rejects_non_descendant_candidate(tmp_path: Path) -> None:
    repo, baseline, _candidate = make_repo(tmp_path)
    git(repo, "checkout", "-q", "--orphan", "unrelated")
    git(repo, "rm", "-q", "-rf", ".")
    (repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "unrelated")
    unrelated = git(repo, "rev-parse", "HEAD")

    with pytest.raises(release_provenance.ProvenanceError, match="exact baseline is not an ancestor"):
        release_provenance.collect_provenance(
            repo=repo,
            candidate=unrelated,
            required_baseline=baseline,
            lockfiles=("requirements.txt",),
        )


def test_provenance_rejects_dirty_release_tree(tmp_path: Path) -> None:
    repo, baseline, candidate = make_repo(tmp_path)
    (repo / "dirty.txt").write_text("not committed\n", encoding="utf-8")

    with pytest.raises(release_provenance.ProvenanceError, match="working tree is dirty"):
        release_provenance.collect_provenance(
            repo=repo,
            candidate=candidate,
            required_baseline=baseline,
            lockfiles=("requirements.txt",),
        )


def test_repository_baseline_constant_is_plan_exact_value() -> None:
    assert release_provenance.REQUIRED_BASELINE_SHA == BASELINE
