from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date

import pytest

from dashboard_api.write_contracts import TransactionValidationError, validate_transaction_request
from services.dashboard_transaction_service import (
    AuthoritativeSheetRow,
    DashboardTransactionConflict,
    DashboardTransactionService,
    GoogleSheetsTransactionAdapter,
    PostgresDashboardTransactionService,
)
from services.dashboard_write_requests import (
    DashboardWriteClaim,
    DashboardWriteRequestConflict,
)


TODAY = date(2026, 10, 2)


def valid_payload(**changes):
    payload = {
        "idempotency_key": "dashboard-request-0001",
        "date": TODAY.isoformat(),
        "scope": "project",
        "direction": "Pemasukan",
        "amount": 100_000,
        "description": "Pembayaran termin",
        "wallet": "CV HB(101)",
        "company": "HOLLA",
        "category": "Lain-lain",
        "project": "PROJECT-001",
    }
    payload.update(changes)
    return payload


def canonical_request(request):
    values = asdict(request)
    values["date"] = values["date"].isoformat()
    return values


class FakeStore:
    def __init__(self):
        self.claims = {}
        self.claim_calls = []
        self.complete_calls = []
        self.complete_failures = 0

    def claim(self, request, *, actor, message_id):
        self.claim_calls.append((request, dict(actor), message_id))
        canonical = canonical_request(request)
        request_json = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        request_hash = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        key_hash = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()
        existing = self.claims.get(key_hash)
        if existing:
            if existing.request_hash != request_hash or existing.canonical_request != canonical:
                raise DashboardWriteRequestConflict("different canonical request")
            return DashboardWriteClaim(**{**asdict(existing), "claimed": False})
        claim = DashboardWriteClaim(
            request_id=len(self.claims) + 1,
            idempotency_key_hash=key_hash,
            request_hash=request_hash,
            canonical_request=canonical,
            actor=dict(actor),
            message_id=message_id,
            status="claimed",
            completion_response=None,
            claimed=True,
        )
        self.claims[key_hash] = claim
        return claim

    def complete(self, claim, response, *, status="completed"):
        self.complete_calls.append((claim, dict(response), status))
        if self.complete_failures:
            self.complete_failures -= 1
            raise OSError("completion database unavailable")
        completed = DashboardWriteClaim(
            **{
                **asdict(claim),
                "status": status,
                "completion_response": dict(response),
                "claimed": False,
            }
        )
        self.claims[claim.idempotency_key_hash] = completed
        return completed


class FakeSheets:
    def __init__(self):
        self.rows = {}
        self.append_calls = []
        self.read_calls = []
        self.append_fail_after_write = False
        self.override_row = None

    def append(self, request, *, sender_name, source, message_id):
        self.append_calls.append((request, sender_name, source, message_id))
        row = make_authoritative_row(request, message_id, sender_name=sender_name, source=source)
        self.rows[message_id] = row
        if self.append_fail_after_write:
            raise TimeoutError("ambiguous Sheets timeout")
        return {"success": True, "row": row.sheet_row}

    def read_by_message_id(self, request, *, message_id):
        self.read_calls.append((request, message_id))
        if self.override_row is not None:
            return self.override_row
        return self.rows.get(message_id)


class FakeCanonicalGateway:
    def __init__(self, *, duplicate=False, quarantine_reason=None):
        self.duplicate = duplicate
        self.quarantine_reason = quarantine_reason
        self.calls = []

    def dispatch(self, command, *, legacy_write):
        self.calls.append((dict(command), legacy_write))
        if self.quarantine_reason:
            return {
                "authority": "postgresql",
                "status": "quarantined",
                "reason_code": self.quarantine_reason,
            }
        return {
            "authority": "postgresql",
            "status": "committed",
            "result": {
                "transaction": {
                    "id": "00000000-0000-4000-8000-000000000601",
                    "version": 1,
                },
                "duplicate": self.duplicate,
            },
        }


class FakeProjection:
    def __init__(self, *, fail=False):
        self.rows = []
        self.fail = fail

    def __call__(self, row):
        self.rows.append(dict(row))
        if self.fail:
            raise OSError("projection unavailable")
        return True


