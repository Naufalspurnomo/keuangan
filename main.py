"""
main.py - Financial Recording Bot v2.2 (Simplified & Secured)

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
    get_available_projects,
    # Status/Summary functions (Dashboard is now managed by Apps Script)
    format_dashboard_message, get_dashboard_summary
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

# Initialize Flask app
app = Flask(__name__)

# Configuration
DEBUG = os.getenv('FLASK_DEBUG', '0') == '1'
FONNTE_TOKEN = os.getenv('FONNTE_TOKEN')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Build Telegram API URL safely (don't log this)
_TELEGRAM_API_URL = None


def get_telegram_api_url():
    """Get Telegram API URL (lazy, secure)."""
    global _TELEGRAM_API_URL
    if _TELEGRAM_API_URL is None and TELEGRAM_BOT_TOKEN:
        _TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    return _TELEGRAM_API_URL


# ===================== START MESSAGE =====================

# Build categories list for display
CATEGORIES_DISPLAY = '\n'.join(f"  • {cat}" for cat in ALLOWED_CATEGORIES)

START_MESSAGE = f"""👋 *Selamat datang di Bot Keuangan v2.3!*

Bot ini mencatat pengeluaran & pemasukan secara otomatis dengan AI.

━━━━━━━━━━━━━━━━━━━━━
📝 *CARA PAKAI (SUPER MUDAH)*
━━━━━━━━━━━━━━━━━━━━━

*Langsung kirim transaksi:*
• `Beli semen 300rb untuk proyek A`
• `Bayar tukang 500rb`
• `Terima DP 5jt`

*Format Bebas:*
• 📷 Foto struk/nota
• 🎤 Voice note (Bahasa Indonesia)

AI akan otomatis:
✓ Deteksi kategori ({', '.join(ALLOWED_CATEGORIES)})
✓ Deteksi tipe (Masuk/Keluar)
✓ Pilih project yang tepat
✓ Simpan ke Google Sheets

━━━━━━━━━━━━━━━━━━━━━
⚙️ *DAFTAR PERINTAH LENGKAP*
━━━━━━━━━━━━━━━━━━━━━

📊 *Laporan & Status*
• `/status` - Dashboard global semua project
• `/laporan` - Ringkasan 7 hari terakhir
• `/laporan 30` - Ringkasan 30 hari terakhir
• `/project` - Lihat daftar project tersedia

🤖 *Tanya AI*
• `/tanya [pertanyaan]` - Analisis keuangan natural
  Contoh: `/tanya pengeluaran terbesar bulan ini apa?`

🔔 *Pengingat (Smart Reminder)*
• `/reminder on` - Nyalakan pengingat otomatis
• `/reminder off` - Matikan pengingat

📂 *Info Lain*
• `/kategori` - Lihat daftar kategori
• `/start` - Tampilkan pesan ini lagi
• `/help` - Bantuan singkat

🔒 *Keamanan*
Bot ini hanya bisa MENAMBAH data, tidak bisa menghapus.
Untuk koreksi data, edit langsung di Google Sheets.

_Tips: Sebutkan nama project agar AI tahu menyimpan dimana!_
"""


HELP_MESSAGE = f"""📖 *PANDUAN BOT KEUANGAN*

*Input Transaksi:*
Langsung kirim salah satu:
• Text: `Beli cat 200rb untuk proyek A`
• Foto struk
• Voice note

*Perintah:*
• `/status` - Ringkasan keuangan
• `/laporan` - Laporan mingguan
• `/project` - Lihat project tersedia
• `/tanya [x]` - Tanya AI tentang data
• `/reminder` - On/off reminder

*Kategori (Auto-detect):*
{', '.join(ALLOWED_CATEGORIES)}

