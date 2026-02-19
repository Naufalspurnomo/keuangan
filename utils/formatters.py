"""
formatters.py - Message Formatting Utilities

Contains:
- format_success_reply: Format success message for transactions
- format_success_reply_new: New format with dompet info
- format_mention: Format mention prefix for groups
- build_selection_prompt: Build company selection prompt
- format_reply_message: Normalize outgoing bot message style
- append_active_transaction_notice: Add active-transaction timeout note
- START_MESSAGE, HELP_MESSAGE: Welcome and help messages
"""

import re
from datetime import datetime
from security import ALLOWED_CATEGORIES, now_wib
from sheets_helper import check_budget_alert, normalize_project_display_name

# Build categories list for display
CATEGORIES_DISPLAY = '\n'.join(f"  • {cat}" for cat in ALLOWED_CATEGORIES)

# Build dompet & company selection display (4 PROJECT options)
# NOTE: KANTOR expenses go to Operasional sheet, not listed here
SELECTION_DISPLAY = """  📁 CV HB (101):
     1. HOLLA
     2. HOJJA
  📁 TX SBY (216):
     3. TEXTURIN-Surabaya
  📁 TX BALI (087):
     4. TEXTURIN-Bali"""

# Group chat triggers
GROUP_TRIGGERS = ["+catat", "+bot", "+input", "/catat"]
ACTIVE_TRANSACTION_TIMEOUT_NOTE = "⏳ *Batas transaksi aktif: 15 menit.*"

START_MESSAGE = f"""BOT Keuangan

Smart. Simple. Sat-set.

Cara pakai:
- Ketik biasa: `beli semen 500rb projek Taman Indah`
- Kirim foto struk/nota (boleh banyak)
- Voice note juga bisa

Di group chat:
- Bot auto respon jika ada nominal + konteks transaksi
- Kalau bot diam, mention `@Bot` atau pakai `+catat` / `/catat`

Dompet & Company:
{SELECTION_DISPLAY}

Perintah cepat:
`/status` `/saldo` `/list` `/laporan` `/laporan30`
`/exportpdf` `/lunas <no>` `/tanya ...` `/link`

Koreksi cepat (reply pesan bot):
- `/revisi 150rb` (ubah nominal utama)
- `/revisi fee 3rb` (ubah fee/admin)
- `/revisi operational` atau `/revisi project Nama Projek`
- `/undo` (hapus transaksi terakhir)
- `/cancel` (batalkan sesi aktif)

Ketik `/help` untuk panduan lengkap.
"""


HELP_MESSAGE = f"""Panduan Bot Keuangan

Input transaksi (contoh):
- Project: `bayar tukang 2jt projek Taman Indah`
- Operasional: `bayar listrik kantor 850rb`
- Transfer/update saldo: `transfer 5jt dari CV HB ke TX SBY`
- Foto struk: kirim langsung, bot OCR lalu konfirmasi jika perlu

Fitur grup:
- Bot auto baca pesan transaksi (ada nominal + kata kerja)
- Jika bot diam, mention `@Bot ...` atau pakai `/catat ...`

Dompet & Company:
{SELECTION_DISPLAY}

Kategori auto-detect:
{', '.join(ALLOWED_CATEGORIES)}

Alur simpan:
1. Bot analisis dan minta data yang kurang
2. Pilih dompet/company
3. Bot kirim draft (`Draft Operasional` / `Draft Project`)
4. Balas angka untuk simpan/ubah/batal

Perintah utama:
`/start`, `/help`, `/status`, `/saldo`, `/list`
`/laporan`, `/laporan30`, `/exportpdf`, `/lunas <no>`
`/tanya ...`, `/link`

Contoh export PDF:
`/exportpdf 2026-01`
`/exportpdf 2025-09-22 2025-10-22`

Koreksi (reply pesan bot):
- `/revisi 150rb` (nominal utama)
- `/revisi fee 3rb` (fee/admin)
- `/revisi operational` (pindah ke operasional)
- `/revisi project Nama Projek` (pindah ke project)
- `/undo` (hapus transaksi terakhir)
- `/cancel` (batalkan sesi aktif)

Catatan akurasi:
- Project: tulis kata `projek/project` + nama projek
- Operasional: tulis kata `kantor`
- Project baru ditandai `(Start)`, pelunasan bisa ditandai `(Finish)`
"""


