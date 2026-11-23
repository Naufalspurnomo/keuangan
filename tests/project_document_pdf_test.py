from __future__ import annotations

import base64
import io
from copy import deepcopy
from typing import Any, cast

import pytest
from PIL import Image as PillowImage
from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.pdfbase import pdfmetrics

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


def image_dimensions(pdf: bytes) -> set[tuple[int, int]]:
    dimensions: set[tuple[int, int]] = set()
    for page in reader(pdf).pages:
        resources = cast(dict[str, Any], page["/Resources"])
        if "/XObject" not in resources:
            continue
        xobjects = cast(dict[str, Any], resources["/XObject"].get_object())
        for reference in xobjects.values():
            image = reference.get_object()
            if image.get("/Subtype") == "/Image":
                dimensions.add((int(image["/Width"]), int(image["/Height"])))
    return dimensions


def page_image_dimensions(page) -> set[tuple[int, int]]:
    resources = cast(dict[str, Any], page["/Resources"])
    if "/XObject" not in resources:
        return set()
    xobjects = cast(dict[str, Any], resources["/XObject"].get_object())
    return {
        (int(image["/Width"]), int(image["/Height"]))
        for reference in xobjects.values()
        if (image := reference.get_object()).get("/Subtype") == "/Image"
    }


def visible_text_runs(pdf: bytes) -> list[dict]:
    runs: list[dict] = []

    def visit(value, cm, tm, font, size):
        cleaned = " ".join(value.split())
        if cleaned and size > 1:
            base_font = str((font or {}).get("/BaseFont") or "").lstrip("/")
            registered_font = base_font.split("+", 1)[-1]
            registered_font = {
                "HankenGrotesk-Regular": "HankenGrotesk",
                "OpenSauceOne-Regular": "OpenSauceOne",
                "Roboto-Regular": "Roboto",
            }.get(registered_font, registered_font)
            x = float(cm[0] * tm[4] + cm[2] * tm[5] + cm[4])
            y = float(cm[1] * tm[4] + cm[3] * tm[5] + cm[5])
            advance = float(cm[0] * tm[0] + cm[2] * tm[1])
            runs.append({
                "text": cleaned,
                "size": float(size),
                "x": x,
                "right": x + advance * pdfmetrics.stringWidth(cleaned, registered_font, float(size)),
                "y": y,
                "font": base_font,
            })

    reader(pdf).pages[0].extract_text(visitor_text=visit)
    return runs


def text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in reader(pdf).pages)


def page_rectangles(pdf: bytes) -> list[tuple[float, ...]]:
    document = reader(pdf)
    content = ContentStream(document.pages[0].get_contents(), document)
    return [tuple(float(item) for item in args) for args, operation in content.operations if operation == b"re"]


def test_hollawall_invoice_uses_reference_title_and_closing():
    value = snapshot()
    pdf = render_project_document_pdf(value)
    runs = visible_text_runs(pdf)
    assert any(run["text"] == "Invoice" and run["size"] >= 15 for run in runs)
    assert any("Revisions beyond the agreed scope" in run["text"] for run in runs)
    assert xobject_count(pdf) >= 2


@pytest.mark.parametrize("brand", ["texturin-surabaya", "texturin-bali"])
def test_texturin_total_has_reference_wide_shaded_band(brand):
    value = snapshot()
    value["project"]["company"] = brand
    value["document"]["template_key"] = brand
    pdf = render_project_document_pdf(value)
    page = reader(pdf).pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    assert any(w > width * .85 and h >= height * .02 and height * .3 < y < height * .6
               for x, y, w, h in page_rectangles(pdf))


def test_hojja_dp_invoice_shows_the_actual_total_in_reference_band():
    value = snapshot()
    value["project"]["company"] = "HOJJA"
    value["document"]["template_key"] = "HOJJA"
    pdf = render_project_document_pdf(value)
    runs = visible_text_runs(pdf)
    assert any(run["text"] == "Total DP :" for run in runs)
    assert any(run["text"] == "Rp 2.500.000" for run in runs)
    page = reader(pdf).pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    assert any(width * .30 < w < width * .5 and h >= height * .02 and height * .35 < y < height * .65
               for x, y, w, h in page_rectangles(pdf))


