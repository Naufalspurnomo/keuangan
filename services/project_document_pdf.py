"""Deterministic branded A5 PDFs for immutable project documents."""

from __future__ import annotations

import base64
import binascii
import io
import warnings
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image as PillowImage
from PIL import UnidentifiedImageError
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

RENDERER_VERSION = "hollawall-a5-v1"
MAX_PROJECT_IMAGE_URL_CHARS = 196_608
MAX_PROJECT_IMAGE_BYTES = 144 * 1024
MAX_PROJECT_IMAGE_PIXELS = 16_000_000
PROJECT_IMAGE_PREFIXES = {
    "data:image/png;base64,": "PNG",
    "data:image/jpeg;base64,": "JPEG",
}
_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets/project-documents"
_DEFAULT_LOGO = _ASSET_DIR / "hollawall-logo.png"
_NAVY = colors.HexColor("#172A46")
_ORANGE = colors.HexColor("#F47C20")
_CYAN = colors.HexColor("#10B8C6")
_MUTED = colors.HexColor("#617087")
_LIGHT = colors.HexColor("#EDF2F6")

_TYPE_LABELS = {
    "sales_order": "SALES ORDER",
    "invoice": "INVOICE",
    "receipt": "KWITANSI",
}
_STATUS_WATERMARKS = {
    "draft": "DRAFT",
    "void": "VOID",
    "superseded": "SUPERSEDED",
}


def _register_fonts() -> tuple[str, str]:
    regular = _ASSET_DIR / "Montserrat-Regular.ttf"
    bold = _ASSET_DIR / "Montserrat-Bold.ttf"
    if regular.is_file() and bold.is_file():
        if "Montserrat" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("Montserrat", str(regular)))
        if "Montserrat-Bold" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("Montserrat-Bold", str(bold)))
        return "Montserrat", "Montserrat-Bold"
    return "Helvetica", "Helvetica-Bold"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any, fallback: str = "—") -> str:
    cleaned = str(value or "").strip()
    return cleaned or fallback


def _paragraph_text(value: Any, fallback: str = "—") -> str:
    return escape(_text(value, fallback), quote=True)


def _project_image_stream(value: Any) -> io.BytesIO | None:
    source = value if isinstance(value, str) else ""
    if not source or len(source) > MAX_PROJECT_IMAGE_URL_CHARS:
        return None
    expected_format = None
    encoded = ""
    for prefix, image_format in PROJECT_IMAGE_PREFIXES.items():
        if source.startswith(prefix):
            expected_format = image_format
            encoded = source[len(prefix):]
            break
    if expected_format is None:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > MAX_PROJECT_IMAGE_BYTES:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PillowImage.DecompressionBombWarning)
            with PillowImage.open(io.BytesIO(raw)) as image:
                if image.format != expected_format:
                    return None
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_PROJECT_IMAGE_PIXELS:
                    return None
                image.verify()
    except (
        OSError,
        UnidentifiedImageError,
        PillowImage.DecompressionBombError,
        PillowImage.DecompressionBombWarning,
    ):
        return None
    return io.BytesIO(raw)


