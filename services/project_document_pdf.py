"""Deterministic branded PDFs for immutable project commercial documents.

The renderer deliberately accepts project artwork only as bounded PNG/JPEG data URLs.
Brand artwork is packaged with the application; remote and snapshot-supplied file URLs
are never opened.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image as PillowImage
from PIL import UnidentifiedImageError
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from services.commercial_document_policy import commercial_policy

RENDERER_VERSION = "branded-commercial-v8"
MAX_PROJECT_IMAGE_URL_CHARS = 196_608
MAX_PROJECT_IMAGE_BYTES = 144 * 1024
MAX_PROJECT_IMAGE_PIXELS = 16_000_000
PROJECT_IMAGE_PREFIXES = {
    "data:image/png;base64,": "PNG",
    "data:image/jpeg;base64,": "JPEG",
}

_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets/project-documents"
_DEFAULT_LOGO = _ASSET_DIR / "hollawall-logo.png"
_BRAND_LOGOS = {
    "hollawall": _ASSET_DIR / "hollawall-logo-reference.png",
    "hojja": _ASSET_DIR / "hojja-logo.png",
    "texturin": _ASSET_DIR / "texturin-logo.png",
    "texturin-surabaya": _ASSET_DIR / "texturin-logo.png",
    "texturin-bali": _ASSET_DIR / "texturin-logo.png",
}
_HOLLAWALL_FOOTER_LOGO = _ASSET_DIR / "hollawall-footer-logo.png"
_HOLLAWALL_FOOTER_LOGO_DATA = _HOLLAWALL_FOOTER_LOGO.read_bytes() if _HOLLAWALL_FOOTER_LOGO.is_file() else b""
_TEXTURIN_SIGNOFF = _ASSET_DIR / "texturin-evanvun-signoff.png"
_TEXTURIN_SIGNOFF_DATA = _TEXTURIN_SIGNOFF.read_bytes() if _TEXTURIN_SIGNOFF.is_file() else b""
_MASTER_ART = {
    key: path.read_bytes()
    for key, path in {
        "hollawall": _ASSET_DIR / "hollawall-master.png",
        "hojja": _ASSET_DIR / "hojja-master.png",
        "texturin": _ASSET_DIR / "texturin-surabaya-master.png",
        "texturin-surabaya": _ASSET_DIR / "texturin-surabaya-master.png",
        "texturin-bali": _ASSET_DIR / "texturin-bali-master.png",
    }.items()
    if path.is_file()
}

_INK = colors.HexColor("#1A1A1A")
_MUTED = colors.HexColor("#666666")
_HOLLA_CYAN = colors.HexColor("#18B8C6")
_HOLLA_LIGHT = colors.HexColor("#F5F5F5")
_HOJJA_PAPER = colors.HexColor("#E5E1D8")
_HOJJA_INK = colors.HexColor("#897B65")
_HOJJA_SAGE = colors.HexColor("#768276")
_TEXTURIN_WARM = colors.HexColor("#E3DCD4")
_TEXTURIN_INK = colors.HexColor("#3D3B3A")
_DISCOUNT = colors.HexColor("#E81E25")

_STATUS_WATERMARKS = {
    "draft": "DRAFT",
    "void": "VOID",
    "superseded": "SUPERSEDED",
}


@dataclass(frozen=True)
class BrandSpec:
    key: str
    page_size: tuple[float, float]
    left_margin: float
    right_margin: float
    top_margin: float
    bottom_margin: float
    identity: str
    primary: colors.Color
    ink: colors.Color
    paper: colors.Color


_BRANDS = {
    "hollawall": BrandSpec(
        "hollawall", A5, 10 * mm, 10 * mm, 8 * mm, 39 * mm,
        "Hollawall Mural Studio", _HOLLA_CYAN, _INK, colors.white,
    ),
    "hojja": BrandSpec(
        "hojja", A4, 28 * mm, 14 * mm, 12 * mm, 42 * mm,
        "HOJJA ArtHouse", _HOJJA_SAGE, _HOJJA_INK, _HOJJA_PAPER,
    ),
    "texturin": BrandSpec(
        "texturin", A4, 13 * mm, 13 * mm, 14 * mm, 20 * mm,
        "texturin decorative finishes", _TEXTURIN_WARM, _TEXTURIN_INK, colors.white,
    ),
    "texturin-surabaya": BrandSpec(
        "texturin-surabaya", A4, 13 * mm, 13 * mm, 14 * mm, 20 * mm,
        "texturin Surabaya · decorative finishes", _TEXTURIN_WARM, _TEXTURIN_INK, colors.white,
    ),
    "texturin-bali": BrandSpec(
        "texturin-bali", A4, 18 * mm, 13 * mm, 14 * mm, 20 * mm,
        "texturin Bali · decorative finishes", _TEXTURIN_WARM, _TEXTURIN_INK, colors.white,
    ),
}


def _is_texturin(brand: BrandSpec) -> bool:
    return brand.key.startswith("texturin")


def _register_fonts(brand: BrandSpec) -> tuple[str, str]:
    families = {
        "hojja": ("OpenSauceOne", "OpenSauceOne-Bold", "OpenSauceOne-Regular.ttf", "OpenSauceOne-Bold.ttf"),
        "texturin": ("HankenGrotesk", "HankenGrotesk-Bold", "HankenGrotesk-Regular.ttf", "HankenGrotesk-Bold.ttf"),
        "texturin-surabaya": ("HankenGrotesk", "HankenGrotesk-Bold", "HankenGrotesk-Regular.ttf", "HankenGrotesk-Bold.ttf"),
        "texturin-bali": ("HankenGrotesk", "HankenGrotesk-Bold", "HankenGrotesk-Regular.ttf", "HankenGrotesk-Bold.ttf"),
        "hollawall": ("Roboto", "Roboto-Bold", "Roboto-Regular.ttf", "Roboto-Bold.ttf"),
    }
    regular_name, bold_name, regular_file, bold_file = families[brand.key]
    regular = _ASSET_DIR / regular_file
    bold = _ASSET_DIR / bold_file
    registered = set(pdfmetrics.getRegisteredFontNames())
    if regular_name in registered and bold_name in registered:
        return regular_name, bold_name
    if regular.is_file() and bold.is_file():
        if regular_name not in registered:
            pdfmetrics.registerFont(TTFont(regular_name, str(regular)))
        if bold_name not in registered:
            pdfmetrics.registerFont(TTFont(bold_name, str(bold)))
        return regular_name, bold_name
    return "Helvetica", "Helvetica-Bold"


def _texturin_italic_font(brand: BrandSpec) -> str:
    regular, _ = _register_fonts(brand)
    path = _ASSET_DIR / "HankenGrotesk-Italic.ttf"
    if not _is_texturin(brand) or not path.is_file():
        return regular
    if "HankenGrotesk-Italic" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("HankenGrotesk-Italic", str(path)))
    return "HankenGrotesk-Italic"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any, fallback: str = "—") -> str:
    cleaned = str(value or "").strip()
    return cleaned or fallback


_INDONESIAN_MONTHS = (
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)


def _date_label(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return "—"
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError:
        return cleaned
    return f"{parsed.day:02d} {_INDONESIAN_MONTHS[parsed.month]} {parsed.year}"


def _paragraph_text(value: Any, fallback: str = "—") -> str:
    return escape(_text(value, fallback), quote=True)


def _normalize_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _brand_for(snapshot: Mapping[str, Any]) -> BrandSpec:
    project = _mapping(snapshot.get("project"))
    issuer = _mapping(snapshot.get("issuer"))
    document = _mapping(snapshot.get("document"))
    explicit = _normalize_identity(document.get("template_key"))
    explicit_brands = {
        "hollawall": "hollawall",
        "hojja": "hojja",
        "texturin": "texturin",
        "texturin surabaya": "texturin-surabaya",
        "texturin bali": "texturin-bali",
    }
    if explicit in explicit_brands:
        return _BRANDS[explicit_brands[explicit]]
    company = _normalize_identity(project.get("company"))
    wallet = _normalize_identity(project.get("wallet"))
    if "texturin bali" in explicit or "texturin bali" in company or "tx bali" in wallet:
        return _BRANDS["texturin-bali"]
    if (
        "texturin surabaya" in explicit or "texturin surabaya" in company
        or "textur sby" in company or "tx sby" in wallet
    ):
        return _BRANDS["texturin-surabaya"]
    candidates = " ".join(
        _normalize_identity(value)
        for value in (
            project.get("company"),
            project.get("issuer_key"),
            issuer.get("display_name"),
            issuer.get("issuer_key"),
            issuer.get("number_code"),
        )
    )
    if re.search(r"\b(?:texturin|tx)\b", candidates):
        return _BRANDS["texturin"]
    if re.search(r"\b(?:hojja|holja|hj)\b", candidates):
        return _BRANDS["hojja"]
    return _BRANDS["hollawall"]


def _document_title(snapshot: Mapping[str, Any]) -> str:
    document_type = str(_mapping(snapshot.get("document")).get("document_type") or "").lower()
    return {
        "sales_order": "QUOTATION",
        "quotation": "QUOTATION",
        "invoice": "INVOICE",
        "receipt": "RECEIPT",
    }.get(document_type, "COMMERCIAL DOCUMENT")


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


def _styles(brand: BrandSpec) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    regular, bold = _register_fonts(brand)
    small = 6.6 if brand.key == "hollawall" else (9.5 if brand.key == "hojja" else 10.0)
    body = 7.0 if brand.key == "hollawall" else (10.0 if brand.key == "hojja" else 10.2)
    return {
        "body": ParagraphStyle(
            f"{brand.key}-body", parent=base["BodyText"], fontName=regular,
            fontSize=body, leading=body * 1.35, textColor=brand.ink,
        ),
        "body_italic": ParagraphStyle(
            f"{brand.key}-body-italic", parent=base["BodyText"], fontName=_texturin_italic_font(brand),
            fontSize=body, leading=body * 1.4, textColor=brand.ink,
        ),
        "small": ParagraphStyle(
            f"{brand.key}-small", parent=base["BodyText"], fontName=regular,
            fontSize=small, leading=small * 1.35, textColor=brand.ink,
        ),
        "small_muted": ParagraphStyle(
            f"{brand.key}-small-muted", parent=base["BodyText"], fontName=regular,
            fontSize=small, leading=small * 1.35, textColor=_MUTED,
        ),
        "label": ParagraphStyle(
            f"{brand.key}-label", parent=base["BodyText"], fontName=bold,
            fontSize=small, leading=small * 1.3, textColor=brand.ink,
            uppercase=True, spaceAfter=0,
        ),
        "value": ParagraphStyle(
            f"{brand.key}-value", parent=base["BodyText"], fontName=regular,
            fontSize=body, leading=body * 1.35, textColor=brand.ink,
        ),
        "value_bold": ParagraphStyle(
            f"{brand.key}-value-bold", parent=base["BodyText"], fontName=bold,
            fontSize=body, leading=body * 1.35, textColor=brand.ink,
        ),
        "title": ParagraphStyle(
            f"{brand.key}-title", parent=base["Heading1"], fontName=bold,
            fontSize=28 if brand.key == "hojja" else (23.25 if _is_texturin(brand) else 16),
            leading=32 if brand.key == "hojja" else (27 if _is_texturin(brand) else 18),
            textColor=brand.ink, alignment=TA_LEFT,
        ),
        "right": ParagraphStyle(
            f"{brand.key}-right", parent=base["BodyText"], fontName=regular,
            fontSize=body, leading=body * 1.35, alignment=TA_RIGHT,
            textColor=brand.ink,
        ),
        "right_bold": ParagraphStyle(
            f"{brand.key}-right-bold", parent=base["BodyText"], fontName=bold,
            fontSize=body, leading=body * 1.35, alignment=TA_RIGHT,
            textColor=brand.ink,
        ),
        "center": ParagraphStyle(
            f"{brand.key}-center", parent=base["BodyText"], fontName=regular,
            fontSize=body, leading=body * 1.35, alignment=TA_CENTER,
            textColor=brand.ink,
        ),
        "table": ParagraphStyle(
            f"{brand.key}-table", parent=base["BodyText"], fontName=regular,
            fontSize=small, leading=small * 1.3, textColor=brand.ink,
        ),
        "table_right": ParagraphStyle(
            f"{brand.key}-table-right", parent=base["BodyText"], fontName=regular,
            fontSize=small, leading=small * 1.3, textColor=brand.ink,
            alignment=TA_RIGHT,
        ),
        "table_header": ParagraphStyle(
            f"{brand.key}-table-header", parent=base["BodyText"], fontName=bold,
            fontSize=small, leading=small * 1.25,
            textColor=colors.white if brand.key == "hojja" else _INK,
        ),
    }


def _safe_logo_path(brand: BrandSpec, logo_path: str | Path | None) -> Path | None:
    if logo_path is None:
        return None
    supplied = Path(logo_path)
    selected = _BRAND_LOGOS[brand.key] if supplied == _DEFAULT_LOGO else supplied
    return selected if selected.is_file() else None


def _image(path: Path, width: float, height: float) -> Image:
    return Image(str(path), width=width, height=height, kind="proportional")


def _zero_padding(table: Table) -> Table:
    table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _brand_header(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    styles: Mapping[str, ParagraphStyle],
    logo_path: str | Path | None,
) -> list[Flowable]:
    issuer = _mapping(snapshot.get("issuer"))
    logo = _safe_logo_path(brand, logo_path)
    title = _document_title(snapshot)
    display = _paragraph_text(issuer.get("display_name"), brand.identity)
    legal = _paragraph_text(issuer.get("legal_name"), "CV Holla Berkreasi")
    address = _paragraph_text(issuer.get("address"))

    if brand.key in _MASTER_ART:
        header: list[Flowable] = []
        if brand.key == "hollawall" and not _hollawall_issuer_fits(snapshot, brand):
            for field in ("legal_name", "address", "phone", "email"):
                if issuer.get(field):
                    header.append(Paragraph(_paragraph_text(issuer[field]), styles["small"]))
            header.append(Spacer(1, 3 * mm))
        if brand.key == "hojja" and not _hojja_phone_fits(snapshot, brand):
            header.extend([Paragraph(f"<b>Telepon:</b> {_paragraph_text(issuer.get('phone'))}", styles["small"]), Spacer(1, 3 * mm)])
        return [*header, Paragraph(title.title(), styles["title"]), Spacer(1, (2 if brand.key == "hollawall" else 5) * mm)]

    if brand.key == "hollawall":
        mark = _image(logo, 20 * mm, 23 * mm) if logo else Paragraph("<b>HOLLAWALL</b>", styles["value_bold"])
        contact = Paragraph(f"<b>{legal}</b><br/>{address}<br/>{_paragraph_text(issuer.get('phone'))}<br/>{_paragraph_text(issuer.get('email'))}", styles["small"])
        header = _zero_padding(Table([[mark, contact]], colWidths=[35 * mm, 95 * mm]))
        return [header, Spacer(1, 3 * mm), Paragraph(title.title(), styles["title"]), Spacer(1, 2 * mm)]

    if brand.key == "hojja":
        mark = (
            _image(logo, 50 * mm, 18 * mm)
            if logo else Paragraph("<b>HOJJA ArtHouse</b>", styles["value_bold"])
        )
        heading = Table(
            [[Paragraph(title, styles["title"]), mark]],
            colWidths=[96 * mm, 62 * mm],
        )
        heading.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
        ]))
        return [heading, Spacer(1, 9 * mm)]

    mark = (
        _image(logo, 56 * mm, 23 * mm)
        if logo else Paragraph("<b>texturin</b><br/>decorative finishes", styles["value_bold"])
    )
    identity = Paragraph(
        f"<b>{brand.identity}</b><br/>{display}<br/>{legal}<br/>{address}",
        styles["small"],
    )
    header = Table([[mark, identity]], colWidths=[100 * mm, 84 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [header, Spacer(1, 7 * mm), Paragraph(title, styles["title"]), Spacer(1, 5 * mm)]


def _metadata(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    styles: Mapping[str, ParagraphStyle],
) -> Flowable:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    client = _text(project.get("client_company"), _text(project.get("client_name")))
    client_parts = [
        str(project.get("client_name") or "").strip(),
        str(project.get("client_contact") or "").strip(),
        str(project.get("client_address") or "").strip(),
    ]
    normalized_client = _normalize_identity(client)
    client_details = " · ".join(
        value
        for value in client_parts
        if value and _normalize_identity(value) != normalized_client
    )
    title = _document_title(snapshot)
    if brand.key == "hojja":
        date_rows: list[list[Flowable]] = [
            [Paragraph("DATE", styles["label"]), Paragraph(_paragraph_text(document.get("issue_date")), styles["right"])],
            [Paragraph("LETTER ID", styles["label"]), Paragraph(_paragraph_text(document.get("official_number"), "DRAFT"), styles["right"])],
        ]
    elif _is_texturin(brand):
        number_label = "QUOTATION NO." if title == "QUOTATION" else "INVOICE NO."
        date_rows = [
            [Paragraph(number_label, styles["label"]), Paragraph(_paragraph_text(document.get("official_number"), "DRAFT"), styles["right"])],
            [Paragraph("DATE", styles["label"]), Paragraph(_paragraph_text(document.get("issue_date")), styles["right"])],
        ]
    else:
        date_rows = [
            [Paragraph("TANGGAL", styles["label"]), Paragraph(_paragraph_text(document.get("issue_date")), styles["right"])],
            [Paragraph("LETTER NO.", styles["label"]), Paragraph(_paragraph_text(document.get("official_number"), "DRAFT"), styles["right"])],
        ]
    if _master_is_invoice(snapshot) and document.get("due_date"):
        date_rows.append([Paragraph("DUE DATE", styles["label"]), Paragraph(_paragraph_text(document.get("due_date")), styles["right"])])
    if not _master_is_invoice(snapshot) and document.get("valid_until"):
        date_rows.append([Paragraph("VALID UNTIL", styles["label"]), Paragraph(_paragraph_text(document.get("valid_until")), styles["right"])])

    if _is_texturin(brand):
        left_label_width, right_label_width = 20 * mm, 34 * mm
        widths = [102 * mm, 82 * mm]
    elif brand.key == "hojja":
        left_label_width, right_label_width = 19 * mm, 28 * mm
        widths = [92 * mm, 66 * mm]
    else:
        left_label_width, right_label_width = 17 * mm, 23 * mm
        widths = [75 * mm, 55 * mm]

    client_rows = [[Paragraph("TO", styles["label"]), Paragraph(_paragraph_text(client), styles["value"])]]
    if client_details:
        client_rows.append([Paragraph("", styles["label"]), Paragraph(_paragraph_text(client_details), styles["small"])])
    client_rows.append([Paragraph("PROJECT", styles["label"]), Paragraph(_paragraph_text(project.get("name")), styles["value_bold"])])
    left = Table(client_rows, colWidths=[left_label_width, widths[0] - left_label_width])
    _zero_padding(left)
    right = Table(date_rows, colWidths=[right_label_width, widths[1] - right_label_width])
    _zero_padding(right)
    table = Table([[left, right]], colWidths=widths)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _items(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    styles: Mapping[str, ParagraphStyle],
) -> Flowable:
    if brand.key == "hollawall":
        widths = [7 * mm, 67 * mm, 15 * mm, 20 * mm, 21 * mm]
        headers = ["", "DESCRIPTION", "AREA", "HARGA/M²", "JUMLAH"]
    elif brand.key == "hojja":
        widths = [103 * mm, 18 * mm, 37 * mm]
        headers = ["DESCRIPTION", "QTY", "TOTAL"]
    else:
        widths = [12 * mm, 68 * mm, 35 * mm, 28 * mm, 41 * mm]
        headers = ["NO.", "DESCRIPTION", "PPM", "QTY/LUAS", "TOTAL"]

    rows: list[list[Flowable]] = [[Paragraph(header, styles["table_header"]) for header in headers]]
    for index, item in enumerate(snapshot.get("lines") or [], start=1):
        line = _mapping(item)
        quantity = f"{_text(line.get('quantity'), '0')} {_text(line.get('unit'), '')}".strip()
        description_text = _paragraph_text(line.get("description"))
        line_discount = int(line.get("line_discount") or 0)
        if line_discount:
            rate = _text(line.get("line_discount_percent"), "0")
            description_text += f"<br/><font color='#775D4F'>Diskon item {escape(rate)}%: -{_idr(line_discount)}</font>"
        row: list[Any]
        if brand.key == "hollawall":
            row = [
                Paragraph(f"<b>{index}.</b>", styles["table"]),
                Paragraph(description_text, styles["table"]),
                Paragraph(_paragraph_text(quantity), styles["table"]),
                Paragraph(_idr(line.get("unit_price")), styles["table_right"]),
                Paragraph(_idr(line.get("line_total")), styles["table_right"]),
            ]
        elif brand.key == "hojja":
            meta = _mapping(line.get("commercial_meta"))
            if meta.get("width") and meta.get("height"):
                dimensions = f"({_text(meta['width'])} × {_text(meta['height'])} {_text(meta.get('dimension_unit'), 'm')})"
                description_text += f"<br/>{escape(dimensions)}"
            description: list[Flowable] = [
                Paragraph(description_text, styles["table"]),
            ]
            document = _mapping(snapshot.get("document"))
            project = _mapping(snapshot.get("project"))
            source = document.get("project_image_url") or project.get("project_image_url") or project.get("image_url")
            stream = _project_image_stream(source)
            if index == 1 and stream is not None:
                artwork = Image(stream, width=78 * mm, height=38 * mm, kind="proportional")
                artwork.hAlign = "LEFT"
                description.extend([Spacer(1, 2 * mm), artwork])
            gross = int(meta.get("original_price") or line.get("line_gross") or line.get("line_total") or 0)
            line_total = int(line.get("line_total") or 0)
            price = _idr(line_total)
            if gross > line_total:
                price = f"<strike>{_idr(gross)}</strike><br/><b>{_idr(line_total)}</b>"
            row = [
                description,
                Paragraph(_paragraph_text(meta.get("display_quantity") or quantity), styles["table"]),
                Paragraph(price, styles["table_right"]),
            ]
        else:
            row = [
                Paragraph(str(index), styles["table"]),
                Paragraph(description_text, styles["table"]),
                Paragraph(_idr(line.get("unit_price")), styles["table_right"]),
                Paragraph(_paragraph_text(quantity), styles["table_right"]),
                Paragraph(_idr(line.get("line_total")), styles["table_right"]),
            ]
        rows.append(list(row))

    table = Table(rows, colWidths=widths, repeatRows=1, splitByRow=1, splitInRow=1)
    header_background = _HOJJA_SAGE if brand.key == "hojja" else (
        _TEXTURIN_WARM if _is_texturin(brand) else _HOLLA_LIGHT
    )
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), header_background),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.1 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.1 * mm),
        ("LINEBELOW", (0, -1), (-1, -1), 0.55, brand.ink),
    ]
    if brand.key == "hollawall":
        commands.extend([
            ("BACKGROUND", (0, 0), (0, 0), _HOLLA_CYAN),
            ("LINEBELOW", (0, 0), (-1, 0), 0.3, colors.HexColor("#D6D6D6")),
        ])
    elif brand.key == "hojja":
        commands.extend([
            ("LINEBEFORE", (-1, 1), (-1, -1), 0.35, _HOJJA_INK),
            ("LINEBELOW", (0, 0), (-1, 0), 0.35, _HOJJA_INK),
        ])
    else:
        commands.append(("LINEBELOW", (0, 0), (-1, 0), 0.35, colors.HexColor("#D0CBC4")))
    table.setStyle(TableStyle(commands))
    return table


def _project_image(snapshot: Mapping[str, Any], brand: BrandSpec) -> list[Flowable]:
    if brand.key == "hojja":
        return []
    document = _mapping(snapshot.get("document"))
    project = _mapping(snapshot.get("project"))
    source = document.get("project_image_url") or project.get("project_image_url") or project.get("image_url")
    stream = _project_image_stream(source)
    if stream is None:
        return []
    max_width = 126 * mm if brand.key == "hollawall" else 158 * mm
    max_height = 40 * mm if brand.key == "hollawall" else 58 * mm
    image = Image(stream, width=max_width, height=max_height, kind="proportional")
    image.hAlign = "LEFT"
    return [Spacer(1, 2 * mm), image, Spacer(1, 2 * mm)]


def _totals(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    styles: Mapping[str, ParagraphStyle],
) -> Flowable:
    totals = _mapping(snapshot.get("totals"))
    discount = int(totals.get("document_discount") or 0)
    tax = int(totals.get("tax") or 0)
    rows: list[list[Flowable]] = [
        [Paragraph("Subtotal", styles["body"]), Paragraph(_idr(totals.get("subtotal")), styles["right"])],
    ]
    if discount:
        rows.append([
            Paragraph("Diskon", styles["body"]),
            Paragraph(f"<font color='#{_DISCOUNT.hexval()[2:]}'>- {_idr(discount)}</font>", styles["right"]),
        ])
    if tax:
        rows.append([Paragraph("Pajak", styles["body"]), Paragraph(_idr(tax), styles["right"])])
    document = _mapping(snapshot.get("document"))
    invoice_kind = str(document.get("invoice_kind") or "").upper()
    is_dp_invoice = _master_is_invoice(snapshot) and invoice_kind == "DP"
    total_label = "TOTAL DP" if is_dp_invoice else "TOTAL"
    if brand.key == "hojja" and is_dp_invoice:
        total_label = "Total DP"
    total_text = f"<b>{total_label}</b>"
    total_amount = f"<b>{_idr(totals.get('total'))}</b>"
    if brand.key == "hojja":
        total_text = f"<font color='white'>{total_text}</font>"
        total_amount = f"<font color='white'>{total_amount}</font>"
    rows.append([Paragraph(total_text, styles["value_bold"]), Paragraph(total_amount, styles["right_bold"])])
    if _is_texturin(brand):
        total_width = brand.page_size[0] - brand.left_margin - brand.right_margin
        rows = [[Paragraph("", styles["body"]), *row] for row in rows]
        widths = [total_width - 63 * mm, 28 * mm, 35 * mm]
    else:
        total_width = 75 * mm if brand.key != "hollawall" else 60 * mm
        widths = [total_width * 0.48, total_width * 0.52]
    table = Table(rows, colWidths=widths, hAlign="RIGHT")
    commands: list[tuple[Any, ...]] = [
        ("TOPPADDING", (0, 0), (-1, -1), 1.3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
        ("LINEABOVE", (0, 0), (-1, 0), 0.65, brand.ink),
        ("LINEBELOW", (0, -1), (-1, -1), 0.65, brand.ink),
    ]
    if brand.key == "hojja":
        commands.extend([
            ("BACKGROUND", (0, -1), (-1, -1), _HOJJA_SAGE),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ])
    elif _is_texturin(brand):
        commands.append(("BACKGROUND", (0, -1), (-1, -1), _TEXTURIN_WARM))
    else:
        commands.append(("BACKGROUND", (0, -1), (-1, -1), _HOLLA_LIGHT))
    table.setStyle(TableStyle(commands))
    return table


def _notes_and_signatures(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    styles: Mapping[str, ParagraphStyle],
    logo_path: str | Path | None,
) -> list[Flowable]:
    document = _mapping(snapshot.get("document"))
    issuer = _mapping(snapshot.get("issuer"))
    bank = _mapping(issuer.get("bank_details"))
    if _is_texturin(brand):
        terms: list[Flowable] = []
        for index, value in enumerate(_texturin_master_terms(snapshot, brand).split("\n\n")):
            if index:
                terms.append(Spacer(1, 1 * mm))
            terms.append(Paragraph(_paragraph_text(value), styles["body_italic"]))
        bank_lines: list[Flowable] = [Paragraph(
            f"<b>BANK DETAILS</b>  Bank {_paragraph_text(bank.get('bank'))}", styles["small"]
        )]
        if bank:
            bank_lines.extend([
                Paragraph(f"Account Name: {_paragraph_text(bank.get('account_name'))}", styles["small"]),
                Paragraph(f"Account No.: {_paragraph_text(bank.get('account_number'))}", styles["small"]),
            ])
        signoff: Flowable | str = ""
        if _TEXTURIN_SIGNOFF_DATA:
            signoff = Image(io.BytesIO(_TEXTURIN_SIGNOFF_DATA), width=38 * mm, height=26 * mm, kind="proportional")
            signoff.hAlign = "RIGHT"
        width = brand.page_size[0] - brand.left_margin - brand.right_margin
        closure = Table([[bank_lines, signoff]], colWidths=[width - 40 * mm, 40 * mm])
        _zero_padding(closure)
        signatories: list[Flowable] = []
        for label, field in (("Disiapkan oleh", "prepared_by"), ("Penanda tangan klien", "client_signatory")):
            if document.get(field):
                signatories.append(Paragraph(f"<b>{label}:</b> {_paragraph_text(document[field])}", styles["small"]))
        return [*terms, Spacer(1, 4 * mm), closure, *([Spacer(1, 2 * mm), *signatories] if signatories else [])]

    heading = "BANK DETAILS" if _is_texturin(brand) else "Payment Information"
    notes: list[Flowable] = [
        Paragraph(f"<b>{heading}</b>", styles["value_bold"]),
        Spacer(1, 1.5 * mm),
        Paragraph(_paragraph_text(document.get("notes"), "Tidak ada catatan tambahan."), styles["body"]),
        Spacer(1, 1 * mm),
        Paragraph(_paragraph_text(document.get("payment_terms"), "Sesuai kesepakatan Project."), styles["body"]),
    ]
    if bank:
        bank_text = " · ".join(_text(bank.get(field)) for field in ("bank", "account_number", "account_name"))
        notes.extend([Spacer(1, 1 * mm), Paragraph(f"<b>{_paragraph_text(bank_text)}</b>", styles["small"])])

    prepared = _paragraph_text(document.get("prepared_by"), _text(issuer.get("display_name"), brand.identity))
    approved = _paragraph_text(document.get("client_signatory"), "Nama & tanda tangan")
    if brand.key == "hollawall":
        heading = Table([["", Paragraph("<b>Payment Information</b>", styles["value_bold"])]], colWidths=[8 * mm, 122 * mm])
        heading.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), _HOLLA_CYAN),
            ("BACKGROUND", (1, 0), (1, 0), _HOLLA_LIGHT),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        notes[0] = heading
        signoff_text = Paragraph(f"Best regards and thank you,<br/><b>{prepared}<br/>Mural Studio</b>", styles["right"])
        logo: Flowable | str = ""
        if logo_path is not None and _HOLLAWALL_FOOTER_LOGO.is_file():
            logo = _image(_HOLLAWALL_FOOTER_LOGO, 11 * mm, 12 * mm)
            logo.hAlign = "RIGHT"
        signoff = Table([[signoff_text, logo]], colWidths=[38 * mm, 12 * mm], hAlign="RIGHT")
        _zero_padding(signoff)
        signoff_items: list[Flowable] = [signoff]
        if document.get("client_signatory"):
            signoff_items.append(Paragraph(f"Penanda tangan klien: {approved}", styles["small_muted"]))
        return [*notes, Spacer(1, 2 * mm), KeepTogether(signoff_items)]

    signatures = Table([
        [Paragraph("DISIAPKAN OLEH", styles["label"]), Paragraph("DISETUJUI KLIEN", styles["label"])],
        [Spacer(1, 12 * mm), Spacer(1, 12 * mm)],
        [Paragraph(prepared, styles["center"]), Paragraph(approved, styles["center"])],
    ], colWidths=[65 * mm, 65 * mm] if brand.key == "hollawall" else [79 * mm, 79 * mm])
    signatures.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.45, brand.ink),
        ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return notes + [Spacer(1, 5 * mm), signatures]


def _quotation_deposit(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    styles: Mapping[str, ParagraphStyle],
) -> Flowable:
    policy = commercial_policy(brand.key)
    percent = _snapshot_deposit_percent(snapshot, brand)
    total = int(_mapping(snapshot.get("totals")).get("total") or 0)
    amount = (total * percent + 50) // 100
    label = f"SIGNATURE FEE ({percent}%)" if _is_texturin(brand) else f"{policy['labels']['deposit']} {percent}%"
    label_text, amount_text = f"<b>{label}</b>", f"<b>{_idr(amount)}</b>"
    if brand.key == "hojja":
        label_text = f"<font color='white'>{label_text}</font>"
        amount_text = f"<font color='white'>{amount_text}</font>"
    table = Table([
        [
            Paragraph(label_text, styles["value_bold"]),
            Paragraph(amount_text, styles["right_bold"]),
        ],
    ], colWidths=[52 * mm, 45 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _HOJJA_SAGE if brand.key == "hojja" else (_TEXTURIN_WARM if _is_texturin(brand) else _HOLLA_LIGHT)),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    return table


def _story(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    logo_path: str | Path | None,
) -> list[Flowable]:
    styles = _styles(brand)
    leading = [
        *_brand_header(snapshot, brand, styles, logo_path),
        _metadata(snapshot, brand, styles),
        Spacer(1, 5 * mm if brand.key != "hollawall" else 3 * mm),
        _items(snapshot, brand, styles),
        *_project_image(snapshot, brand),
        Spacer(1, 7 * mm if brand.key != "hollawall" else 4 * mm),
    ]
    trailing: list[Flowable] = [
        _totals(snapshot, brand, styles),
        Spacer(1, 6 * mm if brand.key != "hollawall" else 4 * mm),
    ]
    if _master_has_deposit(snapshot):
        trailing.extend([_quotation_deposit(snapshot, brand, styles), Spacer(1, 4 * mm)])
    trailing.extend(_notes_and_signatures(snapshot, brand, styles, logo_path))
    return [*leading, *trailing]


def _draw_brand_page(
    canvas: Any,
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    total_pages: int | None,
    logo_path: str | Path | None,
) -> None:
    page_width, page_height = brand.page_size
    canvas.saveState()
    canvas.setFillColor(brand.paper)
    canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    if brand.key == "hollawall":
        master = _MASTER_ART.get("hollawall")
        if master:
            canvas.saveState()
            clip = canvas.beginPath()
            clip.rect(0, page_height * .835, page_width, page_height * .165)
            clip.rect(0, 0, page_width, page_height * .10)
            canvas.clipPath(clip, stroke=0, fill=0)
            canvas.drawImage(ImageReader(io.BytesIO(master)), 0, 0, width=page_width, height=page_height, mask="auto")
            canvas.restoreState()
        issuer = _mapping(snapshot.get("issuer"))
        if _hollawall_issuer_fits(snapshot, brand):
            _canvas_text(canvas, brand, issuer.get("legal_name"), .68, .045, size=7, bold=True, color=_HOLLA_CYAN)
            _canvas_text(canvas, brand, issuer.get("address"), .68, .062, size=6.5, color=_HOLLA_CYAN)
            _canvas_text(canvas, brand, issuer.get("phone"), .68, .079, size=6.5, color=_HOLLA_CYAN)
            _canvas_text(canvas, brand, issuer.get("email"), .68, .096, size=6.5, color=_HOLLA_CYAN)
    elif brand.key == "hojja":
        master = _MASTER_ART.get(brand.key)
        if master:
            canvas.saveState()
            clip = canvas.beginPath()
            clip.rect(0, page_height * .86, page_width, page_height * .14)
            clip.rect(0, 0, page_width, page_height * .14)
            canvas.clipPath(clip, stroke=0, fill=0)
            canvas.drawImage(ImageReader(io.BytesIO(master)), 0, 0, width=page_width, height=page_height, mask="auto")
            canvas.restoreState()
            canvas.setFillColor(colors.Color(229 / 255, 225 / 255, 216 / 255))
            canvas.rect(page_width * .13, page_height * .865, page_width * .52, page_height * .065, fill=1, stroke=0)
            canvas.rect(page_width * .13, page_height * .86, page_width * .78, page_height * .005, fill=1, stroke=0)
            _draw_hojja_contact(canvas, snapshot, brand)
        else:
            canvas.setStrokeColor(_HOJJA_INK)
            canvas.line(0, 36 * mm, page_width, 36 * mm)
            _canvas_text(canvas, brand, "HOJJA ArtHouse", .15, .91, size=10, bold=True)
            _canvas_text(canvas, brand, _mapping(snapshot.get("issuer")).get("phone"), .15, .95, size=9)
        canvas.setStrokeColor(_HOJJA_INK)
        canvas.setLineWidth(0.55)
        canvas.line(15.5 * mm, 0, 15.5 * mm, page_height)
    else:
        master = _MASTER_ART.get(brand.key)
        if master:
            canvas.saveState()
            clip = canvas.beginPath()
            clip.rect(0, page_height * .86, page_width, page_height * .14)
            canvas.clipPath(clip, stroke=0, fill=0)
            canvas.drawImage(ImageReader(io.BytesIO(master)), 0, 0, width=page_width, height=page_height, mask="auto")
            canvas.restoreState()
        canvas.setStrokeColor(_TEXTURIN_WARM)
        canvas.setLineWidth(0.5)
        canvas.line(13 * mm, 12 * mm, page_width - 13 * mm, 12 * mm)

    status = str(_mapping(snapshot.get("document")).get("status") or "draft").lower()
    watermark = _STATUS_WATERMARKS.get(status)
    if watermark:
        canvas.saveState()
        canvas.setFillColor(colors.Color(0.75, 0.18, 0.15, alpha=0.12))
        canvas.setFont("Helvetica-Bold", 42 if brand.page_size == A4 else 34)
        canvas.translate(page_width / 2, page_height / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, watermark)
        canvas.restoreState()

    reference = _text(_mapping(snapshot.get("document")).get("official_number"), "DRAFT")
    footer_y = 6 * mm if brand.key == "hollawall" else (8 * mm if brand.key == "hojja" else 5 * mm)
    footer_left = 48 * mm if brand.key == "hollawall" else brand.left_margin
    canvas.setFillColor(brand.ink)
    canvas.setFont("Helvetica", 5.8)
    footer_text = f"{brand.identity} · {reference}"
    footer_width = page_width - brand.right_margin - footer_left - (30 * mm if total_pages is not None else 0)
    if pdfmetrics.stringWidth(footer_text, "Helvetica", 5.8) > footer_width:
        while footer_text and pdfmetrics.stringWidth(footer_text + "...", "Helvetica", 5.8) > footer_width:
            footer_text = footer_text[:-1]
        footer_text += "..."
    canvas.drawString(footer_left, footer_y, footer_text)
    if total_pages is not None:
        canvas.drawRightString(
            page_width - brand.right_margin,
            footer_y,
            f"Halaman {canvas.getPageNumber()} / {total_pages}",
        )
    canvas.restoreState()


def _canvas_text(
    canvas: Any,
    brand: BrandSpec,
    text: Any,
    x: float,
    top: float,
    *,
    size: float,
    bold: bool = False,
    right: bool = False,
    color: colors.Color | None = None,
) -> None:
    regular, bold_font = _register_fonts(brand)
    canvas.setFont(bold_font if bold else regular, size)
    canvas.setFillColor(color or brand.ink)
    y = brand.page_size[1] * (1 - top)
    value = _text(text)
    if right:
        canvas.drawRightString(brand.page_size[0] * x, y, value)
    else:
        canvas.drawString(brand.page_size[0] * x, y, value)


def _draw_hojja_contact(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.Color(229 / 255, 225 / 255, 216 / 255))
    canvas.rect(brand.page_size[0] * .19, brand.page_size[1] * .035,
                brand.page_size[0] * .40, brand.page_size[1] * .026, fill=1, stroke=0)
    if _hojja_phone_fits(snapshot, brand):
        _canvas_text(canvas, brand, _mapping(snapshot.get("issuer")).get("phone"), .20, .956,
                     size=12, color=colors.HexColor("#897B65"))
    canvas.restoreState()


def _canvas_paragraph(
    canvas: Any,
    brand: BrandSpec,
    text: Any,
    x: float,
    top: float,
    width: float,
    *,
    size: float,
    leading: float | None = None,
    italic: bool = False,
) -> None:
    regular, _ = _register_fonts(brand)
    style = ParagraphStyle(
        f"master-{brand.key}-{x}-{top}",
        fontName=_texturin_italic_font(brand) if italic else regular,
        fontSize=size,
        leading=leading or size * 1.3,
        textColor=brand.ink,
        alignment=TA_LEFT,
    )
    value = _paragraph_text(text).replace("\n", "<br/>")
    paragraph = Paragraph(value, style)
    available = brand.page_size[0] * width
    _, height = paragraph.wrap(available, brand.page_size[1])
    paragraph.drawOn(
        canvas,
        brand.page_size[0] * x,
        brand.page_size[1] * (1 - top) - height,
    )


def _draw_master_watermark(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    status = str(_mapping(snapshot.get("document")).get("status") or "draft").lower()
    watermark = _STATUS_WATERMARKS.get(status)
    if not watermark:
        return
    canvas.saveState()
    canvas.setFillColor(colors.Color(0.45, 0.48, 0.52, alpha=0.16))
    canvas.setFont("Helvetica-Bold", 36 if brand.page_size == A4 else 28)
    canvas.translate(brand.page_size[0] * .72, brand.page_size[1] * .45)
    canvas.rotate(38)
    canvas.drawCentredString(0, 0, watermark)
    canvas.restoreState()


def _draw_master_project_image(
    canvas: Any,
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    x: float,
    top: float,
    width: float,
    height: float,
) -> None:
    document = _mapping(snapshot.get("document"))
    project = _mapping(snapshot.get("project"))
    stream = _project_image_stream(document.get("project_image_url") or project.get("project_image_url") or project.get("image_url"))
    if stream is None:
        return
    canvas.drawImage(
        ImageReader(stream),
        brand.page_size[0] * x,
        brand.page_size[1] * (1 - top - height),
        width=brand.page_size[0] * width,
        height=brand.page_size[1] * height,
        preserveAspectRatio=True,
        anchor="c",
        mask="auto",
    )


def _master_lines(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_mapping(value) for value in snapshot.get("lines") or []]


def _master_document_type(snapshot: Mapping[str, Any]) -> str:
    return str(_mapping(snapshot.get("document")).get("document_type") or "").strip().lower()


def _master_is_receipt(snapshot: Mapping[str, Any]) -> bool:
    return _master_document_type(snapshot) == "receipt"


def _master_is_invoice(snapshot: Mapping[str, Any]) -> bool:
    return _master_document_type(snapshot) == "invoice"


def _master_has_deposit(snapshot: Mapping[str, Any]) -> bool:
    return _master_document_type(snapshot) in {"quotation", "sales_order"}


def _snapshot_deposit_percent(snapshot: Mapping[str, Any], brand: BrandSpec) -> int:
    document = _mapping(snapshot.get("document"))
    value = document.get("deposit_percent")
    if value is None:
        value = commercial_policy(brand.key).get("default_deposit_percent")
    return int(value or 0)


def _texturin_master_terms(snapshot: Mapping[str, Any], brand: BrandSpec) -> str:
    document = _mapping(snapshot.get("document"))
    policy = commercial_policy(brand.key)
    terms = [] if _master_is_invoice(snapshot) else [*policy.get("default_terms", [])]
    percent = _snapshot_deposit_percent(snapshot, brand)
    terms = [
        re.sub(r"signature fee sebesar \d+(?:[.,]\d+)?%", f"signature fee sebesar {percent}%", term, flags=re.IGNORECASE)
        for term in terms
    ]
    terms.extend(
        str(value).strip()
        for value in (document.get("payment_terms"), document.get("notes"))
        if str(value or "").strip()
    )
    if not terms:
        terms = ["Pembayaran sesuai tanggal jatuh tempo yang tercantum."]
    return "\n\n".join(terms)


def _texturin_master_terms_fit(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    regular = _texturin_italic_font(brand)
    style = ParagraphStyle(
        f"master-fit-{brand.key}",
        fontName=regular,
        fontSize=10.2,
        leading=14.2,
        textColor=brand.ink,
        alignment=TA_LEFT,
    )
    value = _paragraph_text(_texturin_master_terms(snapshot, brand)).replace("\n", "<br/>")
    paragraph = Paragraph(value, style)
    _, height = paragraph.wrap(brand.page_size[0] * .87, brand.page_size[1])
    available = brand.page_size[1] * (.922 - .65) - 14.2
    return height <= available


def _commercial_terms(snapshot: Mapping[str, Any], default: str) -> str:
    document = _mapping(snapshot.get("document"))
    parts = [str(document.get(key) or "").strip() for key in ("payment_terms", "notes")]
    return "\n\n".join(part for part in parts if part) or default


def _hollawall_issuer_fits(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    issuer = _mapping(snapshot.get("issuer"))
    regular, bold = _register_fonts(brand)
    fields = (("legal_name", bold, 7), ("address", regular, 6.5),
              ("phone", regular, 6.5), ("email", regular, 6.5))
    header_fits = all(
        "\n" not in _text(issuer.get(field))
        and pdfmetrics.stringWidth(_text(issuer.get(field)), font, size) <= brand.page_size[0] * .29
        for field, font, size in fields
    )
    display = _text(issuer.get("display_name"))
    return header_fits and "\n" not in display and pdfmetrics.stringWidth(display, bold, 8) <= brand.page_size[0] * .16


def _hojja_phone_fits(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    phone = _text(_mapping(snapshot.get("issuer")).get("phone"))
    regular, _ = _register_fonts(brand)
    return "\n" not in phone and pdfmetrics.stringWidth(phone, regular, 12) <= brand.page_size[0] * .38


def _master_item_columns_fit(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    regular, _ = _register_fonts(brand)
    width = brand.page_size[0]
    for line in _master_lines(snapshot):
        if int(line.get("line_discount") or 0):
            return False
        quantity = f"{_text(line.get('quantity'))} {_text(line.get('unit'), '')}".strip()
        if brand.key == "hollawall":
            fields = ((quantity, .57, .43, 6.6), (_idr(line.get("unit_price")), .73, .59, 6.6),
                      (_idr(line.get("line_total")), .90, .75, 6.6))
            description_limit, description_size = .14, 6.8
            description_end = .57 * width - pdfmetrics.stringWidth(quantity, regular, 6.6) - 4
        elif brand.key == "hojja":
            meta = _mapping(line.get("commercial_meta"))
            quantity = _text(meta.get("display_quantity") or line.get("quantity"))
            fields = ((quantity, .67, .53, 10), (_idr(line.get("line_total")), .89, .69, 10))
            if meta.get("original_price"):
                fields += ((_idr(meta["original_price"]), .89, .69, 10),)
            if meta.get("width") and meta.get("height"):
                dimensions = f"({_text(meta['width'])} × {_text(meta['height'])} {_text(meta.get('dimension_unit'), 'm')})"
                if "\n" in dimensions or pdfmetrics.stringWidth(dimensions, regular, 9) > .36 * width:
                    return False
            description_limit, description_size = .15, 10
            description_end = .67 * width - pdfmetrics.stringWidth(quantity, regular, 10) - 5
        else:
            fields = ((_idr(line.get("unit_price")), .553, .42, 10.5),
                      (quantity, .710, .57, 10.5), (_idr(line.get("line_total")), .928, .73, 10.5))
            description_limit, description_size, description_end = .13, 10.5, .41 * width
        if any(pdfmetrics.stringWidth(value, regular, size) > (right - left) * width
               for value, right, left, size in fields):
            return False
        if not _is_texturin(brand) and (
            "\n" in _text(line.get("description"))
            or description_limit * width + pdfmetrics.stringWidth(_text(line.get("description")), regular, description_size) > description_end
        ):
            return False
    return True


def _master_bank_fits(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    bank = _mapping(_mapping(snapshot.get("issuer")).get("bank_details"))
    regular, bold = _register_fonts(brand)
    if _is_texturin(brand):
        values = ((f"Bank {_text(bank.get('bank'))}", .49),
                  (f"Account Name: {_text(bank.get('account_name'))}", .65),
                  (f"Account No.: {_text(bank.get('account_number'))}", .65))
        return all("\n" not in value and pdfmetrics.stringWidth(value, regular, 10.5) <= brand.page_size[0] * limit
                   for value, limit in values)
    value = " · ".join(_text(bank.get(field)) for field in ("bank", "account_number", "account_name"))
    return "\n" not in value and pdfmetrics.stringWidth(value, bold if brand.key == "hollawall" else regular,
                                                        6.6 if brand.key == "hollawall" else 9) <= brand.page_size[0] * .74


def _master_summary_fits(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    totals = _mapping(snapshot.get("totals"))
    regular, bold = _register_fonts(brand)
    width = brand.page_size[0]
    amounts = [totals.get("subtotal"), totals.get("document_discount"), totals.get("tax"), totals.get("total")]
    if _master_has_deposit(snapshot):
        amounts.append((int(totals.get("total") or 0) * _snapshot_deposit_percent(snapshot, brand) + 50) // 100)
    if brand.key == "hollawall":
        left, right, size = .66, .93, 6.2
        labels = ("Subtotal", "Diskon", _master_tax_label(snapshot), "TOTAL", f"DP {_snapshot_deposit_percent(snapshot, brand)}%")
    elif brand.key == "hojja":
        left, right, size = .57, .89, 10
        labels = ("Subtotal", "Diskon", _master_tax_label(snapshot), "TOTAL", "Total DP :")
    else:
        left, right, size = .06, .928, 10.5
        labels = ("Subtotal", "Diskon", _master_tax_label(snapshot), "TOTAL", f"SIGNATURE FEE ({_snapshot_deposit_percent(snapshot, brand)}%)")
    label_width = max(pdfmetrics.stringWidth(label, bold, size) for label in labels)
    amount_width = max(pdfmetrics.stringWidth(_idr(amount), bold, size) for amount in amounts)
    return label_width + amount_width + 6 <= (right - left) * width


def _other_master_content_fits(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    regular, _ = _register_fonts(brand)
    document = _mapping(snapshot.get("document"))
    project = _mapping(snapshot.get("project"))
    image_source = document.get("project_image_url") or project.get("project_image_url") or project.get("image_url")
    image_limit = 2 if brand.key == "hollawall" else 1
    if len(_master_lines(snapshot)) > image_limit and _project_image_stream(image_source) is not None:
        return False
    if brand.key == "hojja" and len(_master_lines(snapshot)) > 2 and _master_has_deposit(snapshot):
        return False
    if brand.key == "hollawall" and _master_has_deposit(snapshot) and int(_mapping(snapshot.get("totals")).get("tax") or 0):
        return False
    term_size, leading, width, available = (6.6, 8, .76, .085) if brand.key == "hollawall" else (9, 12, .72, .08)
    style = ParagraphStyle("master-other-fit", fontName=regular, fontSize=term_size, leading=leading)
    terms = _commercial_terms(snapshot, "Pembayaran sesuai kesepakatan.")
    paragraph = Paragraph(_paragraph_text(terms).replace("\n", "<br/>"), style)
    _, height = paragraph.wrap(brand.page_size[0] * width, brand.page_size[1])
    return height <= brand.page_size[1] * available


def _texturin_master_lines_fit(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    regular, _ = _register_fonts(brand)
    style = ParagraphStyle("master-line-fit", fontName=regular, fontSize=10.5, leading=12.5)
    for line in _master_lines(snapshot):
        paragraph = Paragraph(_paragraph_text(line.get("description")), style)
        _, height = paragraph.wrap(brand.page_size[0] * .28, brand.page_size[1])
        if height > brand.page_size[1] * .035:
            return False
    return True


def _texturin_master_image_fits(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    document = _mapping(snapshot.get("document"))
    project = _mapping(snapshot.get("project"))
    source = document.get("project_image_url") or project.get("project_image_url") or project.get("image_url")
    if _project_image_stream(source) is None:
        return True
    totals = _mapping(snapshot.get("totals"))
    simple_bali_invoice = (
        brand.key == "texturin-bali" and _master_is_invoice(snapshot)
        and not int(totals.get("document_discount") or 0) and not int(totals.get("tax") or 0)
    )
    lines_top = .335 if brand.key == "texturin-bali" else .294
    image_top = lines_top + len(_master_lines(snapshot)) * .035 + .008
    rule_top = .456 if simple_bali_invoice else (.49 if brand.key == "texturin-bali" else .53) - .018
    return rule_top - image_top - .01 >= .075


def _master_metadata_fits(snapshot: Mapping[str, Any], brand: BrandSpec) -> bool:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    regular, _ = _register_fonts(brand)
    if brand.key == "hollawall":
        size, client_width, project_width, number_width = 7, .46, .46, .25
    elif brand.key == "hojja":
        size, client_width, project_width, number_width = 10, .33, .33, .20
    else:
        size, client_width, project_width, number_width = 10.5, .48, .48, .20
    fields = (
        (project.get("client_company") or project.get("client_name"), client_width),
        (project.get("name"), project_width),
        (document.get("official_number"), number_width),
    )
    if not all(
        "\n" not in _text(value) and pdfmetrics.stringWidth(_text(value), regular, size) <= brand.page_size[0] * width
        for value, width in fields
    ):
        return False
    if brand.key == "hollawall":
        date_width, date_size = .20, 6
    elif brand.key == "hojja":
        date_width, date_size = .15, 10
    else:
        date_width, date_size = .13, 10.5
    for field in ("issue_date", "due_date", "valid_until"):
        if document.get(field):
            value = _date_label(document[field]) if _is_texturin(brand) else _text(document[field])
            if "\n" in value or pdfmetrics.stringWidth(value, regular, date_size) > brand.page_size[0] * date_width:
                return False
    return True


def _master_tax_label(snapshot: Mapping[str, Any]) -> str:
    tax_percent = _mapping(snapshot.get("document")).get("tax_percent")
    return f"Pajak {_text(tax_percent)}%" if tax_percent not in (None, "", "0", 0, "0.0") else "Pajak"


def _draw_master_receipt(
    canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec, *, x: float, top: float, width: float,
) -> None:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    totals = _mapping(snapshot.get("totals"))
    payer = project.get("client_name") or project.get("client_company") or "klien"
    receiver = document.get("client_signatory") or project.get("client_name") or _mapping(snapshot.get("issuer")).get("display_name") or brand.identity
    _canvas_paragraph(
        canvas, brand,
        f"Telah diterima dari {payer} untuk pembayaran Project {project.get('name') or '—'}.",
        x, top, width, size=7.5, leading=10,
    )
    _canvas_text(canvas, brand, _idr(totals.get("total")), x, top + .085, size=12, bold=True)
    _canvas_text(canvas, brand, "Diterima oleh", x, top + .13, size=6.3)
    _canvas_text(canvas, brand, receiver, x, top + .153, size=7.1, bold=True)


def _draw_hollawall_master(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    issuer = _mapping(snapshot.get("issuer"))
    totals = _mapping(snapshot.get("totals"))
    title = _document_title(snapshot)
    if title in {"INVOICE", "QUOTATION"}:
        title = title.title()
    _canvas_text(canvas, brand, issuer.get("legal_name"), .68, .045, size=7, bold=True, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, issuer.get("address"), .68, .062, size=6.5, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, issuer.get("phone"), .68, .079, size=6.5, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, issuer.get("email"), .68, .096, size=6.5, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, title, .072, .195, size=15, bold=True)
    _canvas_text(canvas, brand, "To", .072, .232, size=7)
    _canvas_text(canvas, brand, project.get("client_company") or project.get("client_name"), .15, .232, size=7)
    _canvas_text(canvas, brand, "Project", .072, .251, size=7)
    _canvas_text(canvas, brand, project.get("name"), .15, .251, size=7)
    date_top = .213 if _master_is_invoice(snapshot) else .232
    _canvas_text(canvas, brand, "Tanggal", .64, date_top, size=6)
    _canvas_text(canvas, brand, document.get("issue_date"), .73, date_top, size=6)
    _canvas_text(canvas, brand, "Letter No.", .64, date_top + .019, size=6)
    _canvas_text(canvas, brand, document.get("official_number"), .73, date_top + .019, size=6)
    if _master_is_invoice(snapshot):
        _canvas_text(canvas, brand, "DUE DATE", .64, .251, size=6)
        _canvas_text(canvas, brand, document.get("due_date"), .73, .251, size=6)
    elif document.get("valid_until"):
        _canvas_text(canvas, brand, "BERLAKU", .64, .251, size=6)
        _canvas_text(canvas, brand, document.get("valid_until"), .73, .251, size=6)
    if _master_is_receipt(snapshot):
        _draw_master_receipt(canvas, snapshot, brand, x=.14, top=.36, width=.72)
        return
    canvas.saveState()
    canvas.setStrokeColor(brand.ink)
    canvas.setLineWidth(.55)
    canvas.line(brand.page_size[0] * .072, brand.page_size[1] * (1 - .517),
                brand.page_size[0] * .93, brand.page_size[1] * (1 - .517))
    canvas.restoreState()
    for index, line in enumerate(_master_lines(snapshot)[:4]):
        top = .325 + index * .025
        _canvas_text(canvas, brand, f"{index + 1}.", .088, top, size=6.8, bold=True)
        _canvas_text(canvas, brand, line.get("description"), .14, top, size=6.8)
        _canvas_text(canvas, brand, f"{_text(line.get('quantity'))} {_text(line.get('unit'), '')}", .57, top, size=6.6, right=True)
        _canvas_text(canvas, brand, _idr(line.get("unit_price")), .73, top, size=6.6, right=True)
        _canvas_text(canvas, brand, _idr(line.get("line_total")), .90, top, size=6.6, right=True)
    _draw_master_project_image(canvas, snapshot, brand, .13, .365, .58, .10)
    _canvas_text(canvas, brand, "Subtotal", .70, .535, size=5.8)
    _canvas_text(canvas, brand, _idr(totals.get("subtotal")), .93, .535, size=5.8, right=True)
    discount = int(totals.get("document_discount") or 0)
    _canvas_text(canvas, brand, "Diskon", .70, .555, size=5.8, color=_DISCOUNT)
    _canvas_text(canvas, brand, _idr(discount), .93, .555, size=5.8, right=True, color=_DISCOUNT)
    tax = int(totals.get("tax") or 0)
    total_top = .575
    if tax:
        _canvas_text(canvas, brand, _master_tax_label(snapshot), .70, total_top, size=5.8)
        _canvas_text(canvas, brand, _idr(tax), .93, total_top, size=5.8, right=True)
        total_top += .020
    _canvas_text(canvas, brand, "TOTAL", .70, total_top, size=6.2, bold=True)
    _canvas_text(canvas, brand, _idr(totals.get("total")), .93, total_top, size=6.2, bold=True, right=True)
    policy = commercial_policy(brand.key)
    percent = _snapshot_deposit_percent(snapshot, brand)
    last_summary_top = total_top
    if _master_has_deposit(snapshot):
        deposit = (int(totals.get("total") or 0) * percent + 50) // 100
        last_summary_top = total_top + .023
        canvas.saveState()
        canvas.setFillColor(_HOLLA_LIGHT)
        canvas.rect(brand.page_size[0] * .62, brand.page_size[1] * (1 - last_summary_top - .008),
                    brand.page_size[0] * .31, brand.page_size[1] * .026, fill=1, stroke=0)
        canvas.restoreState()
        _canvas_text(canvas, brand, f"{policy['labels']['deposit']} {percent}%", .66, last_summary_top, size=6, bold=True)
        _canvas_text(canvas, brand, _idr(deposit), .93, last_summary_top, size=6, bold=True, right=True)
    canvas.saveState()
    canvas.setStrokeColor(brand.ink)
    canvas.setLineWidth(.55)
    rule_top = max(.606, last_summary_top + .015)
    canvas.line(brand.page_size[0] * .072, brand.page_size[1] * (1 - rule_top),
                brand.page_size[0] * .93, brand.page_size[1] * (1 - rule_top))
    canvas.restoreState()
    default_terms = (
        "Pembayaran sesuai tanggal jatuh tempo yang tercantum."
        if _master_is_invoice(snapshot) else
        f"Jika penawaran disetujui, pembayaran awal {percent}% mengurangi saldo Project. Penawaran berlaku {policy['default_validity_days']} hari sejak diterbitkan."
    )
    _canvas_paragraph(canvas, brand, _commercial_terms(snapshot, default_terms), .14, .675, .76, size=6.6, leading=8)
    bank = _mapping(issuer.get("bank_details"))
    _canvas_text(canvas, brand, f"{_text(bank.get('bank'))} · {_text(bank.get('account_number'))} · {_text(bank.get('account_name'))}", .14, .77, size=6.6, bold=True)
    _canvas_text(canvas, brand, "Best regards and thank you,", .68, .865, size=5.5)
    _canvas_text(canvas, brand, issuer.get("display_name"), .84, .89, size=8, bold=True, color=_HOLLA_CYAN, right=True)
    _canvas_text(canvas, brand, "Mural Studio", .84, .905, size=8, bold=True, color=_HOLLA_CYAN, right=True)
    if _HOLLAWALL_FOOTER_LOGO_DATA:
        canvas.drawImage(ImageReader(io.BytesIO(_HOLLAWALL_FOOTER_LOGO_DATA)), brand.page_size[0] * .85, brand.page_size[1] * .065,
                         width=brand.page_size[0] * .075, height=brand.page_size[1] * .058,
                         preserveAspectRatio=True, mask="auto")
    _canvas_text(canvas, brand, "*Revisions beyond the agreed scope or excessive revision requests may be subject to additional charges", .067, .956, size=6)


def _draw_hojja_master(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    issuer = _mapping(snapshot.get("issuer"))
    totals = _mapping(snapshot.get("totals"))
    _canvas_text(canvas, brand, _document_title(snapshot).title(), .145, .105, size=28, bold=True)
    _canvas_text(canvas, brand, "To", .145, .16, size=10, bold=True)
    _canvas_text(canvas, brand, project.get("client_company") or project.get("client_name"), .255, .16, size=10)
    _canvas_text(canvas, brand, "Project", .145, .185, size=10, bold=True)
    _canvas_text(canvas, brand, project.get("name"), .255, .185, size=10)
    _canvas_text(canvas, brand, "Date", .60, .16, size=10, bold=True)
    _canvas_text(canvas, brand, document.get("issue_date"), .90, .16, size=10, right=True)
    _canvas_text(canvas, brand, "Letter ID", .60, .185, size=10, bold=True)
    _canvas_text(canvas, brand, document.get("official_number"), .90, .185, size=9, right=True)
    if _master_is_invoice(snapshot):
        _canvas_text(canvas, brand, "DUE DATE", .60, .210, size=9, bold=True)
        _canvas_text(canvas, brand, document.get("due_date"), .90, .210, size=9, right=True)
    elif document.get("valid_until"):
        _canvas_text(canvas, brand, "VALID UNTIL", .60, .210, size=9, bold=True)
        _canvas_text(canvas, brand, document.get("valid_until"), .90, .210, size=9, right=True)
    if _master_is_receipt(snapshot):
        _draw_master_receipt(canvas, snapshot, brand, x=.15, top=.29, width=.72)
        return
    lines = _master_lines(snapshot)[:3]
    for index, line in enumerate(lines):
        top = .285 + index * .080
        meta = _mapping(line.get("commercial_meta"))
        _canvas_text(canvas, brand, line.get("description"), .15, top, size=10)
        width = meta.get("width")
        height = meta.get("height")
        if width and height:
            _canvas_text(canvas, brand, f"({_text(width)} × {_text(height)} {_text(meta.get('dimension_unit'), 'm')})", .15, top + .022, size=9)
        if _master_has_deposit(snapshot):
            _canvas_text(canvas, brand, f"DP {_snapshot_deposit_percent(snapshot, brand)}%", .15, top + .047, size=9)
        _canvas_text(canvas, brand, meta.get("display_quantity") or line.get("quantity"), .67, top, size=10, right=True)
        original = meta.get("original_price")
        if original:
            original_price = _idr(original)
            _canvas_text(canvas, brand, original_price, .89, top, size=10, right=True)
            regular, _ = _register_fonts(brand)
            end = brand.page_size[0] * .89
            canvas.setStrokeColor(brand.ink)
            canvas.setLineWidth(.5)
            canvas.line(end - pdfmetrics.stringWidth(original_price, regular, 10),
                        brand.page_size[1] * (1 - top) + 3, end, brand.page_size[1] * (1 - top) + 3)
        _canvas_text(canvas, brand, _idr(line.get("line_total")), .89, top + (.018 if original else 0), size=10, right=True)
    if len(lines) == 1:
        image_top = .35 if _master_has_deposit(snapshot) else .33
        _draw_master_project_image(canvas, snapshot, brand, .15, image_top, .31, .095 if _master_has_deposit(snapshot) else .11)
    subtotal = int(totals.get("subtotal") or 0)
    discount = int(totals.get("document_discount") or 0)
    tax = int(totals.get("tax") or 0)
    summary_top = .47
    total_top = summary_top + (.021 if discount else 0) + (.021 if tax else 0) + .025
    bar_top = total_top + (.031 if _master_has_deposit(snapshot) else 0)
    canvas.saveState()
    canvas.setStrokeColor(_HOJJA_INK)
    canvas.setLineWidth(.5)
    canvas.line(brand.page_size[0] * .145, brand.page_size[1] * (1 - .455),
                brand.page_size[0] * .89, brand.page_size[1] * (1 - .455))
    canvas.setFillColor(_HOJJA_SAGE)
    canvas.rect(brand.page_size[0] * .51, brand.page_size[1] * (1 - bar_top - .006),
                brand.page_size[0] * .38, brand.page_size[1] * .025, fill=1, stroke=0)
    canvas.line(brand.page_size[0] * .145, brand.page_size[1] * (1 - (bar_top + .015)),
                brand.page_size[0] * .89, brand.page_size[1] * (1 - (bar_top + .015)))
    canvas.restoreState()
    _canvas_text(canvas, brand, "Subtotal", .57, summary_top, size=9)
    _canvas_text(canvas, brand, _idr(subtotal), .89, summary_top, size=9, right=True)
    if discount:
        summary_top += .021
        _canvas_text(canvas, brand, "Diskon", .57, summary_top, size=9, color=_DISCOUNT)
        _canvas_text(canvas, brand, _idr(discount), .89, summary_top, size=9, right=True, color=_DISCOUNT)
    if tax:
        summary_top += .021
        _canvas_text(canvas, brand, _master_tax_label(snapshot), .57, summary_top, size=9)
        _canvas_text(canvas, brand, _idr(tax), .89, summary_top, size=9, right=True)
    summary_top += .025
    is_deposit_invoice = _master_is_invoice(snapshot) and str(document.get("invoice_kind") or "").upper() == "DP"
    label = "Total DP :" if is_deposit_invoice else "TOTAL"
    total_color = brand.ink if _master_has_deposit(snapshot) else colors.white
    _canvas_text(canvas, brand, label, .57, summary_top, size=10, bold=True, color=total_color)
    _canvas_text(canvas, brand, _idr(totals.get("total")), .89, summary_top, size=10, bold=True, right=True, color=total_color)
    percent = _snapshot_deposit_percent(snapshot, brand)
    if _master_has_deposit(snapshot):
        deposit = (int(totals.get("total") or 0) * percent + 50) // 100
        summary_top += .031
        _canvas_text(canvas, brand, "Total DP :", .57, summary_top, size=10, bold=True, color=colors.white)
        _canvas_text(canvas, brand, _idr(deposit), .89, summary_top, size=10, bold=True, right=True, color=colors.white)
    payment_top = max(.56, bar_top + .04)
    _canvas_text(canvas, brand, "Payment Information:", .15, payment_top, size=10, bold=True)
    default_terms = "Pembayaran sesuai tanggal jatuh tempo yang tercantum." if _master_is_invoice(snapshot) else "Revisions beyond the agreed scope may be subject to additional charges."
    _canvas_paragraph(canvas, brand, _commercial_terms(snapshot, default_terms), .15, payment_top + .035, .72, size=9, leading=12)
    bank = _mapping(issuer.get("bank_details"))
    _canvas_text(canvas, brand, f"{_text(bank.get('bank'))} · {_text(bank.get('account_number'))} · {_text(bank.get('account_name'))}", .15, payment_top + .13, size=9)


def _draw_texturin_master(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    issuer = _mapping(snapshot.get("issuer"))
    totals = _mapping(snapshot.get("totals"))
    title = _document_title(snapshot).title()
    _canvas_text(canvas, brand, title, .068, .188 if brand.key == "texturin-bali" else .174, size=23.25, bold=True)
    meta_top = .222 if brand.key == "texturin-bali" else .201
    right_meta_top = meta_top if brand.key == "texturin-bali" else meta_top - .018
    deadline_offset = .046 if brand.key == "texturin-bali" else .041
    _canvas_text(canvas, brand, "TO", .068, meta_top, size=10.5, bold=True)
    _canvas_text(canvas, brand, project.get("client_company") or project.get("client_name"), .16, meta_top, size=10.5)
    _canvas_text(canvas, brand, "PROJECT", .068, meta_top + .023, size=10.5, bold=True)
    _canvas_text(canvas, brand, project.get("name"), .16, meta_top + .023, size=10.5)
    _canvas_text(canvas, brand, "NO.", .67, right_meta_top, size=10.5, bold=True)
    _canvas_text(canvas, brand, document.get("official_number"), .928, right_meta_top, size=10.5, right=True)
    _canvas_text(canvas, brand, "DATE", .67, right_meta_top + .023, size=10.5, bold=True)
    _canvas_text(canvas, brand, _date_label(document.get("issue_date")), .928, right_meta_top + .023, size=10.5, right=True)
    if _master_is_invoice(snapshot):
        _canvas_text(canvas, brand, "DUE DATE", .67, right_meta_top + deadline_offset, size=10.5, bold=True)
        _canvas_text(canvas, brand, _date_label(document.get("due_date")), .928, right_meta_top + deadline_offset, size=10.5, right=True)
    elif document.get("valid_until"):
        _canvas_text(canvas, brand, "VALID UNTIL", .67, right_meta_top + deadline_offset, size=10.5, bold=True)
        _canvas_text(canvas, brand, _date_label(document.get("valid_until")), .928, right_meta_top + deadline_offset, size=10.5, right=True)
    if _master_is_receipt(snapshot):
        _draw_master_receipt(canvas, snapshot, brand, x=.12, top=.35, width=.74)
        return
    lines_top = .335 if brand.key == "texturin-bali" else .294
    for index, line in enumerate(_master_lines(snapshot)[:3]):
        top = lines_top + index * .035
        _canvas_text(canvas, brand, index + 1, .079, top, size=10.5)
        _canvas_paragraph(canvas, brand, line.get("description"), .13, top - .012, .28, size=10.5, leading=12.5)
        _canvas_text(canvas, brand, _idr(line.get("unit_price")), .553, top, size=10.5, right=True)
        _canvas_text(canvas, brand, f"{_text(line.get('quantity'))} {_text(line.get('unit'), '')}", .710, top, size=10.5, right=True)
        _canvas_text(canvas, brand, _idr(line.get("line_total")), .928, top, size=10.5, right=True)
    image_top = lines_top + len(_master_lines(snapshot)) * .035 + .008
    simple_bali_invoice = (
        brand.key == "texturin-bali" and _master_is_invoice(snapshot)
        and not int(totals.get("document_discount") or 0) and not int(totals.get("tax") or 0)
    )
    image_rule = .456 if simple_bali_invoice else (.49 if brand.key == "texturin-bali" else .53) - .018
    image_height = min(.14, image_rule - image_top - .01)
    if image_height > 0:
        _draw_master_project_image(canvas, snapshot, brand, .13, image_top, .37, image_height)
    summary_top = .49 if brand.key == "texturin-bali" else .53
    summary_left = .70 if brand.key == "texturin-bali" else .637
    discount = int(totals.get("document_discount") or 0)
    tax = int(totals.get("tax") or 0)
    _, bold_font = _register_fonts(brand)
    maximum_amount_width = max(
        pdfmetrics.stringWidth(_idr(amount), bold_font, 10.5)
        for amount in (totals.get("subtotal"), discount, tax, totals.get("total"))
    )
    maximum_label_width = max(
        pdfmetrics.stringWidth(label, bold_font, 10.5)
        for label in ("Subtotal", "Diskon", _master_tax_label(snapshot), "TOTAL")
    )
    summary_left = min(summary_left, (.928 * brand.page_size[0] - maximum_amount_width - maximum_label_width - 5) / brand.page_size[0])
    total_top = summary_top if simple_bali_invoice else summary_top + (.022 if brand.key != "texturin-bali" or discount else 0) + (.022 if tax else 0) + .033
    canvas.saveState()
    canvas.setFillColor(_TEXTURIN_WARM)
    canvas.setStrokeColor(_TEXTURIN_WARM)
    canvas.setLineWidth(1.2)
    rule_top = .456 if simple_bali_invoice else summary_top - .018
    canvas.line(brand.page_size[0] * .06, brand.page_size[1] * (1 - rule_top),
                brand.page_size[0] * .94, brand.page_size[1] * (1 - rule_top))
    canvas.rect(brand.page_size[0] * .06, brand.page_size[1] * (1 - total_top - .011),
                brand.page_size[0] * .88, brand.page_size[1] * .030, fill=1, stroke=0)
    canvas.line(brand.page_size[0] * .06, brand.page_size[1] * (1 - (total_top + .020)),
                brand.page_size[0] * .94, brand.page_size[1] * (1 - (total_top + .020)))
    canvas.restoreState()
    if not simple_bali_invoice:
        _canvas_text(canvas, brand, "Subtotal", summary_left, summary_top, size=10.5)
        _canvas_text(canvas, brand, _idr(totals.get("subtotal")), .928, summary_top, size=10.5, right=True)
    if brand.key != "texturin-bali" or discount:
        summary_top += .022
        _canvas_text(canvas, brand, "Diskon", summary_left, summary_top, size=10.5, color=_DISCOUNT)
        _canvas_text(canvas, brand, _idr(discount), .928, summary_top, size=10.5, color=_DISCOUNT, right=True)
    if tax:
        summary_top += .022
        _canvas_text(canvas, brand, _master_tax_label(snapshot), summary_left, summary_top, size=10.5)
        _canvas_text(canvas, brand, _idr(tax), .928, summary_top, size=10.5, right=True)
    if not simple_bali_invoice:
        summary_top += .033
    _canvas_text(canvas, brand, "TOTAL", summary_left, summary_top, size=10.5, bold=True)
    _canvas_text(canvas, brand, _idr(totals.get("total")), .928, summary_top, size=10.5, bold=True, right=True)
    percent = _snapshot_deposit_percent(snapshot, brand)
    if _master_has_deposit(snapshot):
        deposit = (int(totals.get("total") or 0) * percent + 50) // 100
        deposit_left = .55 if brand.key != "texturin-bali" else .58
        deposit_label = f"SIGNATURE FEE ({percent}%)"
        deposit_left = min(deposit_left, (.928 * brand.page_size[0]
                           - pdfmetrics.stringWidth(_idr(deposit), bold_font, 9.5)
                           - pdfmetrics.stringWidth(deposit_label, bold_font, 9.5) - 5) / brand.page_size[0])
        _canvas_text(canvas, brand, deposit_label, deposit_left, summary_top + .030, size=9.5, bold=True)
        _canvas_text(canvas, brand, _idr(deposit), .928, summary_top + .030, size=9.5, bold=True, right=True)
    has_terms = brand.key != "texturin-bali" or bool(document.get("payment_terms") or document.get("notes"))
    if has_terms:
        _canvas_paragraph(canvas, brand, _texturin_master_terms(snapshot, brand), .066, .65, .87, size=10.2, leading=14.2, italic=True)
    bank = _mapping(issuer.get("bank_details"))
    bank_top = (.62 if _master_has_deposit(snapshot) else .54) if brand.key == "texturin-bali" and not has_terms else .922
    _canvas_text(canvas, brand, "BANK DETAILS", .054, bank_top, size=10.5, bold=True)
    _canvas_text(canvas, brand, f"Bank {_text(bank.get('bank'))}", .21, bank_top, size=10.5)
    _canvas_text(canvas, brand, f"Account Name: {_text(bank.get('account_name'))}", .054, bank_top + .017, size=10.5)
    _canvas_text(canvas, brand, f"Account No.: {_text(bank.get('account_number'))}", .054, bank_top + .034, size=10.5)
    if _TEXTURIN_SIGNOFF_DATA:
        canvas.drawImage(
            ImageReader(io.BytesIO(_TEXTURIN_SIGNOFF_DATA)),
            brand.page_size[0] * .735,
            brand.page_size[1] * .008,
            width=brand.page_size[0] * .25,
            height=brand.page_size[1] * .125,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )


def _searchable_extra_values(snapshot: Mapping[str, Any]) -> list[str]:
    """Return snapshot fields not already painted visibly on the master."""
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    values: list[Any] = [
        project.get("client_contact"),
        project.get("client_address"),
        document.get("due_date"),
        document.get("valid_until"),
        document.get("notes"),
        document.get("prepared_by"),
        document.get("client_signatory"),
    ]
    if project.get("client_company"):
        values.append(project.get("client_name"))
    return [str(value) for value in values if value is not None and str(value).strip()]


def _draw_searchable_snapshot_layer(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    """Embed non-visual snapshot semantics without changing the canonical master."""
    static_labels = {
        "hollawall": "INVOICE QUOTATION TANGGAL LETTER NO. TOTAL DP Best regards",
        "hojja": "INVOICE QUOTATION DATE LETTER ID Total DP Payment Information",
        "texturin": "INVOICE QUOTATION QUOTATION NO. PPM QTY/LUAS BANK DETAILS THANK YOU Evanvun",
        "texturin-surabaya": "INVOICE QUOTATION QUOTATION NO. PPM QTY/LUAS BANK DETAILS SIGNATURE FEE THANK YOU Evanvun",
        "texturin-bali": "INVOICE QUOTATION QUOTATION NO. PPM QTY/LUAS AREA (M²) BANK DETAILS THANK YOU Evanvun",
    }[brand.key]
    values = [brand.identity, static_labels, *_searchable_extra_values(snapshot)]
    text = canvas.beginText(0, 0)
    text.setFont("Helvetica", 1)
    text.setTextRenderMode(3)
    text.setLeading(1)
    for value in values:
        text.textLine(value.replace("\r", " ").replace("\n", " "))
    canvas.drawText(text)


def _build_master_pdf(snapshot: Mapping[str, Any], brand: BrandSpec) -> bytes:
    target = io.BytesIO()
    document = _mapping(snapshot.get("document"))
    canvas = pdfcanvas.Canvas(
        target,
        pagesize=brand.page_size,
        pageCompression=1,
        invariant=1,
    )
    canvas.setTitle(_text(document.get("official_number"), f"{brand.identity} Draft"))
    canvas.setAuthor(brand.identity)
    canvas.setCreator(RENDERER_VERSION)
    canvas.setSubject("Project commercial document")
    master = _MASTER_ART.get(brand.key)
    if master:
        canvas.drawImage(
            ImageReader(io.BytesIO(master)), 0, 0,
            width=brand.page_size[0], height=brand.page_size[1],
            preserveAspectRatio=False, mask="auto",
        )
    if brand.key == "hojja":
        canvas.setFillColor(colors.Color(229 / 255, 225 / 255, 216 / 255))
        for top, bottom, right in ((.069, .135, .65), (.135, .22, .91), (.265, .70, .91)):
            canvas.rect(brand.page_size[0] * .13, brand.page_size[1] * (1 - bottom),
                        brand.page_size[0] * (right - .13), brand.page_size[1] * (bottom - top),
                        fill=1, stroke=0)
        _draw_hojja_contact(canvas, snapshot, brand)
    if brand.key == "hollawall":
        _draw_hollawall_master(canvas, snapshot, brand)
    elif brand.key == "hojja":
        _draw_hojja_master(canvas, snapshot, brand)
    else:
        _draw_texturin_master(canvas, snapshot, brand)
    _draw_master_watermark(canvas, snapshot, brand)
    _draw_searchable_snapshot_layer(canvas, snapshot, brand)
    canvas.showPage()
    canvas.save()
    return target.getvalue()


def _build_pdf(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    logo_path: str | Path | None,
    total_pages: int | None,
) -> bytes:
    target = io.BytesIO()
    document = _mapping(snapshot.get("document"))
    doc = BaseDocTemplate(
        target,
        pagesize=brand.page_size,
        leftMargin=brand.left_margin,
        rightMargin=brand.right_margin,
        topMargin=(34 * mm if brand.key == "hollawall" else 22 * mm if brand.key == "hojja" else
                   47 * mm if brand.key == "texturin-bali" else 43 * mm) if brand.key in _MASTER_ART else brand.top_margin,
        bottomMargin=25 * mm if brand.key == "hollawall" and _MASTER_ART.get("hollawall") else brand.bottom_margin,
        title=_text(document.get("official_number"), f"{brand.identity} Draft"),
        author=brand.identity,
        creator=RENDERER_VERSION,
        subject="Project commercial document",
        invariant=1,
        pageCompression=1,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
        id=f"{brand.key}-content", leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0,
    )

    def decorate(canvas: Any, _built_doc: Any) -> None:
        _draw_brand_page(canvas, snapshot, brand, total_pages, logo_path)

    doc.addPageTemplates([PageTemplate(id=brand.key, frames=[frame], onPage=decorate)])
    doc.build(_story(snapshot, brand, logo_path))
    return target.getvalue()


def render_project_document_pdf(
    snapshot: Mapping[str, Any],
    *,
    logo_path: str | Path | None = _DEFAULT_LOGO,
) -> bytes:
    """Render deterministic branded PDF bytes from one canonical snapshot."""

    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    brand = _brand_for(snapshot)
    master_content_fits = (
        _texturin_master_terms_fit(snapshot, brand) and _texturin_master_lines_fit(snapshot, brand)
        and _texturin_master_image_fits(snapshot, brand)
        if _is_texturin(brand) else _other_master_content_fits(snapshot, brand)
    )
    document = _mapping(snapshot.get("document"))
    if not _master_is_receipt(snapshot) and (document.get("prepared_by") or document.get("client_signatory")):
        master_content_fits = False
    master_content_fits = (master_content_fits and _master_item_columns_fit(snapshot, brand)
                           and _master_bank_fits(snapshot, brand) and _master_summary_fits(snapshot, brand)
                           and (brand.key != "hollawall" or _hollawall_issuer_fits(snapshot, brand))
                           and (brand.key != "hojja" or _hojja_phone_fits(snapshot, brand)))
    if brand.key in _MASTER_ART and len(_master_lines(snapshot)) <= 3 and master_content_fits and _master_metadata_fits(snapshot, brand):
        return _build_master_pdf(snapshot, brand)
    first_pass = _build_pdf(snapshot, brand, logo_path, None)
    total_pages = _page_count(first_pass)
    return _build_pdf(snapshot, brand, logo_path, total_pages)


def _page_count(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def render_project_document_artifact(snapshot: Mapping[str, Any]) -> tuple[bytes, str]:
    """Repository renderer adapter returning exact bytes and renderer version."""

    return render_project_document_pdf(snapshot), RENDERER_VERSION
