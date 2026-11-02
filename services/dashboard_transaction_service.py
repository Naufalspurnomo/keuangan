"""Dashboard transaction coordination without an exposed HTTP route.

The coordinator validates before I/O, durably claims idempotency, delegates the
financial write to the existing Google Sheets append helpers, and only marks a
request complete after reading the exact authoritative Sheet row back.
Postgres remains a best-effort projection and is never treated as authority.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from config.constants import OPERASIONAL_COLS, OPERASIONAL_SHEET_NAME, SPLIT_PEMASUKAN, SPLIT_PENGELUARAN
from config.wallets import get_dompet_short_name
from dashboard_api.write_contracts import TransactionRequest, validate_transaction_request
from security import secure_log
from services.dashboard_write_requests import DashboardWriteClaim, DashboardWriteRequestStore
from utils.amounts import parse_money_token


class DashboardTransactionUnavailable(RuntimeError):
    """The coordinator cannot prove a safe authoritative transaction state."""


class DashboardTransactionConflict(RuntimeError):
    """Authoritative Sheet evidence conflicts with the claimed request."""


@dataclass(frozen=True, slots=True)
class AuthoritativeSheetRow:
    """Normalized evidence read directly from one authoritative Sheet row."""

    sheet_name: str
    sheet_row: int
    source_block: str
    message_id: str
    transaction_date: date
    direction: str
    amount: int
    description: str
    wallet_reference: str
    project: str | None
    category: str | None
    recorded_by: str
    input_source: str


class WriteRequestStore(Protocol):
    def claim(
        self,
        request: TransactionRequest,
        *,
        actor: Mapping[str, Any],
        message_id: str,
    ) -> DashboardWriteClaim: ...

    def complete(
        self,
        claim: DashboardWriteClaim,
        response: Mapping[str, Any],
        *,
        status: str = "completed",
    ) -> DashboardWriteClaim: ...


class SheetsTransactionAdapter(Protocol):
    def append(
        self,
        request: TransactionRequest,
        *,
        sender_name: str,
        source: str,
        message_id: str,
    ) -> Mapping[str, Any]: ...

    def read_by_message_id(
        self,
        request: TransactionRequest,
        *,
        message_id: str,
    ) -> AuthoritativeSheetRow | None: ...


ProjectExists = Callable[[str, str, str], bool]
ProjectionRepair = Callable[[dict[str, Any]], Any]
Today = Callable[[], date]
_SOURCE_WALLET_RE = re.compile(r"^(?P<description>.*) \[Sumber: (?P<wallet>[^\]]+)\]$")


def _cell(values: list[Any], column: int) -> str:
    index = column - 1
    if index >= len(values):
        return ""
    return str(values[index] or "").strip()


def _sheet_date(value: str) -> date:
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise DashboardTransactionConflict("authoritative Sheet row has an invalid transaction date")


def _matching_rows(values: list[Any], message_id: str) -> list[int]:
    return [index for index, value in enumerate(values, start=1) if str(value or "").strip() == message_id]


class GoogleSheetsTransactionAdapter:
    """Production adapter around existing append helpers plus direct row readback.

    Imports are lazy so isolated coordinator tests never initialize Google API
    clients or perform network access.
    """

    def append(
        self,
        request: TransactionRequest,
        *,
        sender_name: str,
        source: str,
        message_id: str,
    ) -> Mapping[str, Any]:
        from sheets_helper import append_operational_transaction, append_project_transaction

        transaction = {
            "jumlah": request.amount,
            "keterangan": request.description,
            "tipe": request.direction,
            "message_id": message_id,
            "kategori": request.category,
            "company": request.company,
        }
        if request.scope == "project":
            result = append_project_transaction(
                transaction=transaction,
                sender_name=sender_name,
                source=source,
                dompet_sheet=request.wallet,
                project_name=request.project or "",
                allow_queue=False,
                transaction_date=request.date,
            )
        else:
            result = append_operational_transaction(
                transaction=transaction,
                sender_name=sender_name,
                source=source,
                source_wallet=request.wallet,
                category=request.category,
                allow_queue=False,
                transaction_date=request.date,
            )
        if not isinstance(result, Mapping) or result.get("success") is not True:
            raise DashboardTransactionUnavailable("Sheets append helper did not confirm success")
        return result

    def read_by_message_id(
        self,
        request: TransactionRequest,
        *,
        message_id: str,
    ) -> AuthoritativeSheetRow | None:
        if request.scope == "project":
            return self._read_project(request, message_id=message_id)
        return self._read_office(request, message_id=message_id)

    @staticmethod
    def _read_project(request: TransactionRequest, *, message_id: str) -> AuthoritativeSheetRow | None:
        from sheets_helper import get_dompet_sheet

        columns = SPLIT_PEMASUKAN if request.direction == "Pemasukan" else SPLIT_PENGELUARAN
        worksheet = get_dompet_sheet(request.wallet)
        if worksheet is None:
            raise DashboardTransactionUnavailable("authoritative wallet Sheet is unavailable")
        matches = _matching_rows(worksheet.col_values(columns["MESSAGE_ID"]), message_id)
        if not matches:
            return None
        if len(matches) != 1:
            raise DashboardTransactionConflict("multiple authoritative Sheet rows use the same message id")
        row_number = matches[0]
        values = list(worksheet.row_values(row_number) or [])
        return AuthoritativeSheetRow(
            sheet_name=str(getattr(worksheet, "title", request.wallet) or "").strip(),
            sheet_row=row_number,
            source_block=request.direction.casefold(),
            message_id=_cell(values, columns["MESSAGE_ID"]),
            transaction_date=_sheet_date(_cell(values, columns["TANGGAL"])),
            direction=request.direction,
            amount=parse_money_token(_cell(values, columns["JUMLAH"])),
            description=_cell(values, columns["KETERANGAN"]),
            wallet_reference=request.wallet,
            project=_cell(values, columns["PROJECT"]) or None,
            category=None,
            recorded_by=_cell(values, columns["OLEH"]),
            input_source=_cell(values, columns["SOURCE"]),
        )

    @staticmethod
    def _read_office(request: TransactionRequest, *, message_id: str) -> AuthoritativeSheetRow | None:
        from sheets_helper import get_or_create_operational_sheet

        worksheet = get_or_create_operational_sheet()
        if worksheet is None:
            raise DashboardTransactionUnavailable("authoritative operational Sheet is unavailable")
        matches = _matching_rows(worksheet.col_values(OPERASIONAL_COLS["MESSAGE_ID"]), message_id)
        if not matches:
            return None
        if len(matches) != 1:
            raise DashboardTransactionConflict("multiple authoritative Sheet rows use the same message id")
        row_number = matches[0]
        values = list(worksheet.row_values(row_number) or [])
        stored_description = _cell(values, OPERASIONAL_COLS["KETERANGAN"])
        match = _SOURCE_WALLET_RE.fullmatch(stored_description)
        description = match.group("description") if match else stored_description
        wallet_reference = match.group("wallet") if match else ""
        return AuthoritativeSheetRow(
            sheet_name=str(getattr(worksheet, "title", OPERASIONAL_SHEET_NAME) or "").strip(),
            sheet_row=row_number,
            source_block="operasional",
            message_id=_cell(values, OPERASIONAL_COLS["MESSAGE_ID"]),
            transaction_date=_sheet_date(_cell(values, OPERASIONAL_COLS["TANGGAL"])),
            direction="Pengeluaran",
            amount=parse_money_token(_cell(values, OPERASIONAL_COLS["JUMLAH"])),
            description=description,
            wallet_reference=wallet_reference,
            project=None,
            category=_cell(values, OPERASIONAL_COLS["KATEGORI"]) or None,
            recorded_by=_cell(values, OPERASIONAL_COLS["OLEH"]),
            input_source=_cell(values, OPERASIONAL_COLS["SOURCE"]),
        )


def _default_projection_repair(row: dict[str, Any]) -> Any:
    from services.ledger_store import upsert_row

    return upsert_row(row)


class DashboardTransactionService:
    """Coordinate one fail-closed dashboard transaction write."""

    def __init__(
        self,
        *,
        store: WriteRequestStore | None = None,
        sheets: SheetsTransactionAdapter | None = None,
        project_exists: ProjectExists,
        projection_repair: ProjectionRepair | None = None,
        today: Today | None = None,
    ) -> None:
        self._store = store or DashboardWriteRequestStore()
        self._sheets = sheets or GoogleSheetsTransactionAdapter()
        self._project_exists = project_exists
        self._projection_repair = projection_repair or _default_projection_repair
        self._today = today

    def validate(self, payload: Mapping[str, Any]) -> TransactionRequest:
        def project_exists(project: str) -> bool:
            wallet = payload.get("wallet")
            company = payload.get("company")
            if not isinstance(wallet, str) or not isinstance(company, str):
                return False
            return self._project_exists(project, wallet, company)

        kwargs: dict[str, Any] = {"project_exists": project_exists}
        if self._today is not None:
            kwargs["today"] = self._today
        return validate_transaction_request(payload, **kwargs)

    def record(
        self,
        payload: Mapping[str, Any],
        *,
        actor: Mapping[str, Any],
        message_id: str,
    ) -> dict[str, Any]:
        request = self.validate(payload)
        claim = self._store.claim(request, actor=actor, message_id=message_id)
        sheet_message_id = self._sheet_message_id(claim)

        if claim.status == "completed":
            return self._replay_completed(request, claim, sheet_message_id=sheet_message_id)
        if claim.status != "claimed":
            raise DashboardTransactionConflict(f"write request has unsupported terminal status: {claim.status}")

        row = self._sheets.read_by_message_id(request, message_id=sheet_message_id)
        if row is None:
            try:
                self._sheets.append(
                    request,
                    sender_name="Dashboard",
                    source="Dashboard",
                    message_id=sheet_message_id,
                )
            except Exception:
                # An append transport failure is ambiguous. Read authority before
                # deciding whether a retry may append again.
                row = self._sheets.read_by_message_id(request, message_id=sheet_message_id)
                if row is None:
                    raise
            if row is None:
                row = self._sheets.read_by_message_id(request, message_id=sheet_message_id)

        if row is None:
            raise DashboardTransactionUnavailable("authoritative Sheet row is missing after append")
        self._verify_row(request, row, sheet_message_id=sheet_message_id)
        response = self._completion_response(row)
        self._store.complete(claim, response)
        self._repair_projection(request, row)
        return {**response, "duplicate": False}

    @staticmethod
    def _sheet_message_id(claim: DashboardWriteClaim) -> str:
        return f"dashboard:{claim.request_id}:{claim.request_hash}"

    def _replay_completed(
        self,
        request: TransactionRequest,
        claim: DashboardWriteClaim,
        *,
        sheet_message_id: str,
    ) -> dict[str, Any]:
        stored = claim.completion_response
        if not isinstance(stored, dict):
            raise DashboardTransactionConflict("completed request has no stored completion response")
        row = self._sheets.read_by_message_id(request, message_id=sheet_message_id)
        if row is None:
            raise DashboardTransactionConflict("completed request authoritative Sheet row is missing")
        self._verify_row(request, row, sheet_message_id=sheet_message_id)
        expected = self._completion_response(row)
        if stored != expected:
            raise DashboardTransactionConflict("stored completion response conflicts with authoritative Sheet row")
        self._repair_projection(request, row)
        return {**stored, "duplicate": True}

    @staticmethod
    def _verify_row(
        request: TransactionRequest,
        row: AuthoritativeSheetRow,
        *,
        sheet_message_id: str,
    ) -> None:
        expected = {
            "sheet_name": OPERASIONAL_SHEET_NAME if request.scope == "office" else request.wallet,
            "source_block": "operasional" if request.scope == "office" else request.direction.casefold(),
            "message_id": sheet_message_id,
            "transaction_date": request.date,
            "direction": request.direction,
            "amount": request.amount,
            "description": request.description,
            "wallet_reference": get_dompet_short_name(request.wallet) if request.scope == "office" else request.wallet,
            "project": None if request.scope == "office" else request.project,
            "category": request.category if request.scope == "office" else None,
            "recorded_by": "Dashboard",
            "input_source": "Dashboard",
        }
        mismatches = [field for field, value in expected.items() if getattr(row, field) != value]
        if not isinstance(row.sheet_row, int) or row.sheet_row < 1:
            mismatches.append("sheet_row")
        if mismatches:
            raise DashboardTransactionConflict(
                "authoritative Sheet row mismatch: " + ", ".join(sorted(set(mismatches)))
            )

    @staticmethod
    def _completion_response(row: AuthoritativeSheetRow) -> dict[str, Any]:
        return {
            "recorded": True,
            "transaction_id": f"sheet:{row.sheet_name}:{row.source_block}:{row.sheet_row}",
            "sheet_name": row.sheet_name,
            "sheet_row": row.sheet_row,
            "source_block": row.source_block,
            "sheet_message_id": row.message_id,
        }

    def _repair_projection(self, request: TransactionRequest, row: AuthoritativeSheetRow) -> None:
        projection = {
            "tanggal": row.transaction_date.isoformat(),
            "jumlah": row.amount,
            "tipe": row.direction,
            "keterangan": (
                f"{row.description} [Sumber: {row.wallet_reference}]"
                if request.scope == "office"
                else row.description
            ),
            "nama_projek": row.project or "Operasional",
            "kategori": request.category,
            "company": request.company,
            "company_sheet": OPERASIONAL_SHEET_NAME if request.scope == "office" else request.company,
            "dompet_sheet": request.wallet,
            "oleh": row.recorded_by,
            "source": row.input_source,
            "source_wallet": request.wallet if request.scope == "office" else None,
            "message_id": row.message_id,
            "sheet_name": row.sheet_name,
            "sheet_row": row.sheet_row,
            "source_block": row.source_block,
        }
        try:
            self._projection_repair(projection)
        except Exception as exc:
            secure_log(
                "WARNING",
                f"Dashboard transaction projection repair failed: {type(exc).__name__}: {exc}",
            )
