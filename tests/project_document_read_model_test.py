from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

import services.project_document_repository as repository_module
from services.project_document_repository import ProjectDocumentRepository


PROJECT_ID = "00000000-0000-4000-8000-000000000101"
DOCUMENT_ID = "00000000-0000-4000-8000-000000000201"
LINE_ID = "00000000-0000-4000-8000-000000000301"
ALLOCATION_ID = "00000000-0000-4000-8000-000000000401"
NOW = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


def _document() -> dict[str, object]:
    return {
        "id": DOCUMENT_ID,
        "project_id": PROJECT_ID,
        "issuer_key": "cv-holla-berkreasi",
        "document_type": "invoice",
        "invoice_kind": "DP",
        "applies_to_invoice_id": None,
        "status": "draft",
        "official_number": None,
        "issue_date": date(2026, 11, 21),
        "due_date": date(2026, 11, 28),
        "valid_until": None,
        "document_discount_amount": 0,
        "document_discount_percent": Decimal("0"),
        "tax_percent": Decimal("0"),
        "notes": "",
        "payment_terms": "",
        "prepared_by": "",
        "client_signatory": "",
        "project_image_url": None,
        "template_key": "HOLLAWALL",
        "template_version": "commercial-v3",
        "payment_profile_key": "hollawall",
        "immutable_snapshot": None,
        "snapshot_sha256": None,
        "renderer_version": None,
        "revision_of_id": None,
        "superseded_by_id": None,
        "void_reason": None,
        "lock_version": 1,
        "issued_at": None,
        "voided_at": None,
        "superseded_at": None,
        "created_by": {"role": "boss"},
        "updated_by": {"role": "boss"},
        "created_at": NOW,
        "updated_at": NOW,
    }


def _document_row() -> tuple[object, ...]:
    document = _document()
    return tuple(document[column] for column in repository_module._DOCUMENT_COLUMNS)


LINE = {
    "id": LINE_ID,
    "position": 1,
    "description": "Mural",
    "quantity": "2.5",
    "unit": "m²",
    "unit_price": 100_000,
    "line_discount_percent": "0",
    "line_gross": 250_000,
    "line_discount": 0,
    "line_total": 250_000,
    "commercial_meta": {"pricing_mode": "area_rate"},
}
ALLOCATION = {
    "id": ALLOCATION_ID,
    "ledger_source_key": "canonical:payment-1",
    "amount": 100_000,
    "ledger_amount": 100_000,
    "ledger_snapshot": {"source": "canonical"},
    "created_at": str(NOW),
}


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, _params=None):
        self.query = " ".join(str(query).split())
        self.connection.calls.append(self.query)

    def fetchone(self):
        if self.query.startswith("SELECT 1 FROM projects"):
            return (1,)
        raise AssertionError(f"unexpected fetchone query: {self.query}")

    def fetchall(self):
        if self.query.startswith("SELECT id, project_id"):
            return [_document_row()]
        if "SELECT line.document_id" in self.query:
            return [(
                DOCUMENT_ID,
                LINE["id"], LINE["position"], LINE["description"],
                Decimal(LINE["quantity"]), LINE["unit"], LINE["unit_price"],
                Decimal(LINE["line_discount_percent"]), LINE["line_gross"],
                LINE["line_discount"], LINE["line_total"], LINE["commercial_meta"],
            )]
        if "SELECT allocation.document_id" in self.query:
            return [(
                DOCUMENT_ID,
                ALLOCATION["id"], ALLOCATION["ledger_source_key"],
                ALLOCATION["amount"], ALLOCATION["ledger_amount"],
                ALLOCATION["ledger_snapshot"], NOW,
            )]
        if "SELECT id, document_type" in self.query:
            return [
                (
                    DOCUMENT_ID,
                    "sales_order",
                    None,
                    "SO/HW/2026/000001",
                    None,
                    {"totals": {"total": 1_000_000}},
                ),
                (
                    "00000000-0000-4000-8000-000000000202",
                    "invoice",
                    "DP",
                    "INV/HW/2026/000001",
                    date(2026, 11, 28),
                    {"totals": {"total": 400_000}},
                ),
            ]
        if "SELECT receipt.applies_to_invoice_id" in self.query:
            return [("00000000-0000-4000-8000-000000000202", 100_000)]
        raise AssertionError(f"unexpected fetchall query: {self.query}")


