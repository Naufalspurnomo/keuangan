"""
Seed stress test data into Google Sheets (Split Layout + Operasional).

Usage examples:
  python scripts/seed_stress_data.py
  python scripts/seed_stress_data.py --seed 42 --projects 8 --months 7
  python scripts/seed_stress_data.py --start 2025-07-01 --end 2026-01-31
"""

import argparse
import random
from datetime import datetime, timedelta

from config.constants import (
    SPLIT_PEMASUKAN,
    SPLIT_PENGELUARAN,
    OPERASIONAL_COLS,
    SPLIT_LAYOUT_DATA_START,
    OPERASIONAL_DATA_START,
)
from config.wallets import DOMPET_SHEETS
from sheets_helper import (
    get_dompet_sheet,
    get_or_create_operational_sheet,
)


COMPANIES = [
    {"name": "Hollawall", "dompet": "CV HB (101)", "prefix": "HOLLA"},
    {"name": "Hojja", "dompet": "CV HB (101)", "prefix": "HOJJA"},
    {"name": "Texturin Surabaya", "dompet": "TX SBY(216)", "prefix": None},
    {"name": "Texturin Bali", "dompet": "TX BALI(087)", "prefix": None},
]

PROJECT_NAMES = [
    "Wooftopia", "Unilver Indonesia", "Cafe Langit", "Ruko Merdeka",
    "Villa Kintamani", "Taman Sari", "Gedung Pelangi", "Studio Rasa",
    "Hotel Mutiara", "Apartemen Senja", "Kopi Tepi", "Resto Sagara",
]

EXPENSE_DESCS = [
    "Beli cat", "Beli semen", "Beli keramik", "Transport material",
    "Sewa alat", "Beli kayu", "Beli paku", "Beli besi",
]

SALARY_DESCS = [
    "Gaji tukang A", "Gaji tukang B", "Gaji mandor", "Gaji helper",
]

INCOME_DESCS = [
    "DP project", "DP 2 project", "Pelunasan project",
]

OPERATIONAL_DESCS = [
    "Bayar listrik kantor", "Bayar internet kantor", "Beli ATK",
    "Konsumsi rapat", "Gaji admin", "Beli peralatan kantor",
]

OPERATIONAL_CATEGORIES = ["Gaji", "ListrikAir", "Konsumsi", "Peralatan", "Lain Lain"]


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _random_date(start_dt: datetime, end_dt: datetime) -> datetime:
    span_days = max((end_dt - start_dt).days, 1)
    day_offset = random.randint(0, span_days)
    hour = random.randint(8, 18)
    minute = random.choice([0, 10, 20, 30, 40, 50])
    return start_dt + timedelta(days=day_offset, hours=hour, minutes=minute)