def test_hojja_project_artwork_does_not_cross_the_summary_rule():
    value = snapshot()
    value["project"]["company"] = "HOJJA"
    value["document"].update({"template_key": "HOJJA", "project_image_url": project_image_data_url()})
    pdf = render_project_document_pdf(value)
    doc = reader(pdf)
    page = doc.pages[0]
    xobjects = page["/Resources"]["/XObject"].get_object()
    current_matrix = None
    image_bounds = None
    for args, operation in ContentStream(page.get_contents(), doc).operations:
        if operation == b"cm":
            current_matrix = [float(value) for value in args]
        elif operation == b"Do":
            obj = xobjects[args[0]].get_object()
            if obj.get("/Width") == 4 and obj.get("/Height") == 3:
                image_bounds = current_matrix
                break
    assert image_bounds is not None
    rule_y = float(page.mediabox.height) * (1 - .455)
    assert not image_bounds[5] < rule_y < image_bounds[5] + image_bounds[3]


def test_texturin_bali_bank_details_are_below_the_total_band():
    value = snapshot()
    value["project"]["company"] = "TEXTURIN-Bali"
    value["document"].update({"template_key": "TEXTURIN-BALI", "payment_terms": "", "notes": ""})
    runs = visible_text_runs(render_project_document_pdf(value))
    total = next(run for run in runs if run["text"] == "TOTAL")
    bank = next(run for run in runs if run["text"] == "BANK DETAILS")
    assert total["y"] - bank["y"] > 18


def test_texturin_bali_project_artwork_does_not_cross_the_summary_rule():
    value = snapshot()
    value["project"]["company"] = "TEXTURIN-Bali"
    value["document"].update({"template_key": "TEXTURIN-BALI", "payment_terms": "", "notes": "", "project_image_url": project_image_data_url()})
    pdf = render_project_document_pdf(value)
    doc = reader(pdf)
    page = doc.pages[0]
    xobjects = page["/Resources"]["/XObject"].get_object()
    matrix = None
    image_bounds = None
    for args, operation in ContentStream(page.get_contents(), doc).operations:
        if operation == b"cm":
            matrix = [float(value) for value in args]
        elif operation == b"Do":
            obj = xobjects[args[0]].get_object()
            if obj.get("/Width") == 4 and obj.get("/Height") == 3:
                image_bounds = matrix
                break
    assert image_bounds is not None
    rule_y = float(page.mediabox.height) * (1 - .456)
    assert not image_bounds[5] < rule_y < image_bounds[5] + image_bounds[3]


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-surabaya", "texturin-bali"])
@pytest.mark.parametrize("line_count", [1, 2, 3])
def test_project_image_is_present_for_every_short_document(brand, line_count):
    value = snapshot(line_count=line_count)
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "project_image_url": project_image_data_url()})
    pdf = render_project_document_pdf(value)
    assert (4, 3) in image_dimensions(pdf)


def test_hollawall_multi_page_uses_the_same_reference_master_as_short_documents():
    value = snapshot(line_count=4)
    value["document"].update({"document_type": "sales_order", "invoice_kind": None})
    pdf = render_project_document_pdf(value)
    content = text(pdf)
    assert (839, 1191) in image_dimensions(pdf)
    assert "Quotation" in content
    assert "Hollawall Mural Studio · Hollawall" not in content
    assert all(line["description"] in " ".join(content.split()) for line in value["lines"])


def test_hollawall_four_item_quotation_keeps_its_signoff_on_the_page():
    value = snapshot(line_count=4)
    value["document"].update({"document_type": "sales_order", "invoice_kind": None})
    pdf = render_project_document_pdf(value)
    assert len(reader(pdf).pages) == 1
    assert "Best regards and thank you" in text(pdf)


@pytest.mark.parametrize("brand", ["hojja", "texturin-surabaya", "texturin-bali"])
def test_multi_item_documents_keep_the_reference_brand_header(brand):
    value = snapshot(line_count=4)
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "document_type": "sales_order", "invoice_kind": None})
    pdf = render_project_document_pdf(value)
    assert (1191, 1685) in image_dimensions(pdf)
    assert "Quotation" in text(pdf)


@pytest.mark.parametrize("line_count", [1, 4])
def test_hojja_footer_uses_the_current_issuer_phone(line_count):
    value = snapshot(line_count=line_count)
    value["project"]["company"] = "HOJJA"
    value["document"]["template_key"] = "HOJJA"
    value["issuer"]["phone"] = "+62 812 7654 3210"
    assert "+62 812 7654 3210" in text(render_project_document_pdf(value))


