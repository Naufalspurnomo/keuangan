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
from html import escape
from pathlib import Path
from typing import Any, Callable

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
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from services.commercial_document_policy import commercial_policy

RENDERER_VERSION = "branded-commercial-v3"
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
_HOLLAWALL_FOOTER_ART = _ASSET_DIR / "hollawall-footer-art.png"
_HOLLAWALL_FOOTER_LOGO = _ASSET_DIR / "hollawall-footer-logo.png"
_HOLLAWALL_FOOTER_ART_DATA = _HOLLAWALL_FOOTER_ART.read_bytes() if _HOLLAWALL_FOOTER_ART.is_file() else b""

_INK = colors.HexColor("#383838")
_MUTED = colors.HexColor("#666666")
_HOLLA_CYAN = colors.HexColor("#22AEBB")
_HOLLA_ORANGE = colors.HexColor("#F39A00")
_HOLLA_LIGHT = colors.HexColor("#F1F1F1")
_HOJJA_PAPER = colors.HexColor("#E4E0D7")
_HOJJA_INK = colors.HexColor("#6B6255")
_HOJJA_SAGE = colors.HexColor("#7C887D")
_TEXTURIN_WARM = colors.HexColor("#E2DDD6")
_DISCOUNT = colors.HexColor("#C94B4B")

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
        "texturin decorative finishes", _TEXTURIN_WARM, _INK, colors.white,
    ),
    "texturin-surabaya": BrandSpec(
        "texturin-surabaya", A4, 13 * mm, 13 * mm, 14 * mm, 20 * mm,
        "texturin Surabaya · decorative finishes", _TEXTURIN_WARM, _INK, colors.white,
    ),
    "texturin-bali": BrandSpec(
        "texturin-bali", A4, 18 * mm, 13 * mm, 14 * mm, 20 * mm,
        "texturin Bali · decorative finishes", _TEXTURIN_WARM, _INK, colors.white,
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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any, fallback: str = "—") -> str:
    cleaned = str(value or "").strip()
    return cleaned or fallback


def _paragraph_text(value: Any, fallback: str = "—") -> str:
    return escape(_text(value, fallback), quote=True)