def _idr(value: Any) -> str:
    try:
        amount = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("document amount must be integer rupiah") from exc
    return "Rp " + f"{amount:,}".replace(",", ".")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    regular_font, bold_font = _register_fonts()
    return {
        "body": ParagraphStyle(
            "HWBody", parent=base["BodyText"], fontName=regular_font,
            fontSize=7.2, leading=9.2, textColor=_NAVY, spaceAfter=1.5 * mm,
        ),
        "small": ParagraphStyle(
            "HWSmall", parent=base["BodyText"], fontName=regular_font,
            fontSize=6.1, leading=7.5, textColor=_MUTED,
        ),
        "label": ParagraphStyle(
            "HWLabel", parent=base["BodyText"], fontName=bold_font,
            fontSize=5.8, leading=7, textColor=_MUTED, uppercase=True,
        ),
        "table_header": ParagraphStyle(
            "HWTableHeader", parent=base["BodyText"], fontName=bold_font,
            fontSize=5.8, leading=7, textColor=colors.white, uppercase=True,
        ),
        "value": ParagraphStyle(
            "HWValue", parent=base["BodyText"], fontName=bold_font,
            fontSize=7.4, leading=9, textColor=_NAVY,
        ),
        "heading": ParagraphStyle(
            "HWHeading", parent=base["Heading2"], fontName=bold_font,
            fontSize=8.2, leading=10, textColor=_NAVY, spaceBefore=2 * mm,
            spaceAfter=1.5 * mm,
        ),
        "title": ParagraphStyle(
            "HWTitle", parent=base["Heading1"], fontName=bold_font,
            fontSize=15, leading=17, alignment=TA_RIGHT, textColor=_NAVY,
        ),
        "right": ParagraphStyle(
            "HWRight", parent=base["BodyText"], fontName=regular_font,
            fontSize=6.6, leading=8.2, alignment=TA_RIGHT, textColor=_NAVY,
        ),
        "center": ParagraphStyle(
            "HWCenter", parent=base["BodyText"], fontName=regular_font,
            fontSize=6.6, leading=8.2, alignment=TA_CENTER, textColor=_NAVY,
        ),
        "table": ParagraphStyle(
            "HWTable", parent=base["BodyText"], fontName=regular_font,
            fontSize=6.2, leading=7.4, textColor=_NAVY,
        ),
    }


def _header(snapshot: Mapping[str, Any], styles: Mapping[str, ParagraphStyle], logo_path: Path | None):
    issuer = _mapping(snapshot.get("issuer"))
    document = _mapping(snapshot.get("document"))
    document_type = _TYPE_LABELS.get(str(document.get("document_type")), "DOKUMEN")
    official_number = _text(document.get("official_number"), "DRAFT")
    logo: Any
    if logo_path and logo_path.is_file():
        logo = Image(str(logo_path), width=17 * mm, height=17 * mm)
    else:
        logo = Paragraph("<b>HOLLAWALL</b>", styles["value"])
    identity = Paragraph(
        f"<b>{_paragraph_text(issuer.get('display_name'), 'Hollawall')}</b><br/>"
        f"{_paragraph_text(issuer.get('legal_name'), 'CV Holla Berkreasi')}<br/>"
        f"{_paragraph_text(issuer.get('address'))}",
        styles["small"],
    )
    title = Paragraph(
        f"{document_type}<br/><font size='7'>{_paragraph_text(official_number)}</font>",
        styles["title"],
    )
    table = Table([[logo, identity, title]], colWidths=[20 * mm, 65 * mm, 45 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 1.4, _ORANGE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
    ]))
    return table


def _meta(snapshot: Mapping[str, Any], styles: Mapping[str, ParagraphStyle]):
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    client = _text(project.get("client_company"), _text(project.get("client_name")))
    client_details = " · ".join(item for item in [
        str(project.get("client_name") or "").strip(),
        str(project.get("client_contact") or "").strip(),
    ] if item)
    date_rows = [
        [
            Paragraph("TANGGAL TERBIT", styles["label"]),
            Paragraph(_paragraph_text(document.get("issue_date")), styles["right"]),
        ],
    ]
    if document.get("due_date"):
        date_rows.append([
            Paragraph("JATUH TEMPO", styles["label"]),
            Paragraph(_paragraph_text(document.get("due_date")), styles["right"]),
        ])
    if document.get("valid_until"):
        date_rows.append([
            Paragraph("BERLAKU HINGGA", styles["label"]),
            Paragraph(_paragraph_text(document.get("valid_until")), styles["right"]),
        ])
    left = [
        [Paragraph("KEPADA", styles["label"])],
        [Paragraph(_paragraph_text(client), styles["value"])],
        [Paragraph(
            _paragraph_text(client_details or project.get("client_address")),
            styles["small"],
        )],
        [Spacer(1, 1 * mm)],
        [Paragraph("PROYEK", styles["label"])],
        [Paragraph(_paragraph_text(project.get("name")), styles["value"])],
    ]
    left_table = Table(left, colWidths=[78 * mm])
    left_table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    right_table = Table(date_rows, colWidths=[24 * mm, 28 * mm])
    right_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9E0E8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
    ]))
    table = Table([[left_table, right_table]], colWidths=[78 * mm, 52 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return table


def _items(snapshot: Mapping[str, Any], styles: Mapping[str, ParagraphStyle]):
    rows: list[list[Any]] = [[
        Paragraph("DESKRIPSI", styles["table_header"]),
        Paragraph("QTY", styles["table_header"]),
        Paragraph("HARGA", styles["table_header"]),
        Paragraph("TOTAL", styles["table_header"]),
    ]]
    for item in snapshot.get("lines") or []:
        line = _mapping(item)
        quantity = f"{_text(line.get('quantity'), '0')} {_text(line.get('unit'), '')}".strip()
        rows.append([
            Paragraph(_paragraph_text(line.get("description")), styles["table"]),
            Paragraph(_paragraph_text(quantity), styles["table"]),
            Paragraph(_idr(line.get("unit_price")), styles["right"]),
            Paragraph(_idr(line.get("line_total")), styles["right"]),
        ])
    table = Table(rows, colWidths=[66 * mm, 18 * mm, 23 * mm, 23 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD4DE")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FB")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]))
    return table