def make_authoritative_row(request, message_id, *, sender_name="Dashboard", source="Dashboard"):
    office = request.scope == "office"
    description = request.description
    # Adapter returns normalized description without the funding-wallet suffix.
    return AuthoritativeSheetRow(
        sheet_name="Operasional Kantor" if office else request.wallet,
        sheet_row=22,
        source_block="operasional" if office else request.direction.casefold(),
        message_id=message_id,
        transaction_date=request.date,
        direction=request.direction,
        amount=request.amount,
        description=description,
        wallet_reference="CV HB" if office else request.wallet,
        project=None if office else request.project,
        category=request.category if office else None,
        recorded_by=sender_name,
        input_source=source,
    )


def make_service(store=None, sheets=None, projection=None, *, project_uuid_exists=None, project_uuid_name=None):
    store = store or FakeStore()
    sheets = sheets or FakeSheets()
    projection = projection or FakeProjection()
    service = DashboardTransactionService(
        store=store,
        sheets=sheets,
        project_exists=lambda project, wallet, company: (project, wallet, company) == ("PROJECT-001", "CV HB(101)", "HOLLA"),
        project_uuid_exists=project_uuid_exists,
        project_uuid_name=project_uuid_name,
        projection_repair=projection,
        today=lambda: TODAY,
    )
    return service, store, sheets, projection


def test_strict_validation_happens_before_claim_or_sheet_access():
    service, store, sheets, _ = make_service()

    with pytest.raises(TransactionValidationError, match="amount:"):
        service.record(valid_payload(amount=0), actor={"role": "owner"}, message_id="http:1")

    assert store.claim_calls == []
    assert sheets.append_calls == []
    assert sheets.read_calls == []


def test_project_request_claims_appends_reads_back_completes_and_projects():
    service, store, sheets, projection = make_service()

    response = service.record(
        valid_payload(), actor={"email": "owner@example.com", "role": "owner"}, message_id="http:1"
    )

    assert len(store.claim_calls) == 1
    assert len(sheets.append_calls) == 1
    request, sender_name, source, sheet_message_id = sheets.append_calls[0]
    assert request.project == "PROJECT-001"
    assert sender_name == source == "Dashboard"
    assert sheet_message_id.startswith("dashboard:1:")
    assert response == {
        "recorded": True,
        "transaction_id": "sheet:CV HB(101):pemasukan:22",
        "sheet_name": "CV HB(101)",
        "sheet_row": 22,
        "source_block": "pemasukan",
        "sheet_message_id": sheet_message_id,
        "projection_status": "converged",
        "duplicate": False,
    }
    assert store.complete_calls[0][1] == {key: value for key, value in response.items() if key != "duplicate"}
    assert projection.rows[0]["sheet_name"] == "CV HB(101)"
    assert projection.rows[0]["company"] == "HOLLA"
    assert projection.rows[0]["kategori"] == "Lain-lain"


def test_uuid_project_uses_canonical_name_in_sheet_and_uuid_in_projection_with_alternate_pair():
    project_id = "00000000-0000-4000-8000-000000000001"
    probes = []
    service, store, sheets, projection = make_service(
        project_uuid_exists=lambda value, wallet, company: probes.append((value, wallet, company)) or value == project_id,
        project_uuid_name=lambda value: "Project Canonical" if value == project_id else None,
    )

    response = service.record(
        valid_payload(project=project_id, wallet="TX SBY(216)", company="TEXTURIN-Surabaya"),
        actor={"role": "owner"},
        message_id="http:uuid",
    )

    assert response["recorded"] is True
    assert probes == [(project_id, "TX SBY(216)", "TEXTURIN-Surabaya")]
    assert store.claim_calls[0][0].project == project_id
    assert sheets.append_calls[0][0].project == "Project Canonical"
    assert projection.rows[0]["nama_projek"] == "Project Canonical"
    assert projection.rows[0]["project_id"] == project_id


