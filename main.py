"""
main.py - Financial Recording Bot

Features:
- SIMPLIFIED WORKFLOW: No mandatory project selection
- Multi-channel (WhatsApp + Telegram)
- Fixed 8 Categories (auto-detected by AI)
- Pemasukan & Pengeluaran
- Query AI (/tanya)
- Budget Alerts
- SMART REMINDERS: Proactive notifications
- SECURITY: Prompt injection protection, rate limiting, secure logging

WORKFLOW:
1. User sends transaction (text/photo/voice)
2. AI auto-categorizes
3. Saved to single Google Sheet
4. Smart reminders for inactive users
"""

import os
import traceback
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import helper modules
from ai_helper import extract_financial_data, query_data
from sheets_helper import (
    append_transactions, test_connection, 
    generate_report, format_report_message,
    get_all_categories, get_summary,
    format_data_for_ai, check_budget_alert,
    get_company_sheets, COMPANY_SHEETS,
    format_dashboard_message, get_dashboard_summary,
    get_wallet_balances,
    invalidate_dashboard_cache,
)
from security import (
    sanitize_input,
    detect_prompt_injection,
    rate_limit_check,
    secure_log,
    SecurityError,
    RateLimitError,
    ALLOWED_CATEGORIES,
)
from reminder import (
    update_user_activity,
    toggle_reminder,
    start_scheduler,
    get_weekly_summary,
)
from pdf_report import generate_pdf_from_input, parse_month_input, validate_period_data

# Initialize Flask app
app = Flask(__name__)

