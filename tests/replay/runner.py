"""
runner.py - Replay harness runner

Menjalankan narrow_resolver terhadap fixtures berlabel (ground truth) dan
melaporkan akurasi per-field. Ini fondasi langkah #1 roadmap: ukur DULU,
sebelum memutuskan apakah perlu agent loop.

Pakai sebagai CLI:
    python -m tests.replay.runner
    python -m tests.replay.runner --verbose
    python -m tests.replay.runner --fixtures path/lain.json

Field yang dinilai didefinisikan di fixtures `_schema.checked_fields`.
Exit code != 0 jika ada case yang gagal (cocok untuk CI gate).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List

# Allow running as a script (python tests/replay/runner.py) too.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

def _load_resolver():
    """Load resolver file without importing the side-effectful services package."""
    path = os.path.join(_REPO_ROOT, "services", "narrow_resolver.py")
    spec = importlib.util.spec_from_file_location("_replay_narrow_resolver", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load narrow_resolver from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resolve_finance_message = _load_resolver().resolve_finance_message

DEFAULT_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures.json")
DEFAULT_CHECKED_FIELDS = ["project", "main_wallet", "debt_source", "company", "needs_confirmation"]


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    known_gap: bool = False
    field_results: Dict[str, bool] = field(default_factory=dict)
    actual: Dict[str, Any] = field(default_factory=dict)
    expected: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    @property
    def mismatches(self) -> List[str]:
        return [name for name, ok in self.field_results.items() if not ok]

    @property
    def status(self) -> str:
        """PASS/FAIL with xfail/xpass semantics for known gaps."""
        if self.known_gap:
            return "XPASS" if self.passed else "XFAIL"
        return "PASS" if self.passed else "FAIL"

    @property
    def is_unexpected(self) -> bool:
        """True only for results that should fail CI.

        - normal case that fails        -> unexpected (CI red)
        - known_gap that now PASSES      -> unexpected: gap was fixed, remove the flag
        - known_gap that still fails     -> expected (CI stays green)
        """
        if self.known_gap:
            return self.passed  # xpass means the flag is stale -> flag it
        return not self.passed



def _norm(value: Any) -> Any:
    """Normalize for comparison: strip strings, treat ''/None alike."""
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return value


def load_fixtures(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_case(case: Dict[str, Any], checked_fields: List[str]) -> CaseResult:
    expected = case.get("expect", {})
    decision = resolve_finance_message(
        case.get("text", ""),
        ocr_text=case.get("ocr_text", ""),
    )
    actual = decision.to_dict()

    field_results: Dict[str, bool] = {}
    for name in checked_fields:
        field_results[name] = _norm(actual.get(name)) == _norm(expected.get(name))

    return CaseResult(
        case_id=case.get("id", "<no-id>"),
        passed=all(field_results.values()),
        known_gap=bool(case.get("known_gap", False)),
        field_results=field_results,

        actual={k: actual.get(k) for k in checked_fields},
        expected={k: expected.get(k) for k in checked_fields},
        reasons=actual.get("reasons", []),
    )


def run_all(fixtures: Dict[str, Any]) -> List[CaseResult]:
    checked_fields = fixtures.get("_schema", {}).get("checked_fields") or DEFAULT_CHECKED_FIELDS
    return [run_case(case, checked_fields) for case in fixtures.get("cases", [])]


def summarize(results: List[CaseResult], checked_fields: List[str]) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    xfail = sum(1 for r in results if r.known_gap and not r.passed)
    xpass = sum(1 for r in results if r.known_gap and r.passed)
    unexpected = sum(1 for r in results if r.is_unexpected)
    per_field = {name: {"correct": 0, "total": 0} for name in checked_fields}
    for r in results:
        for name, ok in r.field_results.items():
            per_field[name]["total"] += 1
            per_field[name]["correct"] += 1 if ok else 0
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "xfail": xfail,
        "xpass": xpass,
        "unexpected": unexpected,
        "case_accuracy": round(passed / total, 4) if total else 0.0,
        "per_field": per_field,
    }



def print_report(results: List[CaseResult], checked_fields: List[str], verbose: bool) -> None:
    summary = summarize(results, checked_fields)
    print("=" * 60)
    print("REPLAY HARNESS — narrow_resolver vs labeled ground truth")
    print("=" * 60)
    for r in results:
        # Show mismatch detail when a result is unexpected, a known gap, or verbose.
        show_detail = r.is_unexpected or r.known_gap or verbose
        print(f"[{r.status:>5}] {r.case_id}")
        if show_detail:
            for name in r.mismatches:
                print(f"    - {name}: got {r.actual.get(name)!r}, expected {r.expected.get(name)!r}")
            if verbose:
                print(f"    reasons: {r.reasons}")
    print("-" * 60)
    print(f"Cases: {summary['passed']}/{summary['total']} passed "
          f"(accuracy {summary['case_accuracy']:.0%})")
    print(f"  known gaps (xfail): {summary['xfail']}, "
          f"newly fixed (xpass): {summary['xpass']}, "
          f"unexpected (CI-fail): {summary['unexpected']}")
    for name, stat in summary["per_field"].items():
        acc = stat["correct"] / stat["total"] if stat["total"] else 0.0
        print(f"  field {name:>18}: {stat['correct']}/{stat['total']} ({acc:.0%})")
    if summary["xpass"]:
        print("  NOTE: an xpass means a known_gap is now fixed — remove its known_gap flag.")
    print("=" * 60)



def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Run finance replay harness.")
    parser.add_argument("--fixtures", default=DEFAULT_FIXTURES, help="Path to fixtures JSON.")
    parser.add_argument("--verbose", action="store_true", help="Show reasons for every case.")
    args = parser.parse_args(argv)

    fixtures = load_fixtures(args.fixtures)
    checked_fields = fixtures.get("_schema", {}).get("checked_fields") or DEFAULT_CHECKED_FIELDS
    results = run_all(fixtures)
    print_report(results, checked_fields, args.verbose)

    # CI gate: only unexpected results fail (real regressions + stale known_gap flags).
    unexpected = sum(1 for r in results if r.is_unexpected)
    return 1 if unexpected else 0



if __name__ == "__main__":
    raise SystemExit(main())
