"""
Generate a 2-page client guide PDF with a clean visual layout.
Output: docs/Client_Guide.pdf
"""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)


# Color palette
TEAL = colors.HexColor("#1DB7C5")
DARK = colors.HexColor("#231F20")
PINK = colors.HexColor("#EE396D")
GRAY = colors.HexColor("#F3F5F7")
LIGHT = colors.HexColor("#FAFBFC")
BORDER = colors.HexColor("#D7DDE3")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title_white": ParagraphStyle(
            "title_white",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=20,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "subtitle_white": ParagraphStyle(
            "subtitle_white",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            textColor=DARK,
            spaceAfter=2,
        ),
        "h3": ParagraphStyle(
            "h3",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.8,
            leading=12,
            textColor=DARK,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.0,
            leading=11.6,
            textColor=DARK,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.0,
            leading=10.2,
            textColor=DARK,
        ),
        "code": ParagraphStyle(
            "code",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=8.6,
            leading=11,
            textColor=DARK,
        ),
        "center_small": ParagraphStyle(
            "center_small",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10,
            textColor=DARK,
            alignment=TA_CENTER,
        ),
    }


def header_block(title, subtitle, width, styles):
    title_p = Paragraph(title, styles["title_white"])
    subtitle_p = Paragraph(subtitle, styles["subtitle_white"])
    t = Table([[title_p], [subtitle_p]], colWidths=[width])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("BOX", (0, 0), (-1, -1), 0.5, TEAL),
            ]
        )
    )
    return t


def section_header(title, width, styles):
    cell = Paragraph(title, styles["h2"])
    t = Table([["", cell]], colWidths=[6 * mm, width - 6 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), TEAL),
                ("BACKGROUND", (1, 0), (1, 0), LIGHT),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 6),
                ("TOPPADDING", (1, 0), (1, 0), 5),
                ("BOTTOMPADDING", (1, 0), (1, 0), 5),
                ("BOX", (1, 0), (1, 0), 0.5, BORDER),
            ]
        )
    )
    return t


