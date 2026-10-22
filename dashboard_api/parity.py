"""Pure parity checks for source ledger and dashboard read model."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


_DIMENSIONS = ("wallet", "transaction_type", "month")


def _aggregate(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], int]:
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in _DIMENSIONS)
        totals[key] += int(row.get("amount") or 0)
    return dict(totals)


def compare_aggregates(source_rows: Iterable[Mapping[str, Any]], mirror_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    source = _aggregate(source_rows)
    mirror = _aggregate(mirror_rows)
    mismatches = []
    difference = 0
    for key in sorted(set(source) | set(mirror)):
        delta = mirror.get(key, 0) - source.get(key, 0)
        difference += delta
        if delta:
            mismatches.append({
                **dict(zip(_DIMENSIONS, key)),
                "source_idr": source.get(key, 0),
                "mirror_idr": mirror.get(key, 0),
                "difference_idr": delta,
            })
    return {"ok": not mismatches, "difference_idr": difference, "mismatches": mismatches}


def compare_drilldown(source_rows: Iterable[Mapping[str, Any]], mirror_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    source = {str(row["source_key"]): int(row.get("amount") or 0) for row in source_rows}
    mirror = {str(row["source_key"]): int(row.get("amount") or 0) for row in mirror_rows}
    missing = sorted(set(source) - set(mirror))
    extra = sorted(set(mirror) - set(source))
    difference = sum(mirror.values()) - sum(source.values())
    return {
        "ok": not missing and not extra and difference == 0,
        "difference_idr": difference,
        "missing_source_keys": missing,
        "extra_source_keys": extra,
    }