# Configuration
DEBUG = os.getenv('FLASK_DEBUG', '0') == '1'
FONNTE_TOKEN = os.getenv('FONNTE_TOKEN')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Build Telegram API URL safely (don't log this)
_TELEGRAM_API_URL = None
_telegram_session = None  # Global session for connection pooling

def get_telegram_session():
    """Get or create requests Session with connection pooling."""
    global _telegram_session
    if _telegram_session is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        _telegram_session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        # Configure connection pool
        adapter = HTTPAdapter(
            pool_connections=10,  # Keep 10 connections matching
            pool_maxsize=10,     # Allow 10 concurrent connections
            max_retries=retry_strategy
        )
        
        _telegram_session.mount("https://", adapter)
        _telegram_session.mount("http://", adapter)
        
    return _telegram_session


def get_telegram_api_url():
    """Get Telegram API URL (lazy, secure)."""
    global _TELEGRAM_API_URL
    if _TELEGRAM_API_URL is None and TELEGRAM_BOT_TOKEN:
        _TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    return _TELEGRAM_API_URL


# Pending transactions waiting for company selection
# Format: {user_id: {'transactions': [...], 'sender_name': str, 'source': str, 'timestamp': datetime}}
_pending_transactions = {}


# ===================== START MESSAGE =====================

# Build categories list for display
CATEGORIES_DISPLAY = '\n'.join(f"  • {cat}" for cat in ALLOWED_CATEGORIES)
COMPANY_DISPLAY = '\n'.join(f"  {i+1}. {c}" for i, c in enumerate(COMPANY_SHEETS))

START_MESSAGE = f"""👋 *Selamat datang di Bot Keuangan!*

Bot ini mencatat pengeluaran & pemasukan ke Google Sheets.

━━━━━━━━━━━━━━━━━━━━━
📝 *CARA PAKAI (2 LANGKAH)*
━━━━━━━━━━━━━━━━━━━━━

*Langkah 1:* Kirim transaksi
• `Beli cat 500rb untuk Purana Ubud`
• `Bayar tukang 1.5jt`
• 📷 Foto struk
• 🎤 Voice note

*Langkah 2:* Pilih company sheet
Bot akan tanya: "Simpan ke company mana?"
Balas dengan nomor 1-5.

*5 Company Sheets:*
{COMPANY_DISPLAY}

*4 Kategori (Auto-detect):*
{CATEGORIES_DISPLAY}

━━━━━━━━━━━━━━━━━━━━━
⚙️ *PERINTAH*
━━━━━━━━━━━━━━━━━━━━━
• `/status` - Dashboard semua company
• `/laporan` - Ringkasan 7 hari
• `/company` - Lihat daftar company
• `/tanya [x]` - Tanya AI
• `/reminder on/off` - Pengingat
• `/exportpdf 2026-01` - Export PDF bulanan

🔒 Bot hanya MENAMBAH data, tidak bisa hapus.
"""


HELP_MESSAGE = f"""📖 *PANDUAN BOT KEUANGAN*

*Input Transaksi:*
1. Kirim text/foto/voice
2. Pilih nomor company (1-5)

*Company Sheets:*
{COMPANY_DISPLAY}

*Kategori (Auto):*
{', '.join(ALLOWED_CATEGORIES)}

*Perintah:*
• `/status` - Ringkasan
• `/laporan` - Laporan
• `/company` - Daftar company
• `/tanya [x]` - Tanya AI
• `/exportpdf` - Export PDF

_Koreksi data langsung di Google Sheets._"""


# ===================== HELPERS =====================

def send_telegram_reply(chat_id: int, message: str, parse_mode: str = 'Markdown'):
    """Send Telegram reply securely."""
    try:
        api_url = get_telegram_api_url()
        if not api_url:
            return None
        
        # Use existing session (fast) or create new (slow first time)
        session = get_telegram_session()
        
        response = session.post(
            f"{api_url}/sendMessage",
            json={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': parse_mode
            },
            timeout=10
        )
        return response.json()
    except Exception as e:
        secure_log("ERROR", f"Telegram send failed: {type(e).__name__}")
        return None


def send_whatsapp_reply(phone_number: str, message: str):
    """Send WhatsApp reply via Fonnte."""
    try:
        response = requests.post(
            'https://api.fonnte.com/send',
            headers={'Authorization': FONNTE_TOKEN},
            data={'target': phone_number, 'message': message},
            timeout=10
        )
        return response.json()
    except Exception as e:
        secure_log("ERROR", f"Fonnte send failed: {type(e).__name__}")
        return None


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


def get_status_message() -> str:
    """Get current status message - aggregates data from all projects."""
    # Use the dashboard message which aggregates all projects
    return format_dashboard_message()


# ===================== TELEGRAM HANDLERS =====================

@app.route('/telegram', methods=['POST'])
def webhook_telegram():
    """Webhook endpoint for Telegram Bot - SECURED."""
    try:
        update = request.get_json()
        
        if not update or 'message' not in update:
            return jsonify({'ok': True}), 200
        
        message = update['message']
        message_id = message.get('message_id', 0)
        chat_id = message['chat']['id']
        user_id = str(chat_id)
        sender_name = message['from'].get('first_name', 'User')
        
        # Deduplication
        cache_key = f"{chat_id}_{message_id}"
        if hasattr(app, '_processed_messages'):
            if cache_key in app._processed_messages:
                return jsonify({'ok': True}), 200
        else:
            app._processed_messages = set()
        
        app._processed_messages.add(cache_key)
        if len(app._processed_messages) > 100:
            app._processed_messages = set(list(app._processed_messages)[-50:])
        
        # Rate limiting
        allowed, wait_time = rate_limit_check(user_id)
        if not allowed:
            send_telegram_reply(chat_id, f"⏳ Terlalu cepat! Tunggu {wait_time} detik.")
            return jsonify({'ok': True}), 200
        
        secure_log("INFO", f"Telegram message from user_id={user_id}")
        
        # Variables
        text = None
        input_type = 'text'
        media_url = None
        caption = None
        
        # === HANDLE TEXT MESSAGES ===
        if 'text' in message:
            text = message['text'].strip()
            
            # Sanitize input
            text = sanitize_input(text)
            
            # Check for pending transaction - company selection (numbers 1-5)
            if user_id in _pending_transactions and text in ['1', '2', '3', '4', '5']:
                pending = _pending_transactions.pop(user_id)
                company_idx = int(text) - 1
                company_sheet = COMPANY_SHEETS[company_idx]
                
                # Save transactions to selected company
                result = append_transactions(
                    pending['transactions'], 
                    pending['sender_name'], 
                    pending['source'],
                    company_sheet=company_sheet
                )
                
                if result['success']:
                    update_user_activity(user_id, 'telegram', pending['sender_name'])
                    invalidate_dashboard_cache()  # Reset cache so /status is up-to-date
                    reply = format_success_reply(pending['transactions'], company_sheet)
                    send_telegram_reply(chat_id, reply)
                else:
                    send_telegram_reply(chat_id, f"❌ Gagal menyimpan: {result.get('company_error', 'Error')}")
                return jsonify({'ok': True}), 200
            
            # Cancel pending if user sends new text that's not a number
            if user_id in _pending_transactions and text.lower() in ['/cancel', 'batal']:
                _pending_transactions.pop(user_id, None)
                send_telegram_reply(chat_id, "❌ Transaksi dibatalkan.")
                return jsonify({'ok': True}), 200
            
            # /start
            if text.lower() == '/start':
                send_telegram_reply(chat_id, START_MESSAGE)
                return jsonify({'ok': True}), 200
            
            # /help
            if text.lower() == '/help':
                send_telegram_reply(chat_id, HELP_MESSAGE)
                return jsonify({'ok': True}), 200
            
            # /status
            if text.lower() == '/status':
                reply = get_status_message()
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /saldo
            if text.lower() == '/saldo':
                reply = get_wallet_balances()
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /kategori
            if text.lower() == '/kategori':
                reply = f"📁 *Kategori Tersedia:*\n\n{CATEGORIES_DISPLAY}"
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /company - List available company sheets
            if text.lower() in ['/company', '/project']:
                company_list = '\n'.join(f"  {i+1}. {c}" for i, c in enumerate(COMPANY_SHEETS))
                reply = f"🏢 *Company Sheets:*\n\n{company_list}\n\n_Kirim transaksi, lalu pilih nomor company._"
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /list - Show recent transactions
            if text.lower() == '/list':
                from sheets_helper import get_all_data
                data = get_all_data(days=7)  # Last 7 days
                if data:
                    lines = ["📋 *Transaksi Terakhir (7 hari):*\n"]
                    # Group by company_sheet
                    by_company = {}
                    for d in data[-20:]:  # Last 20 transactions
                        company = d.get('company_sheet', 'Unknown')
                        if company not in by_company:
                            by_company[company] = []
                        by_company[company].append(d)
                    
                    for company, items in by_company.items():
                        lines.append(f"\n*{company}:*")
                        for item in items[-5:]:  # 5 per company
                            emoji = "💸" if item['tipe'] == 'Pengeluaran' else "💰"
                            nama = item.get('nama_projek', '')
                            nama_str = f" ({nama})" if nama else ""
                            lines.append(f"  {emoji} {item['keterangan'][:25]}{nama_str} - Rp {item['jumlah']:,}".replace(',', '.'))
                    
                    reply = '\n'.join(lines)
                else:
                    reply = "📋 Tidak ada transaksi dalam 7 hari terakhir."
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            
            # /laporan or /laporan30
            if text.lower().startswith('/laporan'):
                days = 30 if '30' in text else 7
                api_url = get_telegram_api_url()
                if api_url:
                    requests.post(f"{api_url}/sendChatAction", 
                                 json={'chat_id': chat_id, 'action': 'typing'},
                                 timeout=5)
                
                report = generate_report(days=days)
                reply = format_report_message(report)
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /tanya [question]
            if text.lower().startswith('/tanya'):
                question = text[6:].strip()
                if not question:
                    send_telegram_reply(chat_id, 
                        "❓ Format: `/tanya [pertanyaan]`\n\n"
                        "Contoh:\n"
                        "• `/tanya total pengeluaran bulan ini`\n"
                        "• `/tanya kategori terbesar`")
                    return jsonify({'ok': True}), 200
                
                # Check for injection in question
                is_injection, _ = detect_prompt_injection(question)
                if is_injection:
                    send_telegram_reply(chat_id, "❌ Pertanyaan tidak valid.")
                    return jsonify({'ok': True}), 200
                
                api_url = get_telegram_api_url()
                if api_url:
                    requests.post(f"{api_url}/sendChatAction", 
                                 json={'chat_id': chat_id, 'action': 'typing'},
                                 timeout=5)
                
                # Get data context
                data_context = format_data_for_ai(days=30)
                
                # Query AI
                answer = query_data(question, data_context)
                
                reply = f"💡 *Jawaban:*\n\n{answer}"
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /exportpdf - Export monthly PDF report
            if text.lower().startswith('/exportpdf'):
                month_arg = text[10:].strip()
                
                if not month_arg:
                    # Use current month as default
                    now = datetime.now()
                    month_arg = f"{now.year}-{now.month:02d}"
                
                # Show typing indicator
                api_url = get_telegram_api_url()
                if api_url:
                    requests.post(f"{api_url}/sendChatAction", 
                                 json={'chat_id': chat_id, 'action': 'upload_document'},
                                 timeout=5)
                
                try:
                    # Step 1: Parse and validate period (year/month range)
                    year, month = parse_month_input(month_arg)
                    
                    # Step 2: Check if data exists for this period
                    has_data, tx_count, period_name = validate_period_data(year, month)
                    
                    if not has_data:
                        send_telegram_reply(chat_id, 
                            f"❌ *Tidak ada transaksi untuk {period_name}*\n\n"
                            f"PDF tidak dibuat karena tidak ada data.\n\n"
                            f"💡 Tips:\n"
                            f"• Cek periode yang benar\n"
                            f"• Gunakan `/status` untuk lihat data tersedia")
                        return jsonify({'ok': True}), 200
                    
                    # Step 3: Notify user about data found
                    send_telegram_reply(chat_id, 
                        f"✅ Ditemukan *{tx_count} transaksi* untuk {period_name}\n"
                        f"📊 Generating PDF...")
                    
                    # Step 4: Generate PDF
                    pdf_path = generate_pdf_from_input(month_arg)
                    
                    # Send PDF file via Telegram
                    with open(pdf_path, 'rb') as pdf_file:
                        files = {'document': pdf_file}
                        data = {
                            'chat_id': chat_id,
                            'caption': f"📊 Laporan Keuangan Bulanan\n📅 Periode: {period_name}\n📝 Total: {tx_count} transaksi"
                        }
                        response = requests.post(
                            f"{api_url}/sendDocument",
                            data=data,
                            files=files,
                            timeout=60
                        )
                    
                    if response.status_code == 200:
                        secure_log("INFO", f"PDF sent to user {user_id}")
                    else:
                        send_telegram_reply(chat_id, "❌ Gagal mengirim PDF. Coba lagi.")
                        
                except ValueError as e:
                    send_telegram_reply(chat_id, f"❌ {str(e)}\n\nFormat: `/exportpdf 2026-01` atau `/exportpdf januari 2026`")
                except ImportError:
                    send_telegram_reply(chat_id, "❌ PDF generator belum terinstall. Hubungi admin.")
                except Exception as e:
                    secure_log("ERROR", f"PDF export failed: {type(e).__name__}")
                    send_telegram_reply(chat_id, f"❌ Gagal generate PDF: {str(e)[:100]}")
                
                return jsonify({'ok': True}), 200
            
            # /reminder - Toggle reminder on/off
            if text.lower().startswith('/reminder'):
                arg = text[9:].strip().lower()
                if arg in ['off', 'mati', '0']:
                    toggle_reminder(user_id, False)
                    send_telegram_reply(chat_id, "🔕 *Reminder dimatikan.*\n\nKetik `/reminder on` untuk nyalakan lagi.")
                elif arg in ['on', 'nyala', '1']:
                    toggle_reminder(user_id, True)
                    send_telegram_reply(chat_id, "🔔 *Reminder dinyalakan!*\n\nAnda akan dapat notifikasi jika tidak input transaksi 3+ hari.")
                else:
                    send_telegram_reply(chat_id, 
                        "🔔 *Pengaturan Reminder*\n\n"
                        "• `/reminder on` - Nyalakan reminder\n"
                        "• `/reminder off` - Matikan reminder\n\n"
                        "Bot akan kirim pengingat jika Anda tidak input transaksi selama 3+ hari.")
                return jsonify({'ok': True}), 200
            
            # Check for injection in regular text
            is_injection, _ = detect_prompt_injection(text)
            if is_injection:
                send_telegram_reply(chat_id, "❌ Input tidak valid. Kirim transaksi dengan format normal.")
                return jsonify({'ok': True}), 200
        
        # === HANDLE PHOTO ===
        elif 'photo' in message:
            api_url = get_telegram_api_url()
            if api_url:
                requests.post(f"{api_url}/sendChatAction", 
                             json={'chat_id': chat_id, 'action': 'typing'},
                             timeout=5)
            
            photo = message['photo'][-1]
            file_id = photo['file_id']
            caption = message.get('caption', '')
            
            # Sanitize caption
            if caption:
                caption = sanitize_input(caption)
                is_injection, _ = detect_prompt_injection(caption)
                if is_injection:
                    caption = ''  # Discard suspicious caption
            
            file_info = requests.get(f"{api_url}/getFile?file_id={file_id}", timeout=10).json()
            if file_info.get('ok'):
                file_path = file_info['result']['file_path']
                media_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                input_type = 'image'
                text = caption or ''
        
        # === HANDLE VOICE ===
        elif 'voice' in message or 'audio' in message:
            api_url = get_telegram_api_url()
            if api_url:
                requests.post(f"{api_url}/sendChatAction", 
                             json={'chat_id': chat_id, 'action': 'typing'},
                             timeout=5)
            
            voice = message.get('voice') or message.get('audio')
            file_id = voice['file_id']
            
            file_info = requests.get(f"{api_url}/getFile?file_id={file_id}", timeout=10).json()
            if file_info.get('ok'):
                file_path = file_info['result']['file_path']
                media_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                input_type = 'audio'
                text = ''
        
        # === PROCESS TRANSACTION ===
        if input_type == 'text' and not text:
            return jsonify({'ok': True}), 200
        
        # Extract data with AI
        try:
            source = {"text": "Text", "image": "Image", "audio": "Voice"}[input_type]
            
            transactions = extract_financial_data(
                input_data=text or '',
                input_type=input_type,
                sender_name=sender_name,
                media_url=media_url,
                caption=caption
            )
        except SecurityError as e:
            send_telegram_reply(chat_id, f"❌ {str(e)}")
            return jsonify({'ok': True}), 200
        except Exception as e:
            secure_log("ERROR", f"Extract failed: {type(e).__name__}")
            send_telegram_reply(chat_id, "❌ Gagal memproses. Coba lagi.")
            return jsonify({'ok': True}), 200
        
        if not transactions:
            send_telegram_reply(chat_id, 
                "❓ Tidak ada transaksi terdeteksi.\n\n"
                "Contoh format:\n"
                "• `Beli semen 5 sak 300rb`\n"
                "• `Bayar tukang 500rb`")
            return jsonify({'ok': True}), 200
        
        # Store pending transaction and ask for company selection
        _pending_transactions[user_id] = {
            'transactions': transactions,
            'sender_name': sender_name,
            'source': source,
            'timestamp': datetime.now()
        }
        
        # Format preview
        preview_lines = []
        total = 0
        for t in transactions:
            amt = t.get('jumlah', 0)
            total += amt
            preview_lines.append(f"• {t.get('keterangan', '-')}: Rp {amt:,}".replace(',', '.'))
        
        company_options = '\n'.join(f"  {i+1}. {c}" for i, c in enumerate(COMPANY_SHEETS))
        
        reply = (
            "📝 *Transaksi Terdeteksi:*\n" +
            '\n'.join(preview_lines) +
            f"\n\n*Total: Rp {total:,}*\n\n".replace(',', '.') +
            "🏢 *Simpan ke company mana?*\n\n" +
            company_options +
            "\n\n_Balas dengan nomor 1-5, atau ketik /cancel untuk batal._"
        )
        
        send_telegram_reply(chat_id, reply)
        return jsonify({'ok': True}), 200
    
    except Exception as e:
        secure_log("ERROR", f"Telegram webhook error: {type(e).__name__}")
        return jsonify({'ok': True}), 200


# ===================== WHATSAPP HANDLERS =====================

@app.route('/webhook', methods=['GET', 'POST'])
def webhook_fonnte():
    """Webhook endpoint for Fonnte WhatsApp - SECURED."""
    # Handle GET request (Fonnte verification)
    if request.method == 'GET':
        return jsonify({'status': 'ok', 'message': 'Webhook ready'}), 200
    
    # Handle POST request (actual messages)
    try:
        if request.is_json:
            payload = request.get_json()
        else:
            payload = request.form.to_dict()
        
        if not payload:
            return jsonify({'success': False}), 400
        
        sender_number = payload.get('sender', '')
        sender_name = payload.get('name', 'User')
        message = payload.get('message', '').strip()
        media_url = payload.get('url', '')
        msg_type = payload.get('type', 'text').lower()
        
        # Conditional debug logging (only if FLASK_DEBUG=1)
        if DEBUG:
            import json as _json
            try:
                with open('fonnte_debug.log', 'a', encoding='utf-8') as f:
                    f.write(f"\n=== {datetime.now()} ===\n")
                    f.write(_json.dumps(payload, ensure_ascii=False, indent=2))
                    f.write(f"\n--- Extracted: type={msg_type}, url={media_url}, msg_len={len(message)} ---\n")
            except Exception:
                pass  # Silent fail for debug logging
        
        if not sender_number:
            return jsonify({'success': True}), 200
        
        user_id = sender_number
        
        # Rate limiting
        allowed, wait_time = rate_limit_check(user_id)
        if not allowed:
            send_whatsapp_reply(sender_number, f"⏳ Tunggu {wait_time} detik.")
            return jsonify({'success': True}), 200
        
        # Sanitize message
        message = sanitize_input(message)
        sender_name = sanitize_input(sender_name)[:50]
        
        secure_log("INFO", f"WhatsApp message from user")
        
        # === COMPANY SELECTION (numbers 1-5) ===
        if user_id in _pending_transactions and message in ['1', '2', '3', '4', '5']:
            pending = _pending_transactions.pop(user_id)
            company_idx = int(message) - 1
            company_sheet = COMPANY_SHEETS[company_idx]
            
            result = append_transactions(
                pending['transactions'],
                pending['sender_name'],
                pending['source'],
                company_sheet=company_sheet
            )
            
            if result['success']:
                update_user_activity(user_id, 'whatsapp', pending['sender_name'])
                invalidate_dashboard_cache()  # Reset cache
                reply = format_success_reply(pending['transactions'], company_sheet).replace('*', '')
                send_whatsapp_reply(sender_number, reply)
            else:
                send_whatsapp_reply(sender_number, f"❌ Gagal: {result.get('company_error', 'Error')}")
            return jsonify({'success': True}), 200
        
        # Cancel pending
        if user_id in _pending_transactions and message.lower() in ['batal', 'cancel']:
            _pending_transactions.pop(user_id, None)
            send_whatsapp_reply(sender_number, "❌ Transaksi dibatalkan.")
            return jsonify({'success': True}), 200
        
        # === COMMANDS (support both with and without slash) ===
        
        # start
        if message.lower() in ['start', 'mulai', 'hi', 'halo', '/start']:
            send_whatsapp_reply(sender_number, START_MESSAGE.replace('*', ''))
            return jsonify({'success': True}), 200
        
        # help
        if message.lower() in ['help', 'bantuan', '/help']:
            send_whatsapp_reply(sender_number, HELP_MESSAGE.replace('*', ''))
            return jsonify({'success': True}), 200
        
        # status
        if message.lower() in ['status', '/status']:
            reply = get_status_message().replace('*', '')
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # saldo
        if message.lower() in ['saldo', '/saldo']:
            reply = get_wallet_balances().replace('*', '')
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # company
        if message.lower() in ['company', 'project', '/company', '/project']:
            company_list = '\n'.join(f"  {i+1}. {c}" for i, c in enumerate(COMPANY_SHEETS))
            reply = f"🏢 Company Sheets:\n\n{company_list}\n\nKirim transaksi, lalu pilih nomor."
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # laporan
        if message.lower().startswith('laporan') or message.lower().startswith('/laporan'):
            days = 30 if '30' in message else 7
            report = generate_report(days=days)
            reply = format_report_message(report).replace('*', '')
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # tanya
        if message.lower().startswith('tanya ') or message.lower().startswith('/tanya '):
            # Remove prefix
            if message.lower().startswith('/tanya '):
                question = message[7:].strip()
            else:
                question = message[6:].strip()
            
            # Check injection
            is_injection, _ = detect_prompt_injection(question)
            if is_injection:
                send_whatsapp_reply(sender_number, "❌ Pertanyaan tidak valid.")
                return jsonify({'success': True}), 200
            
            data_context = format_data_for_ai(days=30)
            answer = query_data(question, data_context)
            reply = f"💡 {answer}"
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # exportpdf
        if message.lower().startswith('exportpdf') or message.lower().startswith('/exportpdf'):
            # Extract month argument
            if message.lower().startswith('/exportpdf'):
                month_arg = message[10:].strip()
            else:
                month_arg = message[9:].strip()
            
            if not month_arg:
                now = datetime.now()
                month_arg = f"{now.year}-{now.month:02d}"
            
            try:
                # Step 1: Parse and validate period (year/month range)
                year, month = parse_month_input(month_arg)
                
                # Step 2: Check if data exists for this period
                has_data, tx_count, period_name = validate_period_data(year, month)
                
                if not has_data:
                    send_whatsapp_reply(sender_number, 
                        f"❌ Tidak ada transaksi untuk {period_name}\n\n"
                        f"PDF tidak dibuat karena tidak ada data.\n\n"
                        f"💡 Tips:\n"
                        f"• Cek periode yang benar\n"
                        f"• Gunakan 'status' untuk lihat data tersedia")
                    return jsonify({'success': True}), 200
                
                # Step 3: Notify user about data found and generating
                send_whatsapp_reply(sender_number, 
                    f"✅ Ditemukan {tx_count} transaksi untuk {period_name}\n"
                    f"📊 Generating PDF...")
                
                # Step 4: Generate PDF
                pdf_path = generate_pdf_from_input(month_arg)
                
                # Note: Fonnte has limited file sending capability
                # We'll notify user that PDF is generated and provide info
                file_size = os.path.getsize(pdf_path) / 1024  # KB
                
                reply = (
                    f"📊 Laporan Keuangan Bulanan\n"
                    f"📅 Periode: {period_name}\n"
                    f"📝 Total: {tx_count} transaksi\n"
                    f"📦 Ukuran: {file_size:.1f} KB\n\n"
                    f"✅ PDF berhasil dibuat!\n\n"
                    f"⚠️ Untuk download PDF, gunakan Telegram bot atau hubungi admin."
                )
                send_whatsapp_reply(sender_number, reply)
                
            except ValueError as e:
                send_whatsapp_reply(sender_number, f"❌ {str(e)}\n\nFormat: exportpdf 2026-01 atau exportpdf januari 2026")
            except ImportError:
                send_whatsapp_reply(sender_number, "❌ PDF generator belum terinstall.")
            except Exception as e:
                secure_log("ERROR", f"PDF export failed (WA): {type(e).__name__}")
                send_whatsapp_reply(sender_number, f"❌ Gagal generate PDF.")
            
            return jsonify({'success': True}), 200
        
        # kategori
        if message.lower() in ['kategori', '/kategori']:
            reply = "📁 Kategori:\n" + '\n'.join(f"• {cat}" for cat in ALLOWED_CATEGORIES)
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # Check injection for regular messages
        is_injection, _ = detect_prompt_injection(message)
        if is_injection:
            send_whatsapp_reply(sender_number, "❌ Input tidak valid.")
            return jsonify({'success': True}), 200
        
        # === TRANSACTION ===
        
        # Determine input type
        if msg_type in ['image'] or (media_url and 'image' in media_url.lower()):
            input_type = 'image'
        elif msg_type in ['audio', 'ptt', 'voice']:
            input_type = 'audio'
        else:
            input_type = 'text'
        
        # Process
        try:
            source = {"text": "Text", "image": "Image", "audio": "Voice"}[input_type]
            
            transactions = extract_financial_data(
                input_data=message,
                input_type=input_type,
                sender_name=sender_name,
                media_url=media_url if input_type != 'text' else None,
                caption=message if input_type == 'image' else None
            )
        except SecurityError as e:
            send_whatsapp_reply(sender_number, f"❌ {str(e)}")
            return jsonify({'success': True}), 200
        except Exception as e:
            secure_log("ERROR", f"Extract failed: {type(e).__name__}")
            send_whatsapp_reply(sender_number, "❌ Gagal memproses.")
            return jsonify({'success': True}), 200
        
        if not transactions:
            send_whatsapp_reply(sender_number, "❓ Transaksi tidak terdeteksi. Contoh: Beli semen 300rb")
            return jsonify({'success': True}), 200
        
        # Store pending and ask for company selection
        _pending_transactions[user_id] = {
            'transactions': transactions,
            'sender_name': sender_name,
            'source': source,
            'timestamp': datetime.now()
        }
        
        # Format preview
        preview_lines = []
        total = 0
        for t in transactions:
            amt = t.get('jumlah', 0)
            total += amt
            preview_lines.append(f"• {t.get('keterangan', '-')}: Rp {amt:,}".replace(',', '.'))
        
        company_options = '\n'.join(f"  {i+1}. {c}" for i, c in enumerate(COMPANY_SHEETS))
        
        reply = (
            "📝 Transaksi Terdeteksi:\n" +
            '\n'.join(preview_lines) +
            f"\n\nTotal: Rp {total:,}\n\n".replace(',', '.') +
            "🏢 Simpan ke company mana?\n\n" +
            company_options +
            "\n\nBalas dengan nomor 1-5, atau ketik batal"
        )
        
        send_whatsapp_reply(sender_number, reply)
        return jsonify({'success': True}), 200
    
    except Exception as e:
        secure_log("ERROR", f"Fonnte webhook error: {type(e).__name__}")
        return jsonify({'success': False}), 500


# ===================== OTHER ENDPOINTS =====================

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'features': ['company-sheets', '4-categories', 'company-selection']
    }), 200