def _format_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _format_time(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")


def _apply_prefix(prefix: str, base: str) -> str:
    if prefix:
        return f"{prefix} - {base}"
    return base


def _count_existing(sheet, col_idx: int, start_row: int = 1) -> int:
    values = sheet.col_values(col_idx)
    if not values:
        return 0
    count = 0
    for i in range(start_row - 1, len(values)):
        if str(values[i]).strip():
            count += 1
    return count


def _first_empty_row(sheet, col_idx: int, start_row: int) -> int:
    values = sheet.col_values(col_idx)
    if not values:
        return start_row
    for i in range(start_row - 1, len(values)):
        if not str(values[i]).strip():
            return i + 1
    return len(values) + 1


def _build_split_row(tipe: str, no_val: int, dt: datetime, project_name: str, desc: str, amount: int, tx_id: str):
    base = [""] * 9
    if tipe == "Pemasukan":
        base[0] = no_val
        base[1] = _format_time(dt)
        base[2] = _format_date(dt)
        base[3] = amount
        base[4] = project_name
        base[5] = desc
        base[6] = "Seeder"
        base[7] = "Seeder"
        base[8] = tx_id
    else:
        base[0] = no_val
        base[1] = _format_time(dt)
        base[2] = _format_date(dt)
        base[3] = amount
        base[4] = project_name
        base[5] = desc
        base[6] = "Seeder"
        base[7] = "Seeder"
        base[8] = tx_id
    return base


def _build_operational_row(no_val: int, dt: datetime, amount: int, desc: str, category: str, tx_id: str, source_wallet: str):
    desc_full = f"{desc} [Sumber: {source_wallet}]"
    return [
        no_val,
        _format_date(dt),
        amount,
        desc_full,
        "Seeder",
        "Seeder",
        category,
        tx_id,
    ]


def seed_data(start_dt: datetime, end_dt: datetime, projects_per_company: int, seed: int):
    random.seed(seed)

    dompet_sheets = {name: get_dompet_sheet(name) for name in DOMPET_SHEETS}
    op_sheet = get_or_create_operational_sheet()

    # Track NO for income/expense blocks
    no_in = {}
    no_out = {}
    start_row_in = {}
    start_row_out = {}
    for dompet, sheet in dompet_sheets.items():
        no_in[dompet] = _count_existing(sheet, SPLIT_PEMASUKAN["NO"], start_row=SPLIT_LAYOUT_DATA_START)
        no_out[dompet] = _count_existing(sheet, SPLIT_PENGELUARAN["NO"], start_row=SPLIT_LAYOUT_DATA_START)
        start_row_in[dompet] = _first_empty_row(sheet, SPLIT_PEMASUKAN["NO"], SPLIT_LAYOUT_DATA_START)
        start_row_out[dompet] = _first_empty_row(sheet, SPLIT_PENGELUARAN["NO"], SPLIT_LAYOUT_DATA_START)

    op_no = max(_count_existing(op_sheet, OPERASIONAL_COLS["NO"], start_row=OPERASIONAL_DATA_START), 0)

    rows_by_sheet_in = {dompet: [] for dompet in DOMPET_SHEETS}
    rows_by_sheet_out = {dompet: [] for dompet in DOMPET_SHEETS}
    op_rows = []

    for company in COMPANIES:
        dompet = company["dompet"]
        prefix = company["prefix"]
        sheet = dompet_sheets[dompet]

        project_bases = random.sample(PROJECT_NAMES, k=min(projects_per_company, len(PROJECT_NAMES)))
        for idx, base_name in enumerate(project_bases, start=1):
            project_name = _apply_prefix(prefix, base_name)
            start_date = _random_date(start_dt, end_dt - timedelta(days=30))
            finish_date = _random_date(start_date + timedelta(days=14), end_dt)

            is_finished = random.random() < 0.7
            if is_finished:
                finish_name = f"{project_name} (Finish)"
            else:
                finish_name = project_name

            # Income: DP
            no_in[dompet] += 1
            rows_by_sheet_in[dompet].append(
                _build_split_row(
                    "Pemasukan",
                    no_in[dompet],
                    start_date,
                    project_name,
                    "DP project",
                    random.randint(5_000_000, 25_000_000),
                    f"{company['name']}-dp-{idx}",
                )
            )

            # Income: DP2
            mid_date = _random_date(start_date + timedelta(days=7), finish_date)
            no_in[dompet] += 1
            rows_by_sheet_in[dompet].append(
                _build_split_row(
                    "Pemasukan",
                    no_in[dompet],
                    mid_date,
                    project_name,
                    "DP 2 project",
                    random.randint(5_000_000, 20_000_000),
                    f"{company['name']}-dp2-{idx}",
                )
            )

            # Income: Pelunasan (finish)
            if is_finished:
                no_in[dompet] += 1
                rows_by_sheet_in[dompet].append(
                    _build_split_row(
                        "Pemasukan",
                        no_in[dompet],
                        finish_date,
                        finish_name,
                        "Pelunasan project",
                        random.randint(10_000_000, 40_000_000),
                        f"{company['name']}-fin-{idx}",
                    )
                )

            # Expenses
            for exp_idx in range(random.randint(4, 8)):
                exp_date = _random_date(start_date, finish_date)
                desc = random.choice(EXPENSE_DESCS)
                no_out[dompet] += 1
                rows_by_sheet_out[dompet].append(
                    _build_split_row(
                        "Pengeluaran",
                        no_out[dompet],
                        exp_date,
                        project_name,
                        desc,
                        random.randint(200_000, 4_000_000),
                        f"{company['name']}-exp-{idx}-{exp_idx}",
                    )
                )

            # Salary
            for sal_idx in range(random.randint(2, 4)):
                sal_date = _random_date(start_date, finish_date)
                desc = random.choice(SALARY_DESCS)
                no_out[dompet] += 1
                rows_by_sheet_out[dompet].append(
                    _build_split_row(
                        "Pengeluaran",
                        no_out[dompet],
                        sal_date,
                        project_name,
                        desc,
                        random.randint(500_000, 3_000_000),
                        f"{company['name']}-sal-{idx}-{sal_idx}",
                    )
                )

    # Operasional kantor
    months = int((end_dt - start_dt).days / 30) + 1
    for month_idx in range(months * 4):
        dt = _random_date(start_dt, end_dt)
        desc = random.choice(OPERATIONAL_DESCS)
        category = random.choice(OPERATIONAL_CATEGORIES)
        source_wallet = random.choice(DOMPET_SHEETS)
        op_no += 1
        op_rows.append(
            _build_operational_row(
                op_no,
                dt,
                random.randint(200_000, 3_000_000),
                desc,
                category,
                f"op-{month_idx}",
                source_wallet,
            )
        )

    # Batch append to reduce API calls
    for dompet, sheet in dompet_sheets.items():
        rows_in = rows_by_sheet_in.get(dompet, [])
        if rows_in:
            start_row = start_row_in[dompet]
            end_row = start_row + len(rows_in) - 1
            sheet.update(
                f"A{start_row}:I{end_row}",
                rows_in,
                value_input_option="USER_ENTERED",
            )

        rows_out = rows_by_sheet_out.get(dompet, [])
        if rows_out:
            start_row = start_row_out[dompet]
            end_row = start_row + len(rows_out) - 1
            sheet.update(
                f"J{start_row}:R{end_row}",
                rows_out,
                value_input_option="USER_ENTERED",
            )

    if op_rows:
        chunk = 200
        for i in range(0, len(op_rows), chunk):
            op_sheet.append_rows(op_rows[i:i + chunk], value_input_option="USER_ENTERED")


def main():
    parser = argparse.ArgumentParser(description="Seed stress test data into Google Sheets.")
    parser.add_argument("--seed", type=int, default=2026, help="Random seed for reproducibility.")
    parser.add_argument("--projects", type=int, default=6, help="Projects per company.")
    parser.add_argument("--months", type=int, default=6, help="Months back from today if no start/end.")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD.")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD.")
    args = parser.parse_args()

    if args.start and args.end:
        start_dt = _parse_date(args.start)
        end_dt = _parse_date(args.end)
    else:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=args.months * 30)

    if start_dt >= end_dt:
        raise SystemExit("Start date must be before end date.")

    print(f"Seeding data from {start_dt.date()} to {end_dt.date()} ...")
    seed_data(start_dt, end_dt, args.projects, args.seed)
    print("Done.")


if __name__ == "__main__":
    main()
