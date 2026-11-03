from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.dashboard_transaction_service import DashboardTransactionService
from services.project_document_repository import ProjectDocumentConflict, ProjectDocumentRepository
from services.project_documents import ProjectDocumentService


class ValidationStore:
    def claim(self, *args, **kwargs):  # pragma: no cover - validation test only
        raise AssertionError("record was not expected")


class ValidationSheets:
    pass


def test_dashboard_transaction_validation_accepts_authoritative_project_uuid():
    seen = []
    service = DashboardTransactionService(
        store=ValidationStore(),
        sheets=ValidationSheets(),
        project_exists=lambda project, wallet, company: False,
        project_uuid_exists=lambda project_id, wallet, company: seen.append((project_id, wallet, company)) or True,
        today=lambda: date(2026, 11, 3),
    )
    project_id = "00000000-0000-4000-8000-000000000001"

    request = service.validate(
        {
            "idempotency_key": "transaction-key-0001",
            "date": "2026-11-03",
            "scope": "project",
            "direction": "Pemasukan",
            "amount": 500000,
            "description": "Pembayaran DP",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
            "category": "Bahan Alat",
            "project": project_id,
        }
    )

    assert request.project == project_id
    assert seen == [(project_id, "CV HB(101)", "HOLLA")]


def test_dashboard_transaction_legacy_project_identity_validation_is_preserved():
    legacy_seen = []
    service = DashboardTransactionService(
        store=ValidationStore(),
        sheets=ValidationSheets(),
        project_exists=lambda project, wallet, company: legacy_seen.append((project, wallet, company)) or True,
        project_uuid_exists=lambda *_args: False,
        today=lambda: date(2026, 11, 3),
    )

    request = service.validate(
        {
            "idempotency_key": "transaction-key-0002",
            "date": "2026-11-03",
            "scope": "project",
            "direction": "Pengeluaran",
            "amount": 100000,
            "description": "Material",
            "wallet": "CV HB(101)",
            "company": "HOLLA",
            "category": "Bahan Alat",
            "project": "HOLLA - Expo Legacy",
        }
    )

    assert request.project == "HOLLA - Expo Legacy"
    assert legacy_seen == [("HOLLA - Expo Legacy", "CV HB(101)", "HOLLA")]


class ReceiptRepository:
    def __init__(self):
        self.calls = []

    def create_receipt_draft(self, project_id, **kwargs):
        self.calls.append((project_id, kwargs))
        if kwargs["allocations"][0]["ledger_source_key"] == "office:1":
            raise ProjectDocumentConflict("receipt allocation must reference valid project income")
        return {"id": "receipt-1", "status": "draft", "allocations": kwargs["allocations"]}


def test_receipt_reconciliation_rejects_office_expense_or_transfer_sources():
    repository = ReceiptRepository()
    service = ProjectDocumentService(
        repository,
        today=lambda: date(2026, 11, 3),
    )

    with pytest.raises(ProjectDocumentConflict, match="project income"):
        service.create_receipt(
            "00000000-0000-4000-8000-000000000001",
            allocations=[{"ledger_source_key": "office:1", "amount": 1000}],
            values={},
            idempotency_key="receipt-command-0002",
            actor={"email": "owner@example.com"},
        )


def test_repository_income_validator_excludes_expense_office_and_internal_transfer_rows():
    base = {
        "is_valid": True,
        "transaction_type": "Pemasukan",
        "source_block": "pemasukan",
        "project": "project-1",
        "wallet": "CV HB(101)",
        "company": "HOLLA",
        "amount": 1000,
    }
    issuer = {"wallet": "CV HB(101)", "company": "HOLLA"}

    ProjectDocumentRepository._validate_income_row(base, project_id="project-1", issuer=issuer)
    for changes in (
        {"transaction_type": "Pengeluaran"},
        {"source_block": "operasional"},
        {"source_block": "internal_transfer"},
        {"project": "project-2"},
        {"wallet": "OTHER"},
    ):
        with pytest.raises(ProjectDocumentConflict):
            ProjectDocumentRepository._validate_income_row(
                {**base, **changes}, project_id="project-1", issuer=issuer
            )
