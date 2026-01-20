"""
messages.py - Centralized Speech Layer

All bot messages in one place:
- Easy to edit without touching logic
- Consistent across channels (Telegram, WhatsApp, WuzAPI)
- Platform-aware formatting (Markdown vs plain text)

Usage:
    from messages import MSG, fmt
    
    # Get template
    send_reply(MSG.SUCCESS_SAVED)
    
    # Format with data
    send_reply(fmt.success(transactions, dompet, company))
"""

from datetime import datetime
from typing import List, Dict, Optional

# Import single source of truth
try:
    from security import ALLOWED_CATEGORIES
    from sheets_helper import SELECTION_OPTIONS
except ImportError:
    # Fallback if imports fail (e.g. during testing isolated file)
    ALLOWED_CATEGORIES = ["Operasi Kantor", "Bahan Alat", "Gaji", "Lain-lain"]
    SELECTION_OPTIONS = []

# ===================== CONFIGURATION =====================

# TTL for pending transactions (used in messages)
PENDING_TTL_MINUTES = 15

def get_selection_display() -> str:
    """Build selection display string dynamically from sheets_helper."""
    if not SELECTION_OPTIONS:
        return ""
        
    # Group by Dompet
    grouped = {}
    for opt in SELECTION_OPTIONS:
        dompet = opt['dompet']
        if dompet not in grouped:
            grouped[dompet] = []
        grouped[dompet].append(f"{opt['idx']}️⃣ {opt['company']}")
    
    lines = []
    for dompet, opts in grouped.items():
        lines.append(f"📁 {dompet}: {' | '.join(opts)}")
    
    return "\n".join(lines)




# ===================== RAW TEMPLATES =====================

class MSG:
    """Static message templates (no formatting needed)."""
    
    # === STATUS ===
    LOADING_SCAN = "🔍 Scan..."
    LOADING_SCAN_FULL = "🔍 Memindai struk..."
    LOADING_ANALYZE = "🔍 Menganalisis..."
    LOADING_STATUS = "⏳ Mengambil data..."
    
    # === CANCEL ===
    CANCELLED = "❌ Transaksi dibatalkan."
    ALL_REMOVED = "❌ Semua item dihapus. Transaksi dibatalkan."
    
    # === ERRORS ===
    ERROR_SYSTEM = "❌ Terjadi kesalahan sistem."
    ERROR_INVALID_SELECTION = "❌ Balas dengan angka 1-5. Contoh: 1"
    ERROR_SELECTION_SINGLE = "❌ Pilih satu angka saja (1-5)."
    ERROR_SELECTION_RANGE = "❌ Pilihan tidak ada. Ketik 1-5."
    ERROR_INVALID_OPTION = "❌ Pilihan tidak valid."
    
    ERROR_NO_IMAGE_TX = (
        "❓ Tidak ada transaksi terdeteksi dari gambar.\n\n"
        "Tips:\n"
        "• Pastikan struk/nota terlihat jelas\n"
        "• Tambahkan caption seperti: 'Beli material projek X'"
    )
    
    ERROR_PROJECT_INVALID = (
        "❌ Nama projek tidak valid.\n\n"
        "Ketik nama projek dengan jelas, contoh:\n"
        "• Purana Ubud\n"
        "• Villa Sunset Bali\n\n"
        "Atau ketik /cancel untuk batal"
    )
    
    # === EXPIRED ===
    SESSION_EXPIRED = (
        "⌛ Sesi sebelumnya sudah kedaluwarsa (lebih dari 15 menit).\n"
        "Kirim transaksi lagi ya."
    )
    
    # === REVISION ===
    REVISION_NO_QUOTE = (
        "⚠️ Gagal Revisi\n\n"
        "Untuk merevisi, balas (reply) pesan konfirmasi bot.\n\n"
        "1. Reply pesan '✅ Transaksi Tercatat!'\n"
        "2. Ketik /revisi [jumlah baru]"
    )
    
    REVISION_INVALID_FORMAT = (
        "⚠️ Format Salah.\n\n"
        "Untuk merevisi, balas pesan ini dengan format:\n"
        "/revisi [jumlah]\n\n"
        "Contoh: /revisi 150000"
    )
    
    REVISION_INVALID_AMOUNT = (
        "❓ Jumlah tidak valid.\n\n"
        "Gunakan format:\n"
        "• /revisi 150000\n"
        "• /revisi 1.5jt\n"
        "• /revisi 500rb"
    )
    
    REVISION_FAILED = (
        "❌ Gagal update transaksi.\n\n"
        "Kemungkinan penyebab:\n"
        "• Transaksi sudah dihapus\n"
        "• Koneksi ke spreadsheet gagal\n\n"
        "Coba lagi atau hubungi admin."
    )


