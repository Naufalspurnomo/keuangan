from __future__ import annotations

import base64
import io
from copy import deepcopy

import pytest
from PIL import Image as PillowImage
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


HOSTILE_TEXT = (
    "R&D <angle> </para> <b>literal</b> "
    "<font name='DefinitelyMissingFont'>unknown-font</font>"
)


def test_renderer_renders_hostile_line_description_literally():
    value = snapshot()
    value["lines"][0]["description"] = HOSTILE_TEXT

    content = text(render_project_document_pdf(value, logo_path=None))

    assert HOSTILE_TEXT in " ".join(content.split())


PARAGRAPH_STRING_PATHS = (
    ("issuer", "display_name"),
    ("issuer", "legal_name"),
    ("issuer", "address"),
    ("issuer", "bank_details", "bank"),
    ("issuer", "bank_details", "account_number"),
    ("issuer", "bank_details", "account_name"),
    ("project", "client_company"),
    ("project", "client_name"),
    ("project", "client_contact"),
    ("project", "client_address"),
    ("project", "name"),
    ("document", "official_number"),
    ("document", "issue_date"),
    ("document", "due_date"),
    ("document", "valid_until"),
    ("document", "notes"),
    ("document", "payment_terms"),
    ("document", "prepared_by"),
    ("document", "client_signatory"),
    ("lines", 0, "description"),
    ("lines", 0, "quantity"),
    ("lines", 0, "unit"),
)


def _set_nested(value: dict, path: tuple[str | int, ...], replacement: str) -> None:
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement


@pytest.mark.parametrize("path", PARAGRAPH_STRING_PATHS, ids=lambda path: ".".join(map(str, path)))
def test_renderer_escapes_every_external_paragraph_value(path):
    value = snapshot()
    if path == ("project", "client_address"):
        value["project"]["client_company"] = ""
        value["project"]["client_name"] = ""
        value["project"]["client_contact"] = ""
    _set_nested(value, path, HOSTILE_TEXT)

    content = "".join(text(render_project_document_pdf(value, logo_path=None)).split())

    assert "".join(HOSTILE_TEXT.split()) in content


def test_renderer_uses_persisted_signature_labels():
    value = snapshot()
    value["document"]["prepared_by"] = "Nadia Finance"
    value["document"]["client_signatory"] = "Arif Director"

    content = text(render_project_document_pdf(value, logo_path=None))

    assert "Nadia Finance" in content
    assert "Arif Director" in content


def project_image_data_url(image_format: str = "PNG") -> str:
    buffer = io.BytesIO()
    PillowImage.new("RGB", (4, 3), (220, 30, 40)).save(buffer, format=image_format)
    subtype = "png" if image_format == "PNG" else "jpeg"
    return f"data:image/{subtype};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def test_renderer_embeds_valid_small_project_data_image_deterministically():
    value = snapshot()
    value["document"]["project_image_url"] = project_image_data_url()

    first = render_project_document_pdf(value, logo_path=None)
    second = render_project_document_pdf(deepcopy(value), logo_path=None)

    assert first == second
    resources = reader(first).pages[0]["/Resources"]
    assert "/XObject" in resources
    assert len(resources["/XObject"].get_object()) == 1


@pytest.mark.parametrize(
    "image_url",
    [
        "https://attacker.example/project.png",
        "file:///etc/passwd",
        "data:image/gif;base64,R0lGODlhAQABAIAAAAUEBA==",
        "data:image/png;base64,not-valid-base64!",
        "data:image/png;base64,Zm9v",
        "data:image/png;base64," + ("A" * 196_609),
        "data:image/png;base64," + base64.b64encode(b"x" * (144 * 1024 + 1)).decode("ascii"),
    ],
)
def test_renderer_ignores_invalid_oversized_or_remote_project_images_without_io(
    image_url,
    monkeypatch,
):
    value = snapshot()
    value["document"]["project_image_url"] = image_url

    def fail(*_args, **_kwargs):
        raise AssertionError("renderer attempted external image access")

    monkeypatch.setattr("builtins.open", fail)
    first = render_project_document_pdf(value, logo_path=None)
    second = render_project_document_pdf(deepcopy(value), logo_path=None)

    assert first == second
    assert "Lobby Cempaka" in text(first)
    assert "/XObject" not in reader(first).pages[0]["/Resources"]
