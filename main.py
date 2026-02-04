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
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===================== GLOBAL IMPORTS =====================
# AI & Data Processing
from ai_helper import extract_financial_data, RateLimitException

# Google Sheets Integration
from sheets_helper import (
    append_transactions, append_transaction, 
    format_dashboard_message, get_dashboard_summary,
    get_wallet_balances,
    invalidate_dashboard_cache,
    DOMPET_SHEETS, DOMPET_COMPANIES, SELECTION_OPTIONS,
    get_selection_by_idx, get_dompet_for_company,
    check_duplicate_transaction,
    # New Split Layout Functions
    append_project_transaction,
    append_operational_transaction,
    get_all_data,
)

# Services
from services.retry_service import process_retry_queue
from services.project_service import resolve_project_name, add_new_project_to_cache
from services.state_manager import (
    pending_key, pending_is_expired,
    is_message_duplicate, clear_message_duplicate, store_bot_message_ref,
    store_pending_message_ref,
    get_pending_key_from_message,
    store_visual_buffer, get_visual_buffer,
    clear_visual_buffer, has_visual_buffer,
    store_last_bot_report,
    # New Pending Confirmations
    get_pending_confirmation, set_pending_confirmation,
    find_pending_confirmation_in_chat,
    store_user_message, get_user_last_message, clear_user_last_message,
    get_project_lock
)

# Layer Integration - Superseded by SmartHandler
# from layer_integration_v2 import process_with_layers, USE_ENHANCED_LAYERS as USE_LAYERS
USE_LAYERS = True # Enable SmartHandler logic by default

# Utilities
from wuzapi_helper import (
    send_wuzapi_reply, format_mention_body,
    get_clean_jid, download_wuzapi_media,
    download_wuzapi_image, send_wuzapi_document
)
from security import (
    sanitize_input, detect_prompt_injection,
    rate_limit_check, secure_log,
    SecurityError, RateLimitError,
    ALLOWED_CATEGORIES, now_wib,
)
try:
    from pdf_report import generate_pdf_from_input, PDFNoDataError
except ImportError:
    from pdf_report import generate_pdf_from_input

    class PDFNoDataError(Exception):
        def __init__(self, period: str = "periode tersebut"):
            self.period = period
            super().__init__(f"No data for period: {period}")
