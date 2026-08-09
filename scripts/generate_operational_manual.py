"""Generate the handover PDF for the Bot Keuangan operations manual.

Source of truth for copy is docs/PANDUAN_OPERASIONAL_BOT_KEUANGAN.md.
Run:
    python scripts/generate_operational_manual.py
"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "PANDUAN_OPERASIONAL_BOT_KEUANGAN.md"
OUTPUT = ROOT / "output" / "pdf" / "Panduan_Operasional_Bot_Keuangan.pdf"

NAVY = colors.HexColor("#102A43")
TEAL = colors.HexColor("#0C8C87")
MINT = colors.HexColor("#DFF5F1")
INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#627D98")
LINE = colors.HexColor("#D9E2EC")
PALE = colors.HexColor("#F7FAFC")
AMBER = colors.HexColor("#F4B942")
WHITE = colors.white


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "cover_kicker",
            parent=sample["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#8EE6DB"),
            spaceAfter=12,
            alignment=TA_LEFT,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=31,
            leading=36,
            textColor=WHITE,
            spaceAfter=14,
            alignment=TA_LEFT,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=12.5,
            leading=19,
            textColor=colors.HexColor("#D9E2EC"),
            alignment=TA_LEFT,
        ),
        "title": ParagraphStyle(
            "title",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=NAVY,
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=21,
            textColor=NAVY,
            spaceBefore=18,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            textColor=TEAL,
            spaceBefore=12,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9.6,
            leading=14.2,
            textColor=INK,
            spaceAfter=7,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9.4,
            leading=13.6,
            textColor=INK,
            leftIndent=14,
            firstLineIndent=-9,
            spaceAfter=3,
        ),
        "command": ParagraphStyle(
            "command",
            parent=sample["Code"],
            fontName="Courier-Bold",
            fontSize=9.1,
            leading=13,
            textColor=colors.HexColor("#075E54"),
            backColor=colors.HexColor("#EDF8F6"),
            borderColor=colors.HexColor("#B9E5DD"),
            borderWidth=0.4,
            borderPadding=6,
            leftIndent=6,
            rightIndent=6,
            spaceBefore=2,
            spaceAfter=8,
        ),
        "table": ParagraphStyle(
            "table",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=7.7,
            leading=10.2,
            textColor=INK,
        ),
        "table_head": ParagraphStyle(
            "table_head",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.7,
            leading=10.1,
            textColor=WHITE,
        ),
        "note": ParagraphStyle(
            "note",
            parent=sample["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8.6,
            leading=12.2,
            textColor=MUTED,
            leftIndent=10,
            borderColor=TEAL,
            borderWidth=1.2,
            borderPadding=7,
            spaceBefore=3,
            spaceAfter=9,
        ),
    }


def _inline(text: str) -> str:
    escaped = html.escape(text.strip())
    escaped = re.sub(
        r"\*\*(.+?)\*\*",
        r"<b>\1</b>",
        escaped,
    )
    return escaped


def _table_data(lines: list[str], styles: dict[str, ParagraphStyle], width: float) -> Table:
    raw_rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        raw_rows.append(cells)

    col_count = max(len(row) for row in raw_rows)
    if col_count == 4:
        ratios = [0.21, 0.25, 0.27, 0.27]
    elif col_count == 3:
        ratios = [0.25, 0.34, 0.41]
    else:
        ratios = [1 / col_count] * col_count
    col_widths = [width * ratio for ratio in ratios]

    data = []
    for row_index, row in enumerate(raw_rows):
        padded = row + [""] * (col_count - len(row))
        style = styles["table_head"] if row_index == 0 else styles["table"]
        data.append([Paragraph(_inline(cell), style) for cell in padded])

    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
            ]
        )
    )
    return table


def _draw_cover(canvas, doc) -> None:
    page_w, page_h = A4
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, page_w, page_h, stroke=0, fill=1)
    canvas.setFillColor(TEAL)
    canvas.circle(page_w - 30 * mm, page_h - 38 * mm, 41 * mm, stroke=0, fill=1)
    canvas.setFillColor(AMBER)
    canvas.circle(page_w - 13 * mm, page_h - 96 * mm, 10 * mm, stroke=0, fill=1)
    canvas.setStrokeColor(colors.HexColor("#5AC8BE"))
    canvas.setLineWidth(1)
    canvas.line(25 * mm, 42 * mm, page_w - 25 * mm, 42 * mm)
    canvas.setFillColor(colors.HexColor("#8EE6DB"))
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(25 * mm, 32 * mm, "DOKUMEN SERAH-TERIMA ADMIN")
    canvas.setFillColor(colors.HexColor("#D9E2EC"))
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(page_w - 25 * mm, 32 * mm, "Berbasis implementasi bot per 3 Agustus 2026")
    canvas.restoreState()


def _draw_body(canvas, doc) -> None:
    page_w, page_h = A4
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, page_h - 15 * mm, page_w - 18 * mm, page_h - 15 * mm)
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 7.8)
    canvas.drawString(18 * mm, page_h - 11 * mm, "BOT KEUANGAN - PANDUAN OPERASIONAL")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.6)
    canvas.drawRightString(page_w - 18 * mm, 11 * mm, f"Halaman {doc.page}")
    canvas.drawString(18 * mm, 11 * mm, "Gunakan command dan template sesuai konteks transaksi.")
    canvas.restoreState()


def _parse_markdown(source: str, styles: dict[str, ParagraphStyle], content_width: float) -> list:
    lines = source.splitlines()
    story = []
    current_paragraph: list[str] = []
    table_lines: list[str] = []
    # Let sections flow naturally. Forced chapter page breaks made short
    # carry-over content consume mostly blank pages in the printed handbook.
    chapter_breaks: set[str] = set()

    def flush_paragraph() -> None:
        nonlocal current_paragraph
        if current_paragraph:
            text = " ".join(part.strip() for part in current_paragraph).strip()
            if text:
                note = text.startswith("Catatan ") or text.startswith("Jika bot mengirim")
                story.append(Paragraph(_inline(text), styles["note"] if note else styles["body"]))
            current_paragraph = []

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            story.append(Spacer(1, 2))
            story.append(_table_data(table_lines, styles, content_width))
            story.append(Spacer(1, 8))
            table_lines = []

    for index, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped.startswith("|"):
            flush_paragraph()
            table_lines.append(stripped)
            continue
        flush_table()

        if not stripped.strip():
            flush_paragraph()
            continue

        if stripped.startswith("# "):
            flush_paragraph()
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            title = stripped[3:].strip()
            if title in chapter_breaks and story:
                story.append(PageBreak())
            story.append(Paragraph(_inline(title), styles["h2"]))
            continue
        if stripped.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(_inline(stripped[4:]), styles["h3"]))
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            story.append(Paragraph("- " + _inline(stripped[2:]), styles["bullet"]))
            continue
        if re.match(r"^\d+\.\s", stripped):
            flush_paragraph()
            number, text = stripped.split(".", 1)
            story.append(Paragraph(f"{number}. " + _inline(text.strip()), styles["bullet"]))
            continue
        if stripped.startswith("   ") and stripped.strip():
            flush_paragraph()
            story.append(Paragraph(_inline(stripped.strip()), styles["command"]))
            continue

        current_paragraph.append(stripped)

    flush_paragraph()
    flush_table()
    return story


def generate() -> Path:
    source = SOURCE.read_text(encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()

    margin_x = 18 * mm
    margin_top = 21 * mm
    margin_bottom = 17 * mm
    page_w, page_h = A4
    frame = Frame(
        margin_x,
        margin_bottom,
        page_w - 2 * margin_x,
        page_h - margin_top - margin_bottom,
        id="body",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    cover_frame = Frame(
        25 * mm,
        54 * mm,
        page_w - 50 * mm,
        page_h - 115 * mm,
        id="cover",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        title="Buku Panduan Operasional Bot Keuangan",
        author="Bot Keuangan",
        subject="Serah-terima penggunaan dan operasi Bot Keuangan",
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_frame], onPage=_draw_cover),
            PageTemplate(id="body", frames=[frame], onPage=_draw_body),
        ]
    )

    story = [
        Spacer(1, 40 * mm),
        Paragraph("BUKU PANDUAN OPERASIONAL", styles["cover_kicker"]),
        Paragraph("Bot<br/>Keuangan", styles["cover_title"]),
        Paragraph(
            "Panduan lengkap untuk mencatat transaksi, membaca laporan, "
            "mengelola koreksi dan hutang, serta melakukan serah-terima admin dengan aman.",
            styles["cover_subtitle"],
        ),
        Spacer(1, 16 * mm),
        Table(
            [
                [
                    Paragraph("SCOPE", styles["cover_kicker"]),
                    Paragraph("WhatsApp dan Telegram", styles["cover_subtitle"]),
                ],
                [
                    Paragraph("SUMBER DATA", styles["cover_kicker"]),
                    Paragraph("Google Sheets dengan state durable produksi", styles["cover_subtitle"]),
                ],
                [
                    Paragraph("VALIDASI", styles["cover_kicker"]),
                    Paragraph("Command, routing rule, OCR, dan data nyata", styles["cover_subtitle"]),
                ],
            ],
            colWidths=[31 * mm, 105 * mm],
            style=TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#5AC8BE")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            ),
        ),
        NextPageTemplate("body"),
        PageBreak(),
    ]
    story.extend(_parse_markdown(source, styles, frame._width))
    doc.build(story)
    return OUTPUT


if __name__ == "__main__":
    created = generate()
    print(created)
