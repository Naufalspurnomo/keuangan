"""
main.py - Financial Recording Bot

Features:
- SIMPLIFIED WORKFLOW: No mandatory project selection
- Multi-channel (WhatsApp + Telegram)
- Fixed 4 Categories (auto-detected by AI)
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
import re
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===================== GLOBAL IMPORTS =====================
# Import helper modules
from ai_helper import extract_financial_data, query_data, RateLimitException
from sheets_helper import (
    append_transactions, append_transaction, test_connection, 
    generate_report, format_report_message,
    get_all_categories, get_summary,
    format_data_for_ai, check_budget_alert,
    get_company_sheets, COMPANY_SHEETS,
    format_dashboard_message, get_dashboard_summary,
    get_wallet_balances,
    invalidate_dashboard_cache,
    DOMPET_SHEETS, DOMPET_COMPANIES, SELECTION_OPTIONS,
    get_selection_by_idx, get_dompet_for_company,
    find_transaction_by_message_id, update_transaction_amount,
    normalize_project_display_name,
    check_duplicate_transaction,
    # NEW: Split Layout functions
    append_project_transaction,
    append_operational_transaction,
    get_or_create_operational_sheet,
)
from services.retry_service import process_retry_queue
from layer_integration import process_with_layers, USE_LAYERS
from wuzapi_helper import (
    send_wuzapi_reply,
    format_mention_body,
    get_clean_jid,
    download_wuzapi_media,
    download_wuzapi_image
)
from security import (
    sanitize_input,
    detect_prompt_injection,
    rate_limit_check,
    secure_log,
    SecurityError,
    RateLimitError,
    ALLOWED_CATEGORIES,
    now_wib,
)

from pdf_report import generate_pdf_from_input, parse_month_input, validate_period_data

# Services
from services.project_service import resolve_project_name, add_new_project_to_cache
from services.state_manager import (
    pending_key,
    pending_is_expired,
    get_pending_transactions,
    set_pending_transaction,
    clear_pending_transaction,
    has_pending_transaction,
    is_message_duplicate,
    store_bot_message_ref,
    get_original_message_id,
    store_pending_message_ref,
    get_pending_key_from_message,
    clear_pending_message_ref,
    # Visual Buffer for photo + text linking
    store_visual_buffer,
    get_visual_buffer,
    clear_visual_buffer,
    has_visual_buffer,
    record_bot_interaction,
)

from utils.parsers import (
    parse_selection,
    parse_revision_amount,
    should_respond_in_group,
    is_command_match,
    is_prefix_match,
    GROUP_TRIGGERS,
    PENDING_TTL_SECONDS,
)

from utils.formatters import (
    format_success_reply,
    format_success_reply_new,
    format_mention,
    build_selection_prompt,
    START_MESSAGE,
    HELP_MESSAGE,
    CATEGORIES_DISPLAY,
    SELECTION_DISPLAY,
)

# Import centralized config
from config.constants import Commands, Timeouts, GROUP_TRIGGERS, SPREADSHEET_ID, OPERATIONAL_KEYWORDS
from config.errors import UserErrors
from config.allowlist import is_sender_allowed
from config.wallets import (
    format_wallet_selection_prompt,
    get_wallet_selection_by_idx,
    WALLET_SELECTION_OPTIONS,
    get_dompet_short_name,
)

# Initialize Flask app
app = Flask(__name__)

# Configuration
DEBUG = os.getenv('FLASK_DEBUG', '0') == '1'

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


# Legacy: Keep reference to _pending_transactions for backward compatibility
# Now managed by services.state_manager
from services import state_manager as _state

# Re-export for backward compatibility - these point to the state_manager's internal dicts
_pending_transactions = _state._pending_transactions


# ===================== SMART ROUTER (Cost Accounting) =====================

def detect_transaction_context(text: str, transactions: list) -> dict:
    """
    Detect transaction routing context (Smart Router).
    
    Gaji Logic (from Cost Accounting spec):
    - "Transfer gaji Mbak Admin" (no project) -> OPERATIONAL (Sheet Operasional)
    - "Transfer fee Mas Budi untuk Taman Indah" (has project) -> PROJECT (Sheet Dompet)
    
    Returns:
        {
            'mode': 'PROJECT' | 'OPERATIONAL',
            'operational_category': str or None,
            'needs_source_wallet': bool,
            'detected_keywords': list
        }
    """
    text_lower = (text or '').lower()
    
    # Check for operational keywords
    detected_keywords = []
    for kw in OPERATIONAL_KEYWORDS:
        if kw in text_lower:
            detected_keywords.append(kw)
    
    # Check if transactions have valid project names
    # CRITICAL: If there's a project name, it's a PROJECT transaction
    # even if there are operational keywords (e.g., "fee untuk projek X")
    has_valid_project = False
    for t in transactions:
        nama_projek = t.get('nama_projek', '')
        if nama_projek and nama_projek.lower().strip():
            # Additional check - not just a generic name
            generic_names = ['umum', 'kantor', 'ops', 'operasional', 'admin']
            if len(nama_projek) > 2 and nama_projek.lower().strip() not in generic_names:
                has_valid_project = True
                break
    
    # PRIORITY: Project name takes precedence over operational keywords
    # "Fee Mas Budi untuk Taman Indah" -> PROJECT (Taman Indah is the project)
    if has_valid_project:
        return {
            'mode': 'PROJECT',
            'operational_category': None,
            'needs_source_wallet': False,
            'detected_keywords': []
        }
    
    # No project name + operational keywords = OPERATIONAL mode
    if detected_keywords:
        category = map_operational_category(detected_keywords[0])
        return {
            'mode': 'OPERATIONAL',
            'operational_category': category,
            'needs_source_wallet': True,
            'detected_keywords': detected_keywords
        }
    
    # Default: PROJECT mode (let existing company selection flow handle it)
    return {
        'mode': 'PROJECT',
        'operational_category': None,
        'needs_source_wallet': False,
        'detected_keywords': []
    }


def map_operational_category(keyword: str) -> str:
    """Map detected keyword to operational category."""
    keyword_lower = keyword.lower()
    
    if keyword_lower in ['gaji', 'salary', 'upah karyawan', 'honor']:
        return 'Gaji'
    elif keyword_lower in ['listrik', 'pln', 'air', 'pdam', 'listrikair']:
        return 'Listrik Air'
    elif keyword_lower in ['konsumsi', 'makan', 'snack', 'jamu', 'kopi', 'minum']:
        return 'Konsumsi'
    elif keyword_lower in ['peralatan', 'atk', 'alat tulis', 'perlengkapan kantor']:
        return 'Peralatan'
    else:
        return 'Lain Lain'


def apply_lifecycle_markers(project_name: str, transaction: dict) -> str:
    """
    Apply Start/Finish markers to project name based on transaction context.
    
    Smart Timeline Rules (from Cost Accounting spec):
    - START: Pemasukan + "DP/Termin 1" + Projek BARU (belum pernah ada)
    - RUNNING: Transaksi biasa (no marker)
    - FINISH: Pemasukan + "Pelunasan/Lunas"
    """
    if not project_name:
        return project_name
    
    if transaction.get('tipe') != 'Pemasukan':
        return project_name  # Only income can trigger Start/Finish
    
    keterangan = (transaction.get('keterangan', '') or '').lower()
    
    # Check for Pelunasan (Finish) - regardless of project history
    finish_keywords = ['pelunasan', 'lunas', 'final payment', 'pembayaran akhir', 'termin akhir', 'termin terakhir']
    if any(kw in keterangan for kw in finish_keywords):
        return f"{project_name} (Finish)"
    
    # Check for DP/Termin 1 (Start) - ONLY if project is NEW
    start_keywords = ['dp', 'down payment', 'uang muka', 'pembayaran awal', 'termin 1', 'termin pertama']
    if any(kw in keterangan for kw in start_keywords):
        # Check if project already exists in database
        from services.project_service import get_existing_projects
        existing_projects = get_existing_projects()
        
        # Normalize for comparison (case-insensitive)
        project_normalized = project_name.lower().strip()
        is_new_project = True
        
        for existing in existing_projects:
            if existing.lower().strip() == project_normalized:
                is_new_project = False
                break
        
        if is_new_project:
            return f"{project_name} (Start)"
    
    return project_name


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


def format_success_reply_new(transactions: list, dompet_sheet: str, company: str, mention: str = "") -> str:
    """Format success reply message with rich visual indicators."""
    lines = [f"{mention}✅ *Transaksi Berhasil Disimpan!*\n"]
    
    total_masuk = 0
    total_keluar = 0
    nama_projek_set = set()
    
    # Transaction details
    for t in transactions:
        amount = t.get('jumlah', 0)
        tipe = t.get('tipe', 'Pengeluaran') # Default Pengeluaran
        keterangan = t.get('keterangan', '-')
        
        # Visual Logic: Merah (Keluar) vs Hijau (Masuk)
        if tipe == 'Pemasukan':
            icon = "🟢"  # Green Circle
            sign = "+"
            total_masuk += amount
        else:
            icon = "🔴"  # Red Circle
            sign = "-"
            total_keluar += amount
            
        # Format angka: +Rp 100.000 atau -Rp 50.000
        amount_str = f"{sign}Rp {amount:,}".replace(',', '.')
        
        # Baris Item: 🔴 Beli Semen: -Rp 50.000
        lines.append(f"{icon} {keterangan}: *{amount_str}*")
        
        # Collect Project Names
        if t.get('nama_projek'):
            display_name = normalize_project_display_name(t['nama_projek'])
            if display_name:
                nama_projek_set.add(display_name)
    
    # Summary Section (Totalan)
    lines.append("") # Spasi
    
    # Tampilkan ringkasan sesuai apa yang terjadi
    if total_masuk > 0 and total_keluar > 0:
        # Jika campuran (ada masuk dan keluar)
        net = total_masuk - total_keluar
        lines.append(f"📈 Masuk: Rp {total_masuk:,}".replace(',', '.'))
        lines.append(f"📉 Keluar: Rp {total_keluar:,}".replace(',', '.'))
        lines.append(f"📊 *Net Flow: Rp {net:,}*".replace(',', '.'))
    elif total_masuk > 0:
        # Cuma Pemasukan
        lines.append(f"💰 *Total Masuk: Rp {total_masuk:,}*".replace(',', '.'))
    else:
        # Cuma Pengeluaran
        lines.append(f"💸 *Total Keluar: Rp {total_keluar:,}*".replace(',', '.'))
    
    # Location Info
    lines.append(f"\n📍 *{dompet_sheet}* → {company}")
    
    if nama_projek_set:
        projek_str = ', '.join(nama_projek_set)
        lines.append(f"📋 *Projek:* {projek_str}")
    
    # Timestamp
    now = now_wib().strftime("%d %b %Y, %H:%M")
    lines.append(f"⏱️ {now}")
    
    # Footer Actionable
    lines.append("\n💡 _Reply pesan ini untuk revisi_")
    
    return '\n'.join(lines)

# ===================== WUZAPI HANDLERS =====================

@app.route('/webhook_wuzapi', methods=['POST'])
def webhook_wuzapi():
    try:
        import json
        from urllib.parse import unquote
        
        instance_name = request.form.get('instanceName')
        json_data_raw = request.form.get('jsonData')
        user_id_param = request.form.get('userID')
        
        # Debug log
        secure_log("DEBUG", f"WuzAPI Form: instance={instance_name}, userID={user_id_param}")
        
        if not json_data_raw:
            secure_log("WARNING", "WuzAPI: No 'data' parameter found in POST request")
            return jsonify({'status': 'no_data'}), 200
        
        try:
            event_data = json.loads(json_data_raw)
        except json.JSONDecodeError:
            secure_log("ERROR", f"WuzAPI JSON parse failed: {json_data_raw[:200]}")
            return jsonify({'status': 'parse_error'}), 200
        
        secure_log("DEBUG", f"WuzAPI Event: {json.dumps(event_data)[:300]}")
        
        base64_image = event_data.get('base64', '')
        event_type = event_data.get('type', '')
        event = event_data.get('event', {})
        
        if event_type in ['Connected', 'OfflineSyncCompleted', 'OfflineSyncPreview', 'ReadReceipt', 'Receipt']:
            return jsonify({'status': 'ignored_event'}), 200
        
        info = event.get('Info', event)
        if info.get('IsFromMe', False):
            return jsonify({'status': 'own_message'}), 200
        
        sender_alt = info.get('SenderAlt', '')
        sender_jid = info.get('Sender', '')
        
        if sender_alt and '@s.whatsapp.net' in sender_alt:
            sender_number = sender_alt.split('@')[0].split(':')[0]
        elif sender_jid and '@' in sender_jid:
            sender_number = sender_jid.split('@')[0].split(':')[0]
        else:
            secure_log("DEBUG", f"WuzAPI: No valid sender found")
            return jsonify({'status': 'no_sender'}), 200
        
        push_name = info.get('PushName', 'User')
        message_id = info.get('ID', '')
        chat_jid = info.get('Chat', '')
        is_group = '@g.us' in chat_jid

        if not is_sender_allowed([sender_number]):
            reply_target = chat_jid if (is_group and chat_jid) else sender_number
            send_wuzapi_reply(reply_target, "❌ Anda tidak diizinkan menggunakan bot ini.")
            return jsonify({'status': 'forbidden'}), 200
        
        # Get message content
        message_obj = event.get('Message', {})
        text = ''
        input_type = 'text'
        media_url = None
        quoted_msg_id = ''
        quoted_message_text = ''
        
        ext_text = message_obj.get('extendedTextMessage', {}) or message_obj.get('ExtendedTextMessage', {})
        context_info = message_obj.get('contextInfo', {}) or message_obj.get('ContextInfo', {})
        
        if ext_text:
            context_info = ext_text.get('contextInfo', {}) or ext_text.get('ContextInfo', {})
            
        if context_info:
            quoted_msg_id = context_info.get('stanzaID', '') or context_info.get('stanzaId', '')
            quoted_msg_obj = context_info.get('quotedMessage', {}) or context_info.get('QuotedMessage', {})
            if quoted_msg_obj:
                quoted_message_text = (
                    quoted_msg_obj.get('conversation', '') or 
                    quoted_msg_obj.get('extendedTextMessage', {}).get('text', '')
                )

        msg_type = info.get('Type', '')
        if msg_type == 'text':
            text = message_obj.get('conversation', '') or \
                   message_obj.get('extendedTextMessage', {}).get('text', '')
        elif msg_type == 'media':
            caption = message_obj.get('imageMessage', {}).get('caption', '') or \
                     message_obj.get('caption', '')
            text = caption
            input_type = 'image'
            
            if base64_image:
                media_url = f"data:image/jpeg;base64,{base64_image}"
            else:
                if message_id and chat_jid:
                    media_path = download_wuzapi_image(message_id, chat_jid)
                    if media_path:
                        import base64 as b64
                        try:
                            with open(media_path, 'rb') as f:
                                img_data = b64.b64encode(f.read()).decode('utf-8')
                                media_url = f"data:image/jpeg;base64,{img_data}"
                        except Exception:
                            pass
                    else:
                        input_type = 'text'

        if not text and input_type == 'text':
            return jsonify({'status': 'no_text'}), 200
        
        if is_message_duplicate(message_id):
            return jsonify({'status': 'duplicate'}), 200

        return process_wuzapi_message(
            sender_number, push_name, text, input_type, media_url, 
            quoted_msg_id, message_id, is_group, chat_jid, sender_alt,
            quoted_message_text=quoted_message_text
        )
        
    except Exception as e:
        secure_log("ERROR", f"Webhook WuzAPI Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500


def process_wuzapi_message(sender_number: str, sender_name: str, text: str, 
                           input_type: str = 'text', media_url: str = None,
                           quoted_msg_id: str = None, message_id: str = None,
                           is_group: bool = False, chat_jid: str = None,
                           sender_jid: str = None,
                           quoted_message_text: str = None):
    try:
        reply_to = chat_jid if (is_group and chat_jid) else sender_number
        was_visual_link = False

        def send_reply_with_mention(body: str, with_mention: bool = True) -> dict:
            if is_group and with_mention and sender_jid:
                clean_jid = get_clean_jid(sender_jid)
                body_with_mention = format_mention_body(body, sender_name, sender_jid)
                return send_wuzapi_reply(reply_to, body_with_mention, clean_jid)
            else:
                return send_wuzapi_reply(reply_to, body)

        def extract_bot_msg_id(sent_msg: dict) -> str:
            if not sent_msg or not isinstance(sent_msg, dict):
                return None
            return (sent_msg.get('data', {}).get('Id') or
                    sent_msg.get('data', {}).get('id') or
                    sent_msg.get('key', {}).get('id') or
                    sent_msg.get('id') or
                    sent_msg.get('ID'))

        def record_pending_prompt(pkey: str, pending: dict, sent_msg: dict) -> None:
            bot_msg_id = extract_bot_msg_id(sent_msg)
            if not bot_msg_id:
                return
            store_pending_message_ref(bot_msg_id, pkey)
            prompt_ids = pending.setdefault('prompt_message_ids', [])
            prompt_ids.append(str(bot_msg_id))

        def clear_pending_prompt_refs(pending: dict) -> None:
            for msg_id in pending.get('prompt_message_ids', []):
                clear_pending_message_ref(msg_id)

        # --- UNIFIED SAVE FUNCTION ---
        def finalize_transaction_workflow(pending: dict, pkey: str):
            """Unified workflow for transaction finalization (Save or Selection).
            
            Smart Router Integration:
            - OPERATIONAL mode -> Ask for source wallet, save to Operasional Ktr
            - PROJECT mode -> Existing company/dompet resolution flow
            """
            txs = pending.get('transactions', [])
            if not txs:
                return jsonify({'status': 'error_no_tx'}), 200
            
            # =============== SMART ROUTER CHECK ===============
            original_text = pending.get('original_text', '')
            context = detect_transaction_context(original_text, txs)
            
            # CASE: OPERATIONAL MODE - Route to Operasional Ktr
            if context['mode'] == 'OPERATIONAL' and context['needs_source_wallet']:
                # Check if user already selected a source wallet
                source_wallet = pending.get('selected_source_wallet')
                
                if source_wallet:
                    # User has selected wallet -> Save to Operasional Ktr
                    clear_pending_prompt_refs(pending)
                    _pending_transactions.pop(pkey, None)
                    
                    tx_msg_id = pending.get('message_id', '')
                    for t in txs: 
                        t['message_id'] = tx_msg_id
                    
                    # Save each transaction to Operational sheet
                    results = []
                    for tx in txs:
                        result = append_operational_transaction(
                            transaction=tx,
                            sender_name=pending['sender_name'],
                            source=pending['source'],
                            source_wallet=source_wallet,
                            category=context['operational_category'] or 'Lain Lain'
                        )
                        results.append(result)
                    
                    if all(r.get('success') for r in results):
                        invalidate_dashboard_cache()
                        total = sum(tx.get('jumlah', 0) for tx in txs)
                        short_name = get_dompet_short_name(source_wallet)
                        reply = (
                            f"✅ *Operasional Tersimpan!*\n\n"
                            f"📝 Kategori: {context['operational_category']}\n"
                            f"💰 Total: Rp {total:,}\n".replace(',', '.') +
                            f"🏦 Sumber: {short_name}\n"
                            f"📊 Tersimpan di: Operasional Ktr"
                        ).replace('*', '')
                        send_reply_with_mention(reply)
                    else:
                        error_msg = results[0].get('error', 'Unknown error')
                        send_wuzapi_reply(reply_to, f"❌ Gagal simpan: {error_msg}")
                    
                    return jsonify({'status': 'processed_operational'}), 200
                else:
                    # Need to ask user for source wallet selection (1-3)
                    pending['pending_type'] = 'select_source_wallet'
                    pending['operational_context'] = context
                    
                    prompt = format_wallet_selection_prompt()
                    total = sum(tx.get('jumlah', 0) for tx in txs)
                    keterangan = txs[0].get('keterangan', '') if txs else ''
                    
                    header = (
                        f"💼 *Biaya Operasional*\n\n"
                        f"📝 {keterangan}\n"
                        f"💰 Rp {total:,}\n".replace(',', '.') +
                        f"📂 Kategori: {context['operational_category']}\n\n"
                    ).replace('*', '')
                    
                    full_prompt = header + prompt
                    if is_group:
                        full_prompt += "\n\n↩️ Reply pesan ini dengan angka 1-3"
                    
                    sent_msg = send_reply_with_mention(full_prompt)
                    record_pending_prompt(pkey, pending, sent_msg)
                    return jsonify({'status': 'asking_source_wallet'}), 200
            
            # =============== PROJECT MODE (Original Flow) ===============
            # 1. Company Detection & Dompet Resolution
            detected_company = None
            detected_dompet = None
            for t in txs:
                if t.get('company'):
                    detected_company = t['company']
                if t.get('detected_dompet'):
                    detected_dompet = t['detected_dompet']
                if detected_company: break
            
            dompet = None
            if detected_company:
                if detected_company == "UMUM":
                    # For UMUM, we MUST have a specific dompet or we ask user
                    dompet = detected_dompet or pending.get('override_dompet')
                else:
                    dompet = get_dompet_for_company(detected_company)
            
            # 2. Case A: Auto-save (Company Known & Dompet Resolved)
            if detected_company and dompet:
                # LAYER 5 DUPLICATE CHECK
                t0 = txs[0]
                is_dupe, warning_msg = check_duplicate_transaction(
                     t0.get('jumlah', 0), t0.get('keterangan', ''),
                     t0.get('nama_projek', ''), detected_company,
                     days_lookback=2
                )
                
                if is_dupe:
                    pending['pending_type'] = 'confirmation_dupe'
                    pending['selected_option'] = {'dompet': dompet, 'company': detected_company}
                    send_wuzapi_reply(reply_to, warning_msg)
                    return jsonify({'status': 'dupe_warning'}), 200

                # SAVE using Split Layout
                clear_pending_prompt_refs(pending)
                _pending_transactions.pop(pkey, None)
                tx_msg_id = pending.get('message_id', '')
                
                results = []
                for tx in txs:
                    tx['message_id'] = tx_msg_id
                    # Apply lifecycle markers
                    project_name = tx.get('nama_projek', '') or 'Umum'
                    project_name = apply_lifecycle_markers(project_name, tx)
                    
                    result = append_project_transaction(
                        transaction=tx,
                        sender_name=pending['sender_name'],
                        source=pending['source'],
                        dompet_sheet=dompet,
                        project_name=project_name
                    )
                    results.append(result)
                
                if all(r.get('success') for r in results):
                    invalidate_dashboard_cache()
                    reply = format_success_reply_new(txs, dompet, detected_company).replace('*', '')
                    reply += "\n\n💡 Reply pesan ini dengan `/revisi [jumlah]` untuk ralat"
                    sent_msg = send_reply_with_mention(reply)
                    
                    bot_msg_id = extract_bot_msg_id(sent_msg)
                    if bot_msg_id and tx_msg_id:
                        store_bot_message_ref(bot_msg_id, tx_msg_id)
                        from services.state_manager import store_last_bot_report
                        store_last_bot_report(chat_jid, bot_msg_id)
                else:
                    error_msg = results[0].get('error', 'Unknown error')
                    send_wuzapi_reply(reply_to, f"❌ Gagal: {error_msg}")
                return jsonify({'status': 'processed'}), 200
            
            # 3. Case B: Manual Selection (Company Unknown or UMUM without Dompet)
            pending['pending_type'] = 'selection'
            reply = build_selection_prompt(txs).replace('*', '')
            if is_group:
                reply += "\n\n↩️ Reply pesan ini dengan angka 1-5"
            sent_msg = send_reply_with_mention(reply)
            record_pending_prompt(pkey, pending, sent_msg)
            return jsonify({'status': 'asking_company'}), 200
        
        # Rate Limit
        allowed, wait_time = rate_limit_check(sender_number)
        if not allowed:
            return jsonify({'status': 'rate_limited'}), 200
        
        # ============ VISUAL BUFFER ============
        if input_type == 'image' and media_url and not text.strip():
            store_visual_buffer(sender_number, chat_jid, media_url, message_id)
            return jsonify({'status': 'photo_buffered'}), 200
        
        has_visual = has_visual_buffer(sender_number, chat_jid)
        
        # ============ [PRIORITY 1] PENDING CHECK FIRST ============
        # Cek apakah ada transaksi pending SEBELUM masuk ke AI/Filter
        # agar jawaban user tidak terfilter sebagai spam
        sender_pkey = pending_key(sender_number, chat_jid)
        pending_pkey = sender_pkey
        
        if is_group and quoted_msg_id:
            mapped_pkey = get_pending_key_from_message(quoted_msg_id)
            if mapped_pkey: pending_pkey = mapped_pkey

        pending_data = _pending_transactions.get(pending_pkey)
        
        if pending_data and pending_is_expired(pending_data):
            clear_pending_prompt_refs(pending_data)
            _pending_transactions.pop(pending_pkey, None)
            pending_data = None
        elif is_group and quoted_msg_id and not pending_data:
            clear_pending_message_ref(quoted_msg_id)
        
        has_pending = pending_data is not None

        if has_pending:
            secure_log("INFO", f"Bypassing AI Filter due to Pending State: {pending_pkey}")
            text = sanitize_input(text or '') # Just sanitize and proceed
        else:
            # ============ [PRIORITY 2] LAYER 1: SEMANTIC ENGINE ============
            if USE_LAYERS:
                action, layer_response, intent = process_with_layers(
                    user_id=sender_number, message_id=message_id, text=text,
                    sender_name=sender_name, media_url=media_url,
                    caption=text if input_type == 'image' else None,
                    is_group=is_group, chat_id=chat_jid,
                    quoted_message_id=quoted_msg_id, quoted_message_text=quoted_message_text,
                    sender_jid=sender_jid, has_visual=has_visual
                )
                
                if action == "IGNORE":
                    return jsonify({'status': 'ignored_by_layer'}), 200
                if action == "REPLY" and layer_response:
                    send_reply_with_mention(layer_response)
                    return jsonify({'status': 'handled_by_layer'}), 200
                if action == "PROCESS":
                    if intent == "QUERY_STATUS" and layer_response:
                        send_wuzapi_reply(reply_to, "🤔 Menganalisis...")
                        try:
                            data_context = format_data_for_ai(days=30)
                            answer = query_data(layer_response, data_context)
                            send_wuzapi_reply(reply_to, answer.replace('*', '').replace('_', ''))
                            return jsonify({'status': 'queried_by_layer'}), 200
                        except Exception as e:
                            secure_log("ERROR", f"Smart Query failed: {e}")
                    if layer_response:
                        text = layer_response
            
            # Check buffer link (only if not pending)
            media_urls_from_buffer = []
            if input_type == 'text' and not media_url:
                buffered_items = get_visual_buffer(sender_number, chat_jid)
                if buffered_items:
                    if isinstance(buffered_items, list):
                         media_urls_from_buffer = [item.get('media_url') for item in buffered_items]
                    else:
                         media_urls_from_buffer = [buffered_items.get('media_url')]
                    
                    if media_urls_from_buffer:
                        media_url = media_urls_from_buffer[0]
                        input_type = 'image'
                        clear_visual_buffer(sender_number, chat_jid)
                        was_visual_link = True
            
            text = sanitize_input(text or '')
            
            if not USE_LAYERS:
                should_respond, cleaned_text = should_respond_in_group(
                    message=text or "", is_group=is_group, has_media=media_url is not None,
                    has_pending=has_pending or has_visual or was_visual_link, is_mentioned=False
                )
                if not should_respond:
                    return jsonify({'status': 'ignored'}), 200
                text = cleaned_text if cleaned_text else text
        
        # REVISION
        if quoted_msg_id and text and is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
            if not quoted_msg_id:
                send_wuzapi_reply(reply_to, UserErrors.REVISION_NO_QUOTE)
                return jsonify({'status': 'revision_no_quote'}), 200
            
            original_msg_ref = get_original_message_id(quoted_msg_id)
            target_msg_id = original_msg_ref if original_msg_ref else quoted_msg_id
            original_tx = find_transaction_by_message_id(target_msg_id)
            
            if not original_tx:
                 send_wuzapi_reply(reply_to, "❌ Gagal revisi: Tidak dapat menemukan data transaksi asli.")
                 return jsonify({'status': 'revision_tx_not_found'}), 200

            new_amount = parse_revision_amount(text)
            if new_amount > 0:
                old_amount = original_tx['amount']
                success = update_transaction_amount(original_tx['dompet'], original_tx['row'], new_amount)
                if success:
                    invalidate_dashboard_cache()
                    diff = new_amount - old_amount
                    diff_str = f"+Rp {diff:,}" if diff > 0 else f"-Rp {abs(diff):,}"
                    reply = (f"✅ Revisi Berhasil!\n📊 {original_tx['keterangan']}\n"
                             f"Before: Rp {old_amount:,}\nAfter: Rp {new_amount:,}\n"
                             f"Diff: {diff_str}").replace(',', '.')
                    send_reply_with_mention(reply)
                    return jsonify({'status': 'revised'}), 200
                else:
                    send_reply_with_mention(UserErrors.REVISION_FAILED)
                    return jsonify({'status': 'revision_error'}), 200
            else:
                send_wuzapi_reply(reply_to, UserErrors.REVISION_INVALID_AMOUNT)
                return jsonify({'status': 'invalid_revision'}), 200

        # ============ PENDING HANDLING ============
        if has_pending:
            pending = pending_data
            pending_type = pending.get('pending_type', 'selection')
            
            if is_command_match(text, Commands.CANCEL, is_group):
                clear_pending_prompt_refs(pending)
                _pending_transactions.pop(pending_pkey, None)
                send_wuzapi_reply(reply_to, UserErrors.CANCELLED)
                return jsonify({'status': 'cancelled'}), 200
            
            # ... (Removal patterns logic omitted for brevity) ...

            # ===== HANDLE DUPLICATE CONFIRMATION =====
            if pending_type == 'confirmation_dupe':
                if text.lower().strip() == 'y':
                    option = pending.get('selected_option')
                    if not option:
                         send_wuzapi_reply(reply_to, "❌ Error state.")
                         _pending_transactions.pop(pending_pkey, None)
                         return jsonify({'status': 'error'}), 200
                    
                    # Manual Save for Dupe
                    result = append_transactions(pending['transactions'], pending['sender_name'], pending['source'],
                                               dompet_sheet=option['dompet'], company=option['company'])
                    if result['success']:
                        _pending_transactions.pop(pending_pkey, None)
                        reply = format_success_reply_new(pending['transactions'], option['dompet'], option['company'])
                        send_reply_with_mention(reply)
                    return jsonify({'status': 'processed_dupe'}), 200
                else:
                    _pending_transactions.pop(pending_pkey, None)
                    send_wuzapi_reply(reply_to, "❌ Dibatalkan.")
                    return jsonify({'status': 'cancelled'}), 200

            # ===== HANDLE PROJECT CONFIRMATION (REVISED) =====
            if pending_type == 'confirmation_project':
                text_clean = text.lower().strip()
                suggested = pending.get('suggested_project')
                final_project = ""
                
                # 1. POSITIVE CONFIRMATION
                if text_clean in ['ya', 'y', 'ok', 'yes', 'sip', 'benar', 'betul', 'lanjut', 'gas', 'bener', 'yoi']:
                    final_project = suggested
                    send_wuzapi_reply(reply_to, f"✅ Sip, masuk ke projek **{final_project}**.")
                
                # 2. NEGATIVE REJECTION
                elif text_clean in ['tidak', 'bukan', 'no', 'salah', 'ga', 'gak', 'nggak', 'g']:
                    send_wuzapi_reply(reply_to, "Oalah, maaf salah tebak. 🙏\n\nKalau begitu, nama projek yang benar apa?")
                    pending['pending_type'] = 'needs_project'
                    return jsonify({'status': 'asking_correct_name'}), 200
                
                # 3. DIRECT CORRECTION
                else:
                    final_project = sanitize_input(text.strip())
                    
                    # Guard against commands
                    if final_project.startswith('/'):
                        send_wuzapi_reply(reply_to, "⚠️ Command tidak bisa jadi nama projek. Ketik nama projek yang benar atau '/cancel'.")
                        return jsonify({'status': 'invalid_name_command'}), 200

                    if len(final_project) < 3:
                        send_wuzapi_reply(reply_to, "⚠️ Nama projek terlalu pendek.")
                        return jsonify({'status': 'invalid_name_length'}), 200

                    # Learn new project
                    add_new_project_to_cache(final_project)
                    send_wuzapi_reply(reply_to, f"👌 Oke, mencatat projek baru: **{final_project}**")

                # Apply & Finalize
                for t in pending['transactions']:
                    t['nama_projek'] = final_project
                    t.pop('needs_project', None)
                
                return finalize_transaction_workflow(pending, pending_pkey)

            # ===== HANDLE PROJECT NAME INPUT =====
            if pending_type == 'needs_project':
                project_name = sanitize_input(text.strip())[:100]
                if not project_name or len(project_name) < 2:
                    send_wuzapi_reply(reply_to, "❌ Nama projek tidak valid.")
                    return jsonify({'status': 'invalid_project'}), 200
                
                # Smart Check
                resolved = resolve_project_name(project_name)
                
                if resolved.get('status') == 'AMBIGUOUS':
                    pending['pending_type'] = 'confirmation_project'
                    pending['suggested_project'] = resolved['final_name']
                    msg = (f"🤔 Maksud Anda untuk projek *{resolved['final_name']}*?\n"
                           f"✅ Balas *Ya* jika benar\n❌ Ketik nama projek lain jika salah")
                    send_wuzapi_reply(reply_to, msg)
                    return jsonify({'status': 'waiting_project_confirm'}), 200
                
                if resolved.get('status') in ['EXACT', 'AUTO_FIX']:
                    project_name = resolved['final_name']
                
                for t in pending['transactions']:
                    t['nama_projek'] = project_name
                    t.pop('needs_project', None)
                
                return finalize_transaction_workflow(pending, pending_pkey)
            
            # ===== HANDLE SOURCE WALLET SELECTION (OPERATIONAL) =====
            if pending_type == 'select_source_wallet':
                # Parse 1-3 selection for source wallet
                try:
                    selection = int(text.strip())
                    if selection < 1 or selection > 3:
                        raise ValueError("Out of range")
                    
                    wallet_option = get_wallet_selection_by_idx(selection)
                    if not wallet_option:
                        send_wuzapi_reply(reply_to, "❌ Pilihan tidak valid. Ketik 1, 2, atau 3.")
                        return jsonify({'status': 'invalid_wallet_selection'}), 200
                    
                    # Set selected wallet and re-run finalize
                    pending['selected_source_wallet'] = wallet_option['dompet']
                    return finalize_transaction_workflow(pending, pending_pkey)
                    
                except ValueError:
                    send_wuzapi_reply(reply_to, "❌ Pilihan tidak valid.\n\n1. CV HB (101)\n2. TX SBY (216)\n3. TX BALI (087)\n\nBalas angka 1-3")
                    return jsonify({'status': 'invalid_wallet_selection'}), 200
            
            # ===== HANDLE COMPANY SELECTION (PROJECT MODE) =====
            is_valid, selection, error_msg = parse_selection(text)
            if not is_valid:
                send_wuzapi_reply(reply_to, f"❌ {error_msg}")
                return jsonify({'status': 'invalid_selection'}), 200
            
            option = get_selection_by_idx(selection)
            if not option:
                 send_wuzapi_reply(reply_to, UserErrors.SELECTION_OUT_OF_RANGE)
                 return jsonify({'status': 'error'}), 200
            
            pending['selected_option'] = option 
            for t in pending['transactions']:
                t['company'] = option['company']
            
            return finalize_transaction_workflow(pending, pending_pkey)
        
        
        # COMMANDS HANDLER (/start, /help, etc)
        if is_command_match(text, Commands.START, is_group):
            send_wuzapi_reply(reply_to, START_MESSAGE.replace('*', '').replace('_', ''))
            return jsonify({'status': 'ok'}), 200
        
        if is_command_match(text, Commands.HELP, is_group):
            send_wuzapi_reply(reply_to, HELP_MESSAGE.replace('*', '').replace('_', ''))
            return jsonify({'status': 'ok'}), 200

        # ... (Other commands logic remains same) ...

        # AI EXTRACTION
        transactions = []
        try:
            # === FEEDBACK: SCAN START ===
            send_wuzapi_reply(reply_to, "🔍 Scan...")

            final_media_list = media_urls_from_buffer if media_urls_from_buffer else ([media_url] if media_url else [])
            caption_text = text if input_type == 'image' else None
            transactions = extract_financial_data(text or '', input_type, sender_name, final_media_list, caption_text)
            
            if not transactions:
                if input_type == 'image':
                    send_wuzapi_reply(reply_to, "❓ Tidak ada transaksi terdeteksi.")
                return jsonify({'status': 'no_transactions'}), 200

            for t in transactions: t['message_id'] = message_id
            
            if is_group: source = "WhatsApp Group" 
            else: source = "WhatsApp"

            # Check needs project (Manual AI Flag)
            needs_project = any(t.get('needs_project') for t in transactions)
            if needs_project:
                # Create pending and ask
                _pending_transactions[sender_pkey] = {
                    'transactions': transactions,
                    'sender_name': sender_name,
                    'source': source,
                    'created_at': datetime.now(),
                    'message_id': message_id,
                    'pending_type': 'needs_project',
                    'chat_jid': chat_jid,
                    'requires_reply': is_group,
                    'prompt_message_ids': []
                }
                ask_msg = "❓ Perlu nama projek (biar laporan rapi)"
                sent_msg = send_reply_with_mention(ask_msg)
                record_pending_prompt(sender_pkey, _pending_transactions[sender_pkey], sent_msg)
                return jsonify({'status': 'asking_project'}), 200

            # ==================================================================
            # 🔥 SMART INTERCEPT: CEK KEMIRIPAN PROJEK SEBELUM LANJUT 🔥
            # ==================================================================
            ambiguous_project = None
            
            for t in transactions:
                p_name = t.get('nama_projek')
                if not p_name or p_name.lower() == "saldo umum": 
                    continue
                
                res = resolve_project_name(p_name)
                
                if res['status'] == 'EXACT':
                    t['nama_projek'] = res['final_name']
                elif res['status'] == 'AUTO_FIX':
                    secure_log("INFO", f"Auto-fix project: {p_name} -> {res['final_name']}")
                    t['nama_projek'] = res['final_name']
                elif res['status'] == 'NEW':
                    pass
                elif res['status'] == 'AMBIGUOUS':
                    ambiguous_project = res
                    break 
            
            if ambiguous_project:
                _pending_transactions[sender_pkey] = {
                    'transactions': transactions,
                    'sender_name': sender_name,
                    'source': source,
                    'created_at': datetime.now(),
                    'message_id': message_id,
                    'chat_jid': chat_jid,
                    'pending_type': 'confirmation_project', 
                    'suggested_project': ambiguous_project['final_name'],
                    'original_project': ambiguous_project['original'],
                    'requires_reply': is_group,
                    'prompt_message_ids': []
                }
                
                msg = (f"🤔 Maksud Anda untuk projek *{ambiguous_project['final_name']}*?\n"
                       f"(Input Anda: _{ambiguous_project['original']}_)\n\n"
                       f"✅ Balas *Ya* jika benar\n"
                       f"❌ Balas *Tidak* jika ini projek baru")
                
                sent_msg = send_reply_with_mention(msg)
                record_pending_prompt(sender_pkey, _pending_transactions[sender_pkey], sent_msg)
                return jsonify({'status': 'waiting_project_confirm'}), 200
            
            # ==================================================================
            
            # Create/Update pending state for the unified workflow
            pending = {
                'transactions': transactions,
                'sender_name': sender_name,
                'source': source,
                'created_at': datetime.now(),
                'message_id': message_id,
                'chat_jid': chat_jid,
                'requires_reply': is_group,
                'prompt_message_ids': []
            }
            _pending_transactions[sender_pkey] = pending
            
            # Execute unified finalization workflow
            return finalize_transaction_workflow(pending, sender_pkey)

        except Exception as e:
            secure_log("ERROR", f"Processing error: {e}")
            send_wuzapi_reply(reply_to, "❌ Terjadi kesalahan.")
            return jsonify({'status': 'error'}), 200

    except Exception as e:
        secure_log("ERROR", f"WuzAPI flow error: {e}")
        return jsonify({'status': 'error'}), 500

def get_status_message() -> str:
    return format_dashboard_message()

if __name__ == '__main__':
    retry_thread = threading.Thread(target=background_retry_worker, daemon=True)
    retry_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)