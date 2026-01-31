"""
main.py - Financial Recording Bot (Enterprise Edition)

Features:
- COST ACCOUNTING: Splits Operational (Fixed) vs Project (Variable) costs.
- SMART ROUTING: Auto-detects context (Salary/Utilities vs Project Expenses).
- PROJECT LIFECYCLE: Auto-tags projects with (Start) and (Finish).
- MULTI-CHANNEL: WhatsApp + Telegram support.
- SECURE: Rate limiting, prompt injection protection...
"""

import os
import traceback
import requests
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===================== GLOBAL IMPORTS =====================
# AI & Data Processing
from ai_helper import extract_financial_data, query_data, RateLimitException

# Google Sheets Integration
from sheets_helper import (
    append_transactions, append_transaction, 
    format_data_for_ai,
    format_dashboard_message, get_dashboard_summary,
    get_wallet_balances,
    invalidate_dashboard_cache,
    DOMPET_SHEETS, DOMPET_COMPANIES, SELECTION_OPTIONS,
    get_selection_by_idx, get_dompet_for_company,
    check_duplicate_transaction,
    # New Split Layout Functions
    append_project_transaction,
    append_operational_transaction,
)

# Services
from services.retry_service import process_retry_queue
from services.project_service import resolve_project_name, add_new_project_to_cache
from services.state_manager import (
    pending_key, pending_is_expired,
    is_message_duplicate, store_bot_message_ref,
    store_pending_message_ref,
    get_pending_key_from_message,
    store_visual_buffer, get_visual_buffer,
    clear_visual_buffer, has_visual_buffer,
    store_last_bot_report,
    # New Pending Confirmations
    get_pending_confirmation, set_pending_confirmation,
    store_user_message, get_user_last_message, clear_user_last_message
)

# Layer Integration - Superseded by SmartHandler
# from layer_integration_v2 import process_with_layers, USE_ENHANCED_LAYERS as USE_LAYERS
USE_LAYERS = True # Enable SmartHandler logic by default

# Utilities
from wuzapi_helper import (
    send_wuzapi_reply, format_mention_body,
    get_clean_jid, download_wuzapi_media,
    download_wuzapi_image
)
from security import (
    sanitize_input, detect_prompt_injection,
    rate_limit_check, secure_log,
    SecurityError, RateLimitError,
    ALLOWED_CATEGORIES, now_wib,
)
from pdf_report import generate_pdf_from_input, parse_month_input, validate_period_data
from utils.parsers import (
    parse_selection, parse_revision_amount,
    should_respond_in_group, is_command_match,
    is_prefix_match, GROUP_TRIGGERS, PENDING_TTL_SECONDS,
)
from utils.formatters import (
    format_success_reply, format_success_reply_new,
    format_mention, build_selection_prompt,
    START_MESSAGE, HELP_MESSAGE,
    CATEGORIES_DISPLAY, SELECTION_DISPLAY,
)

# Configuration
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

# Configuration Flags
DEBUG = os.getenv('FLASK_DEBUG', '0') == '1'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# ===================== NETWORK HELPERS =====================

_TELEGRAM_API_URL = None
_telegram_session = None

def get_telegram_session():
    """Get or create requests Session with connection pooling."""
    global _telegram_session
    if _telegram_session is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        _telegram_session = requests.Session()
        retry_strategy = Retry(
            total=3, backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retry_strategy)
        _telegram_session.mount("https://", adapter)
        _telegram_session.mount("http://", adapter)
        
    return _telegram_session

def get_telegram_api_url():
    """Get Telegram API URL."""
    global _TELEGRAM_API_URL
    if _TELEGRAM_API_URL is None and TELEGRAM_BOT_TOKEN:
        _TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    return _TELEGRAM_API_URL

def send_telegram_reply(chat_id: int, message: str, parse_mode: str = 'Markdown'):
    """Send Telegram reply securely."""
    try:
        api_url = get_telegram_api_url()
        if not api_url: return None
        
        session = get_telegram_session()
        response = session.post(
            f"{api_url}/sendMessage",
            json={'chat_id': chat_id, 'text': message, 'parse_mode': parse_mode},
            timeout=10
        )
        return response.json()
    except Exception as e:
        secure_log("ERROR", f"Telegram send failed: {type(e).__name__}")
        return None

# Import legacy pending dict (now managed via state_manager proxy)
from services import state_manager as _state
_pending_transactions = _state._pending_transactions


# ===================== LOGIC CORE: SMART ROUTER v2.0 =====================
# Enhanced with amount pattern detection and AI category_scope integration
from handlers.smart_handler import SmartHandler
import services.state_manager as state_manager_module

# Initialize SmartHandler
smart_handler = SmartHandler(state_manager_module)

import re  # Ensure re is available for pattern matching

# Amount pattern detection (matches groq_analyzer.py)
AMOUNT_PATTERNS = [
    re.compile(r'rp[\s.]*\d+', re.IGNORECASE),
    re.compile(r'\d+[\s]*(rb|ribu|k)', re.IGNORECASE),
    re.compile(r'\d+[\s]*(jt|juta)', re.IGNORECASE),
    re.compile(r'\d{4,}'),  # 4+ consecutive digits
]

