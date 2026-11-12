"""Dashboard transaction coordination without an exposed HTTP route.

The coordinator validates before I/O, durably claims idempotency, delegates the
financial write to the existing Google Sheets append helpers, and only marks a
request complete after reading the exact authoritative Sheet row back.
Postgres remains a best-effort projection and is never treated as authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from typing import Any, Protocol

from config.constants import (
    OPERASIONAL_COLS,
    OPERASIONAL_SHEET_NAME,
    SPLIT_LAYOUT_DATA_START,
    SPLIT_PEMASUKAN,
    SPLIT_PENGELUARAN,
)
from config.wallets import DOMPET_COMPANIES, get_dompet_short_name
from dashboard_api.write_contracts import (
    DASHBOARD_TIMEZONE,
    TransactionRequest,
    validate_transaction_request,
)
from security import secure_log
from services.dashboard_write_requests import DashboardWriteClaim, DashboardWriteRequestStore
from services.project_document_repository import (
    ProjectDocumentConflict,
    ProjectDocumentUnavailable,
)
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
ProjectUuidExists = Callable[[str, str, str], bool]
ProjectUuidName = Callable[[str], str | None]
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
    def read_receipt_authority(
        locator: Mapping[str, Any],
        project: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Read one receipt source directly from its authoritative wallet Sheet.

        PostgreSQL supplies only the locator. No cache or projection fallback is
        accepted here. Message-backed rows may move within the same income block;
        manual rows are bound to their recorded row through the source-key hash.
        """

        from gspread import WorksheetNotFound
        from services.ledger_store import build_source_key
        from sheets_helper import get_spreadsheet

        source_key = str(locator.get("source_key") or "").strip()
        source_sheet = str(locator.get("source_sheet") or "").strip()
        source_block = str(locator.get("source_block") or "").strip().casefold()
        message_id = str(locator.get("message_id") or "").strip()
        expected_row = locator.get("source_row")
        project_id = str(project.get("id") or "").strip()
        wallet = str(project.get("wallet") or "").strip()
        company = str(project.get("company") or "").strip()
        if (
            not source_key
            or source_block != "pemasukan"
            or not project_id
            or not wallet
            or not company
            or source_sheet != wallet
            or company not in DOMPET_COMPANIES.get(wallet, ())
        ):
            raise ProjectDocumentConflict("receipt authority locator is invalid")
        try:
            try:
                spreadsheet = get_spreadsheet()
                http_client = getattr(spreadsheet, "client", None)
                if http_client is not None and hasattr(http_client, "timeout"):
                    http_client.timeout = (5, 15)
                worksheet = spreadsheet.worksheet(source_sheet)
            except WorksheetNotFound as exc:
                raise ProjectDocumentConflict(
                    "authoritative receipt wallet Sheet no longer exists"
                ) from exc
            if message_id:
                matches = _matching_rows(
                    worksheet.col_values(SPLIT_PEMASUKAN["MESSAGE_ID"]),
                    message_id,
                )
                if not matches:
                    raise ProjectDocumentConflict(
                        "authoritative receipt source no longer exists"
                    )
                if len(matches) != 1:
                    raise ProjectDocumentConflict(
                        "authoritative receipt source identity is ambiguous"
                    )
                observed_row = matches[0]
            else:
                if (
                    isinstance(expected_row, bool)
                    or not isinstance(expected_row, int)
                    or expected_row < SPLIT_LAYOUT_DATA_START
                ):
                    raise ProjectDocumentConflict(
                        "manual receipt source row is invalid"
                    )
                observed_row = expected_row
            values = list(worksheet.row_values(observed_row) or [])
        except (ProjectDocumentConflict, ProjectDocumentUnavailable):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                "authoritative receipt Sheet is temporarily unavailable"
            ) from exc

        observed_message_id = _cell(values, SPLIT_PEMASUKAN["MESSAGE_ID"])
        if message_id != observed_message_id:
            raise ProjectDocumentConflict(
                "authoritative receipt source message identity changed"
            )
        raw_amount = _cell(values, SPLIT_PEMASUKAN["JUMLAH"])
        sheet_project = _cell(values, SPLIT_PEMASUKAN["PROJECT"])
        try:
            amount = parse_money_token(raw_amount)
            transaction_date = _sheet_date(
                _cell(values, SPLIT_PEMASUKAN["TANGGAL"])
            )
        except (DashboardTransactionConflict, TypeError, ValueError) as exc:
            raise ProjectDocumentConflict(
                "authoritative receipt source contains invalid cash data"
            ) from exc
        row_for_identity = {
            "sheet_name": source_sheet,
            "sheet_row": observed_row,
            "source_block": "pemasukan",
            "message_id": observed_message_id,
            "tanggal": _cell(values, SPLIT_PEMASUKAN["TANGGAL"]),
            "jumlah": raw_amount,
            "keterangan": _cell(values, SPLIT_PEMASUKAN["KETERANGAN"]),
            "nama_projek": sheet_project,
        }
        observed_key = build_source_key(row_for_identity)
        if observed_key != source_key:
            raise ProjectDocumentConflict(
                "authoritative receipt source identity changed"
            )
        if amount <= 0 or sheet_project != project_id:
            raise ProjectDocumentConflict(
                "authoritative receipt source project or amount changed"
            )
        raw_cells = [
            _cell(values, column)
            for column in range(SPLIT_PEMASUKAN["NO"], SPLIT_PEMASUKAN["MESSAGE_ID"] + 1)
        ]
        return {
            "source_key": observed_key,
            "source_sheet": source_sheet,
            "expected_source_row": expected_row,
            "observed_source_row": observed_row,
            "source_block": "pemasukan",
            "message_id": observed_message_id or None,
            "direction": "Pemasukan",
            "amount": amount,
            "transaction_date": transaction_date.isoformat(),
            "project_id": project_id,
            "wallet": wallet,
            "company": company,
            "description": _cell(values, SPLIT_PEMASUKAN["KETERANGAN"]),
            "raw_cells_sha256": hashlib.sha256(
                json.dumps(raw_cells, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
        }

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
        project_uuid_exists: ProjectUuidExists | None = None,
        project_uuid_name: ProjectUuidName | None = None,
        projection_repair: ProjectionRepair | None = None,
        today: Today | None = None,
    ) -> None:
        self._store = store or DashboardWriteRequestStore()
        self._sheets = sheets or GoogleSheetsTransactionAdapter()
        self._project_exists = project_exists
        self._project_uuid_exists = project_uuid_exists
        self._project_uuid_name = project_uuid_name
        self._projection_repair = projection_repair or _default_projection_repair
        self._today = today

    def validate(self, payload: Mapping[str, Any]) -> TransactionRequest:
        def project_exists(project: str) -> bool:
            wallet = payload.get("wallet")
            company = payload.get("company")
            if not isinstance(wallet, str) or not isinstance(company, str):
                return False
            if self._project_uuid_exists is not None:
                try:
                    uuid.UUID(project)
                except (TypeError, ValueError):
                    pass
                else:
                    return self._project_uuid_exists(project, wallet, company)
            return self._project_exists(project, wallet, company)

        kwargs: dict[str, Any] = {"project_exists": project_exists}
        if self._today is not None:
            kwargs["today"] = self._today
        return validate_transaction_request(payload, **kwargs)

    def _sheet_request(self, request: TransactionRequest) -> TransactionRequest:
        if request.scope != "project" or request.project is None:
            return request
        try:
            uuid.UUID(request.project)
        except (TypeError, ValueError):
            return request
        if self._project_uuid_name is None:
            raise DashboardTransactionUnavailable("canonical project name resolver is not configured")
        name = self._project_uuid_name(request.project)
        if not isinstance(name, str) or not name.strip():
            raise DashboardTransactionUnavailable("canonical project name is unavailable")
        return replace(request, project=name.strip())

    @staticmethod
    def _verification_request(
        request: TransactionRequest,
        sheet_request: TransactionRequest,
        row: AuthoritativeSheetRow,
    ) -> TransactionRequest:
        if request.scope != "project" or request.project is None or row.project is None:
            return sheet_request
        try:
            uuid.UUID(request.project)
        except (TypeError, ValueError):
            return sheet_request
        # The unique message id proves this is the authoritative row created for
        # the immutable UUID request. Preserve its historical display name when
        # a project is renamed after append.
        return replace(sheet_request, project=row.project)

    def record(
        self,
        payload: Mapping[str, Any],
        *,
        actor: Mapping[str, Any],
        message_id: str,
    ) -> dict[str, Any]:
        request = self.validate(payload)
        sheet_request = self._sheet_request(request)
        claim = self._store.claim(request, actor=actor, message_id=message_id)
        sheet_message_id = self._sheet_message_id(claim)

        if claim.status == "completed":
            return self._replay_completed(
                request,
                sheet_request,
                claim,
                sheet_message_id=sheet_message_id,
            )
        if claim.status != "claimed":
            raise DashboardTransactionConflict(f"write request has unsupported terminal status: {claim.status}")

        row = self._sheets.read_by_message_id(sheet_request, message_id=sheet_message_id)
        if not claim.claimed and row is None:
            raise DashboardTransactionConflict("write request is already in progress")
        if row is None:
            try:
                self._sheets.append(
                    sheet_request,
                    sender_name="Dashboard",
                    source="Dashboard",
                    message_id=sheet_message_id,
                )
            except Exception:
                # An append transport failure is ambiguous. Read authority before
                # deciding whether a retry may append again.
                row = self._sheets.read_by_message_id(sheet_request, message_id=sheet_message_id)
                if row is None:
                    raise
            if row is None:
                row = self._sheets.read_by_message_id(sheet_request, message_id=sheet_message_id)

        if row is None:
            raise DashboardTransactionUnavailable("authoritative Sheet row is missing after append")
        verification_request = self._verification_request(request, sheet_request, row)
        self._verify_row(verification_request, row, sheet_message_id=sheet_message_id)
        projection_status = "converged" if self._repair_projection(request, row) else "pending"
        response = {**self._completion_response(row), "projection_status": projection_status}
        self._store.complete(claim, response)
        return {**response, "duplicate": not claim.claimed}

    @staticmethod
    def _sheet_message_id(claim: DashboardWriteClaim) -> str:
        return f"dashboard:{claim.request_id}:{claim.request_hash}"

    def _replay_completed(
        self,
        request: TransactionRequest,
        sheet_request: TransactionRequest,
        claim: DashboardWriteClaim,
        *,
        sheet_message_id: str,
    ) -> dict[str, Any]:
        stored = claim.completion_response
        if not isinstance(stored, dict):
            raise DashboardTransactionConflict("completed request has no stored completion response")
        row = self._sheets.read_by_message_id(sheet_request, message_id=sheet_message_id)
        if row is None:
            raise DashboardTransactionConflict("completed request authoritative Sheet row is missing")
        verification_request = self._verification_request(request, sheet_request, row)
        self._verify_row(verification_request, row, sheet_message_id=sheet_message_id)
        expected = self._completion_response(row)
        stored_authority = {key: value for key, value in stored.items() if key != "projection_status"}
        if stored_authority != expected:
            raise DashboardTransactionConflict("stored completion response conflicts with authoritative Sheet row")
        projection_status = "converged" if self._repair_projection(request, row) else "pending"
        if stored.get("projection_status") != projection_status:
            stored = {**stored, "projection_status": projection_status}
            self._store.complete(claim, stored)
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

    def _repair_projection(self, request: TransactionRequest, row: AuthoritativeSheetRow) -> bool:
        project_id = None
        if request.scope == "project" and request.project:
            try:
                project_id = str(uuid.UUID(request.project))
            except (TypeError, ValueError):
                pass
        projection = {
            "project_id": project_id,
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
            "company": OPERASIONAL_SHEET_NAME if request.scope == "office" else request.company,
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
            return True
        except Exception as exc:
            secure_log(
                "WARNING",
                f"Dashboard transaction projection repair failed: {type(exc).__name__}: {exc}",
            )
            return False


class PostgresDashboardTransactionService:
    """Dashboard command boundary after PostgreSQL becomes cash authority."""

    def __init__(
        self,
        *,
        gateway: Any,
        project_exists: ProjectExists,
        project_uuid_exists: ProjectUuidExists,
        today: Today | None = None,
    ) -> None:
        self._gateway = gateway
        self._project_exists = project_exists
        self._project_uuid_exists = project_uuid_exists
        self._today = today

    def validate(self, payload: Mapping[str, Any]) -> TransactionRequest:
        def project_exists(project: str) -> bool:
            wallet = payload.get("wallet")
            company = payload.get("company")
            if not isinstance(wallet, str) or not isinstance(company, str):
                return False
            try:
                canonical_id = str(uuid.UUID(project))
            except (TypeError, ValueError):
                return False
            return canonical_id == project and self._project_uuid_exists(
                canonical_id, wallet, company
            )

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
        email = actor.get("email")
        role = actor.get("role")
        if not isinstance(email, str) or not email.strip() or role not in {"boss", "admin"}:
            raise DashboardTransactionUnavailable(
                "canonical dashboard actor is not authenticated"
            )
        occurred_at = datetime.combine(
            request.date,
            time.min,
            tzinfo=DASHBOARD_TIMEZONE,
        ).isoformat()
        command = {
            "kind": "transaction",
            "idempotency_key": request.idempotency_key,
            "scope": request.scope,
            "project_id": request.project if request.scope == "project" else None,
            "project_label": None,
            "wallet_label": request.wallet,
            "transaction_type": (
                "inflow" if request.direction == "Pemasukan" else "outflow"
            ),
            "amount": request.amount,
            "currency": "IDR",
            "category": request.category,
            "description": request.description,
            "occurred_at": occurred_at,
            "source": "dashboard",
            "source_reference": message_id,
            "evidence": {
                "company": request.company,
                "occurred_at_precision": "date",
            },
            "actor": {
                "id": email.strip().casefold(),
                "email": email.strip().casefold(),
                "role": role,
                "channel": "dashboard",
            },
        }
        result = self._gateway.dispatch(
            command,
            legacy_write=lambda: (_ for _ in ()).throw(
                DashboardTransactionUnavailable(
                    "Sheets fallback is forbidden after PostgreSQL activation"
                )
            ),
        )
        if result.get("status") == "quarantined":
            raise DashboardTransactionConflict(
                f"canonical dashboard command quarantined: {result.get('reason_code')}"
            )
        stored = result.get("result")
        if not isinstance(stored, Mapping):
            raise DashboardTransactionUnavailable(
                "canonical dashboard write has no readback"
            )
        transaction = stored.get("transaction")
        if not isinstance(transaction, Mapping):
            raise DashboardTransactionUnavailable(
                "canonical dashboard transaction readback is missing"
            )
        transaction_id = transaction.get("id")
        version = transaction.get("version")
        if not isinstance(transaction_id, str) or not isinstance(version, int):
            raise DashboardTransactionUnavailable(
                "canonical dashboard transaction identity is invalid"
            )
        return {
            "recorded": True,
            "authority": "postgresql",
            "transaction_id": transaction_id,
            "transaction_version": version,
            "duplicate": stored.get("duplicate") is True,
        }
