"""Pure projection of the bot's authoritative read model into snapshot.v1."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import re
from typing import Any, Mapping, Sequence

from utils.amounts import parse_money_token


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y")
_INCOME_TYPES = frozenset({"pemasukan", "income", "masuk", "credit"})
_EXPENSE_TYPES = frozenset({"pengeluaran", "expense", "keluar", "debit"})


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for pattern in _DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _freshness(data_through: date | None, now: datetime) -> str:
    if data_through is None:
        return "stale"
    now_date = now.astimezone(timezone.utc).date() if now.tzinfo else now.date()
    age_days = max(0, (now_date - data_through).days)
    if age_days <= 1:
        return "fresh"
    if age_days <= 3:
        return "aging"
    return "stale"


def _balance(value: Any) -> int:
    if isinstance(value, Mapping):
        return int(value.get("saldo") or 0)
    return int(value or 0)


def _source_key(row: Mapping[str, Any]) -> str:
    sheet = str(row.get("sheet_name") or row.get("company_sheet") or "unknown").strip()
    block = str(row.get("source_block") or row.get("tipe") or "row").strip().casefold().replace(" ", "_")
    position = str(row.get("sheet_row") or row.get("message_id") or "unknown").strip()
    return f"{sheet}:{block}:{position}"


def build_live_snapshot(
    raw_rows: Sequence[Mapping[str, Any]],
    wallet_balances: Mapping[str, Any],
    debts: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one immutable frontend contract from authoritative read-only inputs."""

    observed_at = now or datetime.now(timezone.utc)
    valid_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    for raw in raw_rows:
        source_key = _source_key(raw)
        if source_key in seen_keys:
            raise ValueError(f"duplicate source key: {source_key}")
        seen_keys.add(source_key)
        transaction_date = _parse_date(raw.get("tanggal") or raw.get("transaction_date"))
        raw_amount = raw.get("jumlah") if "jumlah" in raw else raw.get("amount")
        amount = parse_money_token(raw_amount) if re.search(r"\d", str(raw_amount or "")) else 0
        transaction_type = str(raw.get("tipe") or raw.get("transaction_type") or "").strip()
        direction = transaction_type.casefold()
        if transaction_date is None or amount <= 0 or direction not in (_INCOME_TYPES | _EXPENSE_TYPES):
            quality_rows.append({"source_key": source_key, "invalid_reason": "invalid_date_or_amount"})
            continue
        valid_rows.append(
            {
                "source_key": source_key,
                "transaction_date": transaction_date,
                "transaction_type": "Pemasukan" if direction in _INCOME_TYPES else "Pengeluaran",
                "amount": amount,
                "wallet": str(raw.get("sheet_name") or "").strip(),
                "company": str(raw.get("company_sheet") or "").strip(),
                "project": str(raw.get("nama_projek") or raw.get("project") or "").strip(),
                "notes": str(raw.get("keterangan") or raw.get("notes") or "").strip(),
                "internal_movement": bool(raw.get("internal_movement")),
                "transfer_scope": "internal" if bool(raw.get("internal_movement")) else "external",
            }
        )

    valid_rows.sort(key=lambda row: (row["transaction_date"], row["source_key"]), reverse=True)
    transactions = [
        {**row, "id": index, "transaction_date": row["transaction_date"].isoformat()}
        for index, row in enumerate(valid_rows, start=1)
    ]

    wallets = [
        {
            "source_key": f"{str(name).strip()}:wallet:summary",
            "name": str(name),
            "balance": _balance(value),
        }
        for name, value in wallet_balances.items()
    ]
    cash_balance = sum(item["balance"] for item in wallets)
    inflow = sum(
        row["amount"] for row in valid_rows
        if row["transaction_type"] == "Pemasukan" and not row["internal_movement"]
    )
    outflow = sum(
        row["amount"] for row in valid_rows
        if row["transaction_type"] == "Pengeluaran" and not row["internal_movement"]
    )

    normalized_debts = []
    for index, debt in enumerate(debts, start=1):
        normalized_debts.append(
            {
                "source_key": str(debt.get("source_key") or f"HUTANG:{index}"),
                "date": (_parse_date(debt.get("date") or debt.get("tanggal")) or date.min).isoformat() if (debt.get("date") or debt.get("tanggal")) else None,
                "amount": int(debt.get("amount") or debt.get("nominal") or 0),
                "notes": str(debt.get("notes") or debt.get("keterangan") or ""),
                "borrower": str(debt.get("borrower") or debt.get("yang_hutang") or ""),
                "lender": str(debt.get("lender") or debt.get("yang_dihutangi") or ""),
                "status": str(debt.get("status") or "").strip().upper(),
            }
        )
    open_internal_debt = sum(row["amount"] for row in normalized_debts if row["status"] == "OPEN")

    project_totals: dict[str, int] = defaultdict(int)
    month_totals: dict[str, int] = defaultdict(int)
    for row in valid_rows:
        if row["internal_movement"]:
            continue
        signed = row["amount"] if row["transaction_type"] == "Pemasukan" else -row["amount"]
        project = row["project"] or "Tanpa Proyek"
        project_totals[project] += signed
        month_totals[row["transaction_date"].strftime("%Y-%m")] += signed
    project_summaries = [
        {"name": name, "net_cashflow": amount}
        for name, amount in sorted(project_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    running = cash_balance - sum(month_totals.values())
    cash_trend = []
    for month, movement in sorted(month_totals.items()):
        running += movement
        cash_trend.append({"month": month, "balance": running, "net_movement": movement})

    data_through = max((row["transaction_date"] for row in valid_rows), default=None)
    invalid_rows = len(quality_rows)
    total_rows = len(valid_rows) + invalid_rows
    completeness = round((len(valid_rows) / total_rows) * 100, 1) if total_rows else 0.0
    project_cashflow = sum(
        amount for name, amount in project_totals.items() if name.casefold() not in {"operasional", "tanpa proyek"}
    )
    return {
        "version": "dashboard.snapshot.v1",
        "meta": {
            "as_of": observed_at.isoformat(),
            "data_through": data_through.isoformat() if data_through else None,
            "freshness": _freshness(data_through, observed_at),
            "source": "Hollawall Google Sheets read model",
            "data_completeness": {
                "valid_rows": len(valid_rows),
                "invalid_rows": invalid_rows,
                "completeness_pct": completeness,
            },
        },
        "overview": {
            "metrics": {
                "cash_balance": cash_balance,
                "operating_inflow": inflow,
                "operating_outflow": outflow,
                "net_operating_cashflow": inflow - outflow,
                "open_internal_debt": open_internal_debt,
                "project_cashflow": project_cashflow,
            },
            "counts": {"valid_rows": len(valid_rows), "invalid_rows": invalid_rows},
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
        "quality_rows": quality_rows,
        "wallets": wallets,
        "transactions": transactions,
        "debts": normalized_debts,
        "cash_trend": cash_trend,
        "project_summaries": project_summaries,
    }