def has_amount_pattern(text: str) -> bool:
    """Check if text contains recognizable amount pattern."""
    for pattern in AMOUNT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def detect_transaction_context(text: str, transactions: list, category_scope: str = 'UNKNOWN') -> dict:
    """
    Detects context: PROJECT vs OPERATIONAL.
    
    v2.0 Improvements:
    - Uses category_scope from AI layer when available
    - Checks for amount patterns in text
    - Better keyword matching with word boundaries
    
    Rules:
    1. If AI says OPERATIONAL -> OPERATIONAL (Priority 1 - Trust AI)
    2. Has valid Project Name? -> PROJECT (Priority 2)
    3. Has Operational Keywords + No valid Project? -> OPERATIONAL (Priority 3)
    4. Else -> Default to PROJECT
    """
    text_lower = (text or '').lower()
    
    # NEW v2.0: Trust AI's category_scope if available
    if category_scope == 'OPERATIONAL':
        # Detect which operational category
        detected_keywords = [kw for kw in OPERATIONAL_KEYWORDS if kw in text_lower]
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    
    if category_scope == 'PROJECT':
        # AI is confident this is project-related
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    
    # Fallback: Rule-based detection (when AI uncertain or not used)
    
    # Check Keywords with better matching
    detected_keywords = []
    for kw in OPERATIONAL_KEYWORDS:
        # Use word boundary matching for better accuracy
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            detected_keywords.append(kw)
    
    # Check Project Name Validity
    from config.constants import PROJECT_STOPWORDS
    from services.project_service import get_existing_projects
    
    # Get cache of existing projects for validation
    existing_projects_cache = [p.lower() for p in get_existing_projects()]
    
    has_valid_project = False
    valid_project_name = None
    
    for t in transactions:
        nama_projek = t.get('nama_projek', '')
        if nama_projek and len(nama_projek) > 2:
            clean_name = nama_projek.lower().strip()

            # 1. DATABASE CHECK: Is this a known project?
            # If yes, this is definitely a PROJECT transaction (Override everything)
            if clean_name in existing_projects_cache:
                return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False, 'project_name': nama_projek}

            # Build comprehensive generic names list
            generic_names = {'umum', 'kantor', 'ops', 'operasional', 'admin', 'gaji', 'finance'}
            generic_names.update(OPERATIONAL_KEYWORDS)
            generic_names.update(PROJECT_STOPWORDS)
            
            # Check if name is exactly a generic word
            if clean_name not in generic_names:
                # Also check if it's ONLY an operational keyword
                is_just_keyword = (clean_name in PROJECT_STOPWORDS or clean_name in OPERATIONAL_KEYWORDS)
                
                if not is_just_keyword:
                    has_valid_project = True
                    valid_project_name = nama_projek
                    break
    
    # Decision Tree
    # Priority 1: Keywords found AND NO valid project -> OPERATIONAL
    if detected_keywords and not has_valid_project:
        category = map_operational_category(detected_keywords[0])
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}

    # Priority 2: Has valid project name -> PROJECT
    if has_valid_project:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False, 'project_name': valid_project_name}
    
    # Priority 3: Has keywords (but maybe ambiguous) -> OPERATIONAL
    if detected_keywords:
        category = map_operational_category(detected_keywords[0])
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    
    # Default: PROJECT mode (standard flow asks for company)
    return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}


def map_operational_category(keyword: str) -> str:
    """
    Maps keywords to standard Operational Categories.
    v2.0: Expanded keyword matching.
    """
    k = keyword.lower()
    
    # Payroll
    if k in ['gaji', 'salary', 'upah', 'honor', 'thr', 'bonus', 'upah karyawan']:
        return 'Gaji'
    
    # Utilities
    if k in ['listrik', 'pln', 'air', 'pdam', 'wifi', 'internet', 'listrikair', 'speedy', 'indihome']:
        return 'ListrikAir'
    
    # Consumables
    if k in ['konsumsi', 'makan', 'snack', 'minum', 'jamu', 'kopi']:
        return 'Konsumsi'
    
    # Equipment
    if k in ['peralatan', 'atk', 'alat', 'perlengkapan', 'alat tulis', 'perlengkapan kantor']:
        return 'Peralatan'
    
    return 'Lain Lain'

def apply_lifecycle_markers(project_name: str, transaction: dict, is_new_project: bool = False) -> str:
    """
    Applies (Start) or (Finish) markers to project names.
    Only for 'Pemasukan' transactions.
    """
    if not project_name or transaction.get('tipe') != 'Pemasukan':
        return project_name
        
    desc = (transaction.get('keterangan', '') or '').lower()
    
    # Rule 1: Finish
    finish_keywords = ['pelunasan', 'lunas', 'final payment', 'penyelesaian', 'selesai', 'kelar', 'beres']
    if any(k in desc for k in finish_keywords):
        return f"{project_name} (Finish)"
        
    # Rule 2: Start (New Project Auto-Detect)
    # If explicitly flagged as new OR not in existing check
    if is_new_project:
        return f"{project_name} (Start)"

    from services.project_service import get_existing_projects
    existing = get_existing_projects()
    
    # Check if project exists (case insensitive)
    # If NOT found in existing, tag as (Start)
    if not any(e.lower() == project_name.lower() for e in existing):
        return f"{project_name} (Start)"
            
    return project_name


# ===================== HEALTH CHECK ENDPOINT =====================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check for monitoring and Docker healthcheck."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()}), 200


# ===================== WUZAPI HANDLER =====================