def test_office_request_uses_operational_authority_shape():
    service, store, sheets, projection = make_service()
    payload = valid_payload(
        scope="office",
        direction="Pengeluaran",
        category="Gaji",
    )
    payload.pop("project")

    response = service.record(payload, actor={"role": "owner"}, message_id="http:office")

    request = sheets.append_calls[0][0]
    assert request.scope == "office"
    assert response["sheet_name"] == "Operasional Kantor"
    assert response["source_block"] == "operasional"
    assert projection.rows[0]["keterangan"] == "Pembayaran termin [Sumber: CV HB]"
    assert projection.rows[0]["company"] == "Operasional Kantor"
    assert projection.rows[0]["company_sheet"] == "Operasional Kantor"
    assert projection.rows[0]["dompet_sheet"] == "CV HB(101)"
    assert store.complete_calls[0][2] == "completed"


def test_same_key_different_body_conflicts_before_any_second_sheet_access():
    service, _, sheets, _ = make_service()
    service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")
    reads_after_first = len(sheets.read_calls)

    with pytest.raises(DashboardWriteRequestConflict, match="different canonical request"):
        service.record(valid_payload(amount=200_000), actor={"role": "owner"}, message_id="http:2")

    assert len(sheets.append_calls) == 1
    assert len(sheets.read_calls) == reads_after_first


def test_non_owner_replay_never_appends_when_authoritative_row_is_absent():
    service, store, sheets, _ = make_service()
    request = service.validate(valid_payload())
    store.claim(request, actor={"role": "owner"}, message_id="http:first")

    with pytest.raises(DashboardTransactionConflict, match="already in progress"):
        service.record(valid_payload(), actor={"role": "owner"}, message_id="http:retry")

    assert sheets.append_calls == []


def test_non_owner_replay_reconciles_existing_authoritative_row_without_append():
    service, store, sheets, projection = make_service()
    request = service.validate(valid_payload())
    first = store.claim(request, actor={"role": "owner"}, message_id="http:first")
    sheet_message_id = service._sheet_message_id(first)
    sheets.rows[sheet_message_id] = make_authoritative_row(request, sheet_message_id)

    response = service.record(valid_payload(), actor={"role": "owner"}, message_id="http:retry")

    assert response["duplicate"] is True
    assert sheets.append_calls == []
    assert len(projection.rows) == 1


def test_authoritative_mismatch_fails_closed_without_completing():
    service, store, sheets, projection = make_service()
    original_append = sheets.append

    def append_wrong_amount(request, **kwargs):
        result = original_append(request, **kwargs)
        row = sheets.rows[kwargs["message_id"]]
        sheets.rows[kwargs["message_id"]] = AuthoritativeSheetRow(
            **{**asdict(row), "amount": row.amount + 1}
        )
        return result

    sheets.append = append_wrong_amount

    with pytest.raises(DashboardTransactionConflict, match="amount"):
        service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")

    assert store.complete_calls == []
    assert projection.rows == []


def test_replay_recovers_crash_after_sheet_append_without_duplicate():
    service, store, sheets, projection = make_service()
    store.complete_failures = 1

    with pytest.raises(OSError, match="completion database unavailable"):
        service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")
    assert len(sheets.append_calls) == 1

    response = service.record(valid_payload(), actor={"role": "owner"}, message_id="http:retry")

    assert response["recorded"] is True
    assert len(sheets.append_calls) == 1
    assert len(store.complete_calls) == 2
    # Projection repair is idempotent by deterministic Sheet message ID; retrying
    # after a completion-store crash is allowed to reconcile it again.
    assert len(projection.rows) == 2


def test_ambiguous_append_error_recovers_from_authoritative_readback():
    service, store, sheets, _ = make_service()
    sheets.append_fail_after_write = True

    response = service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")

    assert response["recorded"] is True
    assert len(sheets.append_calls) == 1
    assert len(store.complete_calls) == 1


def test_completed_replay_verifies_sheet_and_repairs_projection_without_append():
    service, _, sheets, projection = make_service()
    first = service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")
    projection.rows.clear()

    replay = service.record(valid_payload(), actor={"role": "owner"}, message_id="http:2")

    assert first["duplicate"] is False
    assert replay == {**first, "duplicate": True}
    assert len(sheets.append_calls) == 1
    assert len(projection.rows) == 1