def _totals(snapshot: Mapping[str, Any], styles: Mapping[str, ParagraphStyle]):
    totals = _mapping(snapshot.get("totals"))
    rows = [
        [Paragraph("Subtotal", styles["body"]), Paragraph(_idr(totals.get("subtotal")), styles["right"])],
    ]
    if int(totals.get("document_discount") or 0):
        rows.append([Paragraph("Diskon", styles["body"]), Paragraph("- " + _idr(totals.get("document_discount")), styles["right"])])
    if int(totals.get("tax") or 0):
        rows.append([Paragraph("Pajak", styles["body"]), Paragraph(_idr(totals.get("tax")), styles["right"])])
    rows.append([Paragraph("<b>TOTAL</b>", styles["value"]), Paragraph(f"<b>{_idr(totals.get('total'))}</b>", styles["right"])])
    table = Table(rows, colWidths=[32 * mm, 32 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 1.1, _CYAN),
        ("TOPPADDING", (0, 0), (-1, -1), 1.1 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.1 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _project_image(snapshot: Mapping[str, Any]):
    document = _mapping(snapshot.get("document"))
    project = _mapping(snapshot.get("project"))
    source = document.get("project_image_url") or project.get("project_image_url") or project.get("image_url")
    stream = _project_image_stream(source)
    if stream is None:
        return []
    image = Image(stream, width=130 * mm, height=42 * mm, kind="proportional")
    image.hAlign = "CENTER"
    return [KeepTogether([image, Spacer(1, 2 * mm)])]


def _notes_and_signatures(snapshot: Mapping[str, Any], styles: Mapping[str, ParagraphStyle]):
    document = _mapping(snapshot.get("document"))
    issuer = _mapping(snapshot.get("issuer"))
    bank = _mapping(issuer.get("bank_details"))
    notes = [
        Paragraph("CATATAN & PEMBAYARAN", styles["heading"]),
        Paragraph(
            _paragraph_text(document.get("notes"), "Tidak ada catatan tambahan."),
            styles["body"],
        ),
        Paragraph(
            _paragraph_text(document.get("payment_terms"), "Sesuai kesepakatan proyek."),
            styles["body"],
        ),
    ]
    if bank:
        bank_text = " · ".join(
            _text(bank.get(field))
            for field in ("bank", "account_number", "account_name")
        )
        notes.append(Paragraph(_paragraph_text(bank_text), styles["small"]))
    signatures = Table([
        [Paragraph("DISIAPKAN OLEH", styles["label"]), Paragraph("DISETUJUI KLIEN", styles["label"])],
        [Spacer(1, 13 * mm), Spacer(1, 13 * mm)],
        [
            Paragraph(
                _paragraph_text(
                    document.get("prepared_by"),
                    _text(issuer.get("display_name"), "Hollawall"),
                ),
                styles["center"],
            ),
            Paragraph(
                _paragraph_text(document.get("client_signatory"), "Nama & tanda tangan"),
                styles["center"],
            ),
        ],
    ], colWidths=[65 * mm, 65 * mm])
    signatures.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEABOVE", (0, 2), (0, 2), 0.5, _MUTED),
        ("LINEABOVE", (1, 2), (1, 2), 0.5, _MUTED),
        ("LINEBEFORE", (1, 0), (1, -1), 0.25, colors.HexColor("#D9E0E8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
    ]))
    return notes + [Spacer(1, 4 * mm), signatures]


def render_project_document_pdf(snapshot: Mapping[str, Any], *, logo_path: str | Path | None = _DEFAULT_LOGO) -> bytes:
    """Render immutable, deterministic A5 PDF bytes from one canonical snapshot."""

    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    styles = _styles()
    target = io.BytesIO()
    logo = Path(logo_path) if logo_path is not None else None
    doc = BaseDocTemplate(
        target,
        pagesize=A5,
        leftMargin=9 * mm,
        rightMargin=9 * mm,
        topMargin=9 * mm,
        bottomMargin=11 * mm,
        title=_text(_mapping(snapshot.get("document")).get("official_number"), "Hollawall Draft"),
        author="Hollawall",
        creator=RENDERER_VERSION,
        subject="Project commercial document",
        invariant=1,
        pageCompression=1,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="content")

    def decorate(canvas, built_doc):
        canvas.saveState()
        status = str(_mapping(snapshot.get("document")).get("status") or "draft").lower()
        watermark = _STATUS_WATERMARKS.get(status)
        if watermark:
            canvas.setFillColor(colors.Color(0.9, 0.2, 0.15, alpha=0.12))
            canvas.setFont("Helvetica-Bold", 38)
            canvas.translate(A5[0] / 2, A5[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, watermark)
            canvas.rotate(-35)
            canvas.translate(-A5[0] / 2, -A5[1] / 2)
        canvas.setStrokeColor(_ORANGE)
        canvas.setLineWidth(1.2)
        canvas.line(9 * mm, 7.5 * mm, A5[0] - 9 * mm, 7.5 * mm)
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 5.8)
        reference = _text(_mapping(snapshot.get("document")).get("official_number"), "DRAFT")
        canvas.drawString(9 * mm, 4.5 * mm, f"Hollawall · {reference}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="A5", frames=[frame], onPage=decorate)])
    story: list[Any] = [
        _header(snapshot, styles, logo),
        _meta(snapshot, styles),
        *_project_image(snapshot),
        _items(snapshot, styles),
        Spacer(1, 3 * mm),
        _totals(snapshot, styles),
        Spacer(1, 2 * mm),
        *_notes_and_signatures(snapshot, styles),
    ]
    doc.build(story)
    raw = target.getvalue()
    # Replace fixed-width placeholder in uncompressed page streams while keeping
    # deterministic bytes. ReportLab may compress streams, so a compact second
    # build with known page count is used instead of mutating PDF internals.
    total_pages = _page_count(raw)
    target = io.BytesIO()
    doc = BaseDocTemplate(
        target, pagesize=A5, leftMargin=9 * mm, rightMargin=9 * mm,
        topMargin=9 * mm, bottomMargin=11 * mm,
        title=_text(_mapping(snapshot.get("document")).get("official_number"), "Hollawall Draft"),
        author="Hollawall", creator=RENDERER_VERSION,
        subject="Project commercial document", invariant=1, pageCompression=1,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="content")

    def final_decorate(canvas, built_doc):
        decorate(canvas, built_doc)
        canvas.saveState()
        canvas.setFillColor(colors.white)
        canvas.rect(A5[0] - 44 * mm, 2.5 * mm, 35 * mm, 5 * mm, fill=1, stroke=0)
        canvas.setFillColor(_MUTED)
        canvas.setFont("Helvetica", 5.8)
        canvas.drawRightString(A5[0] - 9 * mm, 4.5 * mm, f"Halaman {canvas.getPageNumber()} / {total_pages}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="A5", frames=[frame], onPage=final_decorate)])
    story = [
        _header(snapshot, styles, logo), _meta(snapshot, styles),
        *_project_image(snapshot), _items(snapshot, styles),
        Spacer(1, 3 * mm), _totals(snapshot, styles), Spacer(1, 2 * mm),
        *_notes_and_signatures(snapshot, styles),
    ]
    doc.build(story)
    return target.getvalue()


def _page_count(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def render_project_document_artifact(snapshot: Mapping[str, Any]) -> tuple[bytes, str]:
    """Repository renderer adapter returning exact bytes and version."""

    return render_project_document_pdf(snapshot), RENDERER_VERSION