@app.route('/webhook_wuzapi', methods=['POST'])
def webhook_wuzapi():
    try:
        import json
        
        # 1. Parse Data
        json_data_raw = request.form.get('jsonData')
        if not json_data_raw: return jsonify({'status': 'no_data'}), 200
        
        try:
            event_data = json.loads(json_data_raw)
        except json.JSONDecodeError:
            return jsonify({'status': 'parse_error'}), 200
            
        # 2. Extract Event Info
        event = event_data.get('event', {})
        info = event.get('Info', event)
        event_type = event_data.get('type', '')
        
        # FILTER: Ignore non-message events
        ignored_types = ['Connected', 'ReadReceipt', 'Receipt', 'Typing', 'TypingStarted', 
                        'TypingStopped', 'Presence', 'PresenceUpdate', 'ChatState',
                        'Composing', 'Paused']
        
        # Also ignore if event_type is empty (often happens during typing/sync)
        if not event_type or event_type in ignored_types:
            return jsonify({'status': 'ignored_event'}), 200
        
        # FILTER: Ignore own messages
        if info.get('IsFromMe', False):
            return jsonify({'status': 'own_message'}), 200
            
        # 3. Resolve Sender
        sender_alt = info.get('SenderAlt', '')
        sender_jid = info.get('Sender', '')
        sender_number = sender_alt.split('@')[0].split(':')[0] if '@' in sender_alt else \
                       (sender_jid.split('@')[0].split(':')[0] if '@' in sender_jid else '')
                       
        if not sender_number: 
            secure_log("WARNING", f"Webhook: No sender number found in {info}")
            return jsonify({'status': 'no_sender'}), 200
        
        # 4. Access Control
        chat_jid = info.get('Chat', '')
        is_group = '@g.us' in chat_jid
        if not is_sender_allowed([sender_number]):
            secure_log("WARNING", f"Webhook: Access denied for {sender_number}")
            reply_target = chat_jid if (is_group and chat_jid) else sender_number
            send_wuzapi_reply(reply_target, "❌ Akses Ditolak. Hubungi Admin.")
            return jsonify({'status': 'forbidden'}), 200

        # 5. Extract Content
        message_obj = event.get('Message', {})
        text = ''
        input_type = 'text'
        media_url = None
        quoted_msg_id = ''
        
        # FILTER: Only process actual messages (text or media)
        msg_type = info.get('Type', '')
        if msg_type not in ['text', 'media', 'image']:
            secure_log("INFO", f"Webhook: Ignored message type '{msg_type}'")
            return jsonify({'status': f'ignored_type_{msg_type}'}), 200
        
        # Text extraction logic
        if msg_type == 'text':
            text = message_obj.get('conversation') or \
                   message_obj.get('extendedTextMessage', {}).get('text', '')
        elif msg_type in ['media', 'image']:
            text = message_obj.get('imageMessage', {}).get('caption', '')
            input_type = 'image'
            if event_data.get('base64'):
                media_url = f"data:image/jpeg;base64,{event_data['base64']}"
            elif info.get('ID'):
                # Fallback download logic here if needed
                pass

        # LOG THE INCOMING MESSAGE
        secure_log("INFO", f"Webhook: Msg from {sender_number} (Group: {is_group}): {text[:50]}...")

        # Quoted info
        ctx_info = message_obj.get('extendedTextMessage', {}).get('contextInfo', {}) or \
                   message_obj.get('contextInfo', {})
        if ctx_info:
            quoted_msg_id = ctx_info.get('stanzaId')

        # 6. Deduplication
        message_id = info.get('ID', '')
        if is_message_duplicate(message_id):
            secure_log("INFO", f"Webhook: Duplicate message {message_id} ignored")
            return jsonify({'status': 'duplicate'}), 200

        # 7. Process
        return process_wuzapi_message(
            sender_number, info.get('PushName', 'User'), text,
            input_type, media_url, quoted_msg_id, message_id,
            is_group, chat_jid, sender_alt
        )

    except Exception as e:
        secure_log("ERROR", f"Webhook Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500


def process_wuzapi_message(sender_number: str, sender_name: str, text: str, 
                           input_type: str = 'text', media_url: str = None,
                           quoted_msg_id: str = None, message_id: str = None,
                           is_group: bool = False, chat_jid: str = None,
                           sender_jid: str = None, quoted_message_text: str = None):
    try:
        reply_to = chat_jid if (is_group and chat_jid) else sender_number
        
        # --- Helper: Send Reply ---
        def send_reply(body: str, mention: bool = True):
            if is_group and mention and sender_jid:
                clean_jid = get_clean_jid(sender_jid)
                body_fmt = format_mention_body(body, sender_name, sender_jid)
                return send_wuzapi_reply(reply_to, body_fmt, clean_jid)
            return send_wuzapi_reply(reply_to, body)

        # --- Helper: State Management ---
        def extract_bot_msg_id(sent):
            if not sent or not isinstance(sent, dict): return None
            return (sent.get('data', {}).get('Id') or sent.get('id') or sent.get('ID'))

        def cache_prompt(pkey, pending, sent):
            bid = extract_bot_msg_id(sent)
            if bid:
                store_pending_message_ref(bid, pkey)
                pending.setdefault('prompt_message_ids', []).append(str(bid))

        # --- CORE WORKFLOW: FINALIZE TRANSACTION ---
        def finalize_transaction_workflow(pending: dict, pkey: str):
            txs = pending.get('transactions', [])
            if not txs: return jsonify({'status': 'error_no_tx'}), 200
            
            # ROUTING CHECK
            original_text = pending.get('original_text', '')
            category_scope = pending.get('category_scope', 'UNKNOWN')  # From AI layer
            
            # If already routed/flagged, respect it
            if pending.get('is_operational'):
                context = {'mode': 'OPERATIONAL', 'needs_wallet': True, 
                           'category': pending.get('operational_category', 'Lain Lain')}
            else:
                # Pass category_scope from AI layer for smarter routing
                context = detect_transaction_context(original_text, txs, category_scope)

            # === JALUR 1: OPERATIONAL ===
            if context['mode'] == 'OPERATIONAL':
                source_wallet = pending.get('selected_source_wallet')
                
                # Step 1: Ask Wallet if missing
                if not source_wallet:
                    pending['pending_type'] = 'select_source_wallet'
                    pending['is_operational'] = True
                    pending['operational_category'] = context['category']
                    
                    prompt = format_wallet_selection_prompt()
                    total = sum(t.get('jumlah', 0) for t in txs)
                    item = txs[0].get('keterangan', 'Biaya')
                    
                    msg = (f"🏢 *Deteksi: Operasional Kantor*\n"
                           f"📝 {item} (Rp {total:,})\n\n"
                           f"{prompt}").replace(',', '.')
                           
                    sent = send_reply(msg)
                    cache_prompt(pkey, pending, sent)
                    return jsonify({'status': 'asking_wallet'}), 200
                
                # Step 2: Save to Operational Sheet
                results = []
                for tx in txs:
                    res = append_operational_transaction(
                        transaction=tx,
                        sender_name=pending['sender_name'],
                        source=pending['source'],
                        source_wallet=source_wallet,
                        category=context['category']
                    )
                    results.append(res)
                
                if all(r.get('success') for r in results):
                    _pending_transactions.pop(pkey, None)
                    # Clear prompt refs logic here
                    invalidate_dashboard_cache()
                    
                    short_wallet = get_dompet_short_name(source_wallet)
                    reply = (f"✅ *Tersimpan di Operasional Kantor*\n"
                             f"💰 Sumber: {short_wallet}\n"
                             f"📂 Kategori: {context['category']}").replace('*', '')
                    send_reply(reply)
                    return jsonify({'status': 'saved_operational'}), 200
                else:
                    err = results[0].get('error', 'Unknown')
                    send_reply(f"❌ Gagal simpan: {err}")
                    return jsonify({'status': 'error'}), 200

            # === JALUR 2: PROJECT (Standard) ===
            
            # --- VALIDATION: CHECK PROJECT EXISTENCE ---
            # Checks if project exists in Spreadsheet/Cache before proceeding
            if not pending.get('project_confirmed'):
                for t in txs:
                    p_name_raw = t.get('nama_projek')
                    # Skip validation for "Saldo Umum", empty, or "Umum"
                    if not p_name_raw or p_name_raw.lower() in ['saldo umum', 'umum', 'unknown']:
                        continue
                    
                    # Resolve Name
                    res = resolve_project_name(p_name_raw)
                    
                    if res['status'] == 'AMBIGUOUS':
                         pending['pending_type'] = 'confirmation_project'
                         pending['suggested_project'] = res['final_name']
                         send_reply(f"🤔 Maksudnya **{res['final_name']}**?\n✅ Ya / ❌ Bukan")
                         return jsonify({'status': 'asking_project_confirm'}), 200
                    
                    elif res['status'] == 'NEW':
                        # Validasi typo / project baru
                        pending['pending_type'] = 'confirmation_new_project'
                        pending['new_project_name'] = res['original']
                        send_reply(f"🆕 Project **{res['original']}** belum ada.\n\nBuat Project Baru?\n✅ Ya / ❌ Ganti Nama")
                        return jsonify({'status': 'asking_new_project'}), 200
                    
                    elif res['status'] in ['EXACT', 'AUTO_FIX']:
                        # Auto update to canonical name
                        t['nama_projek'] = res['final_name']

            # 1. Resolve Company/Dompet
            detected_company = None
            for t in txs:
                if t.get('company'): 
                    detected_company = t['company']
                    break
            
            dompet = None
            if detected_company:
                if detected_company == "UMUM":
                    dompet = pending.get('override_dompet')
                else:
                    dompet = get_dompet_for_company(detected_company)
            
            # --- AUTO-RESOLVE COMPANY FROM PROJECT HISTORY (NEW) ---
            # If we know the project, but not the company, try to find where it was last used
            if not dompet and pending.get('project_confirmed'):
                from sheets_helper import find_company_for_project
                
                # Check first transaction's project
                p_name_check = txs[0].get('nama_projek')
                if p_name_check:
                    found_dompet, found_comp = find_company_for_project(p_name_check)
                    if found_dompet:
                        dompet = found_dompet
                        detected_company = found_comp
                        secure_log("INFO", f"Auto-resolved project '{p_name_check}' to {found_company}")

            # 2. Save if Resolved
            if detected_company and dompet:
                # Check Duplicates
                t0 = txs[0]
                is_dupe, warn = check_duplicate_transaction(
                    t0.get('jumlah', 0), t0.get('keterangan', ''),
                    t0.get('nama_projek', ''), detected_company
                )
                
                if is_dupe:
                    pending['pending_type'] = 'confirmation_dupe'
                    pending['selected_option'] = {'dompet': dompet, 'company': detected_company}
                    send_reply(warn)
                    return jsonify({'status': 'dupe_warning'}), 200
                
                # Save Logic (Split Layout)
                tx_msg_id = pending.get('message_id', '')
                results = []
                
                for tx in txs:
                    tx['message_id'] = tx_msg_id
                    # Apply Lifecycle (Start/Finish)
                    p_name = tx.get('nama_projek', '') or 'Umum'
                    is_new = pending.get('is_new_project', False)
                    p_name = apply_lifecycle_markers(p_name, tx, is_new_project=is_new)
                    
                    res = append_project_transaction(
                        transaction=tx,
                        sender_name=pending['sender_name'],
                        source=pending['source'],
                        dompet_sheet=dompet,
                        project_name=p_name
                    )
                    results.append(res)
                
                if all(r.get('success') for r in results):
                    invalidate_dashboard_cache()
                    # Rich Reply
                    reply = format_success_reply_new(txs, dompet, detected_company).replace('*', '')
                    sent = send_reply(reply)
                    
                    # Store Bot Ref for Revision
                    bid = extract_bot_msg_id(sent)
                    if bid and tx_msg_id:
                        store_bot_message_ref(bid, tx_msg_id)
                        store_last_bot_report(chat_jid, bid)
                        
                        
                    _pending_transactions.pop(pkey, None)
                    
                    # UPDATE CACHE AFTER SUCCESS
                    if pending.get('is_new_project'):
                        # Add the raw project name to cache (without Start/Finish tag)
                        raw_proj = txs[0].get('nama_projek')
                        if raw_proj:
                            add_new_project_to_cache(raw_proj)

                    return jsonify({'status': 'processed'}), 200
                else:
                    send_reply(f"❌ Gagal: {results[0].get('error')}")
                    return jsonify({'status': 'error'}), 200
            
            # 3. Ask Company if Unresolved
            pending['pending_type'] = 'selection'
            reply = build_selection_prompt(txs).replace('*', '')
            if is_group: reply += "\n\n↩️ Reply angka 1-4"
            sent = send_reply(reply)
            cache_prompt(pkey, pending, sent)
            return jsonify({'status': 'asking_company'}), 200

        # --- FLOW CONTROL ---
        
        # 1. Rate Limit
        allowed, wait = rate_limit_check(sender_number)
        if not allowed: return jsonify({'status': 'rate_limit'}), 200
        
        # 2. Visual Buffer
        if input_type == 'image' and not text.strip():
            store_visual_buffer(sender_number, chat_jid, media_url, message_id)
            return jsonify({'status': 'buffered'}), 200
        
        has_visual = has_visual_buffer(sender_number, chat_jid)

        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        from handlers.pending_handler import handle_pending_response

        pending_conf = get_pending_confirmation(sender_number, chat_jid)
        if pending_conf:
            # Check if handled by pending handler
            result = handle_pending_response(
                user_id=sender_number,
                chat_id=chat_jid,
                text=text,
                pending_data=pending_conf,
                sender_name=sender_name
            )
            
            if result:
                if result.get('response'):
                    send_reply(result['response'])
                
                if result.get('completed'):
                    # Flow finished (saved or cancelled)
                    return jsonify({'status': 'handled_confirmation'}), 200
                else:
                    # Flow continues (asked next question)
                    return jsonify({'status': 'pending_interaction'}), 200
            
            # If result is None, it means the input didn't match the expected options
            # (e.g. user typed something random instead of '1' or '2')
            # So we continue to normal processing (AI Layers)
            pass
        
        # 3. Check Pending (Standard/Legacy)
        sender_pkey = pending_key(sender_number, chat_jid)
        pending_pkey = sender_pkey
        if is_group and quoted_msg_id:
            mapped = get_pending_key_from_message(quoted_msg_id)
            if mapped: pending_pkey = mapped
            
        pending_data = _pending_transactions.get(pending_pkey)
        if pending_data and pending_is_expired(pending_data):
            _pending_transactions.pop(pending_pkey, None)
            pending_data = None
            
        has_pending = pending_data is not None
        
        # 4. Filter AI Trigger
        text = sanitize_input(text or '')
        
        # ========== PRIORITY: COMMANDS FIRST (before layer processing) ==========
        if text.strip().startswith('/'):
            if is_command_match(text, Commands.START, is_group):
                send_reply(START_MESSAGE.replace('*', ''))
                return jsonify({'status': 'command_start'}), 200
            
            if is_command_match(text, Commands.HELP, is_group):
                send_reply(HELP_MESSAGE.replace('*', ''))
                return jsonify({'status': 'command_help'}), 200
            
            if is_command_match(text, Commands.SALDO, is_group):
                try:
                    balances = get_wallet_balances()
                    msg = "💰 SALDO DOMPET\n\n"
                    for dompet, info in balances.items():
                        msg += f"📊 {dompet}\n"
                        msg += f"   Masuk: Rp {info['pemasukan']:,}\n".replace(',', '.')
                        msg += f"   Keluar: Rp {info['pengeluaran']:,}\n".replace(',', '.')
                        msg += f"   Saldo: Rp {info['saldo']:,}\n\n".replace(',', '.')
                    send_reply(msg)
                    return jsonify({'status': 'command_saldo'}), 200
                except Exception as e:
                    send_reply(f"❌ Error: {str(e)}")
                    return jsonify({'status': 'error'}), 200
    
            if is_command_match(text, Commands.STATUS, is_group):
                try:
                    dashboard = get_dashboard_summary()
                    msg = format_dashboard_message(dashboard)
                    send_reply(msg.replace('*', ''))
                    return jsonify({'status': 'command_status'}), 200
                except Exception as e:
                    send_reply(f"❌ Error: {str(e)}")
                    return jsonify({'status': 'error'}), 200
    
    # ========================================
    # NEW: /tanya Command - AI Query dengan Real Data
    # ========================================
            if text.startswith('/tanya '):
                query = text.replace('/tanya ', '').strip()
                
                if not query:
                    send_reply("💡 Contoh: /tanya cek keuangan hari ini")
                    return jsonify({'status': 'command_tanya_empty'}), 200
                
                try:
                    from handlers.query_handler import handle_query_command
                    
                    # Send "analyzing" message first
                    mention = format_mention(sender_name, is_group)
                    send_reply(f"{mention}🤔 Menganalisis data...")
                    
                    # Get answer with real data
                    answer = handle_query_command(query, sender_number, chat_jid)
                    
                    # Send answer
                    response = f"{mention}{answer}"
                    send_reply(response)
                    
                    return jsonify({'status': 'command_tanya_success'}), 200
                    
                except Exception as e:
                    # secure_assert logger is not defined in this scope locally, using secure_log if available or just print
                    secure_log("ERROR", f"/tanya command failed: {e}") 
                    send_reply(f"❌ Maaf, terjadi kesalahan saat menganalisis data.")
                    return jsonify({'status': 'command_tanya_error'}), 200
        
        # Initialize category scope and intent variables (prevent UnboundLocalError)
        layer_category_scope = 'UNKNOWN'
        intent = 'UNKNOWN'
        action = 'IGNORE'
        is_reply_to_bot = False
        
        if has_pending:
            # Bypass AI if pending active to reach state machine below
            pass 
        else:
            # ==== Context Enhancement: Combine with last message if applicable ====
            last_message = get_user_last_message(sender_number, chat_jid, max_age_seconds=60)

            if last_message:
                # Check if current message is just an amount
                if has_amount_pattern(text) and len(text.strip()) < 20:
                    # Likely continuing previous message
                    # Combine context
                    combined_text = f"{last_message} {text}"
                    secure_log("INFO", f"Combined with last message: {combined_text}")
                    text = combined_text
                    # Clear buffer after use
                    clear_user_last_message(sender_number, chat_jid)

            # Store current message for next time
            store_user_message(sender_number, chat_jid, text)

            # Smart Handler (AI Layer)
            if USE_LAYERS:
                # Use the initialized smart_handler instance
                # It returns a dict with action, intent, normalized_text, etc.
                smart_result = smart_handler.process(
                    text=text,
                    chat_jid=chat_jid,
                    sender_number=sender_number,
                    reply_message_id=quoted_msg_id,
                    has_media=(input_type == 'image' or media_url is not None),
                    sender_name=sender_name,
                    quoted_message_text=quoted_message_text,
                    has_visual=has_visual
                )
                
                action = smart_result.get('action', 'IGNORE')
                resp = smart_result.get('response') # For REPLY
                intent = smart_result.get('intent', 'UNKNOWN')
                
                # Store extra data
                layer_category_scope = smart_result.get('category_scope', 'UNKNOWN')
                if intent == "RECORD_TRANSACTION":
                     # In case smart_handler cleaned the text (e.g. from extracted data)
                     if smart_result.get('normalized_text'):
                         text = smart_result.get('normalized_text')
 
                if action == "IGNORE": return jsonify({'status': 'ignored'}), 200
                if action == "REPLY": 
                    send_reply(resp)
                    return jsonify({'status': 'replied'}), 200
                if action == "PROCESS":
                    if intent == "QUERY_STATUS":
                        send_reply("🤔 Menganalisis...")
                        try:
                            # Use the standardized search query from smart handler if available
                            query_text = smart_result.get('layer_response', text)
                            ctx = format_data_for_ai(days=30)
                            ans = query_data(query_text, ctx)
                            send_reply(ans.replace('*',''))
                            return jsonify({'status': 'queried'}), 200
                        except: pass
                    
                    # ========================================
                    # STEP 2: HANDLE SPECIAL INTENTS
                    # ========================================
                    
                    if intent == "TRANSFER_FUNDS":
                        # Force logic for Transfer/Saldo logic
                        if smart_result.get('layer_response'):
                             text = smart_result.get('layer_response')
                        
                        layer_category_scope = "TRANSFER" 
                        pass 
 
                    if intent == "RECORD_TRANSACTION":
                        # Logic continues to Step 8 (Extraction) with refined text/scope
                        
                        # PRE-EMPTIVE CONFIRMATION FOR AMBIGUOUS SCOPE
                        # If AI is unsure (AMBIGUOUS) or UNKNOWN, ask user before extraction/saving
                        if layer_category_scope in ['UNKNOWN', 'AMBIGUOUS']:
                            # Extract temporarily to show context
                            temp_txs = extract_financial_data(text, input_type, sender_name, [media_url] if media_url else None, text if input_type=='image' else None)
                            
                            if temp_txs:
                                # REMOVED local import of format_mention to fix UnboundLocalError
                                set_pending_confirmation(
                                    user_id=sender_number,
                                    chat_id=chat_jid,
                                    data={
                                        'type': 'category_scope',
                                        'transactions': temp_txs,
                                        'raw_text': text,
                                        'original_message_id': message_id
                                    }
                                )
                                
                                mention = format_mention(sender_name, is_group)
                                response = f"""{mention}🤔 Ini untuk Operational Kantor atau Project?
 
 1️⃣ Operational Kantor
    (Gaji staff, listrik, wifi, ATK, dll)
 
 2️⃣ Project  
    (Material, upah tukang, transport ke site)
 
 Balas 1 atau 2"""
                                send_reply(response)
                                return jsonify({'status': 'asking_scope'}), 200
            
            # Check visual link
            if input_type == 'text':
                buf = get_visual_buffer(sender_number, chat_jid)
                if buf:
                    # Handle both list and dict format from buffer
                    if isinstance(buf, list): media_url = buf[0].get('media_url')
                    else: media_url = buf.get('media_url')
                    
                    input_type = 'image'
                    clear_visual_buffer(sender_number, chat_jid)
 
        # 5. REVISION HANDLER (New)
        if quoted_msg_id or is_command_match(text, Commands.UNDO, is_group) or is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
            from handlers.revision_handler import handle_revision_command, handle_undo_command
            
            revision_result = None
            
            # Check for standard commands
            if is_command_match(text, Commands.UNDO, is_group):
                 revision_result = handle_undo_command(sender_number, chat_jid)
            
            # Check for /revisi command or reply revision
            elif quoted_msg_id or is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
                 revision_result = handle_revision_command(sender_number, chat_jid, text, quoted_msg_id)
 
            if revision_result:
                if revision_result.get('action') == 'REPLY':
                    send_reply(revision_result.get('response'))
                    return jsonify({'status': 'handled_revision'}), 200
 
        # 6. PENDING STATE MACHINE
        if has_pending:
            pending = pending_data
            ptype = pending.get('pending_type')
            
            # NEW: Merge concurrent transactions (e.g. multiple images)
            # If user sends another image/transaction while one is pending, ADD to it.
            # NEW: Merge concurrent transactions (e.g. multiple images)
            # If user sends another image/transaction while one is pending, ADD to it.
            # Support Text Merge (heuristic: has digits) when AI is bypassed (intent=UNKNOWN)
            is_potential_text_tx = (intent == 'UNKNOWN' and text and re.search(r'\d', text))
            
            if input_type == 'image' or (intent == 'RECORD_TRANSACTION' and not is_reply_to_bot) or is_potential_text_tx:
                new_txs = extract_financial_data(text, input_type, sender_name, [media_url] if media_url else None, text if input_type=='image' else None)
                
                if new_txs:
                    send_reply("➕ Menambahkan ke antrian transaksi...")
                    # Merge with existing
                    pending['transactions'].extend(new_txs)
                    
                    # Deduplicate based on exact content to avoid double-processing same webhook
                    # Simple hash check on amount + desc
                    unique = {f"{t['jumlah']}_{t['keterangan']}": t for t in pending['transactions']}.values()
                    pending['transactions'] = list(unique)
                    
                    # Update pending state
                    state_manager.set_pending_transaction(pending_key, pending)
                    
                    # Re-send updated prompt
                    reply = build_selection_prompt(pending['transactions'])
                    if is_group: reply += "\n\n↩️ Reply angka 1-4"
                    send_reply(reply)
                    return jsonify({'status': 'merged'}), 200
                
                # If image provided no transaction data during pending state, IGNORE it.
                # Don't let it fall through to 'selection' validation which would error.
                if input_type == 'image':
                    return jsonify({'status': 'ignored_image'}), 200

            # Cancel
            if is_command_match(text, Commands.CANCEL, is_group):
                _pending_transactions.pop(pending_pkey, None)
                send_reply(UserErrors.CANCELLED)
                return jsonify({'status': 'cancelled'}), 200
                
            # A. Select Source Wallet (Operational)
            if ptype == 'select_source_wallet':
                try:
                    sel = int(text.strip())
                    opt = get_wallet_selection_by_idx(sel)
                    if not opt: raise ValueError()
                    
                    pending['selected_source_wallet'] = opt['dompet']
                    return finalize_transaction_workflow(pending, pending_pkey)
                except:
                    send_reply("❌ Pilih angka 1-3.")
                    return jsonify({'status': 'invalid'}), 200
            
            # B. Project Confirmation (Existing - Ambiguous Name)
            if ptype == 'confirmation_project':
                clean = text.lower().strip()
                final_proj = ""
                
                if clean in ['ya', 'y', 'ok', 'siap']:
                    final_proj = pending.get('suggested_project')
                    send_reply(f"✅ Oke, masuk ke **{final_proj}**.")
                elif clean in ['tidak', 'no', 'bukan']:
                    send_reply("Nama projeknya apa?")
                    pending['pending_type'] = 'needs_project'
                    return jsonify({'status': 'asking'}), 200
                else:
                    # Direct correction
                    final_proj = sanitize_input(text.strip())
                    if len(final_proj) < 3:
                        send_reply("⚠️ Nama terlalu pendek.")
                        return jsonify({'status': 'invalid'}), 200
                    add_new_project_to_cache(final_proj)
                    send_reply(f"👌 Project baru: **{final_proj}**")
                
                # Update transactions
                for t in pending['transactions']:
                    t['nama_projek'] = final_proj
                    t.pop('needs_project', None)
                
                # Set confirmed to true so we don't ask again
                pending['project_confirmed'] = True
                return finalize_transaction_workflow(pending, pending_pkey)

            # G. New Project Confirmation (NEW -> Create or Rename)
            if ptype == 'confirmation_new_project':
                clean = text.lower().strip()
                if clean in ['ya', 'y', 'ok', 'siap', 'buat', 'lanjut']:
                    # User confirmed it is new
                    pending['project_confirmed'] = True
                    pending['is_new_project'] = True  # Flag for lifecycle marker
                    # Delayed cache update until save success
                    return finalize_transaction_workflow(pending, pending_pkey)
                    
                elif clean in ['tidak', 'no', 'ganti', 'bukan', 'salah']:
                    send_reply("Nama projeknya apa?")
                    pending['pending_type'] = 'needs_project' 
                    return jsonify({'status': 'asking'}), 200
                else:
                    # Treat input as the CORRECT name (and implicitly NEW if not resolved previously)
                    final_proj = sanitize_input(text.strip())
                    # Check if actually exists now
                    res_check = resolve_project_name(final_proj)
                    if res_check['status'] == 'NEW':
                         pending['is_new_project'] = True
                    
                    send_reply(f"👌 Update ke: **{final_proj}**")
                    for t in pending['transactions']: t['nama_projek'] = final_proj
                    pending['project_confirmed'] = True
                    return finalize_transaction_workflow(pending, pending_pkey)
                
            # C. Needs Project
            if ptype == 'needs_project':
                proj = sanitize_input(text.strip())
                res = resolve_project_name(proj)
                
                if res['status'] == 'AMBIGUOUS':
                    pending['pending_type'] = 'confirmation_project'
                    pending['suggested_project'] = res['final_name']
                    send_reply(f"🤔 Maksudnya **{res['final_name']}**?\n✅ Ya / ❌ Bukan")
                    return jsonify({'status': 'confirm'}), 200
                
                final = res['final_name']
                for t in pending['transactions']: t['nama_projek'] = final
                # Set confirmed to true
                pending['project_confirmed'] = True
                return finalize_transaction_workflow(pending, pending_pkey)
                
            # D. Company Selection
            if ptype == 'selection':
                valid, sel, err = parse_selection(text)
                if not valid:
                    send_reply(f"❌ {err}")
                    return jsonify({'status': 'invalid'}), 200
                
                opt = get_selection_by_idx(sel)
                if not opt:
                    send_reply("❌ Pilihan tidak valid (System Error).")
                    return jsonify({'status': 'error_opt'}), 200
                    
                pending['selected_option'] = opt
                for t in pending['transactions']: t['company'] = opt['company']
                
                return finalize_transaction_workflow(pending, pending_pkey)
            
            # E. Duplicate Confirm
            if ptype == 'confirmation_dupe':
                if text.lower().strip() == 'y':
                    opt = pending.get('selected_option')
                    if not opt:
                         _pending_transactions.pop(pending_pkey, None)
                         send_reply("❌ Error state. Transaksi dibatalkan.")
                         return jsonify({'status': 'error_state'}), 200

                    # Manual save
                    res = append_transactions(pending['transactions'], pending['sender_name'], 
                                            pending['source'], opt['dompet'], opt['company'])
                    if res['success']:
                        _pending_transactions.pop(pending_pkey, None)
                        send_reply("✅ Disimpan (Duplikat).")
                    return jsonify({'status': 'saved_dupe'}), 200
                    _pending_transactions.pop(pending_pkey, None)
                    send_reply("❌ Dibatalkan.")
                    return jsonify({'status': 'cancelled'}), 200

            # F. Undo Confirmation
            if ptype == 'undo_confirmation':
                if text.lower().strip() in ['1', 'ya', 'yes', 'hapus']:
                    from handlers.revision_handler import process_undo_deletion
                    
                    result = process_undo_deletion(pending.get('transactions', []))
                    
                    _pending_transactions.pop(pending_pkey, None)
                    send_reply(result.get('response'))
                    return jsonify({'status': 'undo_completed'}), 200
                else:
                    _pending_transactions.pop(pending_pkey, None)
                    send_reply("❌ Batal hapus.")
                    return jsonify({'status': 'undo_cancelled'}), 200

        # 7. COMMANDS (PRIORITY - Execute BEFORE layer processing)
        # This ensures /start, /help, etc. work properly instead of triggering layers
        if is_command_match(text, Commands.START, is_group):
            send_reply(START_MESSAGE.replace('*', ''))
            return jsonify({'status': 'command_start'}), 200
        
        if is_command_match(text, Commands.HELP, is_group):
            send_reply(HELP_MESSAGE.replace('*', ''))
            return jsonify({'status': 'command_help'}), 200
        
        if is_command_match(text, Commands.SALDO, is_group):
            try:
                balances = get_wallet_balances()
                msg = "💰 *SALDO DOMPET*\n\n"
                for dompet, info in balances.items():
                    msg += f"📊 {dompet}\n"
                    msg += f"   Masuk: Rp {info['pemasukan']:,}\n"
                    msg += f"   Keluar: Rp {info['pengeluaran']:,}\n"
                    msg += f"   Saldo: Rp {info['saldo']:,}\n\n"
                send_reply(msg.replace(',', '.').replace('*', ''))
                return jsonify({'status': 'command_saldo'}), 200
            except Exception as e:
                send_reply(f"❌ Error: {str(e)}")
                return jsonify({'status': 'error'}), 200
        
        if is_command_match(text, Commands.STATUS, is_group):
            try:
                dashboard = get_dashboard_summary()
                msg = format_dashboard_message(dashboard)
                send_reply(msg.replace('*', ''))
                return jsonify({'status': 'command_status'}), 200
            except Exception as e:
                send_reply(f"❌ Error: {str(e)}")
                return jsonify({'status': 'error'}), 200

        # 8. PROCESS NEW INPUT (AI)
        transactions = []
        try:
            send_reply("🔍 Scan...")
            
            final_media = [media_url] if media_url else []
            transactions = extract_financial_data(text, input_type, sender_name, final_media, text if input_type=='image' else None)
            
            if not transactions:
                if input_type == 'image': send_reply("❓ Tidak terbaca.")
                return jsonify({'status': 'no_tx'}), 200
            
            # Setup New Pending State
            _pending_transactions[sender_pkey] = {
                'transactions': transactions,
                'sender_name': sender_name,
                'source': "WhatsApp",
                'created_at': datetime.now(),
                'message_id': message_id,
                'chat_jid': chat_jid,
                'requires_reply': is_group,
                'original_text': text, # Important for Smart Router
                'prompt_message_ids': [],
                'category_scope': layer_category_scope,  # From AI layer (initialized earlier)
            }
            
            # Check for Needs Project (Manual override from AI)
            if layer_category_scope == 'TRANSFER':
                # Force "Saldo Umum" for transfers
                for t in transactions:
                    t['nama_projek'] = 'Saldo Umum'
                    t['company'] = 'UMUM'
                    t['needs_project'] = False
            
            elif any(t.get('needs_project') for t in transactions):
                # Only if NOT operational
                ctx = detect_transaction_context(text, transactions, layer_category_scope)
                if ctx['mode'] == 'PROJECT':
                    _pending_transactions[sender_pkey]['pending_type'] = 'needs_project'
                    send_reply("❓ Nama projeknya apa?")
                    return jsonify({'status': 'asking_project'}), 200

            # Intercept Smart Project Check
            # ... (Existing logic for ambiguous project check) ...
            
            return finalize_transaction_workflow(_pending_transactions[sender_pkey], sender_pkey)
            
        except Exception as e:
            secure_log("ERROR", f"AI Proc Error: {e}")
            send_reply("❌ Error sistem.")
            return jsonify({'status': 'error'}), 200

    except Exception as e:
        secure_log("ERROR", f"Flow Error: {e}")
        return jsonify({'status': 'error'}), 500

def run_retry_service():
    """Background loop to process retry queue."""
    import time
    from sheets_helper import append_transaction
    
    def retry_handler(transaction, metadata):
        try:
            res = append_transaction(
                transaction=transaction,
                sender_name=metadata.get('sender_name', 'System'),
                source=metadata.get('source', 'Retry'),
                dompet_sheet=metadata.get('dompet_sheet'),
                company=metadata.get('company'),
                nama_projek=metadata.get('nama_projek'),
                allow_queue=False
            )
            return res > 0
        except Exception as e:
            secure_log("ERROR", f"Retry handler failed: {e}")
            return False

    while True:
        try:
            processed = process_retry_queue(retry_handler)
            time.sleep(10 if processed > 0 else 60)
        except Exception as e:
            secure_log("ERROR", f"Retry service crashed: {e}")
            time.sleep(60)

if __name__ == '__main__':
    retry_thread = threading.Thread(target=run_retry_service, daemon=True)
    retry_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)