def test_uuid_replay_survives_project_rename_without_changing_sheet_identity():
    project_id = "00000000-0000-4000-8000-000000000001"
    current = {"name": "Original Project"}
    service, _, sheets, projection = make_service(
        project_uuid_exists=lambda value, wallet, company: value == project_id,
        project_uuid_name=lambda _value: current["name"],
    )
    payload = valid_payload(project=project_id)
    first = service.record(payload, actor={"role": "owner"}, message_id="http:first")
    current["name"] = "Renamed Project"
    projection.rows.clear()

    replay = service.record(payload, actor={"role": "owner"}, message_id="http:retry")

    assert replay == {**first, "duplicate": True}
    assert len(sheets.append_calls) == 1
    assert sheets.append_calls[0][0].project == "Original Project"
    assert projection.rows[0]["nama_projek"] == "Original Project"
    assert projection.rows[0]["project_id"] == project_id


def test_projection_repair_failure_is_reported_without_undoing_sheet_authority():
    projection = FakeProjection(fail=True)
    service, store, _, _ = make_service(projection=projection)

    response = service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")

    assert response["recorded"] is True
    assert response["projection_status"] == "pending"
    assert len(store.complete_calls) == 1
    assert store.complete_calls[-1][1]["projection_status"] == "pending"
    assert len(projection.rows) == 1


def test_completed_replay_fails_closed_when_authoritative_row_disappears():
    service, _, sheets, _ = make_service()
    service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")
    sheets.rows.clear()

    with pytest.raises(DashboardTransactionConflict, match="missing"):
        service.record(valid_payload(), actor={"role": "owner"}, message_id="http:2")

    assert len(sheets.append_calls) == 1


def test_google_sheets_adapter_calls_existing_append_helpers_without_queue(monkeypatch):
    import sheets_helper

    project_calls = []
    office_calls = []
    monkeypatch.setattr(
        sheets_helper,
        "append_project_transaction",
        lambda **kwargs: project_calls.append(kwargs) or {"success": True, "row": 9},
    )
    monkeypatch.setattr(
        sheets_helper,
        "append_operational_transaction",
        lambda **kwargs: office_calls.append(kwargs) or {"success": True, "row": 2},
    )
    adapter = GoogleSheetsTransactionAdapter()
    service, _, _, _ = make_service()
    project = service.validate(valid_payload())
    office_payload = valid_payload(scope="office", direction="Pengeluaran", category="Gaji")
    office_payload.pop("project")
    office = service.validate(office_payload)

    adapter.append(project, sender_name="Dashboard", source="Dashboard", message_id="dashboard:1:a")
    adapter.append(office, sender_name="Dashboard", source="Dashboard", message_id="dashboard:2:b")

    assert project_calls[0]["allow_queue"] is False
    assert project_calls[0]["dompet_sheet"] == "CV HB(101)"
    assert project_calls[0]["project_name"] == "PROJECT-001"
    assert project_calls[0]["transaction"]["kategori"] == "Lain-lain"
    assert office_calls[0]["allow_queue"] is False
    assert office_calls[0]["source_wallet"] == "CV HB(101)"
    assert office_calls[0]["category"] == "Gaji"


def test_receipt_authority_reader_uses_exact_message_identity_and_allows_same_sheet_row_move(monkeypatch):
    import sheets_helper
    from config.constants import SPLIT_PEMASUKAN

    project_id = "00000000-0000-4000-8000-000000000001"
    message_id = "dashboard:receipt:0001"
    source_key = f"message:CV HB(101):pemasukan:{message_id}"
    values = ["" for _ in range(18)]
    values[SPLIT_PEMASUKAN["NO"] - 1] = "7"
    values[SPLIT_PEMASUKAN["WAKTU"] - 1] = "09:15:00"
    values[SPLIT_PEMASUKAN["TANGGAL"] - 1] = TODAY.isoformat()
    values[SPLIT_PEMASUKAN["JUMLAH"] - 1] = "100000"
    values[SPLIT_PEMASUKAN["PROJECT"] - 1] = project_id
    values[SPLIT_PEMASUKAN["KETERANGAN"] - 1] = "Pembayaran termin"
    values[SPLIT_PEMASUKAN["OLEH"] - 1] = "Dashboard"
    values[SPLIT_PEMASUKAN["SOURCE"] - 1] = "Dashboard"
    values[SPLIT_PEMASUKAN["MESSAGE_ID"] - 1] = message_id

    class FakeWorksheet:
        def col_values(self, column):
            assert column == SPLIT_PEMASUKAN["MESSAGE_ID"]
            return [""] * 8 + [message_id]

        def row_values(self, row):
            assert row == 9
            return values

    class FakeSpreadsheet:
        def worksheet(self, wallet):
            assert wallet == "CV HB(101)"
            return FakeWorksheet()

    monkeypatch.setattr(sheets_helper, "get_spreadsheet", lambda: FakeSpreadsheet())
    observed = GoogleSheetsTransactionAdapter.read_receipt_authority(
        {
            "source_key": source_key,
            "source_sheet": "CV HB(101)",
            "source_row": 7,
            "source_block": "pemasukan",
            "message_id": message_id,
        },
        {"id": project_id, "wallet": "CV HB(101)", "company": "HOLLA"},
    )

    assert observed["source_key"] == source_key
    assert observed["observed_source_row"] == 9
    assert observed["amount"] == 100_000
    assert observed["project_id"] == project_id
    assert observed["wallet"] == "CV HB(101)"
    assert observed["company"] == "HOLLA"
    assert len(observed["raw_cells_sha256"]) == 64


