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


def make_service(store=None, sheets=None, projection=None):
    store = store or FakeStore()
    sheets = sheets or FakeSheets()
    projection = projection or FakeProjection()
    service = DashboardTransactionService(
        store=store,
        sheets=sheets,
        project_exists=lambda project: project == "PROJECT-001",
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
    }
    assert store.complete_calls[0][1] == response
    assert projection.rows[0]["sheet_name"] == "CV HB(101)"
    assert projection.rows[0]["company"] == "HOLLA"
    assert projection.rows[0]["kategori"] == "Lain-lain"


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
    assert store.complete_calls[0][2] == "completed"


def test_same_key_different_body_conflicts_before_any_second_sheet_access():
    service, _, sheets, _ = make_service()
    service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")
    reads_after_first = len(sheets.read_calls)

    with pytest.raises(DashboardWriteRequestConflict, match="different canonical request"):
        service.record(valid_payload(amount=200_000), actor={"role": "owner"}, message_id="http:2")

    assert len(sheets.append_calls) == 1
    assert len(sheets.read_calls) == reads_after_first


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
    assert len(projection.rows) == 1


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

    assert replay == first
    assert len(sheets.append_calls) == 1
    assert len(projection.rows) == 1


def test_projection_repair_is_best_effort_after_authority_is_verified():
    projection = FakeProjection(fail=True)
    service, store, _, _ = make_service(projection=projection)

    response = service.record(valid_payload(), actor={"role": "owner"}, message_id="http:1")

    assert response["recorded"] is True
    assert len(store.complete_calls) == 1
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