# ===================== DYNAMIC FORMATTERS =====================

class fmt:
    """Dynamic message formatters with data."""
    
    @staticmethod
    def tx_icon(tipe: str) -> str:
        """Get transaction icon: 🟢 for income,🔴 for expense."""
        return "🟢" if tipe == "Pemasukan" else "🔴"
    
    @staticmethod
    def tx_line(t: Dict, indent: str = "") -> str:
        """Format single transaction line."""
        icon = fmt.tx_icon(t.get('tipe', 'Pengeluaran'))
        desc = t.get('keterangan', '-')
        amount = t.get('jumlah', 0)
        return f"{indent}{icon} {desc}: Rp {amount:,}".replace(',', '.')
    
    @staticmethod
    def tx_list(transactions: List[Dict], indent: str = "   ") -> str:
        """Format list of transactions."""
        return "\n".join(fmt.tx_line(t, indent) for t in transactions)
    
    @staticmethod
    def total(amount: int) -> str:
        """Format total amount."""
        return f"📊 Total: Rp {amount:,}".replace(',', '.')
    
    @staticmethod
    def timestamp() -> str:
        """Get current timestamp string."""
        return datetime.now().strftime("%d %b %Y, %H:%M")
    
    # === PROMPTS ===
    
    @staticmethod
    def prompt_project(transactions: List[Dict]) -> str:
        """Prompt user for project name."""
        item_count = len(transactions)
        total = sum(t.get('jumlah', 0) for t in transactions)
        items_str = fmt.tx_list(transactions)
        
        return (
            f"📋 Transaksi terdeteksi ({item_count} item)\n"
            f"{items_str}\n"
            f"{fmt.total(total)}\n\n"
            f"❓ Perlu nama projek (biar laporan per projek rapi)\n"
            f"Balas: nama projek saja\n"
            f"Contoh: Purana Ubud / Villa Sunset\n\n"
            f"⏳ Batas waktu: {PENDING_TTL_MINUTES} menit\n"
            f"Ketik /cancel untuk batal"
        )
    
    @staticmethod
    def prompt_company(transactions: List[Dict], mention: str = "") -> str:
        """Prompt user for company selection (1-5)."""
        item_count = len(transactions)
        total = sum(t.get('jumlah', 0) for t in transactions)
        items_str = fmt.tx_list(transactions)
        
        return (
            f"{mention}📋 Transaksi ({item_count} item)\n"
            f"{items_str}\n"
            f"{fmt.total(total)}\n\n"
            f"❓ Simpan ke company mana? (1-5)\n\n"
            f"{get_selection_display()}\n\n"
            f"⏳ Batas waktu: {PENDING_TTL_MINUTES} menit\n"
            f"💡 Salah pilih? /cancel lalu kirim ulang"
        )
    
    # === SUCCESS ===
    
    @staticmethod
    def success(transactions: List[Dict], dompet: str, company: str, mention: str = "") -> str:
        """Format success message after saving."""
        lines = [f"{mention}✅ Transaksi Tercatat!\n"]
        
        total = 0
        projek_set = set()
        
        for t in transactions:
            amount = t.get('jumlah', 0)
            total += amount
            lines.append(fmt.tx_line(t))
            if t.get('nama_projek'):
                projek_set.add(t['nama_projek'])
        
        lines.append(f"\n{fmt.total(total)}")
        lines.append(f"📍 {dompet} → {company}")
        
        if projek_set:
            lines.append(f"📋 Projek: {', '.join(projek_set)}")
        
        lines.append(f"⏱️ {fmt.timestamp()}")
        lines.append("\n💡 Ralat jumlah: reply /revisi 150rb")
        lines.append("📊 Cek ringkas: /status | /saldo")
        
        return '\n'.join(lines)
    
    @staticmethod
    def revision_success(keterangan: str, old_amount: int, new_amount: int, dompet: str) -> str:
        """Format revision success message."""
        diff = new_amount - old_amount
        diff_str = f"+Rp {diff:,}" if diff > 0 else f"-Rp {abs(diff):,}"
        
        return (
            f"✅ Revisi Berhasil!\n\n"
            f"📊 {keterangan}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"   Sebelum: Rp {old_amount:,}\n"
            f"   Sesudah: Rp {new_amount:,}\n"
            f"   Selisih: {diff_str}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📍 {dompet}\n"
            f"⏱️ {fmt.timestamp()}"
        ).replace(',', '.')
    
    # === MODIFIERS ===
    
    @staticmethod
    def item_removed(keyword: str, remaining: List[Dict], pending_type: str) -> str:
        """Format message after item removed from pending."""
        total = sum(t.get('jumlah', 0) for t in remaining)
        items = fmt.tx_list(remaining, "")
        
        msg = (
            f"✅ Dihapus: {keyword}\n\n"
            f"📋 Transaksi tersisa:\n{items}\n\n"
            f"{fmt.total(total)}\n\n"
        )
        
        if pending_type == 'needs_project':
            msg += "❓ Untuk projek apa ini?\nBalas dengan nama projek atau /cancel"
        else:
            msg += "Ketik 1-5 untuk pilih company atau /cancel"
        
        return msg
    
    @staticmethod
    def item_not_found(keyword: str) -> str:
        """Format message when item not found for removal."""
        return (
            f"❓ Tidak menemukan '{keyword}' dalam transaksi pending.\n\n"
            f"Ketik /cancel untuk batal semua, atau lanjutkan dengan input yang diminta."
        )
    
    @staticmethod
    def error_save(error: str) -> str:
        """Format save error message."""
        return f"❌ Gagal: {error}"


