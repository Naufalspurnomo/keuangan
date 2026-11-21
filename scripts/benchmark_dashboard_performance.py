#!/usr/bin/env python3
"""Authenticated dashboard benchmark with a fail-closed production mutation guard."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

SCHEMA = "hollawall.dashboard-performance/v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_ROUTE_NAMES = {
    "/admin/api/snapshot.php": "snapshot",
    "/admin/api/projects.php": "projects",
    "/admin/api/documents.php": "documents",
    "/admin/api/write-session.php": "write_session",
}


class BenchmarkContractError(ValueError):
    """Raised when benchmark input or observed behavior violates the contract."""


def nearest_rank_percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise BenchmarkContractError("percentile requires at least one value")
    if not 0 < percentile <= 1:
        raise BenchmarkContractError("percentile must be in (0, 1]")
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _distribution(values: Sequence[float]) -> dict[str, float]:
    return {
        "p50": nearest_rank_percentile(values, 0.50),
        "p95": nearest_rank_percentile(values, 0.95),
        "max": max(values),
    }


def summarize_samples(samples: Sequence[Mapping[str, Any]], *, warmup_count: int) -> dict[str, Any]:
    if warmup_count < 0 or warmup_count >= len(samples):
        raise BenchmarkContractError("warmup_count must leave at least one measured sample")
    measured = list(samples[warmup_count:])
    metric_names = (
        "domcontentloaded_ms",
        "dashboard_ready_ms",
        "transactions_ready_ms",
        "documents_ready_ms",
    )
    result: dict[str, Any] = {
        "measured_samples": len(measured),
        "excluded_warmups": warmup_count,
    }
    for name in metric_names:
        result[name] = _distribution([float(sample[name]) for sample in measured])

    request_counts = [int(sample["request_count"]) for sample in measured]
    result["requests"] = {
        "total": sum(request_counts),
        "p50_per_sample": nearest_rank_percentile(request_counts, 0.50),
        "p95_per_sample": nearest_rank_percentile(request_counts, 0.95),
        "failures": sum(int(sample.get("request_failures", 0)) for sample in measured),
        "console_errors": sum(int(sample.get("console_errors", 0)) for sample in measured),
        "mutations": sum(int(sample.get("mutations", 0)) for sample in measured),
    }

    routes: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for sample in measured:
        for route, observations in (sample.get("routes") or {}).items():
            routes[str(route)].extend(observations)
    result["routes"] = {}
    for route, observations in sorted(routes.items()):
        durations = [float(item["duration_ms"]) for item in observations]
        byte_sizes = [int(item.get("bytes", 0)) for item in observations]
        statuses = Counter(str(int(item["status"])) for item in observations)
        result["routes"][route] = {
            "count": len(observations),
            "duration_ms": _distribution(durations),
            "bytes": _distribution(byte_sizes),
            "statuses": dict(sorted(statuses.items())),
        }
    return result


def production_request_allowed(method: str, url: str, *, authenticated: bool) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "hollawall.com" or not parsed.path.startswith("/admin/"):
        return False
    normalized = method.upper()
    if authenticated:
        return normalized in _SAFE_METHODS
    return normalized in _SAFE_METHODS or (normalized == "POST" and parsed.path == "/admin/")


def validate_release_provenance(expected_sha: str, observed: Mapping[str, str]) -> str:
    if not _SHA_RE.fullmatch(expected_sha):
        raise BenchmarkContractError("release SHA must be a lowercase 40-character hexadecimal value")
    mismatches = {name: value for name, value in observed.items() if value != expected_sha}
    if not observed or mismatches:
        raise BenchmarkContractError(f"release mismatch: {sorted(mismatches or {'observed': 'missing'})}")
    return expected_sha


def build_report(
    *,
    release_sha: str,
    base_url: str,
    samples: Sequence[Mapping[str, Any]],
    warmup_count: int,
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    if not base_url.startswith("https://hollawall.com/admin/"):
        raise BenchmarkContractError("production benchmark base URL is not allowlisted")
    return {
        "schema": SCHEMA,
        "release_sha": release_sha,
        "base_url": base_url,
        "started_at": started_at,
        "completed_at": completed_at,
        "warmup_count": warmup_count,
        "sample_count": len(samples),
        "summary": summarize_samples(samples, warmup_count=warmup_count),
        "samples": list(samples),
    }


def _markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    rows = [
        ("DOMContentLoaded", "domcontentloaded_ms"),
        ("Dashboard ready", "dashboard_ready_ms"),
        ("Transactions ready", "transactions_ready_ms"),
        ("Documents ready", "documents_ready_ms"),
    ]
    lines = [
        "# Hollawall Dashboard Performance Evidence",
        "",
        f"- Release SHA: `{report['release_sha']}`",
        f"- Samples: {summary['measured_samples']} measured + {summary['excluded_warmups']} warm-up",
        f"- Started: `{report['started_at']}`",
        f"- Completed: `{report['completed_at']}`",
        "",
        "## Browser timings",
        "",
        "| Metric | p50 ms | p95 ms | max ms |",
        "|---|---:|---:|---:|",
    ]
    for label, key in rows:
        distribution = summary[key]
        lines.append(f"| {label} | {distribution['p50']:.1f} | {distribution['p95']:.1f} | {distribution['max']:.1f} |")
    lines.extend(["", "## API timings", "", "| Route | calls | p50 ms | p95 ms | max ms |", "|---|---:|---:|---:|---:|"])
    for route, values in summary["routes"].items():
        duration = values["duration_ms"]
        lines.append(f"| {route} | {values['count']} | {duration['p50']:.1f} | {duration['p95']:.1f} | {duration['max']:.1f} |")
    requests = summary["requests"]
    lines.extend([
        "",
        "## Integrity",
        "",
        f"- Requests: {requests['total']}",
        f"- Request failures: {requests['failures']}",
        f"- Console errors: {requests['console_errors']}",
        f"- Business mutations: {requests['mutations']}",
        "",
    ])
    return "\n".join(lines)


def write_evidence(report: Mapping[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dashboard-performance.json"
    markdown_path = output_dir / "dashboard-performance.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fetch_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "HollawallPerformance/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise BenchmarkContractError(f"release endpoint returned {response.status}")
        return json.load(response)


def _release_sha(value: Mapping[str, Any]) -> str:
    for key in ("artifact_revision", "release_sha", "sha", "commit_sha"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate
    raise BenchmarkContractError("release endpoint did not include a SHA")


def observe_release_provenance(expected_sha: str, base_url: str, backend_release_url: str) -> str:
    admin = _fetch_json(base_url.rstrip("/") + "/release-manifest.json?performance=1")
    backend = _fetch_json(backend_release_url)
    return validate_release_provenance(expected_sha, {"admin": _release_sha(admin), "backend": _release_sha(backend)})


def _route_name(url: str) -> str | None:
    path = urlparse(url).path
    return _ROUTE_NAMES.get(path)


def _response_bytes(response: Any) -> int:
    value = response.headers.get("content-length")
    if value and value.isdigit():
        return int(value)
    try:
        return len(response.body())
    except Exception:
        return 0


def run_browser_benchmark(
    *,
    base_url: str,
    expected_sha: str,
    project_id: str,
    samples: int,
    warmups: int,
    username: str,
    password: str,
    chromium_path: str,
) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    if samples < 1 or warmups < 0:
        raise BenchmarkContractError("samples must be positive and warmups non-negative")
    observations: list[dict[str, Any]] = []
    authenticated = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium_path, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()

        def guard(route: Any) -> None:
            request = route.request
            if production_request_allowed(request.method, request.url, authenticated=authenticated):
                route.continue_()
                return
            route.abort("blockedbyclient")
            raise BenchmarkContractError(f"production mutation guard blocked {request.method} {urlparse(request.url).path}")

        page.route("**/*", guard)
        page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Masuk ke dashboard", exact=True).click()
        page.locator("h1", has_text="Dashboard").wait_for(state="visible", timeout=120_000)
        authenticated = True

        for index in range(warmups + samples):
            request_started: dict[Any, float] = {}
            routes: dict[str, list[dict[str, Any]]] = defaultdict(list)
            failures: list[str] = []
            console_errors: list[str] = []
            mutations: list[str] = []
            request_count = 0

            def on_request(request: Any) -> None:
                nonlocal request_count
                if _route_name(request.url):
                    request_started[request] = time.perf_counter()
                    request_count += 1
                if authenticated and request.method.upper() not in _SAFE_METHODS:
                    mutations.append(f"{request.method}:{urlparse(request.url).path}")

            def on_response(response: Any) -> None:
                route = _route_name(response.url)
                started = request_started.pop(response.request, None)
                if route and started is not None:
                    routes[route].append({
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        "bytes": _response_bytes(response),
                        "status": response.status,
                    })

            def on_request_failed(request: Any) -> None:
                failures.append(f"{request.method}:{urlparse(request.url).path}")

            def on_console(message: Any) -> None:
                if message.type == "error":
                    console_errors.append(message.text)

            def on_page_error(error: Any) -> None:
                console_errors.append(str(error))

            page.on("request", on_request)
            page.on("response", on_response)
            page.on("requestfailed", on_request_failed)
            page.on("console", on_console)
            page.on("pageerror", on_page_error)

            navigation_start = time.perf_counter()
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            domcontentloaded_ms = (time.perf_counter() - navigation_start) * 1000
            page.locator("h1", has_text="Dashboard").wait_for(state="visible", timeout=120_000)
            dashboard_ready_ms = (time.perf_counter() - navigation_start) * 1000

            transactions_start = time.perf_counter()
            page.goto(f"{base_url}#projects?project={project_id}&tab=transactions", wait_until="domcontentloaded", timeout=60_000)
            page.locator(".project-transaction-detail").wait_for(state="visible", timeout=120_000)
            transactions_ready_ms = (time.perf_counter() - transactions_start) * 1000

            documents_start = time.perf_counter()
            page.goto(f"{base_url}#projects?project={project_id}&tab=documents", wait_until="domcontentloaded", timeout=60_000)
            page.locator(".project-document-list").wait_for(state="visible", timeout=120_000)
            documents_ready_ms = (time.perf_counter() - documents_start) * 1000

            page.remove_listener("request", on_request)
            page.remove_listener("response", on_response)
            page.remove_listener("requestfailed", on_request_failed)
            page.remove_listener("console", on_console)
            page.remove_listener("pageerror", on_page_error)
            if mutations:
                raise BenchmarkContractError(f"production benchmark observed business mutations: {mutations}")
            observations.append({
                "sample": index + 1,
                "warmup": index < warmups,
                "domcontentloaded_ms": round(domcontentloaded_ms, 3),
                "dashboard_ready_ms": round(dashboard_ready_ms, 3),
                "transactions_ready_ms": round(transactions_ready_ms, 3),
                "documents_ready_ms": round(documents_ready_ms, 3),
                "request_count": request_count,
                "request_failures": len(failures),
                "console_errors": len(console_errors),
                "mutations": len(mutations),
                "routes": dict(routes),
            })
        context.close()
        browser.close()
    return observations


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://hollawall.com/admin/")
    parser.add_argument("--backend-release-url", default="https://renewed-loreen-hollawalls-8d8f6f5c.koyeb.app/api/health/release")
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chromium-path", default=os.getenv("CHROMIUM_PATH") or "/usr/bin/google-chrome")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    username = os.getenv("HOLLAWALL_ADMIN_USERNAME", "")
    password = os.getenv("HOLLAWALL_ADMIN_PASSWORD", "")
    if not username or not password:
        raise BenchmarkContractError("owner credentials must be supplied through environment variables")
    started_at = _utc_now()
    observe_release_provenance(args.release_sha, args.base_url, args.backend_release_url)
    samples = run_browser_benchmark(
        base_url=args.base_url,
        expected_sha=args.release_sha,
        project_id=args.project_id,
        samples=args.samples,
        warmups=args.warmups,
        username=username,
        password=password,
        chromium_path=args.chromium_path,
    )
    report = build_report(
        release_sha=args.release_sha,
        base_url=args.base_url,
        samples=samples,
        warmup_count=args.warmups,
        started_at=started_at,
        completed_at=_utc_now(),
    )
    paths = write_evidence(report, args.output_dir)
    print(json.dumps({"release_sha": args.release_sha, "summary": report["summary"], "evidence": {key: str(value) for key, value in paths.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
