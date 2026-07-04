from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List


ALLOWED_METRICS = {"sum", "count", "avg", "max", "min"}
ALLOWED_FILTERS = {"project", "category", "tipe", "date_from", "date_to", "company", "dompet"}
ALLOWED_GROUPS = {None, "project", "category", "tipe", "company", "dompet"}


def _parse_date(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {value}")


def parse_ast(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("AST must be an object")

    metric = str(raw.get("metric") or "sum").strip().lower()
    if metric not in ALLOWED_METRICS:
        raise ValueError("Invalid metric")

    filters = raw.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")

    clean_filters = {}
    for key, value in filters.items():
        key = str(key).strip()
        if key not in ALLOWED_FILTERS:
            raise ValueError(f"Invalid filter: {key}")
        if value in (None, ""):
            continue
        if key in {"date_from", "date_to"}:
            clean_filters[key] = _parse_date(str(value)).isoformat()
        else:
            clean_filters[key] = str(value).strip()

    group_by = raw.get("group_by")
    if group_by == "":
        group_by = None
    if group_by not in ALLOWED_GROUPS:
        raise ValueError("Invalid group_by")

    return {"metric": metric, "filters": clean_filters, "group_by": group_by}


def _amount(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    digits = re.sub(r"[^\d-]", "", text)
    try:
        return int(digits or 0)
    except ValueError:
        return 0


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _row_date(row: Dict[str, Any]):
    try:
        return _parse_date(str(row.get("tanggal") or row.get("date") or ""))
    except ValueError:
        return None


def _field(row: Dict[str, Any], key: str) -> str:
    if key == "project":
        return str(row.get("nama_projek") or row.get("project") or "")
    if key == "category":
        return str(row.get("kategori") or row.get("category") or "")
    if key == "company":
        return str(row.get("company_sheet") or row.get("company") or "")
    if key == "dompet":
        return str(row.get("sheet_name") or row.get("dompet") or row.get("company_sheet") or "")
    return str(row.get(key) or "")


def _matches(row: Dict[str, Any], filters: Dict[str, str]) -> bool:
    row_date = None
    for key, value in filters.items():
        if key == "date_from":
            row_date = row_date or _row_date(row)
            if not row_date or row_date < _parse_date(value):
                return False
            continue
        if key == "date_to":
            row_date = row_date or _row_date(row)
            if not row_date or row_date > _parse_date(value):
                return False
            continue
        if key == "tipe":
            if _norm(_field(row, key)) != _norm(value):
                return False
            continue
        if _norm(value) not in _norm(_field(row, key)):
            return False
    return True


def _metric(metric: str, values: List[int]) -> float:
    if metric == "count":
        return len(values)
    if not values:
        return 0
    if metric == "sum":
        return sum(values)
    if metric == "avg":
        return sum(values) / len(values)
    if metric == "max":
        return max(values)
    if metric == "min":
        return min(values)
    raise ValueError("Invalid metric")


def execute(ast: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    parsed = parse_ast(ast)
    filtered = [row for row in rows or [] if isinstance(row, dict) and _matches(row, parsed["filters"])]
    values = [_amount(row.get("jumlah") or row.get("amount")) for row in filtered]
    result = {
        "metric": parsed["metric"],
        "value": _metric(parsed["metric"], values),
        "row_count": len(filtered),
        "groups": {},
    }

    group_by = parsed.get("group_by")
    if group_by:
        buckets: Dict[str, List[int]] = {}
        for row in filtered:
            label = _field(row, group_by).strip() or "-"
            buckets.setdefault(label, []).append(_amount(row.get("jumlah") or row.get("amount")))
        result["groups"] = {
            label: _metric(parsed["metric"], bucket_values)
            for label, bucket_values in sorted(buckets.items())
        }
    return result


def format_idr(amount: Any) -> str:
    try:
        value = int(round(float(amount or 0)))
    except (TypeError, ValueError):
        value = 0
    return f"Rp {value:,}".replace(",", ".")