# ===================== LONG MESSAGES =====================

def get_start_message() -> str:
    """Get /start welcome message."""
    categories = '\n'.join(f"  • {cat}" for cat in ALLOWED_CATEGORIES)
    
    return f"""👋 Selamat datang di Bot Keuangan!

Bot ini mencatat pengeluaran & pemasukan ke Google Sheets.

━━━━━━━━━━━━━━━━━━━━━
📝 CARA PAKAI
━━━━━━━━━━━━━━━━━━━━━

Private Chat: Langsung kirim transaksi
Group Chat: Awali dengan +catat

Contoh:
• +catat Beli cat 500rb projek Purana
• +catat Isi dompet holla 10jt
• 📷 Foto struk dengan caption +catat

Setelah transaksi terdeteksi, pilih nomor (1-5).

3 Dompet & 5 Company:
{get_selection_display()}

4 Kategori (Auto-detect):
{categories}

━━━━━━━━━━━━━━━━━━━━━
⚙️ PERINTAH
━━━━━━━━━━━━━━━━━━━━━
📊 /status - Dashboard keuangan
💰 /saldo - Saldo per dompet
📋 /list - Transaksi 7 hari terakhir
📈 /laporan - Laporan 7 hari
🗂️ /dompet - Daftar dompet
❓ /help - Panduan lengkap

🔒 Bot hanya MENAMBAH data, tidak bisa hapus."""


def get_help_message() -> str:
    """Get /help message."""
    categories = ', '.join(ALLOWED_CATEGORIES)
    
    return f"""📖 PANDUAN BOT KEUANGAN

Input Transaksi:
1. Private: Langsung kirim
2. Group: Awali dengan +catat
3. Pilih nomor dompet & company (1-5)

3 Dompet & 5 Company:
{get_selection_display()}

4 Kategori (Auto-detect):
{categories}

Perintah:
📊 /status - Dashboard semua dompet
💰 /saldo - Saldo per dompet
📋 /list - Transaksi terakhir
📈 /laporan - Laporan 7 hari
📈 /laporan30 - Laporan 30 hari
🗂️ /dompet - Daftar dompet
🗂️ /kategori - Daftar kategori
🤖 /tanya [x] - Tanya AI
📄 /exportpdf - Export PDF

Koreksi data langsung di Google Sheets."""


# ===================== PLATFORM HELPERS =====================

def strip_markdown(text: str) -> str:
    """Remove Markdown formatting for WhatsApp/WuzAPI."""
    return text.replace('*', '').replace('_', '').replace('`', '')


def for_whatsapp(text: str) -> str:
    """Format message for WhatsApp (plain text)."""
    return strip_markdown(text)


def for_telegram(text: str) -> str:
    """Format message for Telegram (Markdown supported)."""
    return text  # Telegram supports Markdown
