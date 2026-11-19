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


def xobject_count(pdf: bytes) -> int:
    resources = reader(pdf).pages[0]["/Resources"]
    return len(resources["/XObject"].get_object()) if "/XObject" in resources else 0


def text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in reader(pdf).pages)


@pytest.mark.parametrize(
    ("company", "display_name", "document_type", "expected_title", "page_size", "identity"),
    [
        ("HOLLA", "Hollawall", "invoice", "INVOICE", (419.53, 595.28), "Hollawall Mural Studio"),
        ("HOLLA", "Hollawall", "sales_order", "QUOTATION", (419.53, 595.28), "Hollawall Mural Studio"),
        ("HOJJA", "HOJJA ArtHouse", "invoice", "INVOICE", (595.28, 841.89), "HOJJA ArtHouse"),
        ("HOJJA", "HOJJA ArtHouse", "sales_order", "QUOTATION", (595.28, 841.89), "HOJJA ArtHouse"),
        ("TEXTURIN-Bali", "Texturin Bali", "invoice", "INVOICE", (595.28, 841.89), "texturin Bali · decorative finishes"),
        ("TEXTURIN-Surabaya", "Texturin Surabaya", "sales_order", "QUOTATION", (595.28, 841.89), "texturin Surabaya · decorative finishes"),
    ],
)
def test_renderer_selects_brand_page_size_title_and_identity(
    company,
    display_name,
    document_type,
    expected_title,
    page_size,
    identity,
):
    value = snapshot()
    value["project"]["company"] = company
    value["issuer"]["display_name"] = display_name
    value["document"]["document_type"] = document_type

    pdf = render_project_document_pdf(value, logo_path=None)
    document = reader(pdf)
    content = " ".join(text(pdf).split())

    assert float(document.pages[0].mediabox.width) == pytest.approx(page_size[0], abs=0.5)
    assert float(document.pages[0].mediabox.height) == pytest.approx(page_size[1], abs=0.5)
    assert expected_title in content
    assert identity in content


@pytest.mark.parametrize(
    ("company", "display_name", "document_type", "invoice_kind", "expected_labels"),
    [
        ("HOJJA", "HOJJA ArtHouse", "invoice", "DP", ("DATE", "LETTER ID", "Total DP")),
        ("TEXTURIN-Bali", "Texturin Bali", "sales_order", None, ("QUOTATION NO.", "QTY/LUAS", "BANK DETAILS")),
        ("HOLLA", "Hollawall", "invoice", "DP", ("TANGGAL", "LETTER NO.", "TOTAL DP", "Best regards")),
    ],
)
def test_renderer_preserves_reference_labels_and_brand_signoff(
    company, display_name, document_type, invoice_kind, expected_labels,
):
    value = snapshot()
    value["project"]["company"] = company
    value["issuer"]["display_name"] = display_name
    value["document"]["document_type"] = document_type
    value["document"]["invoice_kind"] = invoice_kind
    content = " ".join(text(render_project_document_pdf(value)).split())
    for label in expected_labels:
        assert label in content


def test_quotation_pdf_uses_project_specific_deposit_percent():
    value = snapshot()
    value["document"].update({
        "document_type": "sales_order",
        "template_key": "HOLLAWALL",
        "deposit_percent": "50",
        "payment_terms": "DP 50% sebelum produksi.",
    })

    content = " ".join(text(render_project_document_pdf(value)).split())

    assert "Down Payment 50%" in content
    assert "Rp 1.250.000" in content
    assert "Down Payment 30%" not in content


def test_texturin_surabaya_and_bali_have_distinct_pdf_contracts():
    surabaya = snapshot()
    surabaya["project"].update({"company": "TEXTURIN-Surabaya", "wallet": "TX SBY(216)"})
    surabaya["document"].update({"document_type": "sales_order", "template_key": "TEXTURIN-SURABAYA"})
    surabaya_pdf = render_project_document_pdf(surabaya)
    surabaya_text = " ".join(text(surabaya_pdf).split())

    bali = deepcopy(surabaya)
    bali["project"].update({"company": "TEXTURIN-Bali", "wallet": "TX BALI(087)"})
    bali["document"].update({"document_type": "sales_order", "template_key": "TEXTURIN-BALI"})
    bali_pdf = render_project_document_pdf(bali)
    bali_text = " ".join(text(bali_pdf).split())
    bali_final_invoice = deepcopy(bali)
    bali_final_invoice["document"].update({"document_type": "invoice", "invoice_kind": "FINAL"})
    bali_final_invoice_text = " ".join(text(render_project_document_pdf(bali_final_invoice)).split())
    bali_fallback = snapshot(line_count=4)
    bali_fallback["project"].update({"company": "TEXTURIN-Bali", "wallet": "TX BALI(087)"})
    bali_fallback["document"].update({"document_type": "sales_order", "template_key": "TEXTURIN-BALI"})
    bali_fallback_text = " ".join(text(render_project_document_pdf(bali_fallback)).split())
    bali_fallback_final = deepcopy(bali_fallback)
    bali_fallback_final["document"].update({"document_type": "invoice", "invoice_kind": "FINAL"})
    bali_fallback_final_text = " ".join(text(render_project_document_pdf(bali_fallback_final)).split())

    assert surabaya_pdf != bali_pdf
    assert "texturin Surabaya · decorative finishes" in surabaya_text
    assert "SIGNATURE FEE (30%)" in surabaya_text
    assert "Rp 750.000" in surabaya_text
    assert "Pengecatan dilakukan pada bidang tembok/plafon yang siap dicat." in surabaya_text
    assert "Hasil aplikasi ditargetkan 80% sesuai sampel karena proses handmade." in surabaya_text
    assert "Persetujuan penawaran disertai pembayaran signature fee sebesar 30%" in surabaya_text
    assert "Pembayaran melalui rekening resmi perusahaan." in surabaya_text
    assert "texturin Bali · decorative finishes" in bali_text
    assert "SIGNATURE FEE (30%)" in bali_text
    assert "Rp 750.000" in bali_text
    assert "SIGNATURE FEE" not in bali_final_invoice_text
    assert "SIGNATURE FEE (30%)" in bali_fallback_text
    assert "SIGNATURE FEE" not in bali_fallback_final_text
    assert "BANK DETAILS" in bali_text
    assert "THANK YOU" in bali_text
    assert "Pengecatan dilakukan pada bidang tembok/plafon yang siap dicat." not in bali_text
    assert "Pembayaran melalui rekening resmi perusahaan." not in bali_text


