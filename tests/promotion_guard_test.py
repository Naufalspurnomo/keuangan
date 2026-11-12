from __future__ import annotations

import pytest

from scripts import promotion_guard


SHA = "a" * 40


def clean_source() -> dict[str, object]:
    return {
        "schema": "hollawall.release-provenance/v1",
        "implementation_head_sha": SHA,
        "dirty": False,
    }


def artifact(*, revision: str = SHA) -> dict[str, object]:
    return {
        "component": "koyeb-backend",
        "artifact_revision": revision,
        "source": clean_source(),
    }


def test_required_checks_accept_only_complete_green_set() -> None:
    checks = {name: "success" for name in promotion_guard.REQUIRED_CHECKS}

    assert promotion_guard.validate_required_checks(checks) == list(
        promotion_guard.REQUIRED_CHECKS
    )


def test_required_checks_fail_closed_when_a_job_is_missing() -> None:
    checks = {name: "success" for name in promotion_guard.REQUIRED_CHECKS}
    checks.pop("security")

    with pytest.raises(promotion_guard.PromotionGuardError, match="security"):
        promotion_guard.validate_required_checks(checks)


def test_required_checks_fail_closed_when_a_job_is_red() -> None:
    checks = {name: "success" for name in promotion_guard.REQUIRED_CHECKS}
    checks["container"] = "failure"

    with pytest.raises(promotion_guard.PromotionGuardError, match="container"):
        promotion_guard.validate_required_checks(checks)


def test_artifacts_require_exact_candidate_and_source_sha_parity() -> None:
    manifests = [
        artifact(),
        {**artifact(), "component": "rumahweb-admin"},
        {**artifact(), "component": "rumahweb-presensi"},
    ]

    assert promotion_guard.validate_artifact_sha_parity(
        manifests, candidate_sha=SHA
    ) == SHA


def test_artifacts_reject_revision_source_or_dirty_mismatch() -> None:
    bad_revision = artifact(revision="b" * 40)
    bad_source = {**artifact(), "source": {**clean_source(), "implementation_head_sha": "b" * 40}}
    dirty_source = {**artifact(), "source": {**clean_source(), "dirty": True}}

    for manifest in (bad_revision, bad_source, dirty_source):
        with pytest.raises(promotion_guard.PromotionGuardError):
            promotion_guard.validate_artifact_sha_parity([manifest], candidate_sha=SHA)


def test_rollback_eligibility_is_authority_safe() -> None:
    assert promotion_guard.validate_rollback_eligibility(
        authority_activated=False,
        artifact_canonical_aware=False,
        artifact_revision=SHA,
    ) == SHA
    assert promotion_guard.validate_rollback_eligibility(
        authority_activated=True,
        artifact_canonical_aware=True,
        artifact_revision=SHA,
    ) == SHA

    with pytest.raises(promotion_guard.PromotionGuardError, match="canonical-aware"):
        promotion_guard.validate_rollback_eligibility(
            authority_activated=True,
            artifact_canonical_aware=False,
            artifact_revision=SHA,
        )


def test_rollback_rejects_invalid_revision() -> None:
    with pytest.raises(promotion_guard.PromotionGuardError, match="revision"):
        promotion_guard.validate_rollback_eligibility(
            authority_activated=False,
            artifact_canonical_aware=True,
            artifact_revision="not-a-sha",
        )
