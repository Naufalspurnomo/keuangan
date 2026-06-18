"""
errors.py - Standardized Error Messages

User-facing errors in Bahasa Indonesia.
Developer errors for logging.
"""


class UserErrors:
    """User-facing error messages (friendly, Bahasa Indonesia)."""
    
    # Rate limiting
    RATE_LIMITED = "⏳ Terlalu cepat! Tunggu {seconds} detik."
    
    # Transaction errors
    NO_TRANSACTION = "❓ Transaksi tidak terdeteksi.\n\nContoh: Beli semen 300rb"
    INVALID_INPUT = "❌ Input tidak valid."
    EXTRACTION_FAILED = "❌ Gagal memproses pesan."
    SAVE_FAILED = "❌ Gagal menyimpan transaksi."
    
    # Selection errors
    SELECTION_INVALID = "Balas dengan angka 1-5 untuk memilih."
    SELECTION_SINGLE_ONLY = "Pilih satu saja. Ketik angka 1-5."
    SELECTION_OUT_OF_RANGE = "Pilihan tidak tersedia. Ketik angka 1-5."
    SELECTION_UNAVAILABLE = (
        "❌ Pilihan itu tidak tersedia di prompt ini.\n"
        "Balas angka yang muncul di daftar pilihan terbaru."
    )
    
    # Wallet detection errors
    WALLET_NOT_DETECTED = (
        "❓ Dompet tidak terdeteksi.\n\n"
        "Mohon pilih dompet yang sesuai (1-5):"
    )
    AMBIGUOUS_WALLET = (
        "⚠️ Keyword ambigu.\n\n"
        "Keyword '{keyword}' bisa merujuk ke beberapa dompet/company.\n"
        "Pilih yang benar (1-5):"
    )
    
    # Revision errors
    REVISION_NO_QUOTE = (
        "⚠️ *Gagal Revisi*\n\n"
        "Untuk merevisi, Anda harus **me-reply** (balas) pesan konfirmasi bot.\n\n"
        "1. Reply pesan '✅ Transaksi Tercatat!'\n"
        "2. Ketik `/revisi [jumlah baru]`"
    )
    REVISION_FORMAT_WRONG = (
        "⚠️ Format Salah.\n\n"
        "Untuk merevisi, balas pesan ini dengan format:\n"
        "`/revisi [jumlah]`\n\n"
        "Contoh: `/revisi 150000`"
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
    
    # Session errors
    SESSION_EXPIRED = "⌛ Sesi sebelumnya sudah kedaluwarsa (lebih dari 15 menit).\nKirim transaksi lagi ya."
    NO_ACTIVE_QUESTION = (
        "⚠️ Tidak ada pertanyaan aktif untuk balasan itu.\n"
        "Kemungkinan prompt sudah lewat 15 menit atau transaksi sudah selesai.\n"
        "Kirim ulang transaksi jika masih mau dicatat."
    )
    GROUP_REPLY_REQUIRED = (
        "⚠️ Di grup, balasan singkat seperti angka/Ya wajib reply ke prompt bot yang mau dijawab.\n"
        "Ini mencegah jawaban masuk ke sesi transaksi orang lain."
    )
    GROUP_REPLY_PROMPT_NOT_ACTIVE = (
        "⚠️ Prompt yang di-reply tidak punya sesi aktif.\n"
        "Kemungkinan sudah lewat 15 menit, bot sempat restart, atau yang di-reply bukan prompt bot terbaru.\n"
        "Kirim ulang transaksi jika masih mau dicatat."
    )
    STALE_PENDING_STATE = (
        "⚠️ Sesi lama tidak lengkap lagi, jadi balasan ini tidak diproses.\n"
        "Kemungkinan bot restart atau prompt sebelumnya sudah kedaluwarsa.\n"
        "Kirim ulang transaksi supaya aman."
    )
    SESSION_ACCESS_DENIED = (
        "⚠️ Sesi ini milik user lain.\n"
        "Kalau membantu menjawab, reply langsung ke prompt bot milik sesi itu."
    )
    CANCELLED = "❌ Transaksi dibatalkan."
    ALL_REMOVED = "❌ Semua transaksi dihapus. Transaksi dibatalkan."
    
    # System errors
    SHEET_ERROR = "⚠️ Sistem sedang sibuk, coba lagi dalam 1 menit."
    SHEET_READ_FAILED = "❌ Gagal membaca data spreadsheet. Coba lagi 1 menit."
    SHEET_WRITE_FAILED = (
        "❌ Gagal menyimpan transaksi ke spreadsheet.\n"
        "Data belum dicatat. Coba kirim ulang transaksi; kalau masih gagal, hubungi admin."
    )
    QUERY_FAILED = "❌ Gagal menganalisis data keuangan. Coba lagi 1 menit."
    SYSTEM_PROCESSING_FAILED = (
        "❌ Pesan belum bisa diproses karena sistem gagal membaca konteks transaksi.\n"
        "Coba kirim ulang dengan format lebih jelas."
    )
    UNKNOWN_ERROR = "❌ Terjadi kesalahan sistem. Coba lagi 1 menit."

    # Hutang errors
    HUTANG_FORMAT = "Format: /lunas NO_HUTANG (contoh: /lunas 3)."
    HUTANG_NOT_FOUND = "❌ Hutang #{no} tidak ditemukan atau sudah lunas."
    HUTANG_SETTLE_FAILED = "❌ Pelunasan hutang #{no} gagal.\n⚠️ {reason}"

    # Image/OCR errors
    IMAGE_NOT_READABLE = (
        "❓ Teks atau nominal pada gambar tidak terbaca.\n"
        "Kirim ulang gambar yang lebih jelas atau tambahkan caption transaksi."
    )
    IMAGE_NOT_RECEIPT = (
        "❗ Gambar tidak terdeteksi sebagai struk/transaksi.\n"
        "Kirim struk yang lebih jelas atau tambahkan keterangan transaksi."
    )
    
    # PDF errors
    PDF_NO_DATA = (
        "❌ Tanggal ini tidak ada di database untuk periode {period}.\n\n"
        "PDF tidak dibuat karena tidak ada data.\n\n"
        "💡 Tips:\n"
        "• Cek periode yang benar\n"
        "• Gunakan 'status' untuk lihat data tersedia"
    )
    PDF_FORMAT_ERROR = "❌ Format salah.\n\nFormat: exportpdf 2026-01 atau exportpdf 2025-09-22 2025-10-22"
    PDF_NOT_INSTALLED = "❌ PDF generator belum terinstall."
    PDF_FAILED = "❌ Gagal generate PDF."


class InternalErrors:
    """Internal error types for logging/tracking."""
    SHEET_CONNECTION = "SHEETS_ERROR"
    AI_EXTRACTION = "AI_ERROR"
    VALIDATION = "VALIDATION_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    WEBHOOK = "WEBHOOK_ERROR"
    TELEGRAM = "TELEGRAM_ERROR"
    WUZAPI = "WUZAPI_ERROR"


# For testing
if __name__ == '__main__':
    print("Error Messages Test")
    print(f"RATE_LIMITED: {UserErrors.RATE_LIMITED.format(seconds=30)}")
    print(f"NO_TRANSACTION: {UserErrors.NO_TRANSACTION}")