def _normalize_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _brand_for(snapshot: Mapping[str, Any]) -> BrandSpec:
    project = _mapping(snapshot.get("project"))
    issuer = _mapping(snapshot.get("issuer"))
    document = _mapping(snapshot.get("document"))
    explicit = _normalize_identity(document.get("template_key"))
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
    small = 6.0 if brand.key == "hollawall" else 7.4
    body = 6.6 if brand.key == "hollawall" else 8.1
    return {
        "body": ParagraphStyle(
            f"{brand.key}-body", parent=base["BodyText"], fontName=regular,
            fontSize=body, leading=body * 1.35, textColor=brand.ink,
        ),
        "body_italic": ParagraphStyle(
            f"{brand.key}-body-italic", parent=base["BodyText"], fontName=regular,
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
            fontSize=20 if brand.key == "hojja" else (18 if _is_texturin(brand) else 16),
            leading=23 if brand.key == "hojja" else (21 if _is_texturin(brand) else 18),
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
    document = _mapping(snapshot.get("document"))
    logo = _safe_logo_path(brand, logo_path)
    official = _paragraph_text(document.get("official_number"), "DRAFT")
    title = _document_title(snapshot)
    display = _paragraph_text(issuer.get("display_name"), brand.identity)
    legal = _paragraph_text(issuer.get("legal_name"), "CV Holla Berkreasi")
    address = _paragraph_text(issuer.get("address"))

    if brand.key == "hollawall":
        mark: Flowable = (
            _image(logo, 20 * mm, 23 * mm)
            if logo else Paragraph("<b>HOLLAWALL</b>", styles["value_bold"])
        )
        statement = Paragraph(
            "Making vertical identity, and<br/>transform your space ambience<br/><br/>"
            "Original visuals<br/>Experienced Execution",
            styles["small"],
        )
        contact = Paragraph(
            f"<b>{legal}</b><br/>{address}<br/>"
            f"{_paragraph_text(issuer.get('phone'))}<br/>"
            f"{_paragraph_text(issuer.get('email'))}",
            styles["small"],
        )
        header = Table([[mark, statement, contact]], colWidths=[25 * mm, 57 * mm, 48 * mm])
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (1, 0), (1, 0), 1.1, _HOLLA_CYAN),
            ("LINEAFTER", (1, 0), (1, 0), 1.1, _HOLLA_CYAN),
            ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        heading = Table([
            [Paragraph(title, styles["title"]), Paragraph(official, styles["right_bold"])],
            [Paragraph(f"<b>{brand.identity}</b> · {display}", styles["small"]), ""],
        ], colWidths=[74 * mm, 56 * mm])
        _zero_padding(heading)
        return [header, Spacer(1, 2.5 * mm), heading, Spacer(1, 2 * mm)]

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
    if document.get("due_date"):
        date_rows.append([Paragraph("DUE DATE", styles["label"]), Paragraph(_paragraph_text(document.get("due_date")), styles["right"])])
    if document.get("valid_until"):
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

    left = Table([
        [Paragraph("TO", styles["label"]), Paragraph(_paragraph_text(client), styles["value"])],
        [Paragraph("", styles["label"]), Paragraph(_paragraph_text(client_details), styles["small"])],
        [Paragraph("PROJECT", styles["label"]), Paragraph(_paragraph_text(project.get("name")), styles["value_bold"])],
    ], colWidths=[left_label_width, widths[0] - left_label_width])
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
        row: list[Any]
        if brand.key == "hollawall":
            row = [
                Paragraph(f"<b>{index}.</b>", styles["table"]),
                Paragraph(_paragraph_text(line.get("description")), styles["table"]),
                Paragraph(_paragraph_text(quantity), styles["table"]),
                Paragraph(_idr(line.get("unit_price")), styles["table_right"]),
                Paragraph(_idr(line.get("line_total")), styles["table_right"]),
            ]
        elif brand.key == "hojja":
            description: list[Flowable] = [
                Paragraph(_paragraph_text(line.get("description")), styles["table"]),
            ]
            document = _mapping(snapshot.get("document"))
            project = _mapping(snapshot.get("project"))
            source = document.get("project_image_url") or project.get("project_image_url") or project.get("image_url")
            stream = _project_image_stream(source)
            if index == 1 and stream is not None:
                artwork = Image(stream, width=78 * mm, height=38 * mm, kind="proportional")
                artwork.hAlign = "LEFT"
                description.extend([Spacer(1, 2 * mm), artwork])
            gross = int(line.get("line_gross") or line.get("line_total") or 0)
            line_total = int(line.get("line_total") or 0)
            price = _idr(line_total)
            if gross > line_total:
                price = f"<strike>{_idr(gross)}</strike><br/><b>{_idr(line_total)}</b>"
            row = [
                description,
                Paragraph(_paragraph_text(quantity), styles["table"]),
                Paragraph(price, styles["table_right"]),
            ]
        else:
            row = [
                Paragraph(str(index), styles["table"]),
                Paragraph(_paragraph_text(line.get("description")), styles["table"]),
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
    total_label = "TOTAL DP" if invoice_kind == "DP" else "TOTAL"
    if brand.key == "hojja" and invoice_kind == "DP":
        total_label = "Total DP"
    rows.append([
        Paragraph(f"<b>{total_label}</b>", styles["value_bold"]),
        Paragraph(f"<b>{_idr(totals.get('total'))}</b>", styles["right_bold"]),
    ])
    total_width = 75 * mm if brand.key != "hollawall" else 60 * mm
    table = Table(rows, colWidths=[total_width * 0.48, total_width * 0.52], hAlign="RIGHT")
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
    heading = "BANK DETAILS" if _is_texturin(brand) else "Payment Information"
    notes: list[Flowable] = [
        Paragraph(f"<b>{heading}</b>", styles["value_bold"]),
        Spacer(1, 1.5 * mm),
        Paragraph(_paragraph_text(document.get("notes"), "Tidak ada catatan tambahan."), styles["body"]),
        Spacer(1, 1 * mm),
        Paragraph(_paragraph_text(document.get("payment_terms"), "Sesuai kesepakatan proyek."), styles["body"]),
    ]
    if bank:
        bank_text = " · ".join(_text(bank.get(field)) for field in ("bank", "account_number", "account_name"))
        notes.extend([Spacer(1, 1 * mm), Paragraph(f"<b>{_paragraph_text(bank_text)}</b>", styles["small"])])

    prepared = _paragraph_text(document.get("prepared_by"), _text(issuer.get("display_name"), brand.identity))
    approved = _paragraph_text(document.get("client_signatory"), "Nama & tanda tangan")
    if _is_texturin(brand):
        return notes

    if brand.key == "hollawall":
        signoff_items: list[Flowable] = [
            Paragraph("Best regards and thank you,", styles["right"]),
            Spacer(1, 2 * mm),
        ]
        if logo_path is not None and _HOLLAWALL_FOOTER_LOGO.is_file():
            logo = _image(_HOLLAWALL_FOOTER_LOGO, 30 * mm, 12 * mm)
            logo.hAlign = "RIGHT"
            signoff_items.append(logo)
        signoff_items.append(Paragraph(prepared, styles["right_bold"]))
        signoff_items.append(Paragraph(approved, styles["small_muted"]))
        signoff = Table([[notes, signoff_items]], colWidths=[77 * mm, 53 * mm])
        signoff.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return [signoff]

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


def _texturin_deposit(
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    styles: Mapping[str, ParagraphStyle],
) -> Flowable:
    policy = commercial_policy(brand.key)
    percent = int(policy.get("default_deposit_percent") or 0)
    total = int(_mapping(snapshot.get("totals")).get("total") or 0)
    amount = total * percent // 100
    table = Table([
        [
            Paragraph(f"<b>SIGNATURE FEE ({percent}%)</b>", styles["value_bold"]),
            Paragraph(f"<b>{_idr(amount)}</b>", styles["right_bold"]),
        ],
    ], colWidths=[52 * mm, 45 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _TEXTURIN_WARM),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    return table


def _texturin_bali_total_and_bank(
    snapshot: Mapping[str, Any],
    styles: Mapping[str, ParagraphStyle],
) -> list[Flowable]:
    total = int(_mapping(snapshot.get("totals")).get("total") or 0)
    bank = _mapping(_mapping(snapshot.get("issuer")).get("bank_details"))
    total_table = Table([
        [Paragraph("<b>TOTAL</b>", styles["value_bold"]), Paragraph(f"<b>{_idr(total)}</b>", styles["right_bold"])],
    ], colWidths=[52 * mm, 48 * mm], hAlign="RIGHT")
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _TEXTURIN_WARM),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    bank_text = "<br/>".join(
        _paragraph_text(bank.get(field))
        for field in ("bank", "account_number", "account_name")
    )
    return [
        total_table,
        Spacer(1, 5 * mm),
        Paragraph("<b>BANK DETAILS</b>", styles["value_bold"]),
        Spacer(1, 1.5 * mm),
        Paragraph(bank_text, styles["body"]),
        Spacer(1, 44 * mm),
        Paragraph("Best regards and thank you,<br/><b>Texturin Bali</b>", styles["right"]),
    ]


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
    if brand.key == "texturin-bali":
        return [*leading, *_texturin_bali_total_and_bank(snapshot, styles)]
    trailing: list[Flowable] = [
        _totals(snapshot, brand, styles),
        Spacer(1, 6 * mm if brand.key != "hollawall" else 4 * mm),
    ]
    if brand.key == "texturin-surabaya":
        trailing.extend([_texturin_deposit(snapshot, brand, styles), Spacer(1, 4 * mm)])
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
        if _HOLLAWALL_FOOTER_ART_DATA:
            canvas.drawImage(
                ImageReader(io.BytesIO(_HOLLAWALL_FOOTER_ART_DATA)), 0, 0,
                width=page_width, height=page_width * 432 / 1917, mask="auto",
                preserveAspectRatio=True, anchor="sw",
            )
        canvas.setStrokeColor(_HOLLA_CYAN)
        canvas.setLineWidth(0.8)
        canvas.line(10 * mm, 36 * mm, page_width - 10 * mm, 36 * mm)
    elif brand.key == "hojja":
        canvas.setStrokeColor(_HOJJA_INK)
        canvas.setLineWidth(0.55)
        canvas.line(15.5 * mm, 0, 15.5 * mm, page_height)
        canvas.line(0, 36 * mm, page_width, 36 * mm)
        canvas.setFillColor(_HOJJA_INK)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(28 * mm, 25 * mm, "HOJJA ArtHouse")
        canvas.setFont("Helvetica", 7)
        canvas.drawString(28 * mm, 20 * mm, "Reach us at")
        phone = _text(_mapping(snapshot.get("issuer")).get("phone"), "+62 887-7669-989")
        canvas.drawString(28 * mm, 15 * mm, phone)
    else:
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
    footer_y = 33.5 * mm if brand.key == "hollawall" else (8 * mm if brand.key == "hojja" else 5 * mm)
    footer_left = brand.left_margin
    canvas.setFillColor(brand.ink)
    canvas.setFont("Helvetica", 5.8)
    canvas.drawString(footer_left, footer_y, f"{brand.identity} · {reference}")
    if total_pages is not None:
        canvas.drawRightString(
            page_width - brand.right_margin,
            footer_y,
            f"Halaman {canvas.getPageNumber()} / {total_pages}",
        )
    canvas.restoreState()


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
        topMargin=brand.top_margin,
        bottomMargin=brand.bottom_margin,
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
    first_pass = _build_pdf(snapshot, brand, logo_path, None)
    total_pages = _page_count(first_pass)
    return _build_pdf(snapshot, brand, logo_path, total_pages)


def _page_count(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def render_project_document_artifact(snapshot: Mapping[str, Any]) -> tuple[bytes, str]:
    """Repository renderer adapter returning exact bytes and renderer version."""

    return render_project_document_pdf(snapshot), RENDERER_VERSION