def test_texturin_terms_use_the_reference_italic_font():
    value = snapshot()
    value["project"]["company"] = "TEXTURIN-Surabaya"
    value["document"].update({"template_key": "TEXTURIN-SURABAYA", "document_type": "sales_order", "notes": "", "payment_terms": ""})
    runs = visible_text_runs(render_project_document_pdf(value))
    term = next(run for run in runs if "Pengecatan dilakukan" in run["text"])
    assert "Italic" in term["font"]


@pytest.mark.parametrize("brand", ["texturin-surabaya", "texturin-bali"])
def test_texturin_multi_item_totals_keep_the_full_width_reference_band(brand):
    value = snapshot(line_count=4)
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "document_type": "sales_order", "invoice_kind": None})
    pdf = render_project_document_pdf(value)
    width = float(reader(pdf).pages[0].mediabox.width)
    bands = [(w, h) for _, _, w, h in page_rectangles(pdf) if width * .80 <= w <= width * .95 and 10 < abs(h) < 35]
    assert len(bands) >= 2  # Item header and full-width total band.
    assert "Account Name:" in text(pdf)
    assert "Account No.:" in text(pdf)


def test_texturin_four_item_document_keeps_bank_and_signature_on_the_same_page():
    value = snapshot(line_count=4)
    value["project"]["company"] = "TEXTURIN-Surabaya"
    value["document"].update({"template_key": "TEXTURIN-SURABAYA", "document_type": "sales_order", "invoice_kind": None})
    pdf = render_project_document_pdf(value)
    assert len(reader(pdf).pages) == 1
    assert "BANK DETAILS" in text(pdf)
    assert (283, 244) in page_image_dimensions(reader(pdf).pages[0])


@pytest.mark.parametrize(("brand", "expected"), [
    ("hollawall", (24, 184, 198)),
    ("hojja", (118, 130, 118)),
    ("texturin-surabaya", (227, 220, 212)),
    ("texturin-bali", (227, 220, 212)),
])
def test_summary_colors_match_the_reference_pdf(brand, expected):
    value = snapshot()
    value["project"]["company"] = brand
    value["document"]["template_key"] = brand
    pdf = render_project_document_pdf(value)
    doc = reader(pdf)
    colors = [tuple(float(channel) for channel in args) for args, op in ContentStream(doc.pages[0].get_contents(), doc).operations if op == b"rg" and len(args) == 3]
    assert any(all(abs(actual - target / 255) < .001 for actual, target in zip(color, expected)) for color in colors)


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-surabaya", "texturin-bali"])
def test_large_total_never_overlaps_its_label(brand):
    value = snapshot()
    value["project"]["company"] = brand
    value["document"]["template_key"] = brand
    value["totals"].update({"subtotal": 999_999_999_999_999, "total": 999_999_999_999_999})
    runs = visible_text_runs(render_project_document_pdf(value))
    labels = [run for run in runs if run["text"] in {"TOTAL", "Total DP :"}]
    assert labels
    label = labels[-1]
    amount = next(run for run in runs if run["text"] == "Rp 999.999.999.999.999" and abs(run["y"] - label["y"]) < 1)
    assert label["right"] + 3 < amount["x"]


def test_hollawall_quotation_deposit_is_above_the_summary_rule():
    value = snapshot()
    value["document"].update({"document_type": "sales_order", "invoice_kind": None})
    pdf = render_project_document_pdf(value)
    doc = reader(pdf)
    page = doc.pages[0]
    label = next(run for run in visible_text_runs(pdf) if run["text"].startswith("Down Payment"))
    right = float(page.mediabox.width) * .93
    rules = [float(args[1]) for args, op in ContentStream(page.get_contents(), doc).operations
             if op == b"l" and len(args) == 2 and abs(float(args[0]) - right) < 1]
    assert any(6 < label["y"] - y < 25 for y in rules)


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


def test_hojja_quotation_pdf_uses_project_specific_deposit_percent_consistently():
    value = snapshot()
    value["project"]["company"] = "HOJJA"
    value["issuer"]["display_name"] = "HOJJA ArtHouse"
    value["document"].update({
        "document_type": "sales_order",
        "template_key": "HOJJA",
        "deposit_percent": "45",
        "payment_terms": "DP 45% sebelum produksi.",
    })

    content = " ".join(text(render_project_document_pdf(value)).split())

    assert "DP 45%" in content
    assert "Rp 1.125.000" in content
    assert "Rp 750.000" not in content