def callout_box(title, body_lines, width, styles, accent=TEAL, bg=LIGHT):
    body = "<br/>".join(body_lines)
    p = Paragraph(f"<b>{title}</b><br/>{body}", styles["body"])
    t = Table([[p]], colWidths=[width])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.6, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def example_card(title, lines, width, styles):
    body = "<br/>".join(lines)
    p = Paragraph(
        f"<b>{title}</b><br/><font face='Courier'>{body}</font>",
        styles["code"],
    )
    t = Table([[p]], colWidths=[width])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GRAY),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def command_table(rows, width, styles):
    data = [[Paragraph("<b>Command</b>", styles["small"]), Paragraph("<b>Fungsi</b>", styles["small"])]]
    for cmd, desc in rows:
        data.append([Paragraph(cmd, styles["code"]), Paragraph(desc, styles["small"])])
    t = Table(data, colWidths=[width * 0.28, width * 0.72])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), GRAY),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def build_pdf(output_path):
    styles = _styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    usable_width = A4[0] - doc.leftMargin - doc.rightMargin

    story = []

    # Page 1
    story.append(
        header_block(
            "BOT KEUANGAN - PANDUAN PENGGUNA",
            "Cara input transaksi yang akurat, rapi, dan siap diaudit",
            usable_width,
            styles,
        )
    )
    story.append(Spacer(1, 6))

    story.append(section_header("Checklist cepat sebelum kirim pesan", usable_width, styles))
    checklist = Paragraph(
        "- Tulis nominal + keterangan + konteks (projek atau operasional).<br/>"
        "- Jika projek, tulis kata 'projek/project' + nama projek.<br/>"
        "- Jika operasional, tulis kata 'kantor'.<br/>"
        "- Jika bot minta pilihan, balas angka sesuai menu (batas 15 menit).",
        styles["body"],
    )
    story.append(Spacer(1, 3))
    story.append(checklist)
    story.append(Spacer(1, 6))

    story.append(section_header("Contoh pesan yang ideal", usable_width, styles))
    story.append(Spacer(1, 3))

    col_w = (usable_width - 6 * mm) / 2
    card_left = example_card(
        "Contoh PROJECT",
        [
            "DP 5jt projek Taman Indah",
            "Pelunasan projek Taman Indah 20jt",
            "Beli cat 350rb projek Taman Indah",
        ],
        col_w,
        styles,
    )
    card_right = example_card(
        "Contoh OPERASIONAL",
        [
            "Bayar gaji staff kantor 2.500.000",
            "Beli ATK kantor 150rb",
            "Listrik kantor 1.250.000",
        ],
        col_w,
        styles,
    )
    story.append(Table([[card_left, card_right]], colWidths=[col_w, col_w], hAlign="LEFT", style=[]))
    story.append(Spacer(1, 4))
    story.append(
        example_card(
            "Contoh TRANSFER / UPDATE SALDO DOMPET",
            [
                "Transfer 5jt dari CV HB ke TX SBY",
                "Update saldo: isi dompet TX BALI 2jt dari CV HB",
            ],
            usable_width,
            styles,
        )
    )
    story.append(Spacer(1, 6))

    story.append(
        callout_box(
            "Foto struk dan OCR",
            [
                "Tambahkan caption: 'Struk bensin 205rb + fee 2.500'.",
                "Jika bot menampilkan OCR, balas 'OK' atau ketik nominal yang benar.",
            ],
            usable_width,
            styles,
        )
    )
    story.append(Spacer(1, 6))

    story.append(
        callout_box(
            "Agar bot selalu merespon di grup",
            [
                "Gunakan trigger: '+catat ...' atau '/catat ...'.",
                "Atau mention bot: '@Bot catat ...'.",
                "Pesan harus ada nominal + kata kerja (beli/bayar/transfer).",
            ],
            usable_width,
            styles,
            accent=PINK,
        )
    )

    story.append(PageBreak())

    # Page 2
    story.append(section_header("Dompet dan company", usable_width, styles))
    story.append(Spacer(1, 3))
    story.append(
        Paragraph(
            "<b>Dompet tersedia:</b><br/>"
            "- CV HB (101) -> menaungi HOLLA dan HOJJA<br/>"
            "- TX SBY (216) -> Texturin Surabaya<br/>"
            "- TX BALI (087) -> Texturin Bali",
            styles["body"],
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "<b>Mode Project (pilih company):</b> 1 HOLLA, 2 HOJJA, 3 TEXTURIN-Surabaya, 4 TEXTURIN-Bali<br/>"
            "<b>Mode Operasional (pilih dompet):</b> 1 CV HB (101), 2 TX SBY (216), 3 TX BALI (087)",
            styles["body"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        callout_box(
            "Salah mode? Bisa ganti di menu",
            [
                "Operasional -> Project: pilih '4. Ini ternyata Project'.",
                "Project -> Operasional: pilih '5. Ini ternyata Operasional Kantor'.",
                "Untuk CV HB, nama projek otomatis diprefix HOLLA atau HOJJA.",
            ],
            usable_width,
            styles,
        )
    )
    story.append(Spacer(1, 6))

    story.append(section_header("Alur singkat bot", usable_width, styles))
    story.append(Spacer(1, 3))
    story.append(
        Paragraph(
            "1) User kirim transaksi<br/>"
            "2) Bot analisis dan tanya jika data kurang<br/>"
            "3) Bot minta pilihan dompet/company<br/>"
            "4) Bot tampilkan draft untuk konfirmasi<br/>"
            "5) Bot simpan ke spreadsheet dan kirim ringkasan",
            styles["body"],
        )
    )
    story.append(Spacer(1, 10))

    story.append(section_header("Start & Finish projek", usable_width, styles))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Bot memberi label otomatis di nama projek:<br/>"
            "- (Start) saat projek baru pertama kali muncul.<br/>"
            "- (Finish) saat pemasukan mengandung kata: pelunasan, lunas, selesai, final payment.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        example_card(
            "Contoh pesan untuk Start/Finish",
            [
                "DP 5jt projek Taman Indah  -> (Start)",
                "Pelunasan projek Taman Indah 20jt  -> (Finish)",
            ],
            usable_width,
            styles,
        )
    )
    story.append(Spacer(1, 6))

    story.append(section_header("Command penting", usable_width, styles))
    story.append(Spacer(1, 3))
    story.append(
        Paragraph(
            "<b>Monitoring:</b> /status, /saldo, /list, /laporan, /laporan30<br/>"
            "<b>PDF:</b> /exportpdf 2026-01 &nbsp;|&nbsp; /exportpdf 2025-09-22 2025-10-22<br/>"
            "<b>Revisi:</b> /revisi 150rb, /revisi operational, /revisi project Nama, /undo<br/>"
            "<b>Help:</b> /start, /help, /link",
            styles["body"],
        )
    )
    story.append(Spacer(1, 6))

    story.append(section_header("Catatan penting", usable_width, styles))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "- Batas waktu jawab menu adalah 15 menit. Jika lewat, kirim ulang transaksi.<br/>"
            "- (Start) ditandai saat projek baru. (Finish) saat ada kata: pelunasan, lunas, selesai.<br/>"
            "- Untuk revisi, selalu reply pesan bot agar transaksi yang benar ditemukan.",
            styles["body"],
        )
    )

    doc.build(story)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "Client_Guide.pdf")
    build_pdf(out)
    print(f"PDF created: {out}")
