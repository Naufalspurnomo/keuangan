"""Versioned canonical finance metric oracle.

The oracle consumes immutable transaction chains and projected debt state. It is
pure and deterministic so every interface can compare itself to the same result.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any


METRIC_ORACLE_VERSION = "canonical.finance.metrics.v1"
ACCOUNT_CLASSES = frozenset(
    {"cash", "revenue", "expense", "receivable", "payable", "internal_debt"}
)
INTERNAL_ACCOUNT_CLASSES = frozenset({"receivable", "payable", "internal_debt"})


def _instant(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp with timezone") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return result.astimezone(timezone.utc)


def _money(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an exact IDR integer")
    return value


def _wallet_template() -> dict[str, Any]:
    return {
        "opening_balance": 0,
        "cash_balance": 0,
        "adjustments": 0,
        "available_balance": 0,
        "receivable": 0,
        "payable": 0,
        "adjusted_balance": 0,
        "runway_months_basis_points": None,
        "health": "Critical",
    }


def _project_template() -> dict[str, int]:
    return {
        "revenue": 0,
        "cost": 0,
        "cashflow": 0,
        "gross_profit": 0,
        "margin_basis_points": 0,
        "contribution": 0,
    }


def _state_time(record: Mapping[str, Any]) -> datetime:
    return _instant(record.get("created_at") or record.get("occurred_at"), "transaction state time")


def _effective_record(
    chain: Sequence[Mapping[str, Any]], cutoff: datetime
) -> tuple[Mapping[str, Any] | None, str | None]:
    if not chain:
        raise ValueError("transaction chain must not be empty")
    eligible = [record for record in chain if _state_time(record) <= cutoff]
    if not eligible:
        return None, "after_cutoff"
    latest = eligible[-1]
    if latest.get("status") == "reversal":
        return None, "reversed"
    return latest, None


def _exclusion_reason(record: Mapping[str, Any]) -> str | None:
    evidence = record.get("evidence") or {}
    if not isinstance(evidence, Mapping):
        raise ValueError("transaction evidence must be an object")
    if evidence.get("is_acceptance_test") is True or evidence.get("test_namespace"):
        return "acceptance_test"
    if evidence.get("quarantined") is True or evidence.get("excluded_from_canonical_totals") is True:
        return "quarantine"
    review_status = evidence.get("review_status")
    if review_status not in (None, "approved"):
        return "review"
    return None


def _validated_postings(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    postings = record.get("postings")
    if not isinstance(postings, Sequence) or isinstance(postings, (str, bytes)) or not postings:
        raise ValueError("effective transaction must contain postings")
    total = 0
    result: list[Mapping[str, Any]] = []
    for index, posting in enumerate(postings):
        if not isinstance(posting, Mapping):
            raise ValueError(f"posting {index} must be an object")
        if posting.get("currency") != "IDR":
            raise ValueError("posting currency must be IDR")
        account_class = posting.get("account_class")
        if account_class not in ACCOUNT_CLASSES:
            raise ValueError("posting account_class is not canonical")
        amount = _money(posting.get("signed_amount"), "posting signed_amount")
        total += amount
        result.append(posting)
    if total != 0:
        raise ValueError("effective transaction postings must be balanced")
    return result


def _health(available_balance: int, runway_bps: int | None) -> str:
    if available_balance <= 0:
        return "Critical"
    if runway_bps is not None and runway_bps < 30_000:
        return "Watch"
    return "Healthy"


def _aging_bucket(due_at: datetime, cutoff: datetime) -> str:
    overdue_days = (cutoff.date() - due_at.date()).days
    if overdue_days <= 0:
        return "current"
    if overdue_days <= 30:
        return "days_1_30"
    if overdue_days <= 60:
        return "days_31_60"
    if overdue_days <= 90:
        return "days_61_90"
    return "days_over_90"


def calculate_metrics(
    *,
    cutoff: str,
    transaction_chains: Iterable[Sequence[Mapping[str, Any]]],
    opening_balances: Iterable[Mapping[str, Any]],
    balance_adjustments: Iterable[Mapping[str, Any]],
    debt_projections: Iterable[Mapping[str, Any]],
    monthly_operating_outflow: int,
) -> dict[str, Any]:
    """Calculate canonical v1 metrics at an inclusive UTC cutoff."""

    cutoff_at = _instant(cutoff, "cutoff")
    monthly_outflow = _money(monthly_operating_outflow, "monthly_operating_outflow")
    if monthly_outflow < 0:
        raise ValueError("monthly_operating_outflow must not be negative")

    wallets: defaultdict[str, dict[str, Any]] = defaultdict(_wallet_template)
    projects: defaultdict[str, dict[str, int]] = defaultdict(_project_template)
    excluded = {key: 0 for key in ("acceptance_test", "after_cutoff", "quarantine", "reversed", "review")}
    external_inflow = 0
    external_outflow = 0

    latest_openings: dict[tuple[str, str], tuple[datetime, int]] = {}
    for balance in opening_balances:
        effective_at = _instant(balance.get("effective_at"), "opening balance effective_at")
        if effective_at > cutoff_at:
            continue
        wallet_id = str(balance.get("wallet_id") or "")
        business_unit_id = str(balance.get("business_unit_id") or "")
        if not wallet_id:
            raise ValueError("opening balance wallet_id is required")
        key = (wallet_id, business_unit_id)
        amount = _money(balance.get("amount"), "opening balance amount")
        current = latest_openings.get(key)
        if current is None or effective_at > current[0]:
            latest_openings[key] = (effective_at, amount)

    for (wallet_id, _business_unit_id), (_effective_at, amount) in latest_openings.items():
        wallets[wallet_id]["opening_balance"] += amount

    for adjustment in balance_adjustments:
        if _instant(adjustment.get("effective_at"), "adjustment effective_at") > cutoff_at:
            continue
        wallet_id = str(adjustment.get("wallet_id") or "")
        if not wallet_id:
            raise ValueError("adjustment wallet_id is required")
        wallets[wallet_id]["adjustments"] += _money(
            adjustment.get("delta_amount"), "adjustment delta_amount"
        )

    for chain in transaction_chains:
        record, state_reason = _effective_record(chain, cutoff_at)
        if state_reason:
            excluded[state_reason] += 1
            continue
        assert record is not None
        reason = _exclusion_reason(record)
        if reason:
            excluded[reason] += 1
            continue
        postings = _validated_postings(record)
        accounts = {str(posting["account_class"]) for posting in postings}
        cashflow = 0
        revenue = 0
        cost = 0
        for posting in postings:
            account = str(posting["account_class"])
            amount = int(posting["signed_amount"])
            wallet_id = posting.get("wallet_id")
            if account == "cash" and wallet_id:
                wallets[str(wallet_id)]["cash_balance"] += amount
                cashflow += amount
            elif account == "revenue":
                revenue += -amount
            elif account == "expense":
                cost += amount

        is_internal = (
            record.get("scope") == "internal"
            or record.get("flow_class") == "internal"
            or bool(accounts & INTERNAL_ACCOUNT_CLASSES)
        )
        if not is_internal:
            if cashflow > 0:
                external_inflow += cashflow
            elif cashflow < 0:
                external_outflow += -cashflow

        project_id = record.get("project_id")
        if project_id:
            project = projects[str(project_id)]
            project["revenue"] += revenue
            project["cost"] += cost
            project["cashflow"] += cashflow

    debt_aging = {key: 0 for key in ("current", "days_1_30", "days_31_60", "days_61_90", "days_over_90")}
    for debt in debt_projections:
        outstanding = _money(debt.get("outstanding"), "debt outstanding")
        if outstanding < 0:
            raise ValueError("debt outstanding must not be negative")
        if outstanding == 0 or debt.get("status") in {"paid", "reversed"}:
            continue
        lender = str(debt.get("lender_wallet_id") or "")
        borrower = str(debt.get("borrower_wallet_id") or "")
        if not lender or not borrower or lender == borrower:
            raise ValueError("debt wallet identities are invalid")
        wallets[lender]["receivable"] += outstanding
        wallets[borrower]["payable"] += outstanding
        due_value = debt.get("due_at")
        bucket = "current" if due_value is None else _aging_bucket(
            _instant(due_value, "debt due_at"), cutoff_at
        )
        debt_aging[bucket] += outstanding

    for wallet in wallets.values():
        wallet["cash_balance"] += wallet["opening_balance"]
        wallet["available_balance"] = wallet["cash_balance"] + wallet["adjustments"]
        wallet["adjusted_balance"] = (
            wallet["available_balance"] + wallet["receivable"] - wallet["payable"]
        )
        runway = None
        if monthly_outflow > 0:
            runway = wallet["available_balance"] * 10_000 // monthly_outflow
        wallet["runway_months_basis_points"] = runway
        wallet["health"] = _health(wallet["available_balance"], runway)

    for project in projects.values():
        project["gross_profit"] = project["revenue"] - project["cost"]
        project["margin_basis_points"] = (
            project["gross_profit"] * 10_000 // project["revenue"]
            if project["revenue"]
            else 0
        )
        project["contribution"] = project["gross_profit"]

    return {
        "oracle_version": METRIC_ORACLE_VERSION,
        "cutoff": cutoff_at.isoformat(),
        "excluded": excluded,
        "group": {
            "external_inflow": external_inflow,
            "external_outflow": external_outflow,
            "net_cashflow": external_inflow - external_outflow,
        },
        "wallets": dict(sorted(wallets.items())),
        "projects": dict(sorted(projects.items())),
        "debt_aging": debt_aging,
    }