def test_texturin_surabaya_and_bali_have_distinct_pdf_contracts():
    surabaya = snapshot()
    surabaya["project"].update({"company": "TEXTURIN-Surabaya", "wallet": "TX SBY(216)"})
    surabaya["document"].update({"document_type": "sales_order", "template_key": "TEXTURIN-SURABAYA"})
    surabaya_pdf = render_project_document_pdf(surabaya)
    surabaya_text = " ".join(text(surabaya_pdf).split())

    bali = deepcopy(surabaya)
    bali["project"].update({"company": "TEXTURIN-Bali", "wallet": "TX BALI(087)"})
    bali["document"].update({
        "document_type": "sales_order", "template_key": "TEXTURIN-BALI",
        "valid_until": "2026-11-17",
    })
    bali_pdf = render_project_document_pdf(bali)
    bali_text = " ".join(text(bali_pdf).split())
    bali_runs = visible_text_runs(bali_pdf)
    bali_height = float(reader(bali_pdf).pages[0].mediabox.height)
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
    assert "Pembayaran melalui rekening resmi perusahaan." in bali_text
    bali_validity_y = next(run["y"] for run in bali_runs if run["text"] == "VALID UNTIL")
    assert bali_validity_y == pytest.approx(bali_height * (1 - (.222 + .046)), abs=.1)


def test_texturin_two_item_pdf_matches_the_readable_signed_paper_contract():
    value = snapshot(line_count=2)
    value["project"].update({
        "name": "Gatau", "client_name": "GGWP", "client_company": "",
        "company": "TEXTURIN-Surabaya", "wallet": "TX SBY(216)",
    })
    value["issuer"].update({
        "issuer_key": "texturin-surabaya", "display_name": "Texturin Surabaya",
        "bank_details": {"bank": "BCA", "account_number": "123", "account_name": "Evan Setyawan"},
    })
    value["document"].update({
        "document_type": "sales_order", "template_key": "TEXTURIN-SURABAYA",
        "official_number": "QTN/001", "issue_date": "2026-11-20",
        "valid_until": "2026-11-27", "deposit_percent": "30",
        "payment_terms": "", "notes": "",
    })
    value["lines"] = [
        {
            "description": "Tanah", "quantity": "300", "unit": "m²",
            "unit_price": 10_000, "line_gross": 3_000_000,
            "line_discount_percent": "0", "line_discount": 0,
            "line_total": 3_000_000,
        },
        {
            "description": "Air", "quantity": "200", "unit": "m²",
            "unit_price": 40_000, "line_gross": 8_000_000,
            "line_discount_percent": "0", "line_discount": 0,
            "line_total": 8_000_000,
        },
    ]
    value["totals"].update({
        "subtotal": 11_000_000, "taxable_base": 11_000_000,
        "tax": 0, "total": 11_000_000,
    })

    pdf = render_project_document_pdf(value)
    content = " ".join(text(pdf).split())
    runs = visible_text_runs(pdf)
    page = reader(pdf).pages[0]
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)

    assert "20 November 2026" in content
    assert "VALID UNTIL" in content
    assert "27 November 2026" in content
    assert "Evanvun" in content
    assert xobject_count(pdf) >= 2  # Canonical master plus canonical sign-off artwork.
    for expected in ("Tanah", "Rp 3.000.000", "Air", "Rp 8.000.000", "Rp 11.000.000"):
        assert expected in content
    dynamic = [run for run in runs if run["text"] in {
        "GGWP", "Gatau", "QTN/001", "20 November 2026", "VALID UNTIL", "27 November 2026", "Tanah", "Air",
        "Rp 10.000", "Rp 40.000", "300 m²", "200 m²",
        "Rp 3.000.000", "Rp 8.000.000", "Rp 11.000.000",
    }]
    assert dynamic and min(run["size"] for run in dynamic) >= 9
    assert all(0 <= run["x"] <= run["right"] <= width and 0 <= run["y"] <= height for run in dynamic)

    by_text = {}
    for run in runs:
        by_text.setdefault(run["text"], []).append(run)
    issue_date_y = by_text["20 November 2026"][0]["y"]
    validity_y = by_text["VALID UNTIL"][0]["y"]
    assert validity_y >= height * .775
    assert issue_date_y - validity_y >= 14
    ppm_right = max(run["right"] for key in ("Rp 10.000", "Rp 40.000") for run in by_text[key])
    quantity_right = max(run["right"] for key in ("300 m²", "200 m²") for run in by_text[key])
    item_total_right = max(run["right"] for key in ("Rp 3.000.000", "Rp 8.000.000") for run in by_text[key])
    assert ppm_right < quantity_right < item_total_right
    assert item_total_right == pytest.approx(width * .928, abs=2)


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-surabaya", "texturin-bali"])
def test_dp_invoice_does_not_calculate_a_second_deposit(brand):
    value = snapshot()
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "document_type": "invoice", "invoice_kind": "DP"})
    value["lines"][0].update({"description": "Uang muka", "quantity": "1", "unit": "termin", "unit_price": 2_500_000})
    runs = visible_text_runs(render_project_document_pdf(value))
    rendered = " ".join(run["text"] for run in runs)
    assert "Rp 2.500.000" in rendered
    assert "Rp 750.000" not in rendered
    assert "Rp 1.250.000" not in rendered