@app.route('/test-sheets', methods=['GET'])
def test_sheets():
    try:
        return jsonify({'success': test_connection()}), 200
    except Exception:
        return jsonify({'success': False}), 500


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'name': 'Bot Keuangan',
        'status': 'running'
    }), 200


# ===================== MAIN =====================

if __name__ == '__main__':
    print("=" * 50)
    print("Bot Keuangan")
    print("=" * 50)
    
    print("\nFeatures:")
    print("  [OK] 5 Company Sheets")
    print("  [OK] 4 Categories")
    print("  [OK] Company Selection Workflow")
    print("  [OK] Nama Projek Column")
    
    print(f"\nCompany Sheets: {', '.join(COMPANY_SHEETS)}")
    print(f"Categories: {', '.join(ALLOWED_CATEGORIES)}")
    
    print("\nTesting connections...")
    try:
        if test_connection():
            print("[OK] Google Sheets connected")
    except Exception as e:
        print("[ERR] Sheets error")
    
    print(f"\nFonnte: {'[OK]' if FONNTE_TOKEN else '[X]'}")
    print(f"Telegram: {'[OK]' if TELEGRAM_BOT_TOKEN else '[X]'}")
    
    print("\nCommands:")
    print("  /status    - Dashboard")
    print("  /laporan   - Weekly report")
    print("  /company   - List companies")
    print("  /tanya     - Ask AI")
    
    # Start smart reminder scheduler
    print("\nStarting reminder scheduler...")
    start_scheduler()
    print("[OK] Reminder scheduler active")
    
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)

