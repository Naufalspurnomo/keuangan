from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark_dashboard_performance import (
    BenchmarkContractError,
    build_report,
    nearest_rank_percentile,
    production_request_allowed,
    _release_sha,
    _validated_release_url,
    summarize_samples,
    validate_release_provenance,
    write_evidence,
)


SAMPLE_1 = {
    "domcontentloaded_ms": 250.0,
    "dashboard_ready_ms": 9200.0,
    "transactions_ready_ms": 13700.0,
    "documents_ready_ms": 5800.0,
    "request_count": 11,
    "request_failures": 0,
    "console_errors": 0,
    "mutations": 0,
    "routes": {
        "snapshot": [{"duration_ms": 8900.0, "bytes": 1200, "status": 200}],
        "projects": [{"duration_ms": 4300.0, "bytes": 800, "status": 200}],
    },
}
SAMPLE_2 = {
    **SAMPLE_1,
    "domcontentloaded_ms": 200.0,
    "dashboard_ready_ms": 1800.0,
    "transactions_ready_ms": 1600.0,
    "documents_ready_ms": 1700.0,
    "request_count": 6,
    "routes": {
        "snapshot": [{"duration_ms": 600.0, "bytes": 1200, "status": 200}],
        "projects": [{"duration_ms": 400.0, "bytes": 800, "status": 200}],
    },
}
SAMPLE_3 = {
    **SAMPLE_2,
    "dashboard_ready_ms": 2400.0,
    "transactions_ready_ms": 1900.0,
    "documents_ready_ms": 1500.0,
    "routes": {
        "snapshot": [{"duration_ms": 700.0, "bytes": 1250, "status": 200}],
        "projects": [{"duration_ms": 500.0, "bytes": 810, "status": 200}],
    },
}


def test_nearest_rank_percentile_is_deterministic_and_rejects_empty_values() -> None:
    assert nearest_rank_percentile([1, 2, 3, 4, 5], 0.50) == 3
    assert nearest_rank_percentile([1, 2, 3, 4, 5], 0.95) == 5
    with pytest.raises(BenchmarkContractError, match="at least one"):
        nearest_rank_percentile([], 0.95)


def test_summary_excludes_explicit_warmups_and_reports_p50_p95_max_and_counts() -> None:
    summary = summarize_samples([SAMPLE_1, SAMPLE_2, SAMPLE_3], warmup_count=1)

    assert summary["measured_samples"] == 2
    assert summary["excluded_warmups"] == 1
    assert summary["dashboard_ready_ms"] == {"p50": 1800.0, "p95": 2400.0, "max": 2400.0}
    assert summary["transactions_ready_ms"]["p95"] == 1900.0
    assert summary["requests"] == {
        "total": 12,
        "p50_per_sample": 6,
        "p95_per_sample": 6,
        "failures": 0,
        "console_errors": 0,
        "mutations": 0,
    }
    assert summary["routes"]["snapshot"] == {
        "count": 2,
        "duration_ms": {"p50": 600.0, "p95": 700.0, "max": 700.0},
        "bytes": {"p50": 1200, "p95": 1250, "max": 1250},
        "statuses": {"200": 2},
    }


def test_production_request_guard_allows_login_then_blocks_business_mutations() -> None:
    base = "https://hollawall.com/admin/"
    assert production_request_allowed("POST", base, authenticated=False)
    assert production_request_allowed("GET", base + "api/snapshot.php", authenticated=True)
    assert production_request_allowed("HEAD", base + "release-manifest.json", authenticated=True)
    assert not production_request_allowed("POST", base + "api/transactions.php", authenticated=True)
    assert not production_request_allowed("PATCH", base + "api/projects.php", authenticated=True)
    assert not production_request_allowed("POST", "https://other.example/action", authenticated=False)


def test_release_provenance_requires_all_observed_surfaces_to_match_exact_sha() -> None:
    sha = "9b345bfb9d30e0ff3fa94849aedb376fb90c6f66"
    assert validate_release_provenance(sha, {"admin": sha, "backend": sha}) == sha
    with pytest.raises(BenchmarkContractError, match="release mismatch"):
        validate_release_provenance(sha, {"admin": sha, "backend": "0" * 40})
    with pytest.raises(BenchmarkContractError, match="40-character"):
        validate_release_provenance("9b345bf", {"admin": "9b345bf"})


def test_release_sha_accepts_canonical_frontend_and_backend_manifest_fields() -> None:
    sha = "9b345bfb9d30e0ff3fa94849aedb376fb90c6f66"
    assert _release_sha({"artifact_revision": sha}) == sha
    assert _release_sha({"release_sha": sha}) == sha


@pytest.mark.parametrize(
    "url",
    [
        "http://hollawall.com/admin/release-manifest.json",
        "file:///etc/passwd",
        "https://other.example/release-manifest.json",
        "https://hollawall.com/other/release-manifest.json",
        "https://renewed-loreen-hollawalls-8d8f6f5c.koyeb.app/other",
    ],
)
def test_release_fetch_rejects_noncanonical_urls(url: str) -> None:
    with pytest.raises(BenchmarkContractError, match="not allowlisted"):
        _validated_release_url(url)


def test_release_fetch_accepts_only_canonical_https_surfaces() -> None:
    assert _validated_release_url(
        "https://hollawall.com/admin/release-manifest.json?performance=1"
    ).hostname == "hollawall.com"
    assert _validated_release_url(
        "https://renewed-loreen-hollawalls-8d8f6f5c.koyeb.app/api/health/release"
    ).path == "/api/health/release"


def test_report_and_evidence_are_schema_stable_and_do_not_include_secrets(tmp_path: Path) -> None:
    sha = "9b345bfb9d30e0ff3fa94849aedb376fb90c6f66"
    report = build_report(
        release_sha=sha,
        base_url="https://hollawall.com/admin/",
        samples=[SAMPLE_1, SAMPLE_2, SAMPLE_3],
        warmup_count=1,
        started_at="2026-11-21T00:00:00Z",
        completed_at="2026-11-21T00:01:00Z",
    )
    assert report["schema"] == "hollawall.dashboard-performance/v1"
    assert report["release_sha"] == sha
    assert report["summary"]["measured_samples"] == 2

    paths = write_evidence(report, tmp_path)
    assert set(paths) == {"json", "markdown"}
    loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert loaded == report
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert sha in markdown
    assert "password" not in markdown.casefold()
    assert "cookie" not in markdown.casefold()
