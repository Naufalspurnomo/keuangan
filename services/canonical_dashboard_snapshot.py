"""Pure PostgreSQL-canonical projection for the fresh finance dashboard.

This projection deliberately has no Google Sheets fallback. An empty canonical
database is a valid fresh workspace with zero transactions and balances derived
only from explicitly configured opening balances.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any


SOURCE_NAME = "Hollawall PostgreSQL canonical ledger"


def _instant(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("canonical timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str:
    return _instant(value).isoformat()


def _date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and len(value) == 10:
        return date.fromisoformat(value).isoformat()
    return _instant(value).date().isoformat()


def _effective_record(chain: Sequence[Mapping[str, Any]], cutoff: datetime) -> Mapping[str, Any] | None:
    eligible = [record for record in chain if _instant(record.get("created_at") or record["occurred_at"]) <= cutoff]
    if not eligible:
        return None
    latest = eligible[-1]
    if latest.get("status") == "reversal":
        return None
    evidence = latest.get("evidence") or {}
    if not isinstance(evidence, Mapping):
        raise ValueError("canonical transaction evidence must be an object")
    if (
        evidence.get("is_acceptance_test") is True
        or evidence.get("test_namespace")
        or evidence.get("quarantined") is True
        or evidence.get("excluded_from_canonical_totals") is True
        or evidence.get("review_status") not in (None, "approved")
    ):
        return None
    return latest


def _registry_by_id(rows: Sequence[Mapping[str, Any]], *, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        identity = str(row.get("id") or "")
        display = str(row.get(label) or "").strip()
        if not identity or not display:
            raise ValueError("canonical registry row is incomplete")
        result[identity] = display
    return result


def _latest_opening_balances(rows: Sequence[Mapping[str, Any]], cutoff: datetime) -> dict[str, int]:
    latest: dict[tuple[str, str], tuple[datetime, int]] = {}
    for row in rows:
        effective_at = _instant(row["effective_at"])
        if effective_at > cutoff:
            continue
        key = (str(row["wallet_id"]), str(row.get("business_unit_id") or ""))
        current = latest.get(key)
        amount = int(row["amount"])
        if current is None or effective_at > current[0]:
            latest[key] = (effective_at, amount)
    totals: defaultdict[str, int] = defaultdict(int)
    for (wallet_id, _unit_id), (_at, amount) in latest.items():
        totals[wallet_id] += amount
    return dict(totals)


def _effective_debt(debt: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(debt.get("status") or "").casefold()
    outstanding = int(debt.get("outstanding") or 0)
    if status in {"reversed", "archived"} and outstanding == 0:
        return None
    return {
        **dict(debt),
        "principal": int(debt.get("principal") or 0),
        "repaid": int(debt.get("repaid") or 0),
        "outstanding": outstanding,
        "status": status,
    }


def build_canonical_dashboard_snapshot(
    *,
    transaction_chains: Sequence[Sequence[Mapping[str, Any]]],
    projects: Sequence[Mapping[str, Any]],
    debts: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Sequence[Mapping[str, Any]]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build dashboard.snapshot.v1 solely from canonical PostgreSQL records."""

    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    wallets_by_id = _registry_by_id(registry.get("wallets", []), label="display_name")
    units_by_id = _registry_by_id(registry.get("business_units", []), label="legal_name")
    projects_by_id = {str(row["id"]): dict(row) for row in projects}

    balances: defaultdict[str, int] = defaultdict(int)
    balances.update(
        _latest_opening_balances(registry.get("opening_balances", []), observed_at)
    )
    for adjustment in registry.get("balance_adjustments", []):
        if _instant(adjustment["effective_at"]) <= observed_at:
            balances[str(adjustment["wallet_id"])] += int(adjustment["delta_amount"])

    transactions: list[dict[str, Any]] = []
    project_totals: defaultdict[str, int] = defaultdict(int)
    operating_inflow = 0
    operating_outflow = 0
    data_instants: list[datetime] = []
    monthly_movement: defaultdict[str, int] = defaultdict(int)

    for chain in transaction_chains:
        record = _effective_record(chain, observed_at)
        if record is None:
            continue
        postings = record.get("postings")
        if not isinstance(postings, Sequence) or isinstance(postings, (str, bytes)):
            raise ValueError("canonical transaction postings must be a sequence")
        if sum(int(posting["signed_amount"]) for posting in postings) != 0:
            raise ValueError("canonical transaction postings must be balanced")

        cash_postings = [posting for posting in postings if posting.get("account_class") == "cash"]
        for posting in cash_postings:
            wallet_id = str(posting.get("wallet_id") or "")
            if wallet_id not in wallets_by_id:
                raise ValueError("canonical cash posting references an unknown wallet")
            balances[wallet_id] += int(posting["signed_amount"])

        scope = str(record.get("scope") or "")
        internal = scope == "internal" or record.get("flow_class") == "internal"
        cash_delta = sum(int(posting["signed_amount"]) for posting in cash_postings)
        if not internal:
            if cash_delta > 0:
                operating_inflow += cash_delta
            elif cash_delta < 0:
                operating_outflow += -cash_delta

        occurred_at = _instant(record["occurred_at"])
        data_instants.append(occurred_at)
        if not internal:
            monthly_movement[occurred_at.strftime("%Y-%m")] += cash_delta

        primary_cash = cash_postings[0] if cash_postings else None
        wallet_id = str(primary_cash.get("wallet_id") or "") if primary_cash else ""
        unit_id = str(primary_cash.get("business_unit_id") or "") if primary_cash else ""
        project_id = str(record.get("project_id") or "") or None
        project = projects_by_id.get(project_id or "")
        if project_id and project is None:
            raise ValueError("canonical transaction references an unknown project")
        if project_id:
            project_totals[project_id] += cash_delta

        transactions.append(
            {
                "id": len(transactions) + 1,
                "source_key": f"postgresql:transaction:{record['id']}:v{record['version']}",
                "transaction_date": occurred_at.date().isoformat(),
                "transaction_type": "Pemasukan" if cash_delta > 0 else "Pengeluaran",
                "amount": int(record["amount"]),
                "wallet": wallets_by_id.get(wallet_id, ""),
                "company": units_by_id.get(unit_id, ""),
                "project": project.get("name") if project else None,
                "project_id": project_id,
                "canonical_transaction_id": str(record["id"]),
                "transaction_version": int(record["version"]),
                "project_raw": project.get("name") if project else None,
                "scope": "internal_transfer" if internal else scope,
                "office_category": record.get("category") if scope == "office" else None,
                "category": record.get("category"),
                "recorded_by": (record.get("actor") or {}).get("email")
                or (record.get("actor") or {}).get("id"),
                "input_source": record.get("source"),
                "evidence_source": "canonical_ledger",
                "ocr_mode": None,
                "ocr_confidence": None,
                "notes": str(record.get("description") or ""),
                "internal_movement": internal,
                "transfer_scope": "internal" if internal else "external",
                "updated_at": _iso(record.get("created_at") or record["occurred_at"]),
            }
        )

    transactions.sort(
        key=lambda row: (row["transaction_date"], row["source_key"]), reverse=True
    )
    for index, row in enumerate(transactions, start=1):
        row["id"] = index

    normalized_debts: list[dict[str, Any]] = []
    open_debt = 0
    for raw in debts:
        debt = _effective_debt(raw)
        if debt is None:
            continue
        lender_id = str(debt.get("lender_wallet_id") or "")
        borrower_id = str(debt.get("borrower_wallet_id") or "")
        if lender_id not in wallets_by_id or borrower_id not in wallets_by_id:
            raise ValueError("canonical debt references an unknown wallet")
        open_debt += debt["outstanding"]
        occurred_at = _instant(debt["occurred_at"])
        data_instants.append(occurred_at)
        normalized_debts.append(
            {
                "source_key": f"postgresql:debt:{debt['id']}",
                "debt_id": str(debt["id"]),
                "date": occurred_at.date().isoformat(),
                "due_at": _date(debt.get("due_at")),
                "amount": debt["principal"],
                "principal": debt["principal"],
                "repaid": debt["repaid"],
                "outstanding": debt["outstanding"],
                "notes": str(debt.get("description") or ""),
                "borrower": wallets_by_id[borrower_id],
                "lender": wallets_by_id[lender_id],
                "status": debt["status"].upper(),
                "project_id": str(debt.get("project_id") or "") or None,
                "version": int(debt.get("version") or 1),
                "events": list(debt.get("events") or []),
            }
        )

    project_summaries = []
    for project_id, project in projects_by_id.items():
        status = str(project.get("status") or "planned")
        started_on = _date(project.get("start_date"))
        completed_on = _date(project.get("completion_date"))
        start_date = date.fromisoformat(started_on) if started_on else None
        end_date = date.fromisoformat(completed_on) if completed_on else observed_at.date()
        age_days = max(0, (end_date - start_date).days) if start_date else None
        health = (
            "completed"
            if status == "completed"
            else "unmarked"
            if status != "active" or age_days is None
            else "healthy"
            if age_days <= 14
            else "watch"
            if age_days <= 30
            else "overdue"
        )
        project_transactions = [row for row in transactions if row["project_id"] == project_id]
        activity_dates = [row["transaction_date"] for row in project_transactions]
        project_summaries.append(
            {
                "name": str(project.get("name") or ""),
                "project_id": project_id,
                "portfolio": str(project.get("company") or "Belum ditandai"),
                "net_cashflow": project_totals[project_id],
                "transaction_count": len(project_transactions),
                "first_activity_on": min(activity_dates) if activity_dates else None,
                "last_activity_on": max(activity_dates) if activity_dates else None,
                "started_on": started_on,
                "completed_on": completed_on,
                "age_days": age_days,
                "lifecycle_status": status,
                "health": health,
                "wallet": str(project.get("wallet") or ""),
                "company": str(project.get("company") or ""),
            }
        )
    project_summaries.sort(key=lambda row: row["name"].casefold())

    wallet_rows = [
        {
            "source_key": f"postgresql:wallet:{wallet_id}",
            "wallet_id": wallet_id,
            "name": name,
            "balance": balances[wallet_id],
        }
        for wallet_id, name in wallets_by_id.items()
    ]
    cash_balance = sum(row["balance"] for row in wallet_rows)
    running = cash_balance - sum(monthly_movement.values())
    cash_trend = []
    for month, movement in sorted(monthly_movement.items()):
        running += movement
        cash_trend.append(
            {"month": month, "balance": running, "net_movement": movement}
        )

    data_through = max(data_instants).date().isoformat() if data_instants else None
    return {
        "version": "dashboard.snapshot.v1",
        "meta": {
            "as_of": observed_at.isoformat(),
            "data_through": data_through,
            "freshness": "fresh",
            "source": SOURCE_NAME,
            "data_completeness": {
                "valid_rows": len(transactions),
                "invalid_rows": 0,
                "completeness_pct": 100.0,
            },
        },
        "overview": {
            "metrics": {
                "cash_balance": cash_balance,
                "operating_inflow": operating_inflow,
                "operating_outflow": operating_outflow,
                "net_operating_cashflow": operating_inflow - operating_outflow,
                "open_internal_debt": open_debt,
                "project_cashflow": sum(project_totals.values()),
            },
            "counts": {"valid_rows": len(transactions), "invalid_rows": 0},
            "labels": {},
            "drilldowns": {
                "cash_balance": "wallets",
                "operating_inflow": "transactions:external-income",
                "operating_outflow": "transactions:external-expense",
                "net_operating_cashflow": "transactions:external",
                "open_internal_debt": "debts:open",
                "project_cashflow": "transactions:projects",
            },
        },
        "quality_rows": [],
        "wallets": wallet_rows,
        "transactions": transactions,
        "debts": normalized_debts,
        "cash_trend": cash_trend,
        "project_summaries": project_summaries,
    }
