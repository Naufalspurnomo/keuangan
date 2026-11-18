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
from reportlab.pdfgen import canvas as pdfcanvas
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

RENDERER_VERSION = "branded-commercial-v4"
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
        fontName=regular,
        fontSize=size,
        leading=leading or size * 1.3,
        textColor=brand.ink,
        alignment=TA_LEFT,
    )
    value = _paragraph_text(text).replace("\n", "<br/>")
    paragraph = Paragraph(f"<i>{value}</i>" if italic else value, style)
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


def _draw_master_footer(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    document = _mapping(snapshot.get("document"))
    reference = _text(document.get("official_number"), "DRAFT")
    _canvas_text(canvas, brand, f"{brand.identity} · {reference}", .065, .982, size=5)
    _canvas_text(canvas, brand, "Halaman 1 / 1", .94, .982, size=5, right=True)


def _draw_master_project_image(
    canvas: Any,
    snapshot: Mapping[str, Any],
    brand: BrandSpec,
    x: float,
    top: float,
    width: float,
    height: float,
) -> None:
    stream = _project_image_stream(_mapping(snapshot.get("document")).get("project_image_url"))
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
    document = _mapping(snapshot.get("document"))
    return (
        _master_document_type(snapshot) in {"quotation", "sales_order"}
        or str(document.get("invoice_kind") or "").upper() == "DP"
    )


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
    receiver = document.get("client_signatory") or _mapping(snapshot.get("issuer")).get("display_name") or brand.identity
    _canvas_paragraph(
        canvas, brand,
        f"Telah diterima dari {payer} untuk pembayaran proyek {project.get('name') or '—'}.",
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
    _canvas_text(canvas, brand, issuer.get("legal_name"), .66, .045, size=6.1, bold=True, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, issuer.get("address"), .66, .062, size=5.4, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, issuer.get("phone"), .66, .079, size=5.4, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, issuer.get("email"), .66, .096, size=5.4, color=_HOLLA_CYAN)
    _canvas_text(canvas, brand, title, .072, .195, size=15, bold=True)
    _canvas_text(canvas, brand, "To", .072, .232, size=6)
    _canvas_text(canvas, brand, project.get("client_company") or project.get("client_name"), .13, .232, size=6, bold=True)
    _canvas_text(canvas, brand, "Project", .072, .251, size=6)
    _canvas_text(canvas, brand, project.get("name"), .15, .251, size=6, bold=True)
    _canvas_text(canvas, brand, "Tanggal", .64, .232, size=6)
    _canvas_text(canvas, brand, document.get("issue_date"), .73, .232, size=6)
    _canvas_text(canvas, brand, "Letter No.", .64, .251, size=6)
    _canvas_text(canvas, brand, document.get("official_number"), .73, .251, size=6)
    if _master_is_invoice(snapshot):
        _canvas_text(canvas, brand, "DUE DATE", .64, .270, size=6)
        _canvas_text(canvas, brand, document.get("due_date"), .73, .270, size=6)
    if _master_is_receipt(snapshot):
        _draw_master_receipt(canvas, snapshot, brand, x=.14, top=.36, width=.72)
        return
    for index, line in enumerate(_master_lines(snapshot)[:4]):
        top = .325 + index * .025
        _canvas_text(canvas, brand, f"{index + 1}.", .072, top, size=5.8)
        _canvas_text(canvas, brand, line.get("description"), .135, top, size=5.8)
        _canvas_text(canvas, brand, f"{_text(line.get('quantity'))} {_text(line.get('unit'), '')}", .625, top, size=5.8, right=True)
        _canvas_text(canvas, brand, _idr(line.get("unit_price")), .79, top, size=5.8, right=True)
        _canvas_text(canvas, brand, _idr(line.get("line_total")), .93, top, size=5.8, right=True)
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
    percent = int(policy.get("default_deposit_percent") or 0)
    if _master_has_deposit(snapshot):
        deposit = int(totals.get("total") or 0) * percent // 100
        _canvas_text(canvas, brand, f"{policy['labels']['deposit']} {percent}%", .66, total_top + .030, size=5.5, bold=True)
        _canvas_text(canvas, brand, _idr(deposit), .93, total_top + .030, size=5.5, bold=True, right=True)
    default_terms = (
        "Pembayaran sesuai tanggal jatuh tempo yang tercantum."
        if _master_is_invoice(snapshot) else
        f"Jika penawaran disetujui, pembayaran awal {percent}% mengurangi saldo proyek. Penawaran berlaku {policy['default_validity_days']} hari sejak diterbitkan."
    )
    _canvas_paragraph(canvas, brand, document.get("payment_terms") or default_terms, .14, .70, .76, size=5.5, leading=7)
    bank = _mapping(issuer.get("bank_details"))
    _canvas_text(canvas, brand, f"{_text(bank.get('bank'))} · {_text(bank.get('account_number'))} · {_text(bank.get('account_name'))}", .14, .77, size=5.5, bold=True)
    _canvas_text(canvas, brand, "Best regards and thank you,", .68, .865, size=5.5)
    _canvas_text(canvas, brand, issuer.get("display_name"), .68, .89, size=8, bold=True, color=_HOLLA_CYAN)


def _draw_hojja_master(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    issuer = _mapping(snapshot.get("issuer"))
    totals = _mapping(snapshot.get("totals"))
    _canvas_text(canvas, brand, _document_title(snapshot).title(), .145, .105, size=20, bold=True)
    _canvas_text(canvas, brand, "To", .145, .16, size=7, bold=True)
    _canvas_text(canvas, brand, project.get("client_company") or project.get("client_name"), .235, .16, size=7)
    _canvas_text(canvas, brand, "Project", .145, .185, size=7, bold=True)
    _canvas_text(canvas, brand, project.get("name"), .235, .185, size=7)
    _canvas_text(canvas, brand, "Date", .66, .16, size=7, bold=True)
    _canvas_text(canvas, brand, document.get("issue_date"), .88, .16, size=7, right=True)
    _canvas_text(canvas, brand, "Letter ID", .66, .185, size=7, bold=True)
    _canvas_text(canvas, brand, document.get("official_number"), .88, .185, size=7, right=True)
    if _master_is_invoice(snapshot):
        _canvas_text(canvas, brand, "DUE DATE", .66, .210, size=7, bold=True)
        _canvas_text(canvas, brand, document.get("due_date"), .88, .210, size=7, right=True)
    if _master_is_receipt(snapshot):
        _draw_master_receipt(canvas, snapshot, brand, x=.15, top=.29, width=.72)
        return
    lines = _master_lines(snapshot)[:3]
    for index, line in enumerate(lines):
        top = .275 + index * .080
        meta = _mapping(line.get("commercial_meta"))
        _canvas_text(canvas, brand, line.get("description"), .15, top, size=7.2)
        width = meta.get("width")
        height = meta.get("height")
        if width and height:
            _canvas_text(canvas, brand, f"({_text(width)} × {_text(height)} {_text(meta.get('dimension_unit'), 'm')})", .15, top + .022, size=6.4)
        if _master_has_deposit(snapshot):
            _canvas_text(canvas, brand, f"DP {commercial_policy(brand.key)['default_deposit_percent']}%", .15, top + .047, size=6.4)
        _canvas_text(canvas, brand, meta.get("display_quantity") or line.get("quantity"), .67, top, size=7.2, right=True)
        original = meta.get("original_price")
        if original:
            _canvas_text(canvas, brand, f"Harga awal {_idr(original)}", .89, top, size=6.1, right=True)
        _canvas_text(canvas, brand, f"Harga sepakat {_idr(line.get('line_total'))}", .89, top + .026, size=6.1, bold=True, right=True)
    if len(lines) == 1:
        _draw_master_project_image(canvas, snapshot, brand, .15, .37, .31, .12)
    subtotal = int(totals.get("subtotal") or 0)
    discount = int(totals.get("document_discount") or 0)
    tax = int(totals.get("tax") or 0)
    summary_top = .525
    _canvas_text(canvas, brand, "Subtotal", .57, summary_top, size=6.2)
    _canvas_text(canvas, brand, _idr(subtotal), .89, summary_top, size=6.2, right=True)
    if discount:
        summary_top += .021
        _canvas_text(canvas, brand, "Diskon", .57, summary_top, size=6.2, color=_DISCOUNT)
        _canvas_text(canvas, brand, _idr(discount), .89, summary_top, size=6.2, right=True, color=_DISCOUNT)
    if tax:
        summary_top += .021
        _canvas_text(canvas, brand, _master_tax_label(snapshot), .57, summary_top, size=6.2)
        _canvas_text(canvas, brand, _idr(tax), .89, summary_top, size=6.2, right=True)
    summary_top += .025
    _canvas_text(canvas, brand, "TOTAL", .57, summary_top, size=7, bold=True)
    _canvas_text(canvas, brand, _idr(totals.get("total")), .89, summary_top, size=7, bold=True, right=True)
    percent = int(commercial_policy(brand.key).get("default_deposit_percent") or 0)
    if _master_has_deposit(snapshot):
        deposit = int(totals.get("total") or 0) * percent // 100
        summary_top += .031
        _canvas_text(canvas, brand, "Total DP :", .57, summary_top, size=7, bold=True)
        _canvas_text(canvas, brand, _idr(deposit), .89, summary_top, size=7, bold=True, right=True)
    _canvas_text(canvas, brand, "Payment Information:", .15, .65, size=7, bold=True)
    default_terms = "Pembayaran sesuai tanggal jatuh tempo yang tercantum." if _master_is_invoice(snapshot) else "Revisions beyond the agreed scope may be subject to additional charges."
    _canvas_paragraph(canvas, brand, document.get("payment_terms") or default_terms, .15, .68, .72, size=6.5, leading=8)
    bank = _mapping(issuer.get("bank_details"))
    _canvas_text(canvas, brand, f"{_text(bank.get('bank'))} · {_text(bank.get('account_number'))} · {_text(bank.get('account_name'))}", .15, .77, size=6.3)


def _draw_texturin_master(canvas: Any, snapshot: Mapping[str, Any], brand: BrandSpec) -> None:
    project = _mapping(snapshot.get("project"))
    document = _mapping(snapshot.get("document"))
    issuer = _mapping(snapshot.get("issuer"))
    totals = _mapping(snapshot.get("totals"))
    title = _document_title(snapshot).title()
    _canvas_text(canvas, brand, title, .068, .17 if brand.key == "texturin-bali" else .155, size=18, bold=True)
    meta_top = .218 if brand.key == "texturin-bali" else .198
    _canvas_text(canvas, brand, "TO", .068, meta_top, size=6.5, bold=True)
    _canvas_text(canvas, brand, project.get("client_company") or project.get("client_name"), .16, meta_top, size=6.5)
    _canvas_text(canvas, brand, "PROJECT", .068, meta_top + .022, size=6.5, bold=True)
    _canvas_text(canvas, brand, project.get("name"), .16, meta_top + .022, size=6.5)
    _canvas_text(canvas, brand, "NO.", .67, meta_top, size=6.5, bold=True)
    _canvas_text(canvas, brand, document.get("official_number"), .94, meta_top, size=6.5, right=True)
    _canvas_text(canvas, brand, "DATE", .67, meta_top + .022, size=6.5, bold=True)
    _canvas_text(canvas, brand, document.get("issue_date"), .94, meta_top + .022, size=6.5, right=True)
    if _master_is_invoice(snapshot):
        _canvas_text(canvas, brand, "DUE DATE", .67, meta_top + .044, size=6.5, bold=True)
        _canvas_text(canvas, brand, document.get("due_date"), .94, meta_top + .044, size=6.5, right=True)
    if _master_is_receipt(snapshot):
        _draw_master_receipt(canvas, snapshot, brand, x=.12, top=.35, width=.74)
        return
    lines_top = .327 if brand.key == "texturin-bali" else .285
    for index, line in enumerate(_master_lines(snapshot)[:3]):
        top = lines_top + index * .035
        _canvas_text(canvas, brand, index + 1, .075, top, size=6.5)
        _canvas_text(canvas, brand, line.get("description"), .15, top, size=6.5)
        _canvas_text(canvas, brand, _idr(line.get("unit_price")), .61, top, size=6.5, right=True)
        _canvas_text(canvas, brand, f"{_text(line.get('quantity'))} {_text(line.get('unit'), '')}", .78, top, size=6.5, right=True)
        _canvas_text(canvas, brand, _idr(line.get("line_total")), .94, top, size=6.5, right=True)
    summary_top = .49 if brand.key == "texturin-bali" else .53
    summary_left = .70 if brand.key == "texturin-bali" else .68
    _canvas_text(canvas, brand, "Subtotal", summary_left, summary_top, size=6.5)
    _canvas_text(canvas, brand, _idr(totals.get("subtotal")), .94, summary_top, size=6.5, right=True)
    discount = int(totals.get("document_discount") or 0)
    if discount:
        summary_top += .022
        _canvas_text(canvas, brand, "Diskon", summary_left, summary_top, size=6.5, color=_DISCOUNT)
        _canvas_text(canvas, brand, _idr(discount), .94, summary_top, size=6.5, color=_DISCOUNT, right=True)
    tax = int(totals.get("tax") or 0)
    if tax:
        summary_top += .022
        _canvas_text(canvas, brand, _master_tax_label(snapshot), summary_left, summary_top, size=6.5)
        _canvas_text(canvas, brand, _idr(tax), .94, summary_top, size=6.5, right=True)
    summary_top += .033
    _canvas_text(canvas, brand, "TOTAL", summary_left, summary_top, size=7, bold=True)
    _canvas_text(canvas, brand, _idr(totals.get("total")), .94, summary_top, size=7, bold=True, right=True)
    policy = commercial_policy(brand.key)
    percent = int(policy.get("default_deposit_percent") or 0)
    if brand.key != "texturin-bali" and _master_has_deposit(snapshot):
        deposit = int(totals.get("total") or 0) * percent // 100
        _canvas_text(canvas, brand, f"SIGNATURE FEE ({percent}%)", .55, summary_top + .030, size=6.3, bold=True)
        _canvas_text(canvas, brand, _idr(deposit), .94, summary_top + .030, size=6.3, bold=True, right=True)
    if brand.key != "texturin-bali":
        terms = [] if _master_is_invoice(snapshot) else [*policy.get("default_terms", [])]
        terms.extend(_text(value) for value in (document.get("payment_terms"), document.get("notes")) if _text(value))
        if not terms:
            terms = ["Pembayaran sesuai tanggal jatuh tempo yang tercantum."]
        _canvas_paragraph(canvas, brand, "\n\n".join(terms), .068, .65, .80, size=5.8, leading=7.2, italic=True)
    bank = _mapping(issuer.get("bank_details"))
    bank_top = .60 if brand.key == "texturin-bali" else .865
    _canvas_text(canvas, brand, "BANK DETAILS", .068, bank_top, size=6.3, bold=True)
    _canvas_text(canvas, brand, f"{_text(bank.get('bank'))} · {_text(bank.get('account_number'))}", .068, bank_top + .022, size=6.1)
    _canvas_text(canvas, brand, bank.get("account_name"), .068, bank_top + .044, size=6.1)
    _canvas_text(canvas, brand, "THANK YOU", .83, .90, size=6, bold=True)
    _canvas_text(canvas, brand, issuer.get("display_name"), .94, .94, size=9, right=True)


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
        "texturin": "INVOICE QUOTATION QUOTATION NO. PPM QTY/LUAS BANK DETAILS THANK YOU",
        "texturin-surabaya": "INVOICE QUOTATION QUOTATION NO. PPM QTY/LUAS BANK DETAILS SIGNATURE FEE THANK YOU",
        "texturin-bali": "INVOICE QUOTATION QUOTATION NO. PPM QTY/LUAS AREA (M²) BANK DETAILS THANK YOU",
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
    if brand.key == "hollawall":
        _draw_hollawall_master(canvas, snapshot, brand)
    elif brand.key == "hojja":
        _draw_hojja_master(canvas, snapshot, brand)
    else:
        _draw_texturin_master(canvas, snapshot, brand)
    _draw_master_watermark(canvas, snapshot, brand)
    _draw_master_footer(canvas, snapshot, brand)
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
    if brand.key in _MASTER_ART and len(_master_lines(snapshot)) <= 3:
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
