from __future__ import annotations

import io
from copy import deepcopy

from pypdf import PdfReader

from services.project_document_pdf import (
    RENDERER_VERSION,
    render_project_document_artifact,
    render_project_document_pdf,
)


def snapshot(*, status: str = "issued", line_count: int = 1) -> dict:
    lines = [
        {
            "description": f"Produksi wall branding area lobby nomor {index + 1}",
            "quantity": "2.5",
            "unit": "m2",
            "unit_price": 1_000_000,
            "line_discount_percent": "0",
            "line_gross": 2_500_000,
            "line_discount": 0,
            "line_total": 2_500_000,
        }
        for index in range(line_count)
    ]
    total = 2_500_000 * line_count
    return {
        "schema_version": 1,
        "issued_at": "2026-11-03T10:00:00+00:00",
        "issuer": {
            "issuer_key": "hollawall",
            "legal_name": "CV Holla Berkreasi",
            "display_name": "Hollawall",
            "number_code": "HW",
            "address": "Surabaya, Jawa Timur",
            "phone": "+62 812 0000 0000",
            "email": "finance@example.com",
            "bank_details": {"bank": "BCA", "account_number": "1234567890", "account_name": "CV Holla Berkreasi"},
            "profile_version": 1,
        },
        "project": {
            "id": "project-1",
            "name": "Lobby Cempaka",
            "client_name": "Bapak Arif",
            "client_company": "PT Cempaka Abadi",
            "client_address": "Jakarta",
            "client_contact": "+62 811 1111 1111",
        },
        "document": {
            "id": "document-1",
            "document_type": "invoice",
            "invoice_kind": "DP",
            "status": status,
            "official_number": "INV/HW/2026/000001" if status == "issued" else None,
            "issue_date": "2026-11-03",
            "due_date": "2026-11-10",
            "valid_until": None,
            "notes": "Mohon cantumkan nomor invoice saat melakukan pembayaran.",
            "payment_terms": "Pembayaran melalui rekening resmi perusahaan.",
        },
        "lines": lines,
        "allocations": [],
        "totals": {
            "subtotal": total,
            "document_discount": 0,
            "taxable_base": total,
            "tax": 0,
            "total": total,
        },
    }


def reader(pdf: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(pdf))


def text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in reader(pdf).pages)


def test_renderer_produces_deterministic_a5_branded_pdf():
    value = snapshot()

    first = render_project_document_pdf(value)
    second = render_project_document_pdf(deepcopy(value))

    assert first == second
    assert first.startswith(b"%PDF-")
    document = reader(first)
    assert len(document.pages) == 1
    width = float(document.pages[0].mediabox.width)
    height = float(document.pages[0].mediabox.height)
    assert width == pytest.approx(419.53, abs=0.5)
    assert height == pytest.approx(595.28, abs=0.5)
    content = text(first)
    assert "Hollawall" in content
    assert "CV Holla Berkreasi" in content
    assert "INVOICE" in content
    assert "INV/HW/2026/000001" in content
    assert "PT Cempaka Abadi" in content
    assert "Lobby Cempaka" in content
    assert "Rp 2.500.000" in content
    assert "Halaman 1 / 1" in content
    assert "TOTAL_PAGES" not in content


def test_renderer_paginates_long_tables_and_repeats_headers():
    pdf = render_project_document_pdf(snapshot(line_count=80))
    document = reader(pdf)

    assert len(document.pages) >= 3
    item_pages = [
        page_text
        for page in document.pages
        if "Produksi wall branding" in (page_text := (page.extract_text() or ""))
    ]
    assert len(item_pages) >= 3
    assert all("DESKRIPSI" in page_text and "TOTAL" in page_text for page_text in item_pages)
    assert all("Hollawall" in (page.extract_text() or "") for page in document.pages)
    assert f"Halaman {len(document.pages)} / {len(document.pages)}" in text(pdf)


def test_renderer_marks_non_issued_states_and_returns_repository_artifact():
    draft_pdf = render_project_document_pdf(snapshot(status="draft"))
    void_pdf = render_project_document_pdf(snapshot(status="void"))
    superseded_pdf = render_project_document_pdf(snapshot(status="superseded"))

    assert "DRAFT" in text(draft_pdf)
    assert "VOID" in text(void_pdf)
    assert "SUPERSEDED" in text(superseded_pdf)
    artifact, version = render_project_document_artifact(snapshot())
    assert artifact == render_project_document_pdf(snapshot())
    assert version == RENDERER_VERSION


def test_renderer_ignores_unsafe_optional_images_without_network_or_file_reads(monkeypatch):
    value = snapshot()
    value["project"]["image_url"] = "https://attacker.example/image.png"

    def fail(*_args, **_kwargs):
        raise AssertionError("renderer attempted external image access")

    monkeypatch.setattr("builtins.open", fail)
    pdf = render_project_document_pdf(value, logo_path=None)

    assert pdf.startswith(b"%PDF-")
    assert "Lobby Cempaka" in text(pdf)


import pytest