_Note: Bot hanya bisa menambah data ke project yang sudah ada._"""


# ===================== HELPERS =====================

def send_telegram_reply(chat_id: int, message: str, parse_mode: str = 'Markdown'):
    """Send Telegram reply securely."""
    try:
        api_url = get_telegram_api_url()
        if not api_url:
            return None
        
        response = requests.post(
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


def format_success_reply(transactions: list) -> str:
    """Format success reply message with project info."""
    lines = ["✅ *Transaksi Tercatat!*\n"]
    
    total = 0
    projects_used = set()
    
    for t in transactions:
        amount = t.get('jumlah', 0)
        total += amount
        tipe_icon = "💰" if t.get('tipe') == 'Pemasukan' else "💸"
        lines.append(f"{tipe_icon} {t.get('keterangan', '-')}: Rp {amount:,}".replace(',', '.'))
        lines.append(f"   📁 {t.get('kategori', 'Bahan')}")
        
        # Track projects used
        if t.get('project'):
            projects_used.add(t['project'])
    
    lines.append(f"\n*Total: Rp {total:,}*".replace(',', '.'))
    
    # Show project info
    if projects_used:
        projects_str = ', '.join(projects_used)
        lines.append(f"📋 *Project:* {projects_str}")
    
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
            
            # /kategori
            if text.lower() == '/kategori':
                reply = f"📁 *Kategori Tersedia:*\n\n{CATEGORIES_DISPLAY}"
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /project - List available projects
            if text.lower() == '/project':
                projects = get_available_projects()
                if projects:
                    projects_list = '\n'.join(f"  • {p}" for p in projects)
                    reply = f"📋 *Project Tersedia:*\n\n{projects_list}\n\n_Sebutkan nama project saat input transaksi._"
                else:
                    reply = "📋 *Belum ada project.*\n\nHubungi admin untuk membuat project baru di Google Sheets."
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /list - Show recent transactions
            if text.lower() == '/list':
                from sheets_helper import get_all_data
                data = get_all_data(days=7)  # Last 7 days
                if data:
                    lines = ["📋 *Transaksi Terakhir (7 hari):*\n"]
                    # Group by project
                    by_project = {}
                    for d in data[-20:]:  # Last 20 transactions
                        proj = d.get('project', 'Unknown')
                        if proj not in by_project:
                            by_project[proj] = []
                        by_project[proj].append(d)
                    
                    for proj, items in by_project.items():
                        lines.append(f"\n*{proj}:*")
                        for item in items[-5:]:  # 5 per project
                            emoji = "💸" if item['tipe'] == 'Pengeluaran' else "💰"
                            lines.append(f"  {emoji} {item['keterangan'][:30]} - Rp {item['jumlah']:,}".replace(',', '.'))
                    
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
        
        # Get available projects from spreadsheet
        available_projects = get_available_projects()
        
        # Extract data with AI (passes available_projects for smart selection)
        try:
            source = {"text": "Text", "image": "Image", "audio": "Voice"}[input_type]
            
            transactions = extract_financial_data(
                input_data=text or '',
                input_type=input_type,
                sender_name=sender_name,
                media_url=media_url,
                caption=caption,
                available_projects=available_projects
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
        
        # Save to Sheets (transactions may include 'project' field from AI)
        result = append_transactions(transactions, sender_name, source)
        
        if result['success']:
            # Track user activity for smart reminders
            update_user_activity(user_id, 'telegram', sender_name)
            
            reply = format_success_reply(transactions)
            send_telegram_reply(chat_id, reply)
        elif result.get('project_error'):
            # Project not found error
            send_telegram_reply(chat_id, f"❌ {result['project_error']}")
        else:
            send_telegram_reply(chat_id, "❌ Gagal menyimpan. Coba lagi.")
        
        return jsonify({'ok': True}), 200
    
    except Exception as e:
        secure_log("ERROR", f"Telegram webhook error: {type(e).__name__}")
        return jsonify({'ok': True}), 200


# ===================== WHATSAPP HANDLERS =====================

@app.route('/webhook', methods=['POST'])
def webhook_fonnte():
    """Webhook endpoint for Fonnte WhatsApp - SECURED."""
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
        
        # === COMMANDS ===
        
        # start
        if message.lower() in ['start', 'mulai', 'hi', 'halo']:
            send_whatsapp_reply(sender_number, START_MESSAGE.replace('*', ''))
            return jsonify({'success': True}), 200
        
        # status
        if message.lower() == 'status':
            reply = get_status_message().replace('*', '')
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # laporan
        if message.lower().startswith('laporan'):
            days = 30 if '30' in message else 7
            report = generate_report(days=days)
            reply = format_report_message(report).replace('*', '')
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # tanya
        if message.lower().startswith('tanya '):
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
        
        # kategori
        if message.lower() == 'kategori':
            reply = "📁 Kategori:\n" + '\n'.join(f"• {cat}" for cat in ALLOWED_CATEGORIES)
            send_whatsapp_reply(sender_number, reply)
            return jsonify({'success': True}), 200
        
        # Check injection for regular messages
        is_injection, _ = detect_prompt_injection(message)
        if is_injection:
            send_whatsapp_reply(sender_number, "❌ Input tidak valid.")
            return jsonify({'success': True}), 200
        
        # === TRANSACTION ===
        
        # Get available projects from spreadsheet
        available_projects = get_available_projects()
        
        # Determine input type
        if msg_type in ['image'] or (media_url and 'image' in media_url.lower()):
            input_type = 'image'
        elif msg_type in ['audio', 'ptt', 'voice']:
            input_type = 'audio'
        else:
            input_type = 'text'
        
        # Process (with available_projects for AI selection)
        try:
            source = {"text": "Text", "image": "Image", "audio": "Voice"}[input_type]
            
            transactions = extract_financial_data(
                input_data=message,
                input_type=input_type,
                sender_name=sender_name,
                media_url=media_url if input_type != 'text' else None,
                caption=message if input_type == 'image' else None,
                available_projects=available_projects
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
        
        # Save (transactions may include 'project' field from AI)
        result = append_transactions(transactions, sender_name, source)
        
        if result['success']:
            reply = format_success_reply(transactions).replace('*', '')
            send_whatsapp_reply(sender_number, reply)
        elif result.get('project_error'):
            send_whatsapp_reply(sender_number, f"❌ {result['project_error']}")
        else:
            send_whatsapp_reply(sender_number, "❌ Gagal menyimpan.")
        
        return jsonify({'success': result['success']}), 200
    
    except Exception as e:
        secure_log("ERROR", f"Fonnte webhook error: {type(e).__name__}")
        return jsonify({'success': False}), 500


# ===================== OTHER ENDPOINTS =====================

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'version': '2.1',
        'features': ['simplified-workflow', 'fixed-categories', 'security-hardened']
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
        'name': 'Financial Recording Bot',
        'version': '2.1',
        'status': 'running'
    }), 200


# ===================== MAIN =====================

if __name__ == '__main__':
    print("=" * 50)
    print("Financial Recording Bot v2.1 (Secured)")
    print("=" * 50)
    
    print("\nFeatures:")
    print("  ✓ Simplified Workflow (no project selection)")
    print("  ✓ Fixed 8 Categories")
    print("  ✓ Prompt Injection Protection")
    print("  ✓ Rate Limiting")
    print("  ✓ Secure Logging")
    
    print(f"\nCategories: {', '.join(ALLOWED_CATEGORIES)}")
    
    print("\nTesting connections...")
    try:
        if test_connection():
            print("✓ Google Sheets OK")
    except Exception as e:
        print(f"✗ Sheets error")
    
    print(f"\nFonnte: {'✓' if FONNTE_TOKEN else '✗'}")
    print(f"Telegram: {'✓' if TELEGRAM_BOT_TOKEN else '✗'}")
    
    print("\nCommands:")
    print("  /status    - Check status")
    print("  /laporan   - Weekly report")
    print("  /tanya     - Ask AI")
    print("  /kategori  - List categories")
    print("  /reminder  - Toggle reminder")
    
    # Start smart reminder scheduler
    print("\nStarting reminder scheduler...")
    start_scheduler()
    print("✓ Reminder scheduler active")
    
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)
