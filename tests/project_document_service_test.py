from decimal import Decimal

import pytest

from services.project_document_models import DocumentCalculationError
from services.project_documents import ProjectDocumentService, calculate_document_totals


def test_calculate_document_totals_uses_decimal_half_up_integer_idr():
    totals = calculate_document_totals(
        [
            {
                "description": "Panel",
                "quantity": "2.555",
                "unit": "m2",
                "unit_price": 1001,
                "line_discount_percent": "10",
            },
            {
                "description": "Print",
                "quantity": "1",
                "unit": "unit",
                "unit_price": 444,
                "line_discount_percent": "0",
            },
        ],
        document_discount_percent="5",
        tax_percent="11",
    )

    assert totals["lines"][0] == {
        "description": "Panel",
        "quantity": "2.555",
        "unit": "m2",
        "unit_price": 1001,
        "line_discount_percent": "10",
        "line_gross": 2558,
        "line_discount": 256,
        "line_total": 2302,
    }
    assert totals["subtotal"] == 2746
    assert totals["document_discount"] == 137
    assert totals["taxable_base"] == 2609
    assert totals["tax"] == 287
    assert totals["total"] == 2896


def test_calculate_document_totals_rejects_mixed_document_discounts_and_bad_money():
    line = {"description": "Wall", "quantity": "1", "unit": "unit", "unit_price": 100}

    with pytest.raises(DocumentCalculationError, match="never both"):
        calculate_document_totals(
            [line],
            document_discount_amount=1,
            document_discount_percent="1",
        )
    with pytest.raises(DocumentCalculationError, match="integer rupiah"):
        calculate_document_totals([{**line, "unit_price": Decimal("100.5")}])
    with pytest.raises(DocumentCalculationError, match="taxable base"):
        calculate_document_totals([line], document_discount_amount=101)


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.project = {
            "id": "00000000-0000-4000-8000-000000000001",
            "name": "Expo",
            "status": "planned",
            "issuer_key": "hollawall",
            "lock_version": 1,
        }
        self.document = {
            "id": "00000000-0000-4000-8000-000000000002",
            "project_id": self.project["id"],
            "document_type": "invoice",
            "invoice_kind": "DP",
            "status": "draft",
            "lock_version": 1,
            "lines": [],
            "allocations": [],
        }

    def create_project_with_sales_order(self, values, **kwargs):
        self.calls.append(("create_project_with_sales_order", values, kwargs))
        return {
            "project": {**self.project, **values},
            "sales_order": {
                "id": "00000000-0000-4000-8000-000000000003",
                "document_type": "sales_order",
                "status": "draft",
                "valid_until": "2026-11-17",
                "tax_percent": values["tax_percent"],
                "lock_version": 1,
            },
        }

    def get_project(self, project_id):
        assert project_id == self.project["id"]
        return dict(self.project)

    def create_document_draft(self, project_id, **kwargs):
        self.calls.append(("create_document_draft", project_id, kwargs))
        return {
            **self.document,
            **kwargs["values"],
            "document_type": kwargs["document_type"],
            "due_date": kwargs["values"].get("due_date") or "2026-11-10",
        }

    def create_invoice_draft(self, project_id, **kwargs):
        self.calls.append(("create_invoice_draft", project_id, kwargs))
        values = dict(kwargs["values"])
        if values["invoice_kind"] == "FINAL":
            values["lines"] = [{
                "description": "Pelunasan akhir",
                "quantity": "1",
                "unit": "termin",
                "unit_price": 400_000,
                "line_discount_percent": "0",
                "line_gross": 400_000,
                "line_discount": 0,
                "line_total": 400_000,
            }]
        return {
            **self.document,
            **values,
            "document_type": "invoice",
            "due_date": values.get("due_date") or "2026-11-10",
        }

    def create_receipt_draft(self, project_id, **kwargs):
        self.calls.append(("create_receipt_draft", project_id, kwargs))
        return {
            **self.document,
            "document_type": "receipt",
            "invoice_kind": None,
            "allocations": kwargs["allocations"],
        }

    def get_project_commercial_totals(self, project_id):
        return {"contract_total": 1_000_000, "invoiced_non_final": 600_000}

    def update_draft(self, document_id, changes, **kwargs):
        self.calls.append(("update_draft", document_id, changes, kwargs))
        return {**self.document, **changes, "lock_version": kwargs["expected_version"] + 1}

    def get_document(self, document_id):
        return {
            **self.document,
            "id": document_id,
            "lines": [
                {
                    "description": "Backdrop",
                    "quantity": "1",
                    "unit": "unit",
                    "unit_price": 500000,
                    "line_discount_percent": "0",
                    "line_gross": 500000,
                    "line_discount": 0,
                    "line_total": 500000,
                }
            ],
        }

    def get_issuer_profile(self, issuer_key):
        return {"issuer_key": issuer_key, "legal_name": "CV Holla Berkreasi"}

    def issue_document(self, document_id, **kwargs):
        self.calls.append(("issue_document", document_id, kwargs))
        return {**self.document, "status": "issued", "official_number": "INV/HW/2026/000001"}

    def void_document(self, document_id, **kwargs):
        self.calls.append(("void_document", document_id, kwargs))
        return {**self.document, "status": "void", "void_reason": kwargs["reason"]}

    def revise_document(self, document_id, **kwargs):
        self.calls.append(("revise_document", document_id, kwargs))
        return {**self.document, "revision_of_id": document_id}

    def replay_audit(self, **kwargs):
        self.calls.append(("replay_audit", kwargs))
        return [{"event_type": "document.issued"}]


