"""
formatters.py - Message Formatting Utilities

Contains:
- format_success_reply: Format success message for transactions
- format_success_reply_new: New format with dompet info
- format_mention: Format mention prefix for groups
- build_selection_prompt: Build company selection prompt
- START_MESSAGE, HELP_MESSAGE: Welcome and help messages
"""

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

START_MESSAGE = f"""💼 *Bot Keuangan*

*Smart. Simple. Sat-set.*

*━━ Cara Pakai ━━*
💬 *Ketik Biasa:* `Beli semen 500rb`
📷 *Kirim Foto:* Struk/Nota (bisa banyak!)
🗣️ *Voice Note:* "Bayar tukang 2 juta"

*━━ Di Group Chat ━━*
Gak perlu kode-kodean! Bot otomatis muncul kalau ada transaksi.
Contoh: `Bayar listrik 500rb` (Bot langsung respon)
*Bot cuek?* Mention `@Bot` atau pakai `+catat`

*━━ Dompet & Company ━━*
{SELECTION_DISPLAY}

*━━ Menu ━━*
`/status` Dashboard  •  `/saldo` Cek saldo
`/list` Riwayat  •  `/laporan` Report 7 hari
`/tanya ...` Tanya AI  •  `/link` Buka Sheets

*━━ Tips Akurasi ━━*
- Jika transaksi *project*, tulis kata **projek/project** + nama projek  
  contoh: `bayar fee Nopal projek Taman Cafe Bali`
- Jika *operasional*, tulis kata **kantor**  
  contoh: `bayar gaji Nopal kantor`
- Jika ambigu, bot akan tanya dulu

💡 Reply transaksi + `/revisi` buat koreksi
"""


HELP_MESSAGE = f"""📖 *Panduan Bot Keuangan*

*━━ Input Transaksi ━━*
✅ `Beli material 500rb buat Renovasi`
✅ `Bayar gaji tukang 2jt`
✅ `Isi dompet holja 10jt`
✅ 📷 Foto struk (langsung kirim aja!)

*━━ Fitur Grup Pintar ━━*
Bot otomatis baca pesan yang ada *angka* & *kata kerja*.
• `Beli kopi 25rb` → ✅ Bot respon
• `Halo pagi` → ❌ Bot diam (anti-spam)

*Kalau darurat/bot diam:*
• Mention: `@Bot catat ini dong...`
• Perintah: `/catat ...`

*━━ Pilih Company (1-4) ━━*
{SELECTION_DISPLAY}

*━━ Kategori (Auto Detect) ━━*
{', '.join(ALLOWED_CATEGORIES)}

*━━ Tips Akurasi ━━*
- Project: selalu tulis **projek/project** + nama projek
- Operasional: tulis **kantor** untuk biaya kantor
- Jika sinyal bentrok, bot akan minta konfirmasi

*━━ Menu Lengkap ━━*
📊 `/status` - Dashboard
💰 `/saldo` - Saldo tiap dompet
📋 `/list` - Riwayat transaksi
📈 `/laporan` - Report mingguan
📈 `/laporan30` - Report bulanan
🤖 `/tanya [pertanyaan]` - Analisa AI
🔗 `/link` - Link Spreadsheet
📄 `/exportpdf` - Download PDF

*━━ Koreksi ━━*
Salah input? Reply pesannya, ketik:
`/revisi 150rb` (untuk ubah nominal)
`/cancel` (untuk batal)"""


def format_mention(sender_name: str, is_group: bool = False) -> str:
    """
    Return mention prefix for group chat responses.
    """
    if is_group and sender_name:
        # Clean sender name
        clean_name = sender_name.replace('@', '').strip()
        return f"@{clean_name}, "
    return ""


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
        ket = t.get('keterangan', '-') or '-'
        # Remove OCR artifacts
        if 'Receipt/Struk' in ket or 'Here is the' in ket:
            ket = 'Transfer'
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
    lines.append("💡 Ralat jumlah: reply /revisi 150rb")
    lines.append("📊 Cek ringkas: /status | /saldo")
    
    return '\n'.join(lines)


def format_draft_summary_operational(transactions: list, dompet_sheet: str, category: str, mention: str = "") -> str:
    """Format draft confirmation for operational transactions.
    
    Note: mention parameter is kept for backward compatibility but is ignored.
    The send_reply() function already handles @mention via format_mention_body().
    """
    total = sum(int(t.get('jumlah', 0) or 0) for t in transactions)
    item = transactions[0].get('keterangan', '-') if transactions else '-'
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
    return "\n".join(lines)


def format_draft_summary_project(transactions: list, dompet_sheet: str, company: str, mention: str = "") -> str:
    """Format draft confirmation for project transactions.
    
    Note: mention parameter is kept for backward compatibility but is ignored.
    The send_reply() function already handles @mention via format_mention_body().
    """
    total = sum(int(t.get('jumlah', 0) or 0) for t in transactions)
    item = transactions[0].get('keterangan', '-') if transactions else '-'
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
        "",
        "Konfirmasi simpan?",
        "1️⃣ Simpan",
        "2️⃣ Ganti dompet",
        "3️⃣ Ubah projek",
        "4️⃣ Batal"
    ]
    return "\n".join(lines)


# For testing
if __name__ == '__main__':
    print("Formatter Tests")
    print(f"format_mention('User', True): {format_mention('User', True)}")
    tx = [{'keterangan': 'Test', 'jumlah': 100000, 'tipe': 'Pengeluaran'}]
    print(f"build_selection_prompt: {build_selection_prompt(tx)[:100]}...")