def test_hojja_three_line_document_never_omits_the_third_billed_artwork():
    value = snapshot(line_count=3)
    value["project"]["company"] = "HOJJA"
    value["issuer"]["display_name"] = "HOJJA ArtHouse"
    value["document"]["template_key"] = "HOJJA"

    content = " ".join(text(render_project_document_pdf(value)).split())

    assert "Produksi wall branding area lobby nomor 1" in content
    assert "Produksi wall branding area lobby nomor 2" in content
    assert "Produksi wall branding area lobby nomor 3" in content


def test_master_invoice_visibly_reconciles_tax_and_due_date_without_quotation_terms():
    value = snapshot()
    value["project"].update({"company": "TEXTURIN-Surabaya", "wallet": "TX SBY(216)"})
    value["document"].update({
        "document_type": "invoice", "invoice_kind": "FINAL",
        "template_key": "TEXTURIN-SURABAYA", "payment_terms": "Lunas sebelum pemasangan.",
    })
    value["totals"].update({"taxable_base": 2_500_000, "tax": 275_000, "total": 2_775_000})

    content = " ".join(text(render_project_document_pdf(value)).split())

    assert "DUE DATE" in content
    assert "2026-11-10" in content
    assert "Pajak" in content
    assert "Rp 275.000" in content
    assert "Rp 2.775.000" in content
    assert "Penawaran berlaku" not in content


def test_receipt_pdf_is_an_acknowledgement_not_an_invoice_or_deposit_request():
    value = snapshot()
    value["document"].update({"document_type": "receipt", "invoice_kind": None})

    content = " ".join(text(render_project_document_pdf(value)).split())

    assert "RECEIPT" in content
    assert "Telah diterima dari" in content
    assert "Rp 2.500.000" in content
    assert "Diterima oleh" in content
    assert "Bapak Arif" in content
    assert "Diterima oleh Bapak Arif" in content
    assert "Produksi wall branding area lobby" not in content
    assert "Down Payment" not in content
    assert "Total DP" not in content


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
    assert all("DESCRIPTION" in page_text and "JUMLAH" in page_text for page_text in item_pages)
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


def test_renderer_does_not_duplicate_client_name_as_details():
    value = snapshot()
    value["project"]["client_company"] = ""
    value["project"]["client_contact"] = ""
    value["project"]["client_address"] = ""

    content = text(render_project_document_pdf(value, logo_path=None))

    assert content.count("Bapak Arif") == 1


def project_image_data_url(image_format: str = "PNG") -> str:
    buffer = io.BytesIO()
    PillowImage.new("RGB", (4, 3), (220, 30, 40)).save(buffer, format=image_format)
    subtype = "png" if image_format == "PNG" else "jpeg"
    return f"data:image/{subtype};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def test_renderer_embeds_valid_small_project_data_image_deterministically():
    value = snapshot()
    value["document"]["project_image_url"] = project_image_data_url()

    baseline = render_project_document_pdf(snapshot(), logo_path=None)
    first = render_project_document_pdf(value, logo_path=None)
    second = render_project_document_pdf(deepcopy(value), logo_path=None)

    assert first == second
    assert xobject_count(first) == xobject_count(baseline) + 1


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
    baseline = render_project_document_pdf(snapshot(), logo_path=None)

    def fail(*_args, **_kwargs):
        raise AssertionError("renderer attempted external image access")

    monkeypatch.setattr("builtins.open", fail)
    first = render_project_document_pdf(value, logo_path=None)
    second = render_project_document_pdf(deepcopy(value), logo_path=None)

    assert first == second
    assert "Lobby Cempaka" in text(first)
    assert xobject_count(first) == xobject_count(baseline)
