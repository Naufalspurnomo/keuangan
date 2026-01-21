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
from sheets_helper import check_budget_alert

# Build categories list for display
CATEGORIES_DISPLAY = '\n'.join(f"  • {cat}" for cat in ALLOWED_CATEGORIES)

# Build dompet & company selection display
SELECTION_DISPLAY = """  📁 Dompet Holla:
     1. HOLLA
     2. HOJJA
  📁 Dompet Texturin Sby:
     3. TEXTURIN-Surabaya
  📁 Dompet Evan:
     4. TEXTURIN-Bali
     5. KANTOR"""

# Group chat triggers
GROUP_TRIGGERS = ["+catat", "+bot", "+input", "/catat"]

START_MESSAGE = f"""👋 *Selamat datang di Bot Keuangan!*

Bot ini mencatat pengeluaran & pemasukan ke Google Sheets.

━━━━━━━━━━━━━━━━━━━━━
📝 *CARA PAKAI*
━━━━━━━━━━━━━━━━━━━━━

*Private Chat:* Langsung kirim transaksi
*Group Chat:* Awali dengan `+catat`

*Contoh:*
• `+catat Beli cat 500rb projek Purana`
• `+catat Isi dompet holla 10jt`
• 📷 Foto struk dengan caption `+catat`

Setelah transaksi terdeteksi, pilih nomor (1-5).

*3 Dompet & 5 Company:*
{SELECTION_DISPLAY}

*4 Kategori (Auto-detect):*
{CATEGORIES_DISPLAY}

━━━━━━━━━━━━━━━━━━━━━
⚙️ *PERINTAH*
━━━━━━━━━━━━━━━━━━━━━
📊 `/status` - Dashboard keuangan
💰 `/saldo` - Saldo per dompet
📋 `/list` - Transaksi 7 hari terakhir
📈 `/laporan` - Laporan 7 hari
🗂️ `/dompet` - Daftar dompet
🔗 `/link` - Link Google Sheets
❓ `/help` - Panduan lengkap

🔒 Bot hanya MENAMBAH data, tidak bisa hapus.
"""


HELP_MESSAGE = f"""📖 *PANDUAN BOT KEUANGAN*

*Input Transaksi:*
1. Private: Langsung kirim
2. Group: Awali dengan `+catat`
3. Pilih nomor dompet & company (1-5)

💡 *Tips:*
- Sebutkan nama dompet agar lebih akurat (misal: "Isi dompet evan 2jt")
- Jika bot tidak yakin, bot akan minta pilihan 1-5
- Reply transaksi dengan `/revisi [jumlah]` jika salah nominal

*Contoh Input:*
• `+catat Beli material 500rb projek X`
• `+catat Bayar gaji 2jt`
• `+catat Isi dompet evan 10jt`

*3 Dompet & 5 Company:*
{SELECTION_DISPLAY}

*Kategori (Auto-detect):*
{', '.join(ALLOWED_CATEGORIES)}

━━━━━━━━━━━━━━━━━━━━━
*PERINTAH:*
━━━━━━━━━━━━━━━━━━━━━
📊 `/status` - Dashboard semua dompet
💰 `/saldo` - Saldo per dompet
📋 `/list` - Transaksi terakhir
📈 `/laporan` - Laporan 7 hari
📈 `/laporan30` - Laporan 30 hari
🗂️ `/dompet` - Daftar dompet
🗂️ `/kategori` - Daftar kategori
🤖 `/tanya [x]` - Tanya AI
🔗 `/link` - Link spreadsheet
📄 `/exportpdf` - Export PDF

_Koreksi data langsung di Google Sheets._"""


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
    """Build the selection prompt message with dompet/company options."""
    tx_lines = []
    for t in transactions:
        emoji = "💰" if t.get('tipe') == 'Pemasukan' else "💸"
        tx_lines.append(f"   {emoji} {t.get('keterangan', '-')}: Rp {t.get('jumlah', 0):,}".replace(',', '.'))
    tx_preview = '\n'.join(tx_lines)
    
    total = sum(t.get('jumlah', 0) for t in transactions)
    
    item_count = len(transactions)
    return f"""{mention}📋 Transaksi ({item_count} item)
{tx_preview}
📊 Total: Rp {total:,}

❓ Simpan ke company mana? (1-5)

📁 Dompet Holla: 1️⃣ HOLLA | 2️⃣ HOJJA
📁 Texturin Sby: 3️⃣ TEXTURIN-Surabaya
📁 Dompet Evan: 4️⃣ TEXTURIN-Bali | 5️⃣ KANTOR

⏳ Batas waktu: 15 menit
💡 Salah pilih? /cancel lalu kirim ulang""".replace(',', '.')


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
            nama_projek_set.add(t['nama_projek'])
    
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
    """Format success reply message with dompet and company info."""
    lines = [f"{mention}✅ Transaksi Tercatat!\n"]
    
    total = 0
    nama_projek_set = set()
    
    # Transaction details (compact)
    for t in transactions:
        amount = t.get('jumlah', 0)
        total += amount
        tipe_icon = "💰" if t.get('tipe') == 'Pemasukan' else "💸"
        lines.append(f"{tipe_icon} {t.get('keterangan', '-')}: Rp {amount:,}".replace(',', '.'))
        
        if t.get('nama_projek'):
            nama_projek_set.add(t['nama_projek'])
    
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
    lines.append("\n💡 Ralat jumlah: reply /revisi 150rb")
    lines.append("📊 Cek ringkas: /status | /saldo")
    
    return '\n'.join(lines)


# For testing
if __name__ == '__main__':
    print("Formatter Tests")
    print(f"format_mention('User', True): {format_mention('User', True)}")
    tx = [{'keterangan': 'Test', 'jumlah': 100000, 'tipe': 'Pengeluaran'}]
    print(f"build_selection_prompt: {build_selection_prompt(tx)[:100]}...")