def test_receipt_authority_reader_recomputes_manual_source_fingerprint_from_raw_cells(monkeypatch):
    import sheets_helper
    from config.constants import SPLIT_PEMASUKAN
    from services.ledger_store import build_source_key

    project_id = "00000000-0000-4000-8000-000000000001"
    values = ["" for _ in range(18)]
    values[SPLIT_PEMASUKAN["TANGGAL"] - 1] = "03/11/2026"
    values[SPLIT_PEMASUKAN["JUMLAH"] - 1] = "Rp 100.000"
    values[SPLIT_PEMASUKAN["PROJECT"] - 1] = project_id
    values[SPLIT_PEMASUKAN["KETERANGAN"] - 1] = "Pembayaran manual"
    source_key = build_source_key(
        {
            "sheet_name": "CV HB(101)",
            "sheet_row": 9,
            "source_block": "pemasukan",
            "message_id": "",
            "tanggal": "03/11/2026",
            "jumlah": "Rp 100.000",
            "keterangan": "Pembayaran manual",
            "nama_projek": project_id,
        }
    )

    class FakeWorksheet:
        def row_values(self, row):
            assert row == 9
            return values

    class FakeSpreadsheet:
        def worksheet(self, wallet):
            assert wallet == "CV HB(101)"
            return FakeWorksheet()

    monkeypatch.setattr(sheets_helper, "get_spreadsheet", lambda: FakeSpreadsheet())
    observed = GoogleSheetsTransactionAdapter.read_receipt_authority(
        {
            "source_key": source_key,
            "source_sheet": "CV HB(101)",
            "source_row": 9,
            "source_block": "pemasukan",
            "message_id": None,
        },
        {"id": project_id, "wallet": "CV HB(101)", "company": "HOLLA"},
    )

    assert observed["source_key"] == source_key
    assert observed["amount"] == 100_000
    assert observed["transaction_date"] == "2026-11-03"


