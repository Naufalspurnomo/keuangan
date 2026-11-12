#!/usr/bin/env python3
"""Fail-closed validation for immutable Hollawall release promotion."""

from __future__ import annotations

import re
from typing import Mapping, Sequence


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CHECKS = (
    "backend",
    "browser-e2e",
    "visual",
    "security",
    "frontend",
    "postgresql",
    "php",
    "container",
    "performance",
    "accessibility",
)


class PromotionGuardError(RuntimeError):
    """Raised when a release is not eligible for promotion or rollback."""


def validate_required_checks(checks: Mapping[str, object]) -> list[str]:
    """Return required check names only when every check passed."""
    failed = [name for name in REQUIRED_CHECKS if checks.get(name) != "success"]
    if failed:
        raise PromotionGuardError("required checks are missing or not successful: " + ", ".join(failed))
    return list(REQUIRED_CHECKS)


def _validated_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise PromotionGuardError(f"{field} is not a full commit revision")
    normalized = value.strip().lower()
    if not FULL_SHA.fullmatch(normalized):
        raise PromotionGuardError(f"{field} is not a full commit revision")
    return normalized


def validate_artifact_sha_parity(
    manifests: Sequence[Mapping[str, object]], *, candidate_sha: str
) -> str:
    """Require every immutable artifact to derive from the exact clean candidate."""
    candidate = _validated_sha(candidate_sha, field="candidate revision")
    if not manifests:
        raise PromotionGuardError("no release artifacts were provided")

    components: set[str] = set()
    for manifest in manifests:
        component = manifest.get("component")
        if not isinstance(component, str) or not component.strip():
            raise PromotionGuardError("artifact component is missing")
        if component in components:
            raise PromotionGuardError(f"duplicate artifact component: {component}")
        components.add(component)

        revision = _validated_sha(
            manifest.get("artifact_revision"), field=f"{component} artifact revision"
        )
        source = manifest.get("source")
        if not isinstance(source, Mapping):
            raise PromotionGuardError(f"{component} source provenance is missing")
        if source.get("schema") != "hollawall.release-provenance/v1":
            raise PromotionGuardError(f"{component} source provenance schema is invalid")
        if source.get("dirty") is not False:
            raise PromotionGuardError(f"{component} source provenance is dirty")
        source_sha = _validated_sha(
            source.get("implementation_head_sha"),
            field=f"{component} source revision",
        )
        if revision != candidate or source_sha != candidate:
            raise PromotionGuardError(
                f"{component} artifact/source revision does not match candidate"
            )
    return candidate


def validate_rollback_eligibility(
    *,
    authority_activated: bool,
    artifact_canonical_aware: bool,
    artifact_revision: str,
) -> str:
    """Forbid rollback to a Sheets-primary artifact after canonical activation."""
    revision = _validated_sha(artifact_revision, field="rollback revision")
    if authority_activated and not artifact_canonical_aware:
        raise PromotionGuardError(
            "post-activation rollback artifact must be canonical-aware"
        )
    return revision