from utils.parsers import (
    parse_selection, parse_revision_amount,
    should_respond_in_group, is_command_match,
    is_prefix_match, GROUP_TRIGGERS, PENDING_TTL_SECONDS,
)
from utils.formatters import (
    format_success_reply, format_success_reply_new,
    format_draft_summary_operational, format_draft_summary_project,
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
    apply_company_prefix,
    strip_company_prefix,
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


def get_telegram_file_url(file_id: str) -> Optional[str]:
    """Resolve a Telegram file_id to a downloadable URL."""
    try:
        api_url = get_telegram_api_url()
        if not api_url or not file_id:
            return None

        session = get_telegram_session()
        response = session.get(
            f"{api_url}/getFile",
            params={'file_id': file_id},
            timeout=10
        )
        if response.status_code != 200:
            secure_log("ERROR", f"Telegram getFile failed: {response.status_code}")
            return None

        payload = response.json()
        file_path = payload.get('result', {}).get('file_path')
        if not file_path:
            return None

        return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    except Exception as e:
        secure_log("ERROR", f"Telegram getFile exception: {type(e).__name__}: {e}")
        return None


def send_telegram_document(chat_id: int, file_path: str, caption: str = None) -> Optional[Dict]:
    """Send a document to Telegram."""
    try:
        api_url = get_telegram_api_url()
        if not api_url or not file_path:
            return None

        session = get_telegram_session()
        with open(file_path, "rb") as f:
            response = session.post(
                f"{api_url}/sendDocument",
                data={'chat_id': chat_id, 'caption': caption or ''},
                files={'document': f},
                timeout=30
            )
        return response.json()
    except Exception as e:
        secure_log("ERROR", f"Telegram sendDocument failed: {type(e).__name__}: {e}")
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

from utils.amounts import has_amount_pattern


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
    has_project_word = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
    has_kantor_word = bool(re.search(r"\b(kantor|office|operasional|operational|ops)\b", text_lower))
    
    # NEW v2.0: Trust AI's category_scope if available
    if category_scope == 'OPERATIONAL':
        # Detect which operational category
        detected_keywords = [kw for kw in OPERATIONAL_KEYWORDS if kw in text_lower]
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    
    if category_scope == 'PROJECT':
        # AI is confident this is project-related
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    
    if category_scope == 'AMBIGUOUS':
        return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}

    # Pre-compute operational keywords for quick routing
    detected_keywords = []
    for kw in OPERATIONAL_KEYWORDS:
        # Use word boundary matching for better accuracy
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            detected_keywords.append(kw)

    # Conflict: prioritize "kantor/operasional" over project keyword
    if has_kantor_word:
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    
    # Fallback: Rule-based detection (when AI uncertain or not used)
    
    # Check Keywords with better matching (already computed above)
    
    # Ambiguous keyword detection (e.g., gaji/fee/cicilan)
    try:
        from utils.context_detector import AMBIGUOUS_KEYWORDS as _AMBIGUOUS
        ambiguous_keywords = set(_AMBIGUOUS.keys())
    except Exception:
        ambiguous_keywords = set()
    matched_ambiguous = [
        k for k in ambiguous_keywords
        if re.search(r'\b' + re.escape(k) + r'\b', text_lower)
    ]
    has_ambiguous_keyword = bool(matched_ambiguous)
    generic_ambiguous = {'bayar'}
    has_generic_ambiguous_only = bool(matched_ambiguous) and all(
        k in generic_ambiguous for k in matched_ambiguous
    )

    # Role-based bias (office vs field roles)
    office_roles = set()
    field_roles = set()
    try:
        from utils.context_detector import OFFICE_ROLES as _OFFICE, FIELD_ROLES as _FIELD
        office_roles = set(_OFFICE)
        field_roles = set(_FIELD)
    except Exception:
        office_roles = set()
        field_roles = set()

    has_office_role = any(re.search(r'\b' + re.escape(r) + r'\b', text_lower) for r in office_roles)
    has_field_role = any(re.search(r'\b' + re.escape(r) + r'\b', text_lower) for r in field_roles)
    
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
    detected_ambiguous = [kw for kw in detected_keywords if kw in ambiguous_keywords]
    all_ambiguous = bool(detected_keywords) and len(detected_ambiguous) == len(detected_keywords)
    
    # Explicit bias: "kantor" or "project" keywords should win
    if has_project_word and not has_kantor_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    if has_office_role and not has_project_word:
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    if has_field_role and not has_kantor_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}

    # Priority 1: Keywords found AND NO valid project
    if detected_keywords and not has_valid_project:
        # If all keywords are ambiguous, ask user
        if all_ambiguous or (has_ambiguous_keyword and not has_generic_ambiguous_only):
            return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}
        category = map_operational_category(detected_keywords[0])
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}

    # Priority 2: Has valid project name -> PROJECT
    if has_valid_project:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False, 'project_name': valid_project_name}
    
    # Priority 3: Has keywords (but maybe ambiguous)
    if detected_keywords:
        if all_ambiguous or (has_ambiguous_keyword and not has_generic_ambiguous_only):
            return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}
        category = map_operational_category(detected_keywords[0])
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    
    # If ambiguous keyword exists without project context, ask user
    if has_ambiguous_keyword and not has_valid_project:
        return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}

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
        local_media_path = None
        quoted_msg_id = ''
        
        # FILTER: Only process actual messages (text or media)
        msg_type = info.get('Type', '')
        if not msg_type:
            secure_log("INFO", f"Webhook: Missing message type (info.Type empty). Info keys: {list(info.keys())}")
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
                # Fallback: try download via WuzAPI
                try:
                    local_media_path = download_wuzapi_image(info.get('ID'), chat_jid)
                except Exception:
                    local_media_path = None
            secure_log(
                "INFO",
                f"Webhook: Image message received (caption_len={len(text or '')}, "
                f"base64={'yes' if event_data.get('base64') else 'no'}, "
                f"download={'yes' if local_media_path else 'no'})"
            )

        # Ignore empty text payloads (avoid typing/presence noise)
        if msg_type == 'text' and not (text or '').strip():
            secure_log("INFO", f"Webhook: Empty text ignored from {sender_number}")
            return jsonify({'status': 'empty_text'}), 200

        # LOG THE INCOMING MESSAGE
        secure_log("INFO", f"Webhook: Msg from {sender_number} (Group: {is_group}): {text[:50]}...")

        # Quoted info
        ctx_info = message_obj.get('extendedTextMessage', {}).get('contextInfo', {}) or \
                   message_obj.get('contextInfo', {})
        if ctx_info:
            quoted_msg_id = ctx_info.get('stanzaId')

        # 6. Deduplication (allow upgrade for richer payloads)
        message_id = info.get('ID', '')
        dedup_score = 0
        if text and text.strip():
            dedup_score += min(len(text.strip()), 200)
        if input_type == 'image':
            if local_media_path or media_url or event_data.get('base64'):
                dedup_score += 1000
        if is_message_duplicate(message_id, score=dedup_score, allow_upgrade=True):
            secure_log("INFO", f"Webhook: Duplicate message {message_id} ignored")
            return jsonify({'status': 'duplicate'}), 200

        # 7. Process
        return process_wuzapi_message(
            sender_number, info.get('PushName', 'User'), text,
            input_type, media_url, local_media_path, quoted_msg_id, message_id,
            is_group, chat_jid, sender_alt
        )

    except Exception as e:
        secure_log("ERROR", f"Webhook Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500


# ===================== TELEGRAM HANDLER =====================

@app.route('/telegram', methods=['POST'])
def webhook_telegram():
    try:
        update = request.get_json(silent=True) or {}
        message = update.get('message') or update.get('edited_message')
        if not message:
            return jsonify({'status': 'no_message'}), 200

        sender = message.get('from', {})
        if sender.get('is_bot'):
            return jsonify({'status': 'own_message'}), 200

        chat = message.get('chat', {})
        chat_id = chat.get('id')
        if chat_id is None:
            return jsonify({'status': 'no_chat'}), 200

        chat_type = chat.get('type', 'private')
        is_group = chat_type in ('group', 'supergroup')

        sender_id = sender.get('id')
        sender_name = " ".join(filter(None, [sender.get('first_name'), sender.get('last_name')])).strip()
        if not sender_name:
            sender_name = sender.get('username', 'User')
        sender_number = str(sender_id) if sender_id is not None else sender.get('username', '')
        sender_username = sender.get('username')

        if not is_sender_allowed([sender_number, sender_username, sender_name]):
            secure_log("WARNING", f"Telegram: Access denied for {sender_number}")
            send_telegram_reply(chat_id, "❌ Akses Ditolak. Hubungi Admin.")
            return jsonify({'status': 'forbidden'}), 200

        text = message.get('text') or ''
        input_type = 'text'
        media_url = None

        if message.get('photo'):
            photo = message['photo'][-1]
            file_id = photo.get('file_id')
            media_url = get_telegram_file_url(file_id)
            input_type = 'image'
            if not text:
                text = message.get('caption', '') or ''

        quoted_msg_id = None
        quoted_message_text = None
        reply_msg = message.get('reply_to_message')
        if reply_msg:
            reply_message_id = reply_msg.get('message_id')
            if reply_message_id is not None:
                quoted_msg_id = f"tg:{chat_id}:{reply_message_id}"
            quoted_message_text = reply_msg.get('text') or reply_msg.get('caption')

        message_id = message.get('message_id')
        if message_id is not None:
            message_key = f"tg:{chat_id}:{message_id}"
        else:
            message_key = f"tg:{chat_id}:{update.get('update_id', '')}"

        if is_message_duplicate(message_key):
            secure_log("INFO", f"Telegram: Duplicate message {message_key} ignored")
            return jsonify({'status': 'duplicate'}), 200

        def send_reply(body: str, mention: bool = True):
            return send_telegram_reply(chat_id, body)

        return process_incoming_message(
            sender_number=sender_number,
            sender_name=sender_name,
            text=text,
            input_type=input_type,
            media_url=media_url,
            quoted_msg_id=quoted_msg_id,
            message_id=message_key,
            is_group=is_group,
            chat_jid=str(chat_id),
            sender_jid=None,
            quoted_message_text=quoted_message_text,
            send_reply=send_reply,
            send_document=send_telegram_document,
            source_label='Telegram',
            reply_to=chat_id,
        )
    except Exception as e:
        secure_log("ERROR", f"Telegram Webhook Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500


def process_wuzapi_message(sender_number: str, sender_name: str, text: str, 
                           input_type: str = 'text', media_url: str = None,
                           local_media_path: str = None,
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

        return process_incoming_message(
            sender_number=sender_number,
            sender_name=sender_name,
            text=text,
            input_type=input_type,
            media_url=media_url,
            local_media_path=local_media_path,
            quoted_msg_id=quoted_msg_id,
            message_id=message_id,
            is_group=is_group,
            chat_jid=chat_jid,
            sender_jid=sender_jid,
            quoted_message_text=quoted_message_text,
            send_reply=send_reply,
            send_document=send_wuzapi_document,
            source_label='WhatsApp',
            reply_to=reply_to,
        )
    except Exception as e:
        secure_log("ERROR", f"WuzAPI processing failed: {type(e).__name__}: {e}")
        return jsonify({'status': 'error'}), 500


def process_incoming_message(sender_number: str, sender_name: str, text: str, 
                             input_type: str = 'text', media_url: str = None,
                             local_media_path: str = None,
                             quoted_msg_id: str = None, message_id: str = None,
                             is_group: bool = False, chat_jid: str = None,
                             sender_jid: str = None, quoted_message_text: str = None,
                             send_reply=None, send_document=None,
                             source_label: str = 'WhatsApp', reply_to=None):
    try:
        # --- Helper: State Management ---
        def extract_bot_msg_id(sent):
            if not sent or not isinstance(sent, dict): return None
            return (sent.get('data', {}).get('Id') or sent.get('id') or sent.get('ID'))

        def cache_prompt(pkey, pending, sent):
            bid = extract_bot_msg_id(sent)
            if bid:
                store_pending_message_ref(bid, pkey)
                pending.setdefault('prompt_message_ids', []).append(str(bid))
        
        def build_extraction_inputs(current_text: str, current_input_type: str,
                                    current_media_url: str, current_media_path: str):
            """Prepare input_data/media list/caption for extract_financial_data."""
            if current_input_type == 'image' and current_media_path:
                # Local file path, pass as input_data and no media URLs
                return current_media_path, None, current_text
            media_list = [current_media_url] if current_media_url else None
            caption = current_text if current_input_type == 'image' else None
            return current_text, media_list, caption

        def safe_extract(input_data: str, in_type: str, sender: str, media_list=None, caption=None):
            """Extract financial data with graceful AI rate-limit handling."""
            try:
                return extract_financial_data(input_data, in_type, sender, media_list, caption)
            except RateLimitException as e:
                wait = getattr(e, "wait_time", "beberapa saat")
                send_reply(f"⚠️ AI sedang sibuk (limit). Coba lagi dalam {wait}.")
                return None

        def is_explicit_bot_call(msg: str) -> bool:
            if not msg:
                return False
            t = msg.strip().lower()
            if t.startswith('/catat') or t.startswith('+catat') or t.startswith('+bot'):
                return True
            if re.match(r'^catat\b', t):
                return True
            if t.startswith('bot') or '@bot' in t:
                return True
            return False

        # Event envelope
        event_id = str(message_id) if message_id else f"evt_{uuid.uuid4().hex[:12]}"

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

            # If still ambiguous, ask user to choose scope
            if context.get('mode') == 'AMBIGUOUS':
                set_pending_confirmation(
                    user_id=pending.get('sender_number', sender_number),
                    chat_id=pending.get('chat_jid', chat_jid),
                    data={
                        'type': 'category_scope',
                        'transactions': txs,
                        'raw_text': original_text,
                        'original_message_id': pending.get('message_id')
                    }
                )
                mention = format_mention(pending.get('sender_name', sender_name), is_group)
                response = f"""{mention}🤔 Ini untuk Operational Kantor atau Project?

1️⃣ Operational Kantor
   (Gaji staff, listrik, wifi, ATK, dll)

2️⃣ Project
   (Material, upah tukang, transport ke site)

Balas 1 atau 2"""
                send_reply(response)
                return jsonify({'status': 'asking_scope'}), 200

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
                # Step 2: Draft → Confirm → Commit
                set_pending_confirmation(
                    user_id=sender_number,
                    chat_id=chat_jid,
                    data={
                        'type': 'confirm_commit_operational',
                        'transactions': txs,
                        'source_wallet': source_wallet,
                        'category': context['category'],
                        'sender_name': pending.get('sender_name'),
                        'source': pending.get('source'),
                        'original_message_id': pending.get('message_id'),
                        'event_id': pending.get('event_id'),
                        'pending_key': pkey
                    }
                )
                mention = format_mention(pending.get('sender_name', sender_name), is_group)
                draft_msg = format_draft_summary_operational(
                    txs, source_wallet, context.get('category'), mention
                )
                send_reply(draft_msg)
                return jsonify({'status': 'draft_operational'}), 200

            # === JALUR 2: PROJECT (Standard) ===
            
            # --- VALIDATION: CHECK PROJECT EXISTENCE ---
            # Checks if project exists in Spreadsheet/Cache before proceeding
            if not pending.get('project_validated'):
                for t in txs:
                    p_name_raw = t.get('nama_projek')
                    # Skip validation for "Saldo Umum", empty, or "Umum"
                    if not p_name_raw or p_name_raw.lower() in ['saldo umum', 'umum', 'unknown']:
                        continue
                    
                    # Resolve Name
                    lookup_name = strip_company_prefix(p_name_raw)
                    res = resolve_project_name(lookup_name)
                    
                    if res['status'] == 'AMBIGUOUS':
                         pending['pending_type'] = 'confirmation_project'
                         pending['suggested_project'] = res['final_name']
                         send_reply(f"🤔 Maksudnya **{res['final_name']}**?\n✅ Ya / ❌ Bukan")
                         return jsonify({'status': 'asking_project_confirm'}), 200
                    
                    elif res['status'] == 'NEW':
                        # Validasi typo / project baru
                        pending['pending_type'] = 'confirmation_new_project'
                        pending['new_project_name'] = res['original']
                        send_reply(f"🆕 Project **{res['original']}** belum ada.\n\nBuat Project Baru?\n✅ Ya / ❌ Ganti Nama (Langsung Ketik Nama Baru)")
                        return jsonify({'status': 'asking_new_project'}), 200
                    
                    elif res['status'] in ['EXACT', 'AUTO_FIX']:
                        # Auto update to canonical name
                        t['nama_projek'] = res['final_name']
                
                # Mark as validated once all checks pass (no NEW/AMBIGUOUS trigger)
                pending['project_validated'] = True

            # 1. Resolve Company/Dompet
            detected_company = None
            for t in txs:
                if t.get('company'): 
                    detected_company = t['company']
                    break
            
            dompet = None
            detected_dompet = next((t.get('detected_dompet') for t in txs if t.get('detected_dompet')), None)
            if detected_dompet:
                from config.wallets import get_company_name_from_sheet
                dompet = detected_dompet
                detected_company = get_company_name_from_sheet(dompet)

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
                        secure_log("INFO", f"Auto-resolved project '{p_name_check}' to {found_comp}")

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

                # Project lock check (consistency across dompet)
                p_name_check = t0.get('nama_projek', '')
                if p_name_check and p_name_check.lower() not in ['saldo umum', 'operasional kantor', 'umum', 'unknown']:
                    locked_dompet = get_project_lock(p_name_check)
                    if locked_dompet and locked_dompet != dompet:
                        from config.wallets import get_company_name_from_sheet
                        locked_company = get_company_name_from_sheet(locked_dompet)
                        # Ask user to confirm locked dompet or move project
                        set_pending_confirmation(
                            user_id=sender_number,
                            chat_id=chat_jid,
                            data={
                                'type': 'project_dompet_mismatch',
                                'transactions': txs,
                                'dompet_input': dompet,
                                'company_input': detected_company,
                                'dompet_locked': locked_dompet,
                                'company_locked': locked_company,
                                'sender_name': pending.get('sender_name'),
                                'source': pending.get('source'),
                                'original_message_id': pending.get('message_id'),
                                'event_id': pending.get('event_id'),
                                'is_new_project': pending.get('is_new_project', False),
                                'pending_key': pkey
                            }
                        )
                        msg = (
                            f"⚠️ Project **{p_name_check}** sudah terdaftar di dompet **{locked_dompet}**.\n\n"
                            "Pilih tindakan:\n"
                            f"1️⃣ Gunakan dompet terdaftar ({locked_dompet})\n"
                            f"2️⃣ Pindahkan project ke dompet baru ({dompet})\n"
                            "3️⃣ Batal"
                        )
                        send_reply(msg.replace('*', ''))
                        return jsonify({'status': 'project_lock_mismatch'}), 200

                # New project but first tx is expense → confirm
                if pending.get('is_new_project'):
                    has_income = any(t.get('tipe') == 'Pemasukan' for t in txs)
                    if not has_income:
                        set_pending_confirmation(
                            user_id=sender_number,
                            chat_id=chat_jid,
                            data={
                                'type': 'new_project_first_expense',
                                'transactions': txs,
                                'dompet': dompet,
                                'company': detected_company,
                                'sender_name': pending.get('sender_name'),
                                'source': pending.get('source'),
                                'original_message_id': pending.get('message_id'),
                                'event_id': pending.get('event_id'),
                                'pending_key': pkey
                            }
                        )
                        msg = (
                            f"⚠️ Project baru **{p_name_check}** tetapi transaksi pertama *Pengeluaran*.\n"
                            "Biasanya project baru dimulai dari DP (Pemasukan).\n\n"
                            "Pilih tindakan:\n"
                            "1️⃣ Lanjutkan sebagai project baru\n"
                            "2️⃣ Ubah jadi Operasional Kantor\n"
                            "3️⃣ Batal"
                        )
                        send_reply(msg.replace('*', ''))
                        return jsonify({'status': 'new_project_first_expense'}), 200

                for t in txs:
                    pname = t.get('nama_projek')
                    if pname:
                        t['nama_projek'] = apply_company_prefix(pname, dompet, detected_company)

                # Draft → Confirm → Commit
                set_pending_confirmation(
                    user_id=sender_number,
                    chat_id=chat_jid,
                    data={
                        'type': 'confirm_commit_project',
                        'transactions': txs,
                        'dompet': dompet,
                        'company': detected_company,
                        'sender_name': pending.get('sender_name'),
                        'source': pending.get('source'),
                        'original_message_id': pending.get('message_id'),
                        'event_id': pending.get('event_id'),
                        'is_new_project': pending.get('is_new_project', False),
                        'pending_key': pkey
                    }
                )
                mention = format_mention(pending.get('sender_name', sender_name), is_group)
                draft_msg = format_draft_summary_project(
                    txs, dompet, detected_company, mention
                )
                send_reply(draft_msg)
                return jsonify({'status': 'draft_project'}), 200
            
            # 3. Ask Company if Unresolved
            pending['pending_type'] = 'selection'
            reply = build_selection_prompt(txs).replace('*', '')
            if is_group: reply += "\n\n↩️ Reply angka 1-5"
            sent = send_reply(reply)
            cache_prompt(pkey, pending, sent)
            return jsonify({'status': 'asking_company'}), 200

        # --- FLOW CONTROL ---
        
        # 1. Rate Limit
        allowed, wait = rate_limit_check(sender_number)
        if not allowed: return jsonify({'status': 'rate_limit'}), 200
        
        # 2. Visual Buffer (store all images for "catat diatas" binding)
        if input_type == 'image':
            store_visual_buffer(
                sender_number, chat_jid, media_url, message_id,
                caption=text, media_path=local_media_path
            )
        
        has_visual = has_visual_buffer(sender_number, chat_jid)
        
        # If user says "catat diatas" but no buffered image, ask to reply/attach
        if input_type == 'text':
            ref_phrase = re.search(r'\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b', (text or '').lower())
            if ref_phrase and not has_visual and not quoted_msg_id:
                send_reply("❗ Belum ada gambar/struk sebelumnya. Tolong reply struknya atau kirim ulang.")
                return jsonify({'status': 'missing_reference'}), 200

        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        from handlers.pending_handler import handle_pending_response

        pending_conf = get_pending_confirmation(sender_number, chat_jid)
        if not pending_conf and is_group and text:
            # Allow other group members to answer if only one pending confirmation exists
            t = text.strip().lower()
            is_quick_reply = (
                bool(re.fullmatch(r"\d{1,2}", t)) or
                t in ['ya', 'y', 'iya', 'ok', 'oke', 'yes', 'no', 'tidak', 'bukan',
                      'simpan', 'batal', 'cancel', '/cancel']
            )
            if is_quick_reply:
                _, pending_conf = find_pending_confirmation_in_chat(chat_jid)
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
                    sent = send_reply(result['response'])
                    # Store bot message ref for revision tracking if provided
                    if result.get('bot_ref_event_id'):
                        bid = extract_bot_msg_id(sent)
                        if bid:
                            store_bot_message_ref(bid, result.get('bot_ref_event_id'))
                            store_last_bot_report(chat_jid, bid)
                
                if result.get('completed'):
                    # Flow finished (saved or cancelled)
                    return jsonify({'status': 'handled_confirmation'}), 200
                else:
                    # Flow continues (asked next question)
                    return jsonify({'status': 'pending_interaction'}), 200

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

        # If /cancel is sent without any pending flow, clear visual buffer and stop.
        if is_command_match(text, Commands.CANCEL, is_group) and not has_pending and not pending_conf:
            clear_visual_buffer(sender_number, chat_jid)
            send_reply(UserErrors.CANCELLED)
            return jsonify({'status': 'cancelled_no_pending'}), 200

        # If user replies with a selection number but no pending is found,
        # try to resolve a single active pending in the same group chat.
        if not has_pending:
            clean_sel = (text or "").strip()
            if clean_sel.isdigit() and len(clean_sel) <= 2:
                if is_group and chat_jid:
                    candidates = []
                    for pkey, pval in _pending_transactions.items():
                        if pkey.startswith(chat_jid) and pval and not pending_is_expired(pval):
                            candidates.append((pkey, pval))
                    if len(candidates) == 1:
                        pending_pkey, pending_data = candidates[0]
                        has_pending = True
                    else:
                        send_reply("⚠️ Tidak ada pertanyaan aktif atau sesi sudah kedaluwarsa.\nBalas (reply) pesan bot yang sesuai atau kirim ulang transaksi.")
                        return jsonify({'status': 'no_pending_selection'}), 200
                else:
                    send_reply("⚠️ Tidak ada pertanyaan aktif atau sesi sudah kedaluwarsa.\nKirim ulang transaksi ya.")
                    return jsonify({'status': 'no_pending_selection'}), 200

        # Group noise gate (pre-AI): avoid processing random media/chatter
        # If user recently sent an image, allow follow-up text to bind.
        raw_text = text or ""
        explicit_catat = bool(re.match(r'^\s*\+?catat\b', raw_text, re.IGNORECASE))
        has_visual = has_visual_buffer(sender_number, chat_jid) if is_group else False
        if is_group and not has_pending:
            is_mentioned = False
            try:
                is_mentioned = is_explicit_bot_call(text)
            except Exception:
                is_mentioned = False
            should, cleaned = should_respond_in_group(
                text or "",
                is_group,
                has_media=(input_type == 'image' or media_url is not None or has_visual),
                has_pending=has_pending,
                is_mentioned=is_mentioned
            )
            if not should:
                return jsonify({'status': 'ignored_group'}), 200
            if cleaned:
                text = cleaned
        
        # 4. Filter AI Trigger
        if explicit_catat:
            text = re.sub(r'^\s*\+?catat\b', '', raw_text, flags=re.IGNORECASE).strip()
        text = sanitize_input(text or '')
        force_record = explicit_catat
        
        # ========== PRIORITY: COMMANDS FIRST (before layer processing) ==========
        if text.strip().startswith('/'):
            # /catat -> force transaction, strip command
            if text.lower().startswith('/catat'):
                force_record = True
                text = text[len('/catat'):].strip()

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
        transfer_dompet = None
        smart_result = {}
        processing_ack_sent = False
        
        if has_pending:
            # Bypass AI if pending active to reach state machine below
            pass 
        else:
            # ==== Context Enhancement: Combine with last message if applicable ====
            last_message = get_user_last_message(sender_number, chat_jid, max_age_seconds=60)

            if last_message:
                def _is_amount_only(msg: str) -> bool:
                    clean = msg.strip().lower()
                    if not clean or clean.startswith("/"):
                        return False
                    if not has_amount_pattern(clean):
                        return False
                    return bool(re.fullmatch(r"(rp|rb|ribu|k|jt|juta|m|milyar|b|bn|[0-9]|[.,\s])+", clean))

                def _should_combine_amount(prev_msg: str, cur_msg: str) -> bool:
                    if not _is_amount_only(cur_msg):
                        return False
                    prev = (prev_msg or "").strip()
                    if prev.startswith("/") and " " in prev:
                        return False
                    return True

                # Check if current message is just an amount and safe to combine
                if _should_combine_amount(last_message, text):
                    # Likely continuing previous message
                    combined_text = f"{last_message} {text}"
                    secure_log("INFO", f"Combined with last message: {combined_text}")
                    text = combined_text
                    # Clear buffer after use
                    clear_user_last_message(sender_number, chat_jid)

            # Store current message for next time
            store_user_message(sender_number, chat_jid, text)

            # Smart Handler (AI Layer)
            if USE_LAYERS:
                if force_record:
                    action = "PROCESS"
                    intent = "RECORD_TRANSACTION"
                    # Use SmartHandler for better normalization/scope, but never allow IGNORE.
                    smart_scope = None
                    try:
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
                        if smart_result.get('normalized_text'):
                            text = smart_result.get('normalized_text')
                        smart_scope = smart_result.get('category_scope')
                        if smart_scope in [None, '', 'UNKNOWN']:
                            smart_scope = None
                    except Exception:
                        smart_result = {}
                        smart_scope = None

                    # Fallback lightweight scope detection for explicit "catat"
                    if not smart_scope:
                        text_lower = (text or "").lower()
                        has_project_word = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
                        has_kantor_word = bool(re.search(r"\b(kantor|office|operasional|ops)\b", text_lower))
                        has_operational_kw = any(
                            re.search(r'\b' + re.escape(kw) + r'\b', text_lower)
                            for kw in OPERATIONAL_KEYWORDS
                        )
                        if has_kantor_word or has_operational_kw:
                            smart_scope = "OPERATIONAL"
                        elif has_project_word:
                            smart_scope = "PROJECT"
                        else:
                            smart_scope = "UNKNOWN"

                    layer_category_scope = smart_scope or "UNKNOWN"
                else:
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
                    if intent == "RECORD_TRANSACTION":
                        # Send quick ack only when explicitly addressed or private chat
                        if (force_record or (not is_group) or is_explicit_bot_call(text)) and not processing_ack_sent:
                            send_reply("⏳ Memproses...")
                            processing_ack_sent = True

                    if intent == "QUERY_STATUS":
                        send_reply("🤔 Menganalisis...")
                        try:
                            from handlers.query_handler import handle_query_command
                            query_text = smart_result.get('layer_response', text)
                            ans = handle_query_command(query_text, sender_number, chat_jid, raw_query=text)
                            send_reply(ans.replace('*', ''))
                            return jsonify({'status': 'queried'}), 200
                        except Exception as e:
                            secure_log("ERROR", f"Query handler failed: {e}")
                    
                    # ========================================
                    # STEP 2: HANDLE SPECIAL INTENTS
                    # ========================================
                    
                    if intent == "TRANSFER_FUNDS":
                        # Force logic for Transfer/Saldo logic
                        if smart_result.get('layer_response'):
                             text = smart_result.get('layer_response')
                        
                        layer_category_scope = "TRANSFER" 
                        # Try to resolve dompet directly from text to avoid extra prompts
                        from config.wallets import resolve_dompet_from_text
                        transfer_dompet = resolve_dompet_from_text(text)

                    if intent == "RECORD_TRANSACTION":
                        # Logic continues to Step 8 (Extraction) with refined text/scope
                        
                        # PRE-EMPTIVE CONFIRMATION FOR AMBIGUOUS SCOPE
                        # If AI is unsure (AMBIGUOUS) or UNKNOWN, ask user before extraction/saving
                        if layer_category_scope in ['UNKNOWN', 'AMBIGUOUS']:
                            # Extract temporarily to show context
                            inp, media_list, caption = build_extraction_inputs(
                                text, input_type, media_url, local_media_path
                            )
                            temp_txs = safe_extract(
                                inp, input_type, sender_name, media_list, caption
                            )
                            
                            if temp_txs is None:
                                return jsonify({'status': 'rate_limit'}), 200
                            if temp_txs:
                                # REMOVED local import of format_mention to fix UnboundLocalError
                                set_pending_confirmation(
                                    user_id=sender_number,
                                    chat_id=chat_jid,
                                    data={
                                        'type': 'category_scope',
                                        'transactions': temp_txs,
                                        'raw_text': text,
                                        'original_message_id': event_id,
                                        'event_id': event_id
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
                    # Only auto-bind if text looks like transaction intent
                    should_bind, _ = should_respond_in_group(
                        text or "",
                        is_group,
                        has_media=True,
                        has_pending=False,
                        is_mentioned=is_explicit_bot_call(text)
                    )
                    if should_bind:
                        # Handle both list and dict format from buffer
                        item = buf[0] if isinstance(buf, list) else buf
                        media_url = item.get('media_url')
                        local_media_path = item.get('media_path')
                        buf_caption = item.get('caption') or ''
                        
                        # If user says "catat diatas" and caption exists, use caption as text
                        ref_phrase = re.search(r'\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b', text.lower())
                        if ref_phrase and buf_caption.strip():
                            text = buf_caption.strip()
                        
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
            # Support Text Merge (heuristic: has digits) when AI is bypassed (intent=UNKNOWN)
            is_potential_text_tx = (intent == 'UNKNOWN' and text and re.search(r'\d', text))
            expects_selection_reply = ptype in {
                'selection',
                'select_source_wallet',
                'confirmation_project',
                'confirmation_new_project',
                'confirmation_dupe',
                'needs_project',
            }
            
            if not expects_selection_reply and (
                input_type == 'image'
                or (intent == 'RECORD_TRANSACTION' and not is_reply_to_bot)
                or is_potential_text_tx
            ):
                inp, media_list, caption = build_extraction_inputs(
                    text, input_type, media_url, local_media_path
                )
                new_txs = safe_extract(
                    inp, input_type, sender_name, media_list, caption
                )
                
                if new_txs is None:
                    return jsonify({'status': 'rate_limit'}), 200
                if new_txs:
                    send_reply("➕ Menambahkan ke antrian transaksi...")
                    # Merge with existing
                    pending['transactions'].extend(new_txs)
                    
                    # Deduplicate based on exact content to avoid double-processing same webhook
                    # Simple hash check on amount + desc
                    unique = {f"{t['jumlah']}_{t['keterangan']}": t for t in pending['transactions']}.values()
                    pending['transactions'] = list(unique)
                    
                    # Update pending state
                    state_manager_module.set_pending_transaction(pending_key, pending)
                    
                    # Re-send updated prompt
                    reply = build_selection_prompt(pending['transactions'])
                    if is_group: reply += "\n\n↩️ Reply angka 1-5"
                    send_reply(reply)
                    return jsonify({'status': 'merged'}), 200
                
                # If image provided no transaction data during pending state, IGNORE it.
                # Don't let it fall through to 'selection' validation which would error.
                if input_type == 'image':
                    return jsonify({'status': 'ignored_image'}), 200

            # Cancel
            if is_command_match(text, Commands.CANCEL, is_group):
                _pending_transactions.pop(pending_pkey, None)
                clear_visual_buffer(sender_number, chat_jid)
                send_reply(UserErrors.CANCELLED)
                return jsonify({'status': 'cancelled'}), 200
            
            # Z. Needs Amount
            if ptype == 'needs_amount':
                try:
                    amt = parse_revision_amount(text)
                except Exception:
                    amt = 0
                if not amt:
                    send_reply("❗ Nominalnya berapa? (contoh: 150rb)")
                    return jsonify({'status': 'asking_amount'}), 200
                
                for t in pending.get('transactions', []):
                    if t.get('needs_amount') or int(t.get('jumlah', 0) or 0) <= 0:
                        t['jumlah'] = int(amt)
                        t.pop('needs_amount', None)
                
                pending.pop('pending_type', None)
                return finalize_transaction_workflow(pending, pending_pkey)
                
            # A. Select Source Wallet (Operational)
            if ptype == 'select_source_wallet':
                clean = text.strip().lower()
                if clean == '4' or 'project' in clean or 'projek' in clean:
                    pending['pending_type'] = None
                    pending['is_operational'] = False
                    pending.pop('operational_category', None)
                    pending['project_confirmed'] = False
                    pending['category_scope'] = 'PROJECT'
                    needs_project = any(not t.get('nama_projek') or t.get('needs_project') for t in pending.get('transactions', []))
                    if needs_project:
                        pending['pending_type'] = 'needs_project'
                        send_reply("Nama projeknya apa?")
                        return jsonify({'status': 'switch_to_project'}), 200
                    return finalize_transaction_workflow(pending, pending_pkey)
                try:
                    sel = int(text.strip())
                    opt = get_wallet_selection_by_idx(sel)
                    if not opt: raise ValueError()
                    
                    pending['selected_source_wallet'] = opt['dompet']
                    return finalize_transaction_workflow(pending, pending_pkey)
                except:
                    send_reply("❌ Pilih angka 1-4.")
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
                pending['project_validated'] = True
                return finalize_transaction_workflow(pending, pending_pkey)

            # G. New Project Confirmation (NEW -> Create or Rename)
            if ptype == 'confirmation_new_project':
                clean = text.lower().strip()
                if clean in ['ya', 'y', 'ok', 'siap', 'buat', 'lanjut']:
                    # User confirmed it is new
                    pending['project_confirmed'] = True
                    pending['is_new_project'] = True  # Flag for lifecycle marker
                    pending['project_validated'] = True
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
                    res_check = resolve_project_name(strip_company_prefix(final_proj))
                    if res_check['status'] == 'NEW':
                         pending['is_new_project'] = True
                    
                    send_reply(f"👌 Update ke: **{final_proj}**")
                    for t in pending['transactions']: t['nama_projek'] = final_proj
                    pending['project_confirmed'] = True
                    pending['project_validated'] = True
                    return finalize_transaction_workflow(pending, pending_pkey)
                
            # C. Needs Project
            if ptype == 'needs_project':
                proj = sanitize_input(text.strip())
                res = resolve_project_name(strip_company_prefix(proj))
                
                if res['status'] == 'AMBIGUOUS':
                    pending['pending_type'] = 'confirmation_project'
                    pending['suggested_project'] = res['final_name']
                    send_reply(f"???? Maksudnya **{res['final_name']}**?\n??? Ya / ??? Bukan")
                    return jsonify({'status': 'confirm'}), 200
                
                if res['status'] == 'NEW':
                    for t in pending['transactions']:
                        t['nama_projek'] = res['final_name']
                    pending['pending_type'] = 'confirmation_new_project'
                    pending['new_project_name'] = res['original']
                    send_reply(f"???? Project **{res['original']}** belum ada.\n\nBuat Project Baru?\n??? Ya / ??? Ganti Nama (Langsung Ketik Nama Baru)")
                    return jsonify({'status': 'asking_new_project'}), 200
                
                final = res['final_name']
                for t in pending['transactions']: t['nama_projek'] = final
                # Set confirmed to true
                pending['project_confirmed'] = True
                pending['project_validated'] = True
                return finalize_transaction_workflow(pending, pending_pkey)
                
            # D. Company Selection
            if ptype == 'selection':
                clean = text.strip().lower()
                if clean == '5' or any(k in clean for k in ['operasional', 'kantor']):
                    pending['pending_type'] = 'select_source_wallet'
                    pending['is_operational'] = True
                    pending['operational_category'] = pending.get('operational_category', 'Lain Lain')
                    pending['project_confirmed'] = False
                    prompt = format_wallet_selection_prompt()
                    mention = format_mention(pending.get('sender_name', sender_name), is_group)
                    send_reply(f"{mention}🏢 Diganti ke Operasional Kantor\n\n{prompt}".replace('*', ''))
                    return jsonify({'status': 'switch_to_operational'}), 200
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

            # F. OCR Amount Confirmation (image safety)
            if ptype == 'confirm_amount':
                clean = text.lower().strip()
                if clean in ['ok', 'oke', 'ya', 'y', 'benar', 'betul']:
                    pending.pop('pending_type', None)
                    pending.pop('pending_amount', None)
                    return finalize_transaction_workflow(pending, pending_pkey)
                else:
                    try:
                        amt = parse_revision_amount(clean)
                    except Exception:
                        amt = 0
                    if not amt or int(amt) <= 0:
                        send_reply("⚠️ Nominal tidak valid. Balas *OK* atau ketik nominal yang benar (contoh: 202500).")
                        return jsonify({'status': 'invalid_amount'}), 200
                    for t in pending.get('transactions', []):
                        t['jumlah'] = int(amt)
                        t.pop('needs_amount', None)
                    pending.pop('pending_type', None)
                    pending.pop('pending_amount', None)
                    return finalize_transaction_workflow(pending, pending_pkey)

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
    
        if is_command_match(text, Commands.LIST, is_group):
            try:
                data = get_all_data(days=7)
                if not data:
                    send_reply("📭 Belum ada transaksi 7 hari terakhir.")
                else:
                    data.sort(key=lambda x: x.get('tanggal', ''), reverse=True)
                    msg = "📜 *Riwayat Transaksi (7 Hari)*\n\n"
                    # Limit to 15
                    for tx in data[:15]:
                        try:
                            t_amt = tx.get('jumlah', 0) or 0
                            amt = int(t_amt)
                        except: amt = 0
                        
                        icon = "🔴" if str(tx.get('tipe', 'Pengeluaran')) == 'Pengeluaran' else "🟢"
                        src = tx.get('nama_projek') or tx.get('company_sheet') or "?"
                        msg += f"{icon} {tx['tanggal']} - Rp {amt:,}\n"
                        msg += f"   _{tx['keterangan']}_ [{src}]\n"
                    
                    msg = msg.replace(',', '.')
                    send_reply(msg)
                return jsonify({'status': 'command_list'}), 200
            except Exception as e:
                send_reply(f"❌ Error: {str(e)}")
                return jsonify({'status': 'error'}), 200

        if is_command_match(text, Commands.LAPORAN, is_group) or is_command_match(text, Commands.LAPORAN_30, is_group):
            try:
                is_30 = '30' in text
                days = 30 if is_30 else 7
                data = get_all_data(days=days)
                
                income = sum(int(t.get('jumlah',0) or 0) for t in data if str(t.get('tipe')) == 'Pemasukan')
                expense = sum(int(t.get('jumlah',0) or 0) for t in data if str(t.get('tipe')) == 'Pengeluaran')
                profit = income - expense
                
                msg = f"📊 *Laporan {'Bulanan (30 Hari)' if days==30 else 'Mingguan (7 Hari)'}*\n\n"
                msg += f"💰 Pemasukan: Rp {income:,}\n"
                msg += f"💸 Pengeluaran: Rp {expense:,}\n"
                msg += f"📈 Profit: Rp {profit:,}\n\n"
                msg += f"Jumlah Transaksi: {len(data)}\n"
                msg = msg.replace(',', '.')
                send_reply(msg)
                return jsonify({'status': 'command_laporan'}), 200
            except Exception as e:
                send_reply(f"❌ Error: {str(e)}")
                return jsonify({'status': 'error'}), 200

        if is_command_match(text, Commands.LINK, is_group):
            url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
            send_reply(f"🔗 *Google Sheets Link:*\n{url}")
            return jsonify({'status': 'command_link'}), 200
            
        if is_prefix_match(text, Commands.EXPORT_PDF_PREFIXES, is_group) or is_command_match(text, Commands.EXPORT_PDF_PREFIXES, is_group):
             try:
                 parts = text.strip().split(' ', 1)
                 arg = parts[1] if len(parts) > 1 else now_wib().strftime("%Y-%m")
                 
                 send_reply(f"⏳ Proses Membuat PDF {arg}...")
                 from pdf_report import generate_pdf_from_input
                 fpath = generate_pdf_from_input(arg)
                 
                 if fpath and os.path.exists(fpath):
                     if send_document:
                         send_document(reply_to, fpath, caption=f"Laporan {arg}")
                     else:
                         fname = os.path.basename(fpath)
                         send_reply(f"✅ PDF berhasil dibuat: {fname}\nDi channel ini belum bisa kirim PDF. Silakan ambil dari server.")
                 else:
                     send_reply("❌ Gagal membuat PDF (Data kosong/Format salah).")
                 return jsonify({'status': 'command_pdf'}), 200
             except PDFNoDataError as nde:
                 period = getattr(nde, "period", arg or "periode tersebut")
                 send_reply(UserErrors.PDF_NO_DATA.format(period=period))
                 return jsonify({'status': 'error_pdf_no_data'}), 200
             except ValueError as ve:
                 msg = str(ve).lower()
                 if "tidak ada data" in msg:
                     send_reply(UserErrors.PDF_NO_DATA.format(period=arg or "periode tersebut"))
                     return jsonify({'status': 'error_pdf_no_data'}), 200
                 send_reply(UserErrors.PDF_FORMAT_ERROR)
                 return jsonify({'status': 'error_pdf'}), 200
             except Exception as e:
                 msg = str(e).lower()
                 secure_log("ERROR", f"PDF Error: {e}")
                 if "tidak ada data" in msg:
                     send_reply(UserErrors.PDF_NO_DATA.format(period=arg or "periode tersebut"))
                     return jsonify({'status': 'error_pdf_no_data'}), 200
                 if "tahun tidak valid" in msg or "bulan tidak valid" in msg or "format tidak" in msg:
                     send_reply(UserErrors.PDF_FORMAT_ERROR)
                     return jsonify({'status': 'error_pdf'}), 200
                 send_reply("❌ Gagal export PDF. Coba lagi beberapa saat.")
                 return jsonify({'status': 'error'}), 200

        # 8. PROCESS NEW INPUT (AI)
        transactions = []
        try:
            if not processing_ack_sent:
                send_reply("🔍 Scan...")
            
            inp, media_list, caption = build_extraction_inputs(
                text, input_type, media_url, local_media_path
            )
            transactions = safe_extract(inp, input_type, sender_name, media_list, caption)
            if transactions is None:
                return jsonify({'status': 'rate_limit'}), 200
            
            if not transactions:
                if message_id:
                    clear_message_duplicate(message_id)
                if input_type == 'image': send_reply("❓ Tidak terbaca.")
                return jsonify({'status': 'no_tx'}), 200
            
            # Clear visual buffer on successful extraction to avoid double-binding
            if input_type == 'image':
                clear_visual_buffer(sender_number, chat_jid)
            
            # Setup New Pending State
            _pending_transactions[sender_pkey] = {
                'transactions': transactions,
                'sender_name': sender_name,
                'source': source_label,
                'created_at': datetime.now(),
                'message_id': event_id,
                'event_id': event_id,
                'chat_jid': chat_jid,
                'quoted_message_id': quoted_msg_id,
                'requires_reply': is_group,
                'original_text': text, # Important for Smart Router
                'normalized_text': text,
                'input_type': input_type,
                'caption': text if input_type == 'image' else None,
                'attachments': {
                    'media_url': media_url,
                    'media_path': local_media_path
                },
                'prompt_message_ids': [],
                'category_scope': layer_category_scope,  # From AI layer (initialized earlier)
                'override_dompet': transfer_dompet if layer_category_scope == 'TRANSFER' else None,
            }

            # OCR safety: ask confirmation for single-transaction images
            if input_type == 'image' and len(transactions) == 1:
                t0 = transactions[0]
                try:
                    amt0 = int(t0.get('jumlah', 0) or 0)
                except Exception:
                    amt0 = 0
                if amt0 > 0:
                    _pending_transactions[sender_pkey]['pending_type'] = 'confirm_amount'
                    item = t0.get('keterangan', 'Transaksi')
                    amt_text = f"{amt0:,}".replace(',', '.')
                    send_reply(f"📷 OCR terdeteksi: {item} (Rp {amt_text}).\nBalas *OK* jika benar, atau ketik nominal yang benar.")
                    return jsonify({'status': 'confirm_amount'}), 200

            # If amount missing/zero, ask user before proceeding
            missing_amount = [t for t in transactions if int(t.get('jumlah', 0) or 0) <= 0]
            if missing_amount:
                for t in missing_amount:
                    t['needs_amount'] = True
                _pending_transactions[sender_pkey]['pending_type'] = 'needs_amount'
                item = missing_amount[0].get('keterangan', 'Transaksi')
                send_reply(f"❗ Nominal untuk \"{item}\" berapa? (contoh: 150rb)")
                return jsonify({'status': 'asking_amount'}), 200

            if all(t.get('nama_projek') and not t.get('needs_project') for t in transactions):
                _pending_transactions[sender_pkey]['project_confirmed'] = True
            
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
            
        except ValueError as e:
            msg = str(e)
            secure_log("WARNING", f"AI Proc ValueError: {msg}")
            if message_id:
                clear_message_duplicate(message_id)
            if input_type == 'image':
                if "Tidak ada teks ditemukan" in msg:
                    send_reply("❓ Tidak terbaca.")
                elif "tidak terdeteksi sebagai struk" in msg:
                    send_reply("❗ Gambar tidak terdeteksi sebagai struk. Tolong kirim struk yang jelas atau tambahkan keterangan transaksi.")
                else:
                    send_reply("❌ Error sistem.")
            else:
                send_reply("❌ Error sistem.")
            return jsonify({'status': 'error'}), 200
        except Exception as e:
            secure_log("ERROR", f"AI Proc Error: {e}")
            if message_id:
                clear_message_duplicate(message_id)
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