def test_receipt_authority_reader_fails_closed_on_duplicate_missing_or_api_failure(monkeypatch):
    import sheets_helper
    from config.constants import SPLIT_PEMASUKAN
    from services.project_document_repository import (
        ProjectDocumentConflict,
        ProjectDocumentUnavailable,
    )

    project_id = "00000000-0000-4000-8000-000000000001"
    message_id = "dashboard:receipt:0002"
    locator = {
        "source_key": f"message:CV HB(101):pemasukan:{message_id}",
        "source_sheet": "CV HB(101)",
        "source_row": 7,
        "source_block": "pemasukan",
        "message_id": message_id,
    }
    project = {"id": project_id, "wallet": "CV HB(101)", "company": "HOLLA"}

    class DuplicateWorksheet:
        def col_values(self, column):
            assert column == SPLIT_PEMASUKAN["MESSAGE_ID"]
            return [message_id, message_id]

    class FakeSpreadsheet:
        def __init__(self, worksheet):
            self._worksheet = worksheet

        def worksheet(self, _wallet):
            return self._worksheet

    monkeypatch.setattr(
        sheets_helper,
        "get_spreadsheet",
        lambda: FakeSpreadsheet(DuplicateWorksheet()),
    )
    with pytest.raises(ProjectDocumentConflict, match="ambiguous"):
        GoogleSheetsTransactionAdapter.read_receipt_authority(locator, project)

    class MissingWorksheet:
        def col_values(self, _column):
            return [f"{message_id}:component"]

    monkeypatch.setattr(
        sheets_helper,
        "get_spreadsheet",
        lambda: FakeSpreadsheet(MissingWorksheet()),
    )
    with pytest.raises(ProjectDocumentConflict, match="no longer exists"):
        GoogleSheetsTransactionAdapter.read_receipt_authority(locator, project)

    from gspread import WorksheetNotFound

    class MissingSpreadsheet:
        def worksheet(self, _wallet):
            raise WorksheetNotFound("missing")

    monkeypatch.setattr(
        sheets_helper,
        "get_spreadsheet",
        lambda: MissingSpreadsheet(),
    )
    with pytest.raises(ProjectDocumentConflict, match="wallet Sheet no longer exists"):
        GoogleSheetsTransactionAdapter.read_receipt_authority(locator, project)

    def unavailable():
        raise TimeoutError("credential detail")

    monkeypatch.setattr(sheets_helper, "get_spreadsheet", unavailable)
    with pytest.raises(ProjectDocumentUnavailable, match="temporarily unavailable") as raised:
        GoogleSheetsTransactionAdapter.read_receipt_authority(locator, project)
    assert "credential detail" not in str(raised.value)


def test_google_sheets_adapter_reads_exact_project_row(monkeypatch):
    import sheets_helper
    from config.constants import SPLIT_PEMASUKAN

    values = ["" for _ in range(18)]
    values[SPLIT_PEMASUKAN["NO"] - 1] = "7"
    values[SPLIT_PEMASUKAN["WAKTU"] - 1] = "09:15:00"
    values[SPLIT_PEMASUKAN["TANGGAL"] - 1] = TODAY.isoformat()
    values[SPLIT_PEMASUKAN["JUMLAH"] - 1] = "100000"
    values[SPLIT_PEMASUKAN["PROJECT"] - 1] = "PROJECT-001"
    values[SPLIT_PEMASUKAN["KETERANGAN"] - 1] = "Pembayaran termin"
    values[SPLIT_PEMASUKAN["OLEH"] - 1] = "Dashboard"
    values[SPLIT_PEMASUKAN["SOURCE"] - 1] = "Dashboard"
    values[SPLIT_PEMASUKAN["MESSAGE_ID"] - 1] = "dashboard:1:a"

    class FakeWorksheet:
        title = "CV HB(101)"

        def col_values(self, column):
            assert column == SPLIT_PEMASUKAN["MESSAGE_ID"]
            return [""] * 8 + ["dashboard:1:a"]

        def row_values(self, row):
            assert row == 9
            return values

    monkeypatch.setattr(sheets_helper, "get_dompet_sheet", lambda _wallet: FakeWorksheet())
    service, _, _, _ = make_service()
    request = service.validate(valid_payload())

    row = GoogleSheetsTransactionAdapter().read_by_message_id(request, message_id="dashboard:1:a")

    assert row == AuthoritativeSheetRow(
        sheet_name="CV HB(101)",
        sheet_row=9,
        source_block="pemasukan",
        message_id="dashboard:1:a",
        transaction_date=TODAY,
        direction="Pemasukan",
        amount=100_000,
        description="Pembayaran termin",
        wallet_reference="CV HB(101)",
        project="PROJECT-001",
        category=None,
        recorded_by="Dashboard",
        input_source="Dashboard",
    )


def test_google_sheets_adapter_rejects_duplicate_authority_message_ids(monkeypatch):
    import sheets_helper

    class DuplicateWorksheet:
        def col_values(self, _column):
            return ["MessageID", "dashboard:1:a", "dashboard:1:a"]

    monkeypatch.setattr(sheets_helper, "get_dompet_sheet", lambda _wallet: DuplicateWorksheet())
    service, _, _, _ = make_service()
    request = service.validate(valid_payload())

    with pytest.raises(DashboardTransactionConflict, match="multiple authoritative"):
        GoogleSheetsTransactionAdapter().read_by_message_id(request, message_id="dashboard:1:a")