def service(repository=None):
    repository = repository or FakeRepository()
    return ProjectDocumentService(repository), repository


def test_create_project_leaves_volatile_defaults_to_atomic_repository_command():
    subject, repository = service()

    result = subject.create_project(
        {"name": "Expo", "client_name": "Client", "issuer_key": "hollawall"},
        idempotency_key="project-command-0001",
        actor={"email": "owner@example.com"},
    )

    assert result["sales_order"]["valid_until"] == "2026-11-17"
    assert result["sales_order"]["tax_percent"] == "0"
    assert "sales_order_valid_until" not in repository.calls[0][1]
    assert [call[0] for call in repository.calls] == ["create_project_with_sales_order"]


def test_invoice_leaves_due_date_and_status_validation_to_atomic_repository_command():
    subject, repository = service()

    invoice = subject.create_invoice(
        repository.project["id"],
        kind="FINAL",
        values={"notes": "Pelunasan"},
        idempotency_key="invoice-command-0001",
        actor={"email": "owner@example.com"},
    )

    call = repository.calls[-1]
    assert call[0] == "create_invoice_draft"
    assert "due_date" not in call[2]["values"]
    assert call[2]["values"]["tax_percent"] == "0"
    assert call[2]["values"]["invoice_kind"] == "FINAL"
    assert "lines" not in call[2]["values"]
    assert invoice["lines"][0]["line_total"] == 400_000
    assert invoice["due_date"] == "2026-11-10"
    assert invoice["invoice_kind"] == "FINAL"
    assert not any(item[0] == "get_project" for item in repository.calls)


def test_invoice_status_is_not_prechecked_outside_repository_transaction():
    repository = FakeRepository()
    repository.project["status"] = "completed"
    subject, _ = service(repository)

    subject.create_invoice(
        repository.project["id"],
        kind="DP",
        values={"lines": [{"description": "DP", "quantity": "1", "unit": "unit", "unit_price": 1}]},
        idempotency_key="invoice-command-0002",
        actor={"email": "owner@example.com"},
    )

    assert not any(item[0] == "get_project" for item in repository.calls)
    assert repository.calls[-1][0] == "create_invoice_draft"


def test_receipt_creation_delegates_atomic_allocation_revalidation():
    subject, repository = service()

    result = subject.create_receipt(
        repository.project["id"],
        allocations=[{"ledger_source_key": "sheet:income:42", "amount": 300000}],
        values={"notes": "Diterima"},
        idempotency_key="receipt-command-0001",
        actor={"email": "owner@example.com"},
    )

    assert result["document_type"] == "receipt"
    call = repository.calls[-1]
    assert call[0] == "create_receipt_draft"
    assert call[2]["allocations"] == [{"ledger_source_key": "sheet:income:42", "amount": 300000}]


def test_issue_delegates_atomic_canonical_rendering_to_repository():
    subject, repository = service()
    issued = subject.issue_document(
        repository.document["id"],
        expected_version=1,
        idempotency_key="issue-command-0001",
        actor={"email": "owner@example.com"},
    )

    assert issued["status"] == "issued"
    call = repository.calls[-1]
    assert call[0] == "issue_document"
    assert call[1] == repository.document["id"]
    assert call[2] == {
        "expected_version": 1,
        "idempotency_key": "issue-command-0001",
        "actor": {"email": "owner@example.com"},
    }
    assert "snapshot" not in call[2]
    assert "pdf_bytes" not in call[2]
    assert "pdf_renderer" not in call[2]


def test_service_does_not_generate_issue_time_before_repository_idempotency_claim():
    repository = FakeRepository()
    subject = ProjectDocumentService(repository)

    subject.issue_document(
        repository.document["id"],
        expected_version=1,
        idempotency_key="issue-command-default-clock-0001",
        actor={"email": "owner@example.com"},
    )

    assert "issued_at" not in repository.calls[-1][2]


def test_void_revision_and_replay_are_explicit_lifecycle_commands():
    subject, repository = service()

    voided = subject.void_document(
        repository.document["id"],
        reason="Cancelled by client",
        expected_version=1,
        idempotency_key="void-command-0001",
        actor={"email": "owner@example.com"},
    )
    revision = subject.revise_document(
        repository.document["id"],
        expected_version=1,
        idempotency_key="revise-command-0001",
        actor={"email": "owner@example.com"},
    )
    events = subject.replay_audit(document_id=repository.document["id"])

    assert voided["status"] == "void"
    assert revision["revision_of_id"] == repository.document["id"]
    assert events == [{"event_type": "document.issued"}]