@pytest.mark.parametrize("brand", ["texturin-surabaya", "texturin-bali"])
def test_texturin_item_description_stays_in_its_column_and_project_image_is_visible(brand):
    value = snapshot(line_count=2)
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "document_type": "sales_order", "project_image_url": project_image_data_url()})
    pdf = render_project_document_pdf(value)
    runs = visible_text_runs(pdf)
    description = [run for run in runs if "Produksi wall branding" in run["text"]]
    prices = [run for run in runs if run["text"] == "Rp 1.000.000"]
    assert len(description) == len(prices) == 2
    assert max(run["right"] for run in description) < min(run["x"] for run in prices)
    assert (4, 3) in image_dimensions(pdf)


def test_hollawall_due_date_is_above_the_table_header():
    value = snapshot()
    runs = visible_text_runs(render_project_document_pdf(value))
    due = next(run for run in runs if run["text"] == "DUE DATE")
    height = float(reader(render_project_document_pdf(value)).pages[0].mediabox.height)
    assert due["y"] > height * (1 - .267)


def test_hojja_number_does_not_overlap_its_label():
    value = snapshot()
    value["project"]["company"] = "HOJJA"
    value["document"]["template_key"] = "HOJJA"
    runs = visible_text_runs(render_project_document_pdf(value))
    label = next(run for run in runs if run["text"] == "Letter ID")
    number = next(run for run in runs if run["text"] == value["document"]["official_number"])
    assert label["right"] + 3 < number["x"]


def test_hojja_project_image_is_visible_with_multiple_items():
    value = snapshot(line_count=2)
    value["project"]["company"] = "HOJJA"
    value["document"].update({"template_key": "HOJJA", "project_image_url": project_image_data_url()})
    assert (4, 3) in image_dimensions(render_project_document_pdf(value))


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-surabaya", "texturin-bali"])
def test_explicit_template_overrides_other_brand_names(brand):
    value = snapshot()
    value["project"]["company"] = "TEXTURIN-Surabaya" if brand != "texturin-surabaya" else "HOJJA"
    value["document"]["template_key"] = brand
    pdf = render_project_document_pdf(value)
    expected_width = 419.53 if brand == "hollawall" else 595.28
    assert float(reader(pdf).pages[0].mediabox.width) == pytest.approx(expected_width, abs=.5)
    assert brand.replace("-", " ").split()[0] in " ".join(text(pdf).lower().split())


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-bali"])
def test_long_payment_terms_are_paginated_without_losing_the_end(brand):
    value = snapshot()
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "payment_terms": "Ketentuan pembayaran khusus. " * 300 + "AKHIR-KETENTUAN"})
    pdf = render_project_document_pdf(value)
    assert len(reader(pdf).pages) > 1
    assert "AKHIR-KETENTUAN" in text(pdf)


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-surabaya", "texturin-bali"])
def test_multi_item_quotation_keeps_deposit_amount(brand):
    value = snapshot(line_count=4)
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "document_type": "sales_order", "deposit_percent": "50"})
    content = " ".join(text(render_project_document_pdf(value)).split())
    assert "Rp 5.000.000" in content


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-surabaya", "texturin-bali"])
def test_long_customer_and_project_names_stay_within_the_page(brand):
    value = snapshot()
    value["project"].update({
        "company": brand,
        "client_company": "Perusahaan Pelanggan Internasional " * 5,
        "name": "Pekerjaan Interior Ruang Pertemuan " * 5,
    })
    value["document"]["template_key"] = brand
    pdf = render_project_document_pdf(value)
    width = float(reader(pdf).pages[0].mediabox.width)
    runs = visible_text_runs(pdf)
    assert all(0 <= run["x"] <= run["right"] <= width for run in runs)


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-bali"])
def test_custom_notes_are_visible_in_the_pdf(brand):
    value = snapshot()
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "notes": "Catatan khusus untuk pelanggan."})
    rendered = " ".join(run["text"] for run in visible_text_runs(render_project_document_pdf(value)))
    assert "Catatan khusus untuk pelanggan." in rendered