class _Connection:
    def __init__(self) -> None:
        self.autocommit = False
        self.calls: list[str] = []
        self.pipeline_entries = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @contextmanager
    def pipeline(self):
        self.pipeline_entries += 1
        yield object()

    def cursor(self):
        return _Cursor(self)


def _repository(connection: _Connection) -> ProjectDocumentRepository:
    return ProjectDocumentRepository(
        "postgresql://isolated-test",
        connection_factory=lambda _dsn: connection,
    )


def test_list_documents_uses_one_pipeline_round_trip_and_preserves_nested_records() -> None:
    connection = _Connection()

    documents = _repository(connection).list_documents(PROJECT_ID)

    assert connection.pipeline_entries == 1
    assert connection.autocommit is True
    assert len(connection.calls) == 3
    assert documents[0]["id"] == DOCUMENT_ID
    assert documents[0]["issue_date"] == "2026-11-21"
    assert documents[0]["lines"] == [LINE]
    assert documents[0]["allocations"] == [ALLOCATION]


def test_payment_summary_uses_one_pipeline_round_trip_and_preserves_totals() -> None:
    connection = _Connection()

    summary = _repository(connection).get_project_payment_summary(PROJECT_ID)

    assert connection.pipeline_entries == 1
    assert connection.autocommit is True
    assert len(connection.calls) == 3
    assert summary["contract_total"] == 1_000_000
    assert summary["invoiced_total"] == 400_000
    assert summary["paid_total"] == 100_000
    assert summary["contract_outstanding"] == 900_000
    assert summary["invoices"] == [{
        "invoice_id": "00000000-0000-4000-8000-000000000202",
        "invoice_kind": "DP",
        "official_number": "INV/HW/2026/000001",
        "due_date": "2026-11-28",
        "invoice_total": 400_000,
        "paid_total": 100_000,
        "outstanding": 300_000,
        "payment_status": "PARTIALLY_PAID",
    }]


class _EmptyReadCursor(_Cursor):
    def fetchone(self):
        if "FROM projects WHERE id = %s" in self.query:
            project = {
                "id": PROJECT_ID,
                "name": "Project read model",
                "client_name": "Client",
                "client_company": None,
                "client_address": None,
                "client_contact": None,
                "issuer_key": "cv-holla-berkreasi",
                "wallet": "CV HB(101)",
                "company": "HOLLA",
                "status": "active",
                "start_date": date(2026, 11, 21),
                "completion_date": None,
                "contract_notes": None,
                "lock_version": 1,
                "created_by": {"role": "boss"},
                "updated_by": {"role": "boss"},
                "created_at": NOW,
                "updated_at": NOW,
            }
            return tuple(project[column] for column in repository_module._PROJECT_COLUMNS)
        return super().fetchone()

    def fetchall(self):
        return []


class _EmptyReadConnection(_Connection):
    def cursor(self):
        return _EmptyReadCursor(self)


def test_get_project_uses_autocommit_read() -> None:
    connection = _EmptyReadConnection()

    project = _repository(connection).get_project(PROJECT_ID)

    assert project["id"] == PROJECT_ID
    assert connection.autocommit is True


def test_project_and_quotation_collections_use_autocommit_reads() -> None:
    for operation in (
        lambda repository: repository.list_projects(),
        lambda repository: repository.list_project_quotations(PROJECT_ID),
    ):
        connection = _EmptyReadConnection()

        assert operation(_repository(connection)) == []
        assert connection.autocommit is True