def _is_already_bold(line: str) -> bool:
    stripped = (line or "").strip()
    return len(stripped) >= 2 and stripped.startswith("*") and stripped.endswith("*")


def _is_title_candidate(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped:
        return False
    if _is_already_bold(stripped):
        return False
    if stripped.startswith(("@", "-", "•", "`", ">", "|")):
        return False
    if re.match(r"^\d+[\.\)]\s+", stripped):
        return False
    if "http://" in stripped or "https://" in stripped:
        return False
    if stripped.count("*") >= 2 or stripped.count("`") >= 2:
        return False
    if len(stripped) > 90:
        return False
    return True


def ensure_bold_title(body: str) -> str:
    """Ensure first non-empty line (title) is bolded once."""
    if not isinstance(body, str):
        return body

    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        if _is_title_candidate(line):
            leading = len(line) - len(line.lstrip())
            trailing = len(line) - len(line.rstrip())
            core = line.strip()
            lines[idx] = f"{' ' * leading}*{core}*{' ' * trailing}"
        break
    return "\n".join(lines)


def append_active_transaction_notice(body: str) -> str:
    """Append active transaction timeout note if not already present."""
    text = (body or "").strip()
    if not text:
        return text
    if re.search(r"15\s*menit", text, flags=re.IGNORECASE):
        return text
    return f"{text}\n\n{ACTIVE_TRANSACTION_TIMEOUT_NOTE}"


def format_reply_message(body: str, active_transaction: bool = False) -> str:
    """Normalize outgoing bot message style."""
    formatted = ensure_bold_title(body or "")
    if active_transaction:
        formatted = append_active_transaction_notice(formatted)
    return formatted


def format_mention(sender_name: str, is_group: bool = False) -> str:
    """
    Return mention prefix for group chat responses.
    """
    if is_group and sender_name:
        # Clean sender name
        clean_name = sender_name.replace('@', '').strip()
        return f"@{clean_name}, "
    return ""


def _clean_preview_keterangan(value: str) -> str:
    """Normalize noisy OCR/LLM boilerplate for user-facing previews."""
    ket = (value or "-").strip()
    lower = ket.lower()
    noisy_markers = (
        "receipt/struk content:",
        "based on the provided image",
        "here is the extracted information",
        "the main transaction amount is listed",
    )
    if any(marker in lower for marker in noisy_markers):
        return "Transfer"
    return ket


def build_selection_prompt(transactions: list, mention: str = "") -> str:
    """Build the selection prompt message with dompet/company options.
    
    Note: mention parameter is kept for backward compatibility but is ignored.
    The send_reply() function already handles @mention via format_mention_body().
    """
    tx_lines = []
    for t in transactions:
        is_in = t.get('tipe') == 'Pemasukan'
        emoji = "💰" if is_in else "💸"
        label = "PEMASUKAN" if is_in else "PENGELUARAN"
        # Clean and truncate keterangan to avoid OCR garbage
        ket = _clean_preview_keterangan(t.get('keterangan', '-') or '-')
        # Truncate long descriptions
        if len(ket) > 40:
            ket = ket[:37] + '...'
        amount = t.get('jumlah', 0)
        tx_lines.append(f"   {emoji} {label}: Rp {amount:,}".replace(',', '.'))
        tx_lines.append(f"      _{ket}_")
    tx_preview = '\n'.join(tx_lines)
    
    total = sum(t.get('jumlah', 0) for t in transactions)
    item_count = len(transactions)
    
    # Don't include mention here - send_reply() already adds it via format_mention_body()
    return f"""📋 *TRANSAKSI TERDETEKSI*
━━━━━━━━━━━━━━━━━━━━━
{tx_preview}
━━━━━━━━━━━━━━━━━━━━━
📊 *Total: Rp {total:,}* ({item_count} item)

❓ *Simpan ke company mana?*

1️⃣ HOLLA _(CV HB)_
2️⃣ HOJJA _(CV HB)_
3️⃣ TEXTURIN-Surabaya _(TX SBY)_
4️⃣ TEXTURIN-Bali _(TX BALI)_
5️⃣ Operasional Kantor

↩️ _Balas dengan angka 1-5_
⏳ Batas waktu: 15 menit""".replace(',', '.')


def format_success_reply(transactions: list, company_sheet: str) -> str:
    """Format success reply message with company and project info."""
    lines = ["✅ *Transaksi Tercatat!*\n"]
    
    total = 0
    nama_projek_set = set()
    
    for t in transactions:
        amount = t.get('jumlah', 0)
        total += amount
        tipe_icon = "💰" if t.get('tipe') == 'Pemasukan' else "💸"
        lines.append(f"{tipe_icon} {t.get('keterangan', '-')}: Rp {amount:,}".replace(',', '.'))
        lines.append(f"   📁 {t.get('kategori', 'Lain-lain')}")
        
        # Track nama projek
        if t.get('nama_projek'):
            display_name = normalize_project_display_name(t['nama_projek'])
            if display_name:
                nama_projek_set.add(display_name)
    
    lines.append(f"\n*Total: Rp {total:,}*".replace(',', '.'))
    
    # Show company and project info
    lines.append(f"🏢 *Company:* {company_sheet}")
    if nama_projek_set:
        projek_str = ', '.join(nama_projek_set)
        lines.append(f"📋 *Nama Projek:* {projek_str}")
    
    # Check budget
    alert = check_budget_alert()
    if alert.get('message'):
        lines.append(f"\n{alert['message']}")
    
    return '\n'.join(lines)


def format_success_reply_new(transactions: list, dompet_sheet: str, company: str, mention: str = "") -> str:
    """Format success reply message with dompet and company info.
    
    Note: mention parameter is kept for backward compatibility but should be empty string.
    The send_reply() function already handles @mention via format_mention_body().
    """
    # Don't include mention here - send_reply() already adds it via format_mention_body()
    lines = ["✅ Transaksi Tercatat!\n"]
    
    total = 0
    nama_projek_set = set()
    
    # Transaction details (compact)
    for t in transactions:
        amount = t.get('jumlah', 0)
        total += amount
        is_in = t.get('tipe') == 'Pemasukan'
        tipe_icon = "💰" if is_in else "💸"
        label = "PEMASUKAN" if is_in else "PENGELUARAN"
        
        lines.append(f"{tipe_icon} {label} {t.get('keterangan', '-')}: Rp {amount:,}".replace(',', '.'))
        
        if t.get('nama_projek'):
            display_name = normalize_project_display_name(t['nama_projek'])
            if display_name:
                nama_projek_set.add(display_name)
    
    lines.append(f"\n📊 Total: Rp {total:,}".replace(',', '.'))
    
    # Location info (compact)
    lines.append(f"📍 {dompet_sheet} → {company}")
    
    if nama_projek_set:
        projek_str = ', '.join(nama_projek_set)
        lines.append(f"📋 Projek: {projek_str}")
    
    # Timestamp
    now = now_wib().strftime("%d %b %Y, %H:%M")
    lines.append(f"⏱️ {now}")
    
    # Next steps
    lines.append("\n↩️ Batalkan: /undo")
    lines.append("💡 Ralat jumlah utama: reply /revisi 150rb")
    lines.append("💡 Ralat fee: reply /revisi fee 3rb")
    lines.append("📊 Cek ringkas: /status | /saldo")
    
    return '\n'.join(lines)


def format_success_reply_operational(transactions: list, dompet_sheet: str, category: str = "", mention: str = "") -> str:
    """Format success reply message for operational transactions.

    Note: mention parameter is kept for backward compatibility but should be empty string.
    The send_reply() function already handles @mention via format_mention_body().
    """
    lines = ["✅ Transaksi Operasional Tercatat!\n"]

    total = 0
    for t in transactions:
        amount = int(t.get('jumlah', 0) or 0)
        total += amount
        is_in = t.get('tipe') == 'Pemasukan'
        tipe_icon = "💰" if is_in else "💸"
        label = "PEMASUKAN" if is_in else "PENGELUARAN"
        ket = _clean_preview_keterangan(t.get('keterangan', '-') or '-')
        lines.append(f"{tipe_icon} {label} {ket}: Rp {amount:,}".replace(',', '.'))

    lines.append(f"\n📊 Total: Rp {total:,}".replace(',', '.'))
    lines.append(f"📍 {dompet_sheet} → Operasional Kantor")
    lines.append(f"📂 Kategori: {category or 'Lain Lain'}")
    lines.append("📋 Projek: Operasional Kantor")

    tx_ids = [t.get('tx_id') for t in transactions if t.get('tx_id')]
    if tx_ids:
        lines.append(f"🆔 TX: {', '.join(tx_ids)}")

    now = now_wib().strftime("%d %b %Y, %H:%M")
    lines.append(f"⏱️ {now}")

    lines.append("\n↩️ Batalkan: /undo")
    lines.append("💡 Ralat jumlah utama: reply /revisi 150rb")
    lines.append("💡 Ralat fee: reply /revisi fee 3rb")
    lines.append("📊 Cek ringkas: /status | /saldo")

    return '\n'.join(lines)


def format_draft_summary_operational(transactions: list, dompet_sheet: str, category: str, mention: str = "") -> str:
    """Format draft confirmation for operational transactions.
    
    Note: mention parameter is kept for backward compatibility but is ignored.
    The send_reply() function already handles @mention via format_mention_body().
    """
    total = sum(int(t.get('jumlah', 0) or 0) for t in transactions)
    item = _clean_preview_keterangan(transactions[0].get('keterangan', '-') if transactions else '-')
    short_dompet = dompet_sheet or "-"
    
    # Don't include mention here - send_reply() already adds it via format_mention_body()
    lines = [
        "🧾 Draft Operasional",
        f"📝 {item}",
        f"💰 Nominal: Rp {total:,}".replace(',', '.'),
        f"💼 Dompet: {short_dompet}",
        f"📂 Kategori: {category or 'Lain Lain'}",
        "",
        "Konfirmasi simpan?",
        "1️⃣ Simpan",
        "2️⃣ Ganti dompet",
        "3️⃣ Ubah kategori",
        "4️⃣ Batal"
    ]
    return append_active_transaction_notice("\n".join(lines))


def format_draft_summary_project(transactions: list, dompet_sheet: str, company: str, mention: str = "",
                                 debt_source: str = "") -> str:
    """Format draft confirmation for project transactions.
    
    Note: mention parameter is kept for backward compatibility but is ignored.
    The send_reply() function already handles @mention via format_mention_body().
    """
    total = sum(int(t.get('jumlah', 0) or 0) for t in transactions)
    item = _clean_preview_keterangan(transactions[0].get('keterangan', '-') if transactions else '-')
    project_names = sorted({t.get('nama_projek') for t in transactions if t.get('nama_projek')})
    proj_display = ", ".join(project_names) if project_names else "-"
    short_dompet = dompet_sheet or "-"
    
    # Don't include mention here - send_reply() already adds it via format_mention_body()
    lines = [
        "🧾 Draft Project",
        f"📝 {item}",
        f"💰 Nominal: Rp {total:,}".replace(',', '.'),
        f"💼 Dompet: {short_dompet}",
        f"🏢 Company: {company or '-'}",
        f"📋 Projek: {proj_display}",
    ]
    if debt_source:
        lines.append(f"💳 Sumber dana (utang): {debt_source}")
    lines.extend([
        "",
        "Konfirmasi simpan?",
        "1️⃣ Simpan",
        "2️⃣ Ganti dompet",
        "3️⃣ Ubah projek",
        "4️⃣ Batal"
    ])
    return append_active_transaction_notice("\n".join(lines))


# For testing
if __name__ == '__main__':
    print("Formatter Tests")
    print(f"format_mention('User', True): {format_mention('User', True)}")
    tx = [{'keterangan': 'Test', 'jumlah': 100000, 'tipe': 'Pengeluaran'}]
    print(f"build_selection_prompt: {build_selection_prompt(tx)[:100]}...")
