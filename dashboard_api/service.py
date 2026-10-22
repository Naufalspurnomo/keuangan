"""Deterministic calculations for Hollawall's read-only command center."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Sequence

from dashboard_api.contracts import DashboardContractError, DashboardFilters


INCOME_TYPES = frozenset({"pemasukan", "income", "masuk", "credit"})
EXPENSE_TYPES = frozenset({"pengeluaran", "expense", "keluar", "debit"})
INTERNAL_TYPES = frozenset(
    {
        "transfer internal",
        "internal transfer",
        "transfer_internal",
        "hutang",
        "utang",
        "internal debt",
        "internal_debt",
    }
)
OPEN_DEBT_STATUSES = frozenset({"open", "terbuka", "unpaid", "belum lunas"})
METRIC_ORDER = (
    "cash_position",
    "inflow",
    "outflow",
    "net_movement",
    "open_internal_debt",
    "data_completeness",
)
DRILLDOWN_TYPES = {
    "inflow": "income",
    "outflow": "expense",
    "net_movement": "operating",
    "cash_position": "operating",
    "open_internal_debt": "internal_debt_open",
    "data_completeness": "invalid_or_incomplete",
}


def _normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _in_scope(row: Mapping[str, Any], filters: DashboardFilters) -> bool:
    transaction_date = _as_date(row.get("transaction_date"))
    if transaction_date is not None and not (filters.date_from <= transaction_date <= filters.date_to):
        return False
    if filters.wallet and row.get("wallet") != filters.wallet:
        return False
    if filters.company and row.get("company") != filters.company:
        return False
    if filters.project and row.get("project") != filters.project:
        return False
    return True


def _valid_financial_row(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("is_valid")
        and _as_date(row.get("transaction_date")) is not None
        and isinstance(row.get("amount"), int)
        and not isinstance(row.get("amount"), bool)
        and int(row["amount"]) > 0
    )


def _is_internal(row: Mapping[str, Any]) -> bool:
    transaction_type = _normalized(row.get("transaction_type"))
    source_block = _normalized(row.get("source_block"))
    return (
        transaction_type in INTERNAL_TYPES
        or source_block in {"hutang", "debt", "internal_transfer", "transfer"}
    )


def _is_open_debt(row: Mapping[str, Any]) -> bool:
    if not _is_internal(row):
        return False
    status = _normalized(row.get("status") or row.get("debt_status"))
    return status in OPEN_DEBT_STATUSES


def _operating_direction(row: Mapping[str, Any]) -> str | None:
    if _is_internal(row):
        return None
    transaction_type = _normalized(row.get("transaction_type"))
    if transaction_type in INCOME_TYPES:
        return "inflow"
    if transaction_type in EXPENSE_TYPES:
        return "outflow"
    return None


def build_overview(
    rows: Sequence[Mapping[str, Any]],
    filters: DashboardFilters,
    now: datetime,
) -> dict[str, Any]:
    """Build one internally consistent overview from one normalized subset."""

    scoped = [row for row in rows if _in_scope(row, filters)]
    valid = [row for row in scoped if _valid_financial_row(row)]
    inflow = sum(int(row["amount"]) for row in valid if _operating_direction(row) == "inflow")
    outflow = sum(int(row["amount"]) for row in valid if _operating_direction(row) == "outflow")
    open_internal_debt = sum(int(row["amount"]) for row in valid if _is_open_debt(row))
    completeness = round((len(valid) / len(scoped)) * 100) if scoped else 0

    values = {
        "cash_position": inflow - outflow,
        "inflow": inflow,
        "outflow": outflow,
        "net_movement": inflow - outflow,
        "open_internal_debt": open_internal_debt,
        "data_completeness": completeness,
    }
    metrics = {name: values[name] for name in METRIC_ORDER}
    return {
        "metrics": metrics,
        "matching_source_keys": [str(row.get("source_key") or "") for row in scoped],
        "completeness": {
            "total_rows": len(scoped),
            "valid_rows": len(valid),
            "invalid_rows": len(scoped) - len(valid),
        },
        "meta": {
            "as_of": now.isoformat(),
            "filters": filters.to_query(),
        },
    }


def build_drilldown(filters: DashboardFilters, metric: str) -> dict[str, str]:
    """Return the exact transaction filter represented by a headline metric."""

    if metric not in DRILLDOWN_TYPES:
        raise DashboardContractError("unknown dashboard metric")
    return {
        "view": "transactions",
        **filters.to_query(),
        "transaction_type": DRILLDOWN_TYPES[metric],
    }
