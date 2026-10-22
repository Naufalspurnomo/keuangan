#!/usr/bin/env python3
"""Build a sanitized, deterministic read-only dashboard snapshot from Hollawall XLSX."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

WALLETS = ("CV HB(101)", "TX SBY(216)", "TX BALI(087)")
INTERNAL_MARKERS = ("|utang", "|terima", "|bayar", "hutang_paid_", "hutang ke dompet", "terima pelunasan hutang", "bayar hutang ke")


def _iso_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        candidate = value[:10]
        try:
            return date.fromisoformat(candidate).isoformat()
        except ValueError:
            return None
    return None


def _is_internal(message_id: str, project: str, notes: str) -> bool:
    haystack = " ".join((message_id, project, notes)).lower()
    return any(marker in haystack for marker in INTERNAL_MARKERS)


def _company(wallet: str, project: str) -> str:
    if wallet == "TX SBY(216)":
        return "Texturin Surabaya"
    if wallet == "TX BALI(087)":
        return "Texturin Bali"
    return "Hojja" if project.lower().startswith("hojja") else "Hollawall"


def _source_datetime(modified_at: str) -> datetime:
    normalized = modified_at.replace("Z", "+00:00")
    value = datetime.fromisoformat(normalized)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def build_snapshot(workbook_path: str | Path, source_modified_at: str) -> dict[str, Any]:
    workbook = load_workbook(workbook_path, data_only=True, read_only=False)
    wallets = []
    balance_by_wallet: dict[str, int] = {}
    dashboard = workbook["Dashboard"]
    for row in range(26, 40):
        wallet = dashboard.cell(row, 1).value
        balance = dashboard.cell(row, 2).value
        if wallet in WALLETS and isinstance(balance, (int, float)):
            balance_by_wallet[str(wallet)] = int(round(balance))
    for wallet in WALLETS:
        wallets.append({"name": wallet, "balance": balance_by_wallet.get(wallet, 0)})

    transactions: list[dict[str, Any]] = []
    invalid_rows = 0
    sequential_id = 0
    for wallet in WALLETS:
        sheet = workbook[wallet]
        for row in range(9, sheet.max_row + 1):
            for transaction_type, start in (("Pemasukan", 1), ("Pengeluaran", 10)):
                raw_date = sheet.cell(row, start + 2).value
                raw_amount = sheet.cell(row, start + 3).value
                message_id = str(sheet.cell(row, start + 8).value or "").strip()
                if not any((raw_date, raw_amount, message_id)):
                    continue
                transaction_date = _iso_date(raw_date)
                if not transaction_date or not isinstance(raw_amount, (int, float)) or not message_id:
                    invalid_rows += 1
                    continue
                project = str(sheet.cell(row, start + 4).value or "Saldo Umum").strip()
                notes = str(sheet.cell(row, start + 5).value or "").strip()
                sequential_id += 1
                transactions.append({
                    "id": sequential_id,
                    "source_key": message_id,
                    "transaction_date": transaction_date,
                    "transaction_type": transaction_type,
                    "amount": int(round(raw_amount)),
                    "wallet": wallet,
                    "company": _company(wallet, project),
                    "project": project,
                    "notes": notes,
                    "internal_movement": _is_internal(message_id, project, notes),
                })
    transactions.sort(key=lambda row: (row["transaction_date"], row["source_key"]), reverse=True)

    debts = []
    if "HUTANG" in workbook.sheetnames:
        debt_sheet = workbook["HUTANG"]
        for row in range(2, debt_sheet.max_row + 1):
            amount = debt_sheet.cell(row, 3).value
            status = str(debt_sheet.cell(row, 7).value or "").upper()
            message_id = str(debt_sheet.cell(row, 9).value or "").strip()
            if not isinstance(amount, (int, float)) or not message_id:
                continue
            debts.append({
                "source_key": message_id,
                "date": _iso_date(debt_sheet.cell(row, 2).value),
                "amount": int(round(amount)),
                "notes": str(debt_sheet.cell(row, 4).value or "").strip(),
                "borrower": str(debt_sheet.cell(row, 5).value or "").strip(),
                "lender": str(debt_sheet.cell(row, 6).value or "").strip(),
                "status": status,
            })

    external = [row for row in transactions if not row["internal_movement"]]
    operating_inflow = sum(row["amount"] for row in external if row["transaction_type"] == "Pemasukan")
    operating_outflow = sum(row["amount"] for row in external if row["transaction_type"] == "Pengeluaran")
    open_internal_debt = sum(row["amount"] for row in debts if row["status"] == "OPEN")
    project_totals: dict[str, int] = defaultdict(int)
    month_totals: dict[str, int] = defaultdict(int)
    for row in external:
        signed_amount = row["amount"] if row["transaction_type"] == "Pemasukan" else -row["amount"]
        month_totals[row["transaction_date"][:7]] += signed_amount
        if row["project"].strip().lower() != "saldo umum":
            project_totals[row["project"]] += signed_amount
    project_cashflow = sum(project_totals.values())
    project_summaries = [
        {"name": name, "net_cashflow": amount}
        for name, amount in sorted(project_totals.items(), key=lambda item: abs(item[1]), reverse=True)[:8]
    ]
    cash_balance = sum(balance_by_wallet.values())
    running_balance = cash_balance - sum(month_totals.values())
    cash_trend = []
    for month, movement in sorted(month_totals.items()):
        running_balance += movement
        cash_trend.append({"month": month, "balance": running_balance, "net_movement": movement})
    latest_date = max((row["transaction_date"] for row in transactions), default=None)
    source_dt = _source_datetime(source_modified_at)
    now = datetime.now(timezone.utc)
    source_age_hours = max(0, (now - source_dt.astimezone(timezone.utc)).total_seconds() / 3600)
    data_age_hours = source_age_hours
    if latest_date:
        latest_dt = datetime.combine(date.fromisoformat(latest_date), time.max, tzinfo=timezone.utc)
        data_age_hours = max(0, (now - latest_dt).total_seconds() / 3600)
    age_hours = max(source_age_hours, data_age_hours)
    freshness = "fresh" if age_hours <= 24 else "aging" if age_hours <= 72 else "stale"
    valid_rows = len(transactions)
    total_rows = valid_rows + invalid_rows
    completeness = round(valid_rows / total_rows * 100, 1) if total_rows else 0.0

    return {
        "version": "dashboard.snapshot.v1",
        "meta": {
            "as_of": source_dt.isoformat(),
            "data_through": latest_date,
            "freshness": freshness,
            "source": "Hollawall Keuangan.xlsx · Google Drive owner snapshot",
            "data_completeness": {"valid_rows": valid_rows, "invalid_rows": invalid_rows, "completeness_pct": completeness},
        },
        "overview": {
            "metrics": {
                "cash_balance": cash_balance,
                "operating_inflow": operating_inflow,
                "operating_outflow": operating_outflow,
                "net_operating_cashflow": operating_inflow - operating_outflow,
                "open_internal_debt": open_internal_debt,
                "project_cashflow": project_cashflow,
            },
            "counts": {"valid_rows": valid_rows, "invalid_rows": invalid_rows},
            "labels": {
                "cash_balance": "Saldo kas",
                "operating_inflow": "Pemasukan operasional",
                "operating_outflow": "Pengeluaran operasional",
                "net_operating_cashflow": "Arus kas operasional bersih",
                "open_internal_debt": "Hutang antar-dompet terbuka",
                "project_cashflow": "Arus kas proyek bersih",
            },
            "drilldowns": {},
        },
        "wallets": wallets,
        "transactions": transactions,
        "debts": debts,
        "cash_trend": cash_trend,
        "project_summaries": project_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook")
    parser.add_argument("output")
    parser.add_argument("--source-modified-at", required=True)
    args = parser.parse_args()
    snapshot = build_snapshot(args.workbook, args.source_modified_at)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "version": snapshot["version"],
        "transactions": len(snapshot["transactions"]),
        "invalid_rows": snapshot["overview"]["counts"]["invalid_rows"],
        "data_through": snapshot["meta"]["data_through"],
        "freshness": snapshot["meta"]["freshness"],
        "output_bytes": output.stat().st_size,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