def test_google_sheets_adapter_forwards_validated_transaction_date(monkeypatch):
    captured = {}

    def fake_append_project_transaction(**kwargs):
        captured.update(kwargs)
        return {"success": True, "row": 9}

    monkeypatch.setattr("sheets_helper.append_project_transaction", fake_append_project_transaction)
    request = validate_transaction_request(
        valid_payload(),
        project_exists=lambda _project: True,
        today=lambda: TODAY,
    )

    GoogleSheetsTransactionAdapter().append(
        request,
        sender_name="Dashboard",
        source="Dashboard",
        message_id="dashboard:1:hash",
    )

    assert captured["transaction_date"] == TODAY


def make_postgres_service(gateway=None):
    gateway = gateway or FakeCanonicalGateway()
    project_id = "00000000-0000-4000-8000-000000000501"
    service = PostgresDashboardTransactionService(
        gateway=gateway,
        project_exists=lambda _project, _wallet, _company: False,
        project_uuid_exists=lambda value, wallet, company: (
            value == project_id
            and wallet == "CV HB(101)"
            and company == "HOLLA"
        ),
        today=lambda: TODAY,
    )
    return service, gateway, project_id


def test_postgres_dashboard_owner_session_maps_to_canonical_boss_actor():
    service, gateway, project_id = make_postgres_service()

    service.record(
        valid_payload(project=project_id),
        actor={"email": "Owner@Example.com", "role": "owner"},
        message_id="dashboard-api:owner",
    )

    command, _legacy_write = gateway.calls[0]
    assert command["actor"] == {
        "id": "owner@example.com",
        "email": "owner@example.com",
        "role": "boss",
        "channel": "dashboard",
    }


def test_postgres_dashboard_path_uses_canonical_id_and_never_sheets_shape():
    service, gateway, project_id = make_postgres_service()

    result = service.record(
        valid_payload(project=project_id),
        actor={"email": "Boss@Example.com", "role": "boss"},
        message_id="dashboard-api:canonical",
    )

    command, legacy_write = gateway.calls[0]
    assert command["project_id"] == project_id
    assert command["wallet_label"] == "CV HB(101)"
    assert "business_unit_id" not in command
    assert command["occurred_at"] == "2026-10-02T00:00:00+07:00"
    assert command["evidence"] == {
        "company": "HOLLA",
        "occurred_at_precision": "date",
    }
    assert command["actor"] == {
        "id": "boss@example.com",
        "email": "boss@example.com",
        "role": "boss",
        "channel": "dashboard",
    }
    with pytest.raises(Exception, match="Sheets fallback is forbidden"):
        legacy_write()
    assert result == {
        "recorded": True,
        "authority": "postgresql",
        "transaction_id": "00000000-0000-4000-8000-000000000601",
        "transaction_version": 1,
        "duplicate": False,
    }
    assert "sheet_row" not in result


def test_postgres_dashboard_rejects_project_label_and_quarantine():
    service, gateway, _project_id = make_postgres_service(
        FakeCanonicalGateway(quarantine_reason="unmapped_project")
    )

    with pytest.raises(TransactionValidationError, match="project:"):
        service.record(
            valid_payload(project="PROJECT-001"),
            actor={"email": "boss@example.com", "role": "boss"},
            message_id="dashboard-api:label",
        )
    assert gateway.calls == []


def test_postgres_dashboard_rejects_unauthenticated_actor_before_dispatch():
    service, gateway, project_id = make_postgres_service()

    with pytest.raises(Exception, match="actor is not authenticated"):
        service.record(
            valid_payload(project=project_id),
            actor={"role": "boss"},
            message_id="dashboard-api:no-actor",
        )
    assert gateway.calls == []


def test_postgres_dashboard_propagates_duplicate_readback():
    service, _gateway, project_id = make_postgres_service(
        FakeCanonicalGateway(duplicate=True)
    )

    result = service.record(
        valid_payload(project=project_id),
        actor={"email": "boss@example.com", "role": "admin"},
        message_id="dashboard-api:duplicate",
    )

    assert result["duplicate"] is True