@pytest.mark.parametrize("brand", ["hollawall", "hojja", "texturin-surabaya", "texturin-bali"])
def test_quotation_deposit_rounds_half_up_like_the_invoice(brand):
    value = snapshot()
    value["project"]["company"] = brand
    value["document"].update({"template_key": brand, "document_type": "sales_order", "deposit_percent": "50"})
    value["totals"].update({"subtotal": 3, "total": 3})
    runs = visible_text_runs(render_project_document_pdf(value))
    assert any(run["text"] == "Rp 2" for run in runs)


def test_texturin_long_terms_use_paginated_flow_without_losing_content_or_signoff():
    value = snapshot(line_count=2)
    value["project"].update({
        "name": "Gatau", "client_name": "GGWP", "client_company": "",
        "company": "TEXTURIN-Surabaya", "wallet": "TX SBY(216)",
    })
    value["issuer"].update({
        "issuer_key": "texturin-surabaya", "display_name": "Texturin Surabaya",
        "bank_details": {"bank": "BCA", "account_number": "123", "account_name": "Evan Setyawan"},
    })
    marker = "AKHIR-KETENTUAN-TERVERIFIKASI"
    value["document"].update({
        "document_type": "sales_order", "template_key": "TEXTURIN-SURABAYA",
        "official_number": "QTN/LONG", "issue_date": "2026-11-20",
        "valid_until": "2026-11-27", "deposit_percent": "45",
        "payment_terms": (("Ketentuan pembayaran khusus Project. " * 230) + marker)[:9_000],
        "notes": "Catatan quotation tetap terbaca.",
    })

    pdf = render_project_document_pdf(value)
    content = " ".join(text(pdf).split())

    assert len(reader(pdf).pages) >= 2
    assert marker in content
    assert "Pengecatan dilakukan pada bidang tembok/plafon yang siap dicat." in content
    assert "Hasil aplikasi ditargetkan 80% sesuai sampel karena proses handmade." in content
    assert "Persetujuan penawaran disertai pembayaran signature fee sebesar 45%" in content
    assert "signature fee sebesar 30%" not in content
    assert "BANK DETAILS" in content
    assert "SIGNATURE FEE (45%)" in content
    assert (283, 244) in image_dimensions(pdf)  # Canonical Evanvun sign-off, including later pages.
    final_page = reader(pdf).pages[-1]
    assert "BANK DETAILS" in (final_page.extract_text() or "")
    assert (283, 244) in page_image_dimensions(final_page)


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

    pdf = render_project_document_pdf(value)
    content = " ".join(text(pdf).split())
    runs = visible_text_runs(pdf)
    page_height = float(reader(pdf).pages[0].mediabox.height)
    by_text = {run["text"]: run for run in runs}

    assert "DUE DATE" in content
    assert "10 November 2026" in by_text
    assert by_text["DUE DATE"]["y"] >= page_height * .775
    assert by_text["03 November 2026"]["y"] - by_text["DUE DATE"]["y"] >= 14
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
    assert "Halaman 1 / 1" not in content
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
        pytest.param("https://attacker.example/project.png", id="remote-url"),
        pytest.param("file:///etc/passwd", id="local-file"),
        pytest.param("data:image/gif;base64,R0lGODlhAQABAIAAAAUEBA==", id="unsupported-mime"),
        pytest.param("data:image/png;base64,not-valid-base64!", id="invalid-base64"),
        pytest.param("data:image/png;base64,Zm9v", id="invalid-png"),
        pytest.param("data:image/png;base64," + ("A" * 196_609), id="encoded-over-limit"),
        pytest.param(
            "data:image/png;base64," + base64.b64encode(b"x" * (144 * 1024 + 1)).decode("ascii"),
            id="decoded-over-limit",
        ),
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
