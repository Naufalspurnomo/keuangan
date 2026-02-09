"""
main.py

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
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from flask import Flask, request, jsonify
from dotenv import load_dotenv
from werkzeug.exceptions import RequestEntityTooLarge

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
    append_hutang_entry,
    update_hutang_status_by_no,
    cancel_hutang_by_event_id,
    find_open_hutang,
    get_all_data,
    find_company_for_project_exact,
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
    get_visual_buffer_by_message, remove_visual_buffer_by_message,
    mark_visual_message_consumed, clear_visual_message_consumed,
    is_visual_message_consumed,
    store_last_bot_report,
    store_last_tx_event,
    # New Pending Confirmations
    get_pending_confirmation, set_pending_confirmation,
    has_pending_confirmation,
    find_pending_confirmation_in_chat,
    store_user_message, get_user_last_message, clear_user_last_message,
    get_project_lock, set_project_lock
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
from utils.groq_analyzer import is_saldo_update
from utils.formatters import (
    format_success_reply, format_success_reply_new,
    format_draft_summary_operational, format_draft_summary_project,
    build_selection_prompt,
    START_MESSAGE, HELP_MESSAGE,
    CATEGORIES_DISPLAY, SELECTION_DISPLAY,
)
from utils.lifecycle import apply_lifecycle_markers
from utils.wallet_updates import (
    is_absolute_balance_update,
    pick_wallet_target_amount,
    compute_balance_adjustment,
)

# Configuration
from config.constants import Commands, Timeouts, GROUP_TRIGGERS, SPREADSHEET_ID, OPERATIONAL_KEYWORDS, FAST_MODE
from config.errors import UserErrors
from config.allowlist import is_sender_allowed
from config.wallets import (
    format_wallet_selection_prompt,
    get_wallet_selection_by_idx,
    WALLET_SELECTION_OPTIONS,
    get_dompet_short_name,
    apply_company_prefix,
    extract_company_prefix,
    strip_company_prefix,
    DOMPET_ALIASES,
    get_company_name_from_sheet,
    resolve_dompet_from_text,
)

# Initialize Flask app
app = Flask(__name__)

# Configuration Flags
DEBUG = os.getenv('FLASK_DEBUG', '0') == '1'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
IMAGE_GRACE_SECONDS = int(os.getenv('IMAGE_GRACE_SECONDS', '5'))
GROUP_REPLY_HINT_COOLDOWN_SECONDS = int(os.getenv('GROUP_REPLY_HINT_COOLDOWN_SECONDS', '25'))
GROUP_REPLY_HINT_CHAT_COOLDOWN_SECONDS = int(os.getenv('GROUP_REPLY_HINT_CHAT_COOLDOWN_SECONDS', '12'))
_group_reply_hint_cache: Dict[str, datetime] = {}
_group_reply_hint_lock = threading.Lock()


def should_send_group_reply_hint(chat_jid: str, sender_number: str, hint_type: str) -> bool:
    """
    Throttle repetitive group guidance messages per user/chat/hint type.
    Returns True when hint should be sent, False when it should be suppressed.
    """
    if not chat_jid or not sender_number:
        return True

    now = datetime.now()
    key_user = f"{chat_jid}:{sender_number}:{hint_type}"
    key_chat = f"{chat_jid}:*:{hint_type}"
    ttl_user = max(1, GROUP_REPLY_HINT_COOLDOWN_SECONDS)
    ttl_chat = max(1, GROUP_REPLY_HINT_CHAT_COOLDOWN_SECONDS)
    ttl = max(ttl_user, ttl_chat)

    with _group_reply_hint_lock:
        # Lightweight cleanup to keep cache bounded in long-running process
        stale_keys = [
            k for k, ts in _group_reply_hint_cache.items()
            if not isinstance(ts, datetime) or (now - ts).total_seconds() > (ttl * 8)
        ]
        for k in stale_keys:
            _group_reply_hint_cache.pop(k, None)

        # Chat-level throttle first: avoid spam burst in busy groups.
        last_sent_chat = _group_reply_hint_cache.get(key_chat)
        if last_sent_chat and (now - last_sent_chat).total_seconds() < ttl_chat:
            return False

        # User-level throttle: avoid repeating hint to the same user.
        last_sent_user = _group_reply_hint_cache.get(key_user)
        if last_sent_user and (now - last_sent_user).total_seconds() < ttl_user:
            return False

        _group_reply_hint_cache[key_chat] = now
        _group_reply_hint_cache[key_user] = now
        return True
MAX_WEBHOOK_BYTES = int(os.getenv('MAX_WEBHOOK_BYTES', str(25 * 1024 * 1024)))
app.config['MAX_CONTENT_LENGTH'] = MAX_WEBHOOK_BYTES
app.config['MAX_FORM_MEMORY_SIZE'] = MAX_WEBHOOK_BYTES


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(_err):
    secure_log("WARNING", f"Webhook payload too large (>{MAX_WEBHOOK_BYTES} bytes)")
    # Return 200 to prevent provider retry storm for oversized payloads.
    return jsonify({'status': 'payload_too_large'}), 200

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


# ===================== LOGIC CORE: SMART ROUTER =====================
# Enhanced with amount pattern detection and AI category_scope integration
from handlers.smart_handler import SmartHandler
import services.state_manager as state_manager_module

# Initialize SmartHandler
smart_handler = SmartHandler(state_manager_module)

from utils.amounts import has_amount_pattern


def detect_transaction_context(text: str, transactions: list, category_scope: str = 'UNKNOWN') -> dict:
    """
    Detects context: PROJECT vs OPERATIONAL.
    
    Improvements:
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
    
    # Trust AI's category_scope if available (but allow explicit project override)
    if category_scope == 'OPERATIONAL' and has_project_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    if category_scope == 'OPERATIONAL':
        # Detect which operational category
        detected_keywords = [kw for kw in OPERATIONAL_KEYWORDS if kw in text_lower]
        category = map_operational_category(detected_keywords[0]) if detected_keywords else 'Lain Lain'
        return {'mode': 'OPERATIONAL', 'category': category, 'needs_wallet': True}
    
    if category_scope == 'PROJECT':
        # AI is confident this is project-related
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}

    if category_scope == 'TRANSFER':
        # Wallet balance updates are recorded to dompet with "Saldo Umum".
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}
    
    if category_scope == 'AMBIGUOUS':
        return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}

    # Pre-compute operational keywords for quick routing
    detected_keywords = []
    for kw in OPERATIONAL_KEYWORDS:
        # Use word boundary matching for better accuracy
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            detected_keywords.append(kw)

    # Mixed explicit keywords need confirmation
    if has_project_word and has_kantor_word:
        return {'mode': 'AMBIGUOUS', 'category': None, 'needs_wallet': True}

    # Explicit project keyword should win
    if has_project_word:
        return {'mode': 'PROJECT', 'category': None, 'needs_wallet': False}

    # Otherwise, kantor/operasional wins
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
    Expanded keyword matching.
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


DEBT_PAYMENT_KEYWORDS = [
    "bayar", "lunas", "lunasi", "pelunasan", "cicil", "cicilan", "angsuran"
]

def _is_debt_payment_text(text: str) -> bool:
    lower = (text or "").lower()
    if not re.search(r"\b(utang|hutang)\b", lower):
        return False
    return any(re.search(rf"\b{re.escape(k)}\b", lower) for k in DEBT_PAYMENT_KEYWORDS)


def _extract_dompet_mentions(text: str) -> List[str]:
    lower = (text or "").lower()
    aliases = sorted(DOMPET_ALIASES.items(), key=lambda x: -len(x[0]))
    seen = set()
    dompets: List[str] = []
    for alias, dompet in aliases:
        if alias and alias in lower:
            if dompet not in seen:
                seen.add(dompet)
                dompets.append(dompet)
    return dompets


def _pick_dompet_by_prep(text: str, preps: List[str]) -> Optional[str]:
    lower = (text or "").lower()
    aliases = sorted(DOMPET_ALIASES.items(), key=lambda x: -len(x[0]))
    for prep in preps:
        for alias, dompet in aliases:
            pattern = rf"\b{re.escape(prep)}\b[^a-z0-9]{{0,10}}(?:dompet|rekening|rek|wallet)?\s*{re.escape(alias)}\b"
            if re.search(pattern, lower):
                return dompet
    return None


def _handle_auto_hutang_payment(text: str) -> Optional[str]:
    """
    Auto mark hutang as PAID based on natural language.
    Returns response text if handled, otherwise None.
    """
    if not _is_debt_payment_text(text):
        return None

    lower = (text or "").lower()
    if re.search(r"\b(projek|project|proyek|prj)\b", lower):
        return None
    # Allow direct "no 3" or "nomor 3"
    m_no = re.search(r"\b(?:no|nomor)\.?\s*(\d+)\b", lower)
    if m_no:
        info = update_hutang_status_by_no(int(m_no.group(1)), "PAID")
        if not info:
            return "❌ No hutang tidak ditemukan."
        invalidate_dashboard_cache()
        return (
            f"✅ Hutang #{info['no']} ditandai PAID.\n"
            f"{info.get('keterangan', '-')}\n"
            f"{info.get('yang_hutang', '-')} → {info.get('yang_dihutangi', '-')}\n"
            f"Rp {info.get('amount', 0):,}"
        ).replace(',', '.')

    amount = parse_revision_amount(text) or 0
    lender = _pick_dompet_by_prep(text, ["ke", "kepada", "kpd", "untuk"])
    borrower = _pick_dompet_by_prep(text, ["dari", "dr"])

    if not lender and not borrower:
        return (
            "🤔 Ini pelunasan hutang dompet atau transaksi project?\n"
            "Jika hutang dompet, tulis: bayar hutang ke TX SBY 2jt / bayar hutang no 3.\n"
            "Jika transaksi project, tulis kata 'projek'."
        )

    # Try strict match first (by pair + amount)
    candidates = []
    if amount > 0:
        candidates = find_open_hutang(
            yang_hutang=borrower,
            yang_dihutangi=lender,
            amount=amount
        )
        if not candidates:
            candidates = find_open_hutang(
                yang_hutang=borrower or None,
                yang_dihutangi=lender or None,
                amount=amount
            )

    # Fallback: match by pair only
    if not candidates:
        candidates = find_open_hutang(
            yang_hutang=borrower or None,
            yang_dihutangi=lender or None,
            amount=None
        )

    if not candidates and amount > 0:
        candidates = find_open_hutang(amount=amount)

    if not candidates:
        return "❌ Tidak ada hutang OPEN yang cocok. Tulis contoh: bayar hutang ke TX SBY 2jt."

    if len(candidates) > 1:
        lines = ["🤔 Ada beberapa hutang OPEN. Balas dengan format: `bayar hutang no 3`."]
        for item in candidates[:5]:
            lines.append(
                f"#{item['no']} {item.get('yang_hutang','-')} → {item.get('yang_dihutangi','-')} "
                f"Rp {item.get('amount',0):,} ({item.get('keterangan','-')})"
            )
        return "\n".join(lines).replace(',', '.')

    chosen = candidates[0]
    info = update_hutang_status_by_no(int(chosen.get('no', 0)), "PAID")
    if not info:
        return "❌ Gagal menandai hutang PAID."
    invalidate_dashboard_cache()
    return (
        f"✅ Hutang #{info['no']} ditandai PAID.\n"
        f"{info.get('keterangan', '-')}\n"
        f"{info.get('yang_hutang', '-')} → {info.get('yang_dihutangi', '-')}\n"
        f"Rp {info.get('amount', 0):,}"
    ).replace(',', '.')



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
        try:
            json_data_raw = request.form.get('jsonData')
        except RequestEntityTooLarge:
            secure_log("WARNING", f"Webhook payload too large while reading form (>{MAX_WEBHOOK_BYTES} bytes)")
            return jsonify({'status': 'payload_too_large'}), 200
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
        # DEBUG: Log message structure for reply debugging
        if msg_type == 'text':
            msg_keys = list(message_obj.keys()) if isinstance(message_obj, dict) else []
            secure_log("DEBUG", f"Webhook: text msg_keys={msg_keys}")
            if message_obj.get('extendedTextMessage'):
                ext_keys = list(message_obj['extendedTextMessage'].keys())
                secure_log("DEBUG", f"Webhook: extendedTextMessage keys={ext_keys}")

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

            # Some WuzAPI events declare image type but provide neither base64 nor downloadable media.
            # Avoid passing empty media source to OCR pipeline.
            if not media_url and not local_media_path:
                if (text or '').strip():
                    secure_log("WARNING", "Webhook image payload missing media; fallback to caption-only text extraction")
                    input_type = 'text'
                else:
                    secure_log("WARNING", "Webhook image payload missing media and caption; skipping message")
                    return jsonify({'status': 'image_missing_media'}), 200

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

        # Quoted info - check multiple possible locations in WuzAPI payload
        ctx_info = None
        # Priority 1: extendedTextMessage (reply to text/media)
        if message_obj.get('extendedTextMessage', {}).get('contextInfo'):
            ctx_info = message_obj['extendedTextMessage']['contextInfo']
        # Priority 2: plain text reply metadata (some WuzAPI builds)
        elif message_obj.get('messageContextInfo'):
            ctx_info = message_obj['messageContextInfo']
        # Priority 3: imageMessage (reply with image)
        elif message_obj.get('imageMessage', {}).get('contextInfo'):
            ctx_info = message_obj['imageMessage']['contextInfo']
        # Priority 4: direct contextInfo on message
        elif message_obj.get('contextInfo'):
            ctx_info = message_obj['contextInfo']
        # Priority 5: Check in event.Info (some WuzAPI versions)
        elif info.get('ContextInfo'):
            ctx_info = info['ContextInfo']
        # Priority 6: Check event root level
        elif event_data.get('event', {}).get('ContextInfo'):
            ctx_info = event_data['event']['ContextInfo']
        
        if ctx_info:
            quoted_msg_id = (
                ctx_info.get('stanzaId')
                or ctx_info.get('StanzaId')
                or ctx_info.get('stanzaID')
                or ctx_info.get('quotedMessageID')
                or ctx_info.get('quotedMessageId')
                or ''
            )
            if quoted_msg_id:
                secure_log("INFO", f"Webhook: Quoted message detected: {quoted_msg_id[:20]}...")
            else:
                # Debug: log what keys are in contextInfo
                secure_log("DEBUG", f"Webhook: contextInfo found but no stanzaId. Keys: {list(ctx_info.keys())}")

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
                             source_label: str = 'WhatsApp', reply_to=None,
                             deferred: bool = False):
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

        def _normalize_amount(value) -> int:
            """Best-effort parse amount to non-negative integer."""
            try:
                if value is None:
                    return 0
                if isinstance(value, bool):
                    return int(value)
                if isinstance(value, int):
                    return abs(value)
                if isinstance(value, float):
                    return abs(int(value))
                raw = str(value).strip()
                if not raw:
                    return 0
                parsed = parse_revision_amount(raw)
                if parsed > 0:
                    return parsed
                raw = raw.replace("rp", "").replace("Rp", "").replace("RP", "")
                digits = re.sub(r"[^0-9]", "", raw)
                return int(digits) if digits else 0
            except Exception:
                return 0

        def _normalize_key_text(value) -> str:
            text_value = sanitize_input(str(value or "")).lower().strip()
            return re.sub(r"\s+", " ", text_value)

        def _normalize_transaction(tx: dict) -> Optional[dict]:
            if not isinstance(tx, dict):
                return None

            normalized = dict(tx)
            normalized["jumlah"] = _normalize_amount(normalized.get("jumlah", 0))

            ket = sanitize_input(str(normalized.get("keterangan", "") or "")).strip()
            normalized["keterangan"] = ket[:200] if ket else "Transaksi"

            tipe = normalized.get("tipe", "Pengeluaran")
            if tipe not in ("Pemasukan", "Pengeluaran"):
                tipe = "Pengeluaran"
            normalized["tipe"] = tipe

            if normalized["jumlah"] <= 0:
                normalized["needs_amount"] = True
            else:
                normalized.pop("needs_amount", None)
            return normalized

        def _tx_content_key(tx: dict) -> Tuple[str, str, str, str]:
            project = strip_company_prefix(str(tx.get("nama_projek", "") or ""))
            return (
                _normalize_key_text(tx.get("tipe", "Pengeluaran")),
                _normalize_key_text(tx.get("keterangan", "")),
                _normalize_key_text(project),
                _normalize_key_text(tx.get("kategori", "")),
            )

        def _tx_identity_key(tx: dict) -> Tuple[str, str, str, str, int]:
            content = _tx_content_key(tx)
            amount = int(tx.get("jumlah", 0) or 0)
            return (content[0], content[1], content[2], content[3], amount)

        def _merge_transaction_queue(existing: list, incoming: list) -> Tuple[list, dict]:
            """
            Merge queue safely:
            - normalize every tx
            - drop exact duplicates
            - prefer valid amount (>0) over zero for the same content
            """
            merged: List[dict] = []
            identity_index: Dict[Tuple[str, str, str, str, int], int] = {}
            content_index: Dict[Tuple[str, str, str, str], int] = {}
            meta = {"added": 0, "duplicates": 0, "upgraded": 0}

            def _upsert(raw_tx, is_incoming: bool) -> None:
                tx = _normalize_transaction(raw_tx)
                if not tx:
                    if is_incoming:
                        meta["duplicates"] += 1
                    return

                identity = _tx_identity_key(tx)
                if identity in identity_index:
                    if is_incoming:
                        meta["duplicates"] += 1
                    return

                content = _tx_content_key(tx)
                prev_idx = content_index.get(content)
                if prev_idx is not None:
                    prev_tx = merged[prev_idx]
                    prev_amt = int(prev_tx.get("jumlah", 0) or 0)
                    new_amt = int(tx.get("jumlah", 0) or 0)

                    if prev_amt <= 0 < new_amt:
                        prev_identity = _tx_identity_key(prev_tx)
                        merged[prev_idx] = tx
                        identity_index.pop(prev_identity, None)
                        identity_index[identity] = prev_idx
                        if is_incoming:
                            meta["upgraded"] += 1
                        return

                    if new_amt <= 0 < prev_amt:
                        if is_incoming:
                            meta["duplicates"] += 1
                        return

                insert_idx = len(merged)
                merged.append(tx)
                identity_index[identity] = insert_idx
                content_index.setdefault(content, insert_idx)
                if is_incoming:
                    meta["added"] += 1

            for old_tx in existing or []:
                _upsert(old_tx, is_incoming=False)
            for new_tx in incoming or []:
                _upsert(new_tx, is_incoming=True)

            return merged, meta

        def _first_missing_amount_tx(transactions: list) -> Optional[dict]:
            for tx in transactions or []:
                try:
                    amount = int(tx.get("jumlah", 0) or 0)
                except Exception:
                    amount = 0
                if tx.get("needs_amount") or amount <= 0:
                    return tx
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

        def schedule_group_image_grace() -> None:
            if IMAGE_GRACE_SECONDS <= 0:
                return

            def _worker():
                time.sleep(IMAGE_GRACE_SECONDS)
                buf = get_visual_buffer(sender_number, chat_jid)
                if not buf:
                    return
                item = next((b for b in buf if b.get('message_id') == message_id), None)
                if not item:
                    return
                item_message_id = item.get('message_id') or message_id
                if item_message_id and is_visual_message_consumed(chat_jid, item_message_id):
                    return

                pkey = pending_key(sender_number, chat_jid)
                pending = _pending_transactions.get(pkey)
                if pending and not pending_is_expired(pending):
                    return
                if has_pending_confirmation(sender_number, chat_jid):
                    secure_log(
                        "INFO",
                        f"Skip deferred image {message_id}: pending confirmation is active"
                    )
                    return

                deferred_text = item.get('caption') or ''
                if not deferred_text:
                    item_ctx = item.get('context') if isinstance(item.get('context'), dict) else {}
                    deferred_text = (item_ctx.get('original_text') or '').strip()

                process_incoming_message(
                    sender_number=sender_number,
                    sender_name=sender_name,
                    text=deferred_text,
                    input_type='image',
                    media_url=item.get('media_url'),
                    local_media_path=item.get('media_path'),
                    quoted_msg_id=quoted_msg_id,
                    message_id=item_message_id,
                    is_group=is_group,
                    chat_jid=chat_jid,
                    sender_jid=sender_jid,
                    quoted_message_text=quoted_message_text,
                    send_reply=send_reply,
                    send_document=send_document,
                    source_label=source_label,
                    reply_to=reply_to,
                    deferred=True
                )

            threading.Thread(target=_worker, daemon=True).start()

        # Event envelope
        event_id = str(message_id) if message_id else f"evt_{uuid.uuid4().hex[:12]}"
        claimed_visual_source_id = None
        bound_visual_message_id = None

        def _resolve_visual_source_message_id() -> Optional[str]:
            if bound_visual_message_id:
                return str(bound_visual_message_id)
            if input_type != 'image':
                return None
            if message_id:
                return str(message_id)
            if quoted_msg_id:
                quoted_item = get_visual_buffer_by_message(chat_jid, quoted_msg_id)
                if quoted_item and quoted_item.get('message_id'):
                    return str(quoted_item.get('message_id'))
            return None

        def _claim_visual_source_once() -> bool:
            nonlocal claimed_visual_source_id
            visual_source_id = _resolve_visual_source_message_id()
            if not visual_source_id:
                return True
            if claimed_visual_source_id == visual_source_id:
                return True
            if not mark_visual_message_consumed(chat_jid, visual_source_id):
                send_reply("ℹ️ Struk ini sudah diproses. Gunakan /revisi atau /undo jika perlu koreksi.")
                return False
            claimed_visual_source_id = visual_source_id
            return True

        def _release_visual_source_claim() -> None:
            nonlocal claimed_visual_source_id
            if not claimed_visual_source_id:
                return
            clear_visual_message_consumed(chat_jid, claimed_visual_source_id)
            claimed_visual_source_id = None

        def _has_wallet_context_hint(raw_text: str) -> bool:
            lower = (raw_text or "").lower().strip()
            if not lower:
                return False
            if not resolve_dompet_from_text(lower):
                return False
            if re.search(r"\b(dompet|wallet|saldo|utang|hutang|minjem|minjam|pinjam|dari|dr|pakai)\b", lower):
                return True
            return bool(re.search(r"\b(tx\s*sby|tx\s*bali|cv\s*hb|101|216|087)\b", lower))

        def _should_bind_visual_text(raw_text: str) -> bool:
            clean = (raw_text or "").strip()
            if not clean:
                return False
            lower = clean.lower()
            if re.search(r"\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b", lower):
                return True
            if is_explicit_bot_call(clean):
                return True
            if has_amount_pattern(clean):
                return True
            if _has_wallet_context_hint(clean):
                return True
            should, _ = should_respond_in_group(
                clean,
                is_group,
                has_media=False,
                has_pending=False,
                is_mentioned=is_explicit_bot_call(clean)
            )
            return should

        def _get_pending_confirmation_by_key(conf_key: str) -> Optional[dict]:
            """Resolve pending confirmation by exact key format: '<chat_id>:<user_id>'."""
            if not conf_key or ":" not in conf_key:
                return None
            chat_part, user_part = conf_key.split(":", 1)
            if not chat_part or not user_part:
                return None
            return get_pending_confirmation(user_part, chat_part)

        def _count_active_group_sessions(target_chat_id: str) -> int:
            """Count active pending transaction + confirmation sessions in a group chat."""
            if not target_chat_id:
                return 0

            total = 0
            now = datetime.now()

            # Pending transaction sessions (group keys are prefixed with '<chat_id>:')
            for pkey, pdata in list(_pending_transactions.items()):
                if not isinstance(pkey, str) or not pkey.startswith(f"{target_chat_id}:"):
                    continue
                if pdata and not pending_is_expired(pdata):
                    total += 1

            # Pending confirmation sessions
            for ckey, cdata in list(state_manager_module.PENDING_CONFIRMATIONS.items()):
                if not isinstance(ckey, str) or not ckey.startswith(f"{target_chat_id}:"):
                    continue
                expires = cdata.get('expires_at') if isinstance(cdata, dict) else None
                if isinstance(expires, datetime) and now > expires:
                    continue
                total += 1

            return total

        def _looks_like_ambiguous_reply(raw_text: str) -> bool:
            """
            Detect short/ambiguous reply-like messages in group chat
            that should be tied to a specific prompt via reply.
            """
            clean = (raw_text or "").strip().lower()
            if not clean:
                return False

            if bool(re.fullmatch(r"\d{1,2}", clean)):
                return True

            if clean in {
                'ya', 'y', 'iya', 'ok', 'oke', 'yes',
                'no', 'tidak', 'bukan',
                'simpan', 'batal', 'cancel', '/cancel',
                'operasional', 'operational', 'ops', 'kantor',
                'project', 'projek'
            }:
                return True

            # Bare amount replies like "150rb" / "rp 41.852" are ambiguous in busy groups.
            if bool(re.fullmatch(r"(rp\s*)?\d[\d\.,\s]*(rb|ribu|k|jt|juta)?", clean)):
                return True

            return False

        # --- CORE WORKFLOW: FINALIZE TRANSACTION ---
        def finalize_transaction_workflow(pending: dict, pkey: str):
            raw_txs = pending.get('transactions', [])
            txs, _ = _merge_transaction_queue(raw_txs, [])
            pending['transactions'] = txs
            if not txs:
                return jsonify({'status': 'error_no_tx'}), 200

            missing_tx = _first_missing_amount_tx(txs)
            if missing_tx:
                pending['pending_type'] = 'needs_amount'
                item = missing_tx.get('keterangan', 'Transaksi')
                send_reply(f"Nominal untuk \"{item}\" berapa? (contoh: 150rb)")
                return jsonify({'status': 'asking_amount'}), 200

            def _assign_tx_ids(transactions: list, event_id: str) -> None:
                base = event_id or f"evt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                for idx, tx in enumerate(transactions, start=1):
                    tx_id = f"{base}|{idx}"
                    tx['message_id'] = tx_id
                    tx['tx_id'] = tx_id

            def _detect_operational_category(keterangan: str) -> str:
                keterangan_lower = (keterangan or "").lower()
                if 'gaji' in keterangan_lower:
                    return 'Gaji'
                if any(x in keterangan_lower for x in ['listrik', 'pln', 'token', 'air', 'pdam']):
                    return 'ListrikAir'
                if any(x in keterangan_lower for x in ['konsumsi', 'snack', 'makan', 'minum']):
                    return 'Konsumsi'
                if any(x in keterangan_lower for x in ['atk', 'printer', 'kertas', 'tinta', 'peralatan']):
                    return 'Peralatan'
                if 'internet' in keterangan_lower or 'wifi' in keterangan_lower:
                    return 'ListrikAir'
                return 'Lain Lain'

            def _extract_debt_source(text: str) -> Optional[str]:
                if not text:
                    return None
                lower = text.lower()
                if not re.search(r"\b(utang|hutang|minjem|minjam|pinjam)\b", lower):
                    return None
                # If this looks like paying a debt, do not treat as new borrowing
                if _is_debt_payment_text(lower):
                    if not _pick_dompet_by_prep(lower, ["dari", "dr"]):
                        return None
                # Prefer explicit lender markers to avoid clashing with project/company words
                by_prep = _pick_dompet_by_prep(lower, ["dari", "dr", "ke", "kepada", "kpd"])
                if by_prep:
                    return by_prep

                # Fallback: only parse the text tail that starts from debt keyword
                m = re.search(r"\b(utang|hutang|minjem|minjam|pinjam)\b", lower)
                if m:
                    tail = lower[m.start():]
                    from_tail = resolve_dompet_from_text(tail)
                    if from_tail:
                        return from_tail

                # Last resort: full text parse
                return resolve_dompet_from_text(lower)

            def _send_and_track(response: str, event_id: str) -> None:
                sent = send_reply(response)
                bid = extract_bot_msg_id(sent)
                if bid:
                    store_bot_message_ref(bid, event_id)
                    store_last_bot_report(chat_jid, bid)
                # Fallback: track last event per user/chat even if bot msg ID missing
                store_last_tx_event(sender_number, chat_jid, event_id)
            
            # ROUTING CHECK
            original_text = pending.get('original_text', '')
            category_scope = pending.get('category_scope', 'UNKNOWN')  # From AI layer
            debt_source_hint = _extract_debt_source(original_text)
            has_debt_context = bool(
                re.search(r"\b(utang|hutang|minjem|minjam|pinjam)\b", (original_text or "").lower())
            )
            
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
                response = """🤔 Ini untuk Operational Kantor atau Project?

1️⃣ Operational Kantor
   (Gaji staff, listrik, wifi, ATK, dll)

2️⃣ Project
   (Material, upah tukang, transport ke site)

Balas 1 atau 2"""
                sent = send_reply(response)
                bid = extract_bot_msg_id(sent)
                if bid:
                    store_pending_message_ref(bid, f"{pending.get('chat_jid', chat_jid)}:{pending.get('sender_number', sender_number)}")
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
                
                # Step 2: Save to Operational Sheet (fast mode auto-commit)
                if FAST_MODE:
                    event_id = pending.get('event_id') or pending.get('message_id')
                    _assign_tx_ids(txs, event_id)
                    category = context.get('category') or _detect_operational_category(
                        txs[0].get('keterangan', '') if txs else ''
                    )
                    for tx in txs:
                        kategori = category or _detect_operational_category(tx.get('keterangan', ''))
                        append_operational_transaction(
                            transaction={
                                'jumlah': tx['jumlah'],
                                'keterangan': tx['keterangan'],
                                'message_id': tx.get('message_id')
                            },
                            sender_name=pending.get('sender_name', sender_name),
                            source=pending.get('source', 'WhatsApp'),
                            source_wallet=source_wallet,
                            category=kategori
                        )
                        # Debit dompet sheet (Pengeluaran)
                        append_project_transaction(
                            transaction={
                                'jumlah': tx['jumlah'],
                                'keterangan': tx['keterangan'],
                                'tipe': 'Pengeluaran',
                                'message_id': tx.get('message_id')
                            },
                            sender_name=pending.get('sender_name', sender_name),
                            source=pending.get('source', 'WhatsApp'),
                            dompet_sheet=source_wallet,
                            project_name="Operasional Kantor"
                        )

                    invalidate_dashboard_cache()
                    _pending_transactions.pop(pkey, None)

                    total_amount = sum(int(t.get('jumlah', 0) or 0) for t in txs)
                    response = (
                        f"✅ Tersimpan: Operasional — Rp {total_amount:,} — {source_wallet}\n"
                        "Ketik /undo jika salah."
                    ).replace(',', '.')
                    _send_and_track(response, event_id)
                    return jsonify({'status': 'saved_operational'}), 200

                # Strict mode: Draft → Confirm → Commit
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
                draft_msg = format_draft_summary_operational(
                    txs, source_wallet, context.get('category'), mention
                )
                send_reply(draft_msg)
                return jsonify({'status': 'draft_operational'}), 200

            # === JALUR 2: PROJECT (Standard) ===
            lock_note = None
            new_project_expense_note = None
            wallet_set_note = None
            
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
                        # Safety: never auto-pick ambiguous project names unless the user
                        # explicitly gave a trusted prefix (HOLLA/HOJJA) that resolves exactly.
                        raw_prefix = extract_company_prefix(p_name_raw or "")
                        if FAST_MODE and raw_prefix:
                            prefixed_candidate = f"{raw_prefix} - {lookup_name}"
                            prefixed_res = resolve_project_name(prefixed_candidate)
                            if prefixed_res.get('status') in ['EXACT', 'AUTO_FIX']:
                                t['nama_projek'] = prefixed_res.get('final_name') or prefixed_candidate
                                pending['project_confirmed'] = True
                                continue

                        pending['pending_type'] = 'confirmation_project'
                        pending['suggested_project'] = res.get('final_name') or res.get('original') or lookup_name
                        msg = (
                             f"🤔 *KONFIRMASI PROJECT*\n"
                             f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                             f"Maksudnya *{pending['suggested_project']}*?\n\n"
                             f"━━━━━━━━━━━━━━━━━━━━━\n"
                             f"✅ *Ya* — Lanjutkan\n"
                             f"❌ *Bukan* — Langsung ketik nama yang benar"
                         )
                        send_reply(msg)
                        return jsonify({'status': 'asking_project_confirm'}), 200
                    
                    elif res['status'] == 'NEW':
                        has_income = any(t.get('tipe') == 'Pemasukan' for t in txs)
                        pending['pending_type'] = 'confirmation_new_project'
                        pending['new_project_name'] = res['original']
                        if not has_income:
                            pending['new_project_first_expense'] = True
                            msg = (
                                f"\U0001F4C1 *PROJECT BARU*\n"
                                f"--------------------\n\n"
                                f"Project *{res['original']}* belum terdaftar.\n"
                                f"\U0001F4B8 *Transaksi: Pengeluaran*\n\n"
                                f"\U0001F4A1 Biasanya project baru dimulai dari *DP (Pemasukan)*\n\n"
                                f"--------------------\n"
                                f"Pilih tindakan:\n\n"
                                f"\u0031\ufe0f\u20e3 Lanjutkan sebagai project baru\n"
                                f"\u0032\ufe0f\u20e3 Ubah jadi Operasional Kantor\n"
                                f"\u0033\ufe0f\u20e3 Batal\n\n"
                                f"Atau ketik *nama lain* untuk ganti"
                            )
                            send_reply(msg)
                            return jsonify({'status': 'asking_new_project'}), 200
                        msg = (
                            f"\U0001F4C1 *PROJECT BARU*\n"
                            f"--------------------\n\n"
                            f"Project *{res['original']}* belum terdaftar.\n\n"
                            f"--------------------\n"
                            f"Pilih tindakan:\n\n"
                            f"Ya - *Buat project baru*\n"
                            f"Ketik nama lain untuk ganti\n\n"
                            f"Balas *Ya* atau ketik nama baru"
                        )
                        send_reply(msg)
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
                if has_debt_context and debt_source_hint and detected_dompet == debt_source_hint and not detected_company:
                    secure_log(
                        "INFO",
                        f"Ignoring detected dompet {detected_dompet} as main dompet (treated as debt source context)"
                    )
                else:
                    dompet = detected_dompet
                    detected_company = get_company_name_from_sheet(dompet)

            if detected_company:
                if detected_company == "UMUM":
                    dompet = pending.get('override_dompet')
                else:
                    dompet = get_dompet_for_company(detected_company)
            
            explicit_dompet = resolve_dompet_from_text(original_text)
            if explicit_dompet:
                if has_debt_context and debt_source_hint and explicit_dompet == debt_source_hint:
                    secure_log(
                        "INFO",
                        f"Ignoring explicit dompet {explicit_dompet} as main dompet (treated as debt source context)"
                    )
                else:
                    dompet = explicit_dompet
                    detected_company = get_company_name_from_sheet(dompet)

            # --- AUTO-RESOLVE COMPANY FROM PROJECT HISTORY (NEW) ---
            # If we know the project, but not the company, try to find where it was last used
            if not dompet and pending.get('project_confirmed'):
                # Check first transaction's project
                p_name_check = txs[0].get('nama_projek')
                if p_name_check:
                    found_dompet, found_comp = find_company_for_project_exact(p_name_check)
                    if found_dompet:
                        dompet = found_dompet
                        detected_company = found_comp
                        if found_comp:
                            secure_log("INFO", f"Auto-resolved project exact-match '{p_name_check}' to {found_comp}")
                        else:
                            secure_log(
                                "INFO",
                                f"Auto-resolved dompet for project '{p_name_check}' to {found_dompet}; company remains ambiguous"
                            )

            # 2. Save if Resolved
            if detected_company and dompet:
                debt_source = debt_source_hint

                is_transfer_flow = pending.get('category_scope') == 'TRANSFER'
                is_wallet_set_mode = is_transfer_flow and is_absolute_balance_update(original_text)
                skip_duplicate_check = False

                if is_wallet_set_mode:
                    target_amount = pick_wallet_target_amount(txs)
                    if target_amount <= 0:
                        send_reply("❗ Nominal target saldo belum terbaca. Contoh: update saldo dompet TX SBY 10jt")
                        return jsonify({'status': 'wallet_set_missing_amount'}), 200

                    balances = get_wallet_balances()
                    dompet_info = balances.get(dompet, {})
                    current_balance = int(dompet_info.get('saldo', 0) or 0)
                    adjustment = compute_balance_adjustment(current_balance, target_amount)

                    if int(adjustment.get('amount', 0) or 0) <= 0:
                        _pending_transactions.pop(pkey, None)
                        response = (
                            f"ℹ️ Saldo {dompet} sudah sesuai target (Rp {target_amount:,}). "
                            "Tidak ada transaksi penyesuaian."
                        ).replace(',', '.')
                        _send_and_track(response, pending.get('event_id') or pending.get('message_id'))
                        return jsonify({'status': 'wallet_set_no_change'}), 200

                    adj_amount = int(adjustment.get('amount', 0) or 0)
                    adj_tipe = str(adjustment.get('tipe') or 'Pemasukan')
                    adj_delta = int(adjustment.get('delta', 0) or 0)

                    tx_template = dict(txs[0]) if txs else {}
                    tx_template['jumlah'] = adj_amount
                    tx_template['tipe'] = adj_tipe
                    tx_template['nama_projek'] = 'Saldo Umum'
                    tx_template['company'] = 'UMUM'
                    tx_template['needs_project'] = False
                    tx_template['keterangan'] = (
                        f"Set saldo ke Rp {target_amount:,} (saldo sebelumnya Rp {current_balance:,})"
                    ).replace(',', '.')
                    txs[:] = [tx_template]
                    pending['transactions'] = txs

                    sign = "+" if adj_delta > 0 else "-"
                    wallet_set_note = (
                        f"Mode set saldo: target Rp {target_amount:,}, "
                        f"saldo sebelumnya Rp {current_balance:,}, "
                        f"penyesuaian {sign}Rp {abs(adj_delta):,}."
                    ).replace(',', '.')
                    skip_duplicate_check = True

                # Check Duplicates
                t0 = txs[0]
                if not skip_duplicate_check:
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
                        locked_company = get_company_name_from_sheet(locked_dompet)
                        if FAST_MODE:
                            dompet = locked_dompet
                            detected_company = locked_company
                            lock_note = f"Dompet disesuaikan ke {locked_dompet} (sesuai riwayat project)."
                        else:
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
                                    'debt_source_dompet': debt_source,
                                    'raw_text': original_text,
                                    'sender_name': pending.get('sender_name'),
                                    'source': pending.get('source'),
                                    'original_message_id': pending.get('message_id'),
                                    'event_id': pending.get('event_id'),
                                    'is_new_project': pending.get('is_new_project', False),
                                    'pending_key': pkey
                                }
                            )
                            msg = (
                                f"⚠️ *KONFIRMASI DOMPET*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                                f"📁 Project: *{p_name_check}*\n"
                                f"📌 Terdaftar di: *{locked_dompet}*\n"
                                f"🔄 Input baru: *{dompet}*\n\n"
                                f"━━━━━━━━━━━━━━━━━━━━━\n"
                                f"*Pilih tindakan:*\n\n"
                                f"1️⃣  Gunakan dompet terdaftar ({locked_dompet})\n"
                                f"2️⃣  Pindahkan project ke ({dompet})\n"
                                f"3️⃣  Batal\n\n"
                                f"↩️ _Balas dengan angka 1, 2, atau 3_"
                            )
                            send_reply(msg)
                            return jsonify({'status': 'project_lock_mismatch'}), 200

                # Normalize debt_source only after final dompet is resolved
                if debt_source == dompet:
                    debt_source = None


                for t in txs:
                    pname = t.get('nama_projek')
                    if pname:
                        t['nama_projek'] = apply_company_prefix(pname, dompet, detected_company)

                # Fast mode: commit directly
                if FAST_MODE:
                    event_id = pending.get('event_id') or pending.get('message_id')
                    _assign_tx_ids(txs, event_id)
                    for tx in txs:
                        pname = tx.get('nama_projek') or 'Umum'
                        pname = apply_company_prefix(pname, dompet, detected_company)
                        pname = apply_lifecycle_markers(
                            pname, tx, is_new_project=pending.get('is_new_project', False), allow_finish=True
                        )
                        append_project_transaction(
                            transaction={
                                'jumlah': tx['jumlah'],
                                'keterangan': tx['keterangan'],
                                'tipe': tx.get('tipe', 'Pengeluaran'),
                                'message_id': tx.get('message_id')
                            },
                            sender_name=pending.get('sender_name', sender_name),
                            source=pending.get('source', 'WhatsApp'),
                            dompet_sheet=dompet,
                            project_name=pname
                        )
                        if pname and pname.lower() not in ['saldo umum', 'operasional kantor', 'umum', 'unknown']:
                            set_project_lock(pname, dompet, actor=pending.get('sender_name', sender_name), reason='commit')

                    # If funded by another dompet (utang), record lender outflow only
                    if debt_source and debt_source != dompet:
                        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in txs)
                        if total_amount > 0:
                            debt_desc = f"Hutang ke dompet {dompet}"
                            append_project_transaction(
                                transaction={
                                    'jumlah': total_amount,
                                    'keterangan': debt_desc,
                                    'tipe': 'Pengeluaran',
                                    'message_id': f"{event_id}|UTANG"
                                },
                                sender_name=pending.get('sender_name', sender_name),
                                source=pending.get('source', 'WhatsApp'),
                                dompet_sheet=debt_source,
                                project_name="Saldo Umum"
                            )
                            # Log hutang entry (borrower = dompet, lender = debt_source)
                            append_hutang_entry(
                                amount=total_amount,
                                keterangan=txs[0].get('keterangan', '') if txs else '',
                                yang_hutang=dompet,
                                yang_dihutangi=debt_source,
                                message_id=f"{event_id}|HUTANG"
                            )

                    if pending.get('is_new_project'):
                        raw_proj = txs[0].get('nama_projek') if txs else ''
                        if raw_proj:
                            add_new_project_to_cache(raw_proj)

                    invalidate_dashboard_cache()
                    _pending_transactions.pop(pkey, None)
                    response = format_success_reply_new(txs, dompet, detected_company, "").replace('*', '')
                    if lock_note:
                        response += f"\n {lock_note}"
                    if new_project_expense_note:
                        response += f"\n {new_project_expense_note}"
                    if wallet_set_note:
                        response += f"\n {wallet_set_note}"
                    if debt_source and debt_source != dompet:
                        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in txs)
                        response += f"\n💳 Utang dicatat: {debt_source} → {dompet} (Rp {total_amount:,})".replace(',', '.')
                    _send_and_track(response, event_id)
                    return jsonify({'status': 'saved_project'}), 200

                # Strict mode: Draft ? Confirm ? Commit
                set_pending_confirmation(
                    user_id=sender_number,
                    chat_id=chat_jid,
                    data={
                        'type': 'confirm_commit_project',
                        'transactions': txs,
                        'dompet': dompet,
                        'company': detected_company,
                        'debt_source_dompet': debt_source,
                        'sender_name': pending.get('sender_name'),
                        'source': pending.get('source'),
                        'original_message_id': pending.get('message_id'),
                        'event_id': pending.get('event_id'),
                        'is_new_project': pending.get('is_new_project', False),
                        'pending_key': pkey,
                        'raw_text': original_text
                    }
                )
                draft_msg = format_draft_summary_project(
                    txs, dompet, detected_company, mention, debt_source or ""
                )
                if wallet_set_note:
                    draft_msg += f"\n{wallet_set_note}"
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

        recent_text_for_image = ""
        recent_scope_hint = None
        
        # 2. Visual Buffer (store all images for "catat diatas" binding)
        if input_type == 'image' and not deferred:
            recent_text_for_image = (get_user_last_message(sender_number, chat_jid, max_age_seconds=30) or "").strip()
            if recent_text_for_image:
                recent_lower = recent_text_for_image.lower()
                if re.search(r"\b(operasional|kantor|operational|office|ops)\b", recent_lower):
                    recent_scope_hint = "OPERATIONAL"
                elif re.search(r"\b(projek|project|proyek|prj)\b", recent_lower):
                    recent_scope_hint = "PROJECT"

            visual_context = {}
            if recent_scope_hint:
                visual_context["category_scope"] = recent_scope_hint
            if recent_text_for_image:
                visual_context["original_text"] = recent_text_for_image

            store_visual_buffer(
                sender_number, chat_jid, media_url, message_id,
                caption=text, media_path=local_media_path, context=visual_context
            )
        
        has_visual = has_visual_buffer(sender_number, chat_jid)
        
        # If user says "catat diatas" but no buffered image, ask to reply/attach
        if input_type == 'text':
            ref_phrase = re.search(r'\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b', (text or '').lower())
            if ref_phrase and not has_visual and not quoted_msg_id:
                send_reply("❗ Belum ada gambar/struk sebelumnya. Tolong reply struknya atau kirim ulang.")
                return jsonify({'status': 'missing_reference'}), 200

        # Strict group mode: answer-like texts must reply to a mapped bot prompt.
        # This avoids cross-session mistakes when multiple users interact concurrently.
        if is_group and input_type == 'text' and _looks_like_ambiguous_reply(text):
            active_sessions = _count_active_group_sessions(chat_jid)
            if active_sessions > 0:
                quoted_pending_ref = get_pending_key_from_message(quoted_msg_id) if quoted_msg_id else ''
                if not quoted_pending_ref and quoted_msg_id:
                    # Fallback: user replied, but prompt->pending mapping might be missing.
                    # If user still has own pending confirmation, let flow continue.
                    user_pending_conf = get_pending_confirmation(sender_number, chat_jid)
                    if user_pending_conf:
                        quoted_pending_ref = f"{chat_jid}:{sender_number}"
                    else:
                        user_pending_key = pending_key(sender_number, chat_jid)
                        user_pending_data = _pending_transactions.get(user_pending_key)
                        if user_pending_data and not pending_is_expired(user_pending_data):
                            quoted_pending_ref = user_pending_key
                if not quoted_pending_ref:
                    if should_send_group_reply_hint(chat_jid, sender_number, "reply_required_for_answers"):
                        send_reply("⚠️ Untuk jawaban (angka/ya/nominal), wajib *reply* ke pesan bot yang ingin dijawab.")
                    return jsonify({'status': 'reply_required_for_answers'}), 200

        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        from handlers.pending_handler import handle_pending_response
        quoted_pending_key = ''
        pending_conf_key = ''
        if is_group and quoted_msg_id:
            quoted_pending_key = get_pending_key_from_message(quoted_msg_id) or ''
            if quoted_pending_key:
                secure_log("DEBUG", f"Found pending ref: {quoted_msg_id[:20]}... -> {quoted_pending_key}")
            else:
                secure_log("DEBUG", f"No pending ref for quoted_msg_id: {quoted_msg_id[:20]}...")

        pending_conf = None
        if is_group and quoted_pending_key:
            # Reply to bot prompt takes precedence and can target any user's session.
            pending_conf = _get_pending_confirmation_by_key(quoted_pending_key)
            if pending_conf:
                pending_conf_key = quoted_pending_key

        if not pending_conf:
            pending_conf = get_pending_confirmation(sender_number, chat_jid)
            if pending_conf:
                pending_conf_key = f"{chat_jid}:{sender_number}"

        if not pending_conf and is_group and text and not quoted_msg_id:
            # Allow other group members to answer if only one pending confirmation exists
            t = text.strip().lower()
            has_choice_token = bool(re.search(r"(?<!\d)[12](?![\d.,])", t))
            is_quick_reply = (
                bool(re.fullmatch(r"\d{1,2}", t)) or
                has_choice_token or
                t in ['ya', 'y', 'iya', 'ok', 'oke', 'yes', 'no', 'tidak', 'bukan',
                      'simpan', 'batal', 'cancel', '/cancel']
            )
            if is_quick_reply:
                conf_key, conf_data = find_pending_confirmation_in_chat(chat_jid)
                if conf_data:
                    # Safety: do not allow cross-user quick reply to execute destructive undo flow.
                    own_conf_key = f"{chat_jid}:{sender_number}"
                    if conf_key != own_conf_key and conf_data.get('type') == 'undo_confirmation':
                        secure_log(
                            "INFO",
                            f"Skip cross-user undo confirmation in group for {sender_number} (owner={conf_key})"
                        )
                    else:
                        pending_conf = conf_data
                        pending_conf_key = conf_key
        if pending_conf:
            if input_type == 'image' and not (text or '').strip():
                secure_log(
                    "INFO",
                    f"Buffered image {message_id} while pending confirmation is active; waiting user reply"
                )
                return jsonify({'status': 'buffered_image_pending_confirmation'}), 200
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
                    bid = extract_bot_msg_id(sent)
                    if bid and pending_conf_key:
                        # Allow next answer to be routed by replying bot prompt message.
                        store_pending_message_ref(bid, pending_conf_key)
                    # Store bot message ref for revision tracking if provided
                    if result.get('bot_ref_event_id'):
                        bid = bid or extract_bot_msg_id(sent)
                        if bid:
                            store_bot_message_ref(bid, result.get('bot_ref_event_id'))
                            store_last_bot_report(chat_jid, bid)
                        store_last_tx_event(sender_number, chat_jid, result.get('bot_ref_event_id'))
                
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
            mapped = quoted_pending_key or get_pending_key_from_message(quoted_msg_id)
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
                        if not isinstance(pkey, str):
                            continue
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
        quoted_visual_item = None
        if is_group and quoted_msg_id:
            quoted_visual_item = get_visual_buffer_by_message(chat_jid, quoted_msg_id)
        quoted_visual_actionable = bool(quoted_visual_item and _should_bind_visual_text(text))
        has_visual = (
            has_visual_buffer(sender_number, chat_jid) or quoted_visual_actionable
        ) if is_group else False
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

            if is_prefix_match(text, Commands.LUNAS_PREFIXES, is_group):
                try:
                    match = re.search(r"\b(\d+)\b", text)
                    if not match:
                        send_reply("Format: /lunas NO_HUTANG (contoh: /lunas 3)")
                        return jsonify({'status': 'command_lunas_invalid'}), 200
                    no = int(match.group(1))
                    info = update_hutang_status_by_no(no, "PAID")
                    if not info:
                        send_reply("No hutang tidak ditemukan.")
                        return jsonify({'status': 'command_lunas_not_found'}), 200
                    invalidate_dashboard_cache()
                    msg = (
                        f"Hutang #{info['no']} ditandai PAID.\n"
                        f"{info.get('keterangan', '-')}\n"
                        f"{info.get('yang_hutang', '-')} -> {info.get('yang_dihutangi', '-')}\n"
                        f"Rp {info.get('amount', 0):,}"
                    )
                    send_reply(msg.replace(',', '.'))
                    return jsonify({'status': 'command_lunas'}), 200
                except Exception as e:
                    send_reply(f"Error: {str(e)}")
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
                    send_reply("🤔 Menganalisis data...")
                    
                    # Get answer with real data
                    answer = handle_query_command(query, sender_number, chat_jid)
                    
                    # Send answer
                    response = answer
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
                        if has_project_word:
                            smart_scope = "PROJECT"
                        elif has_kantor_word or has_operational_kw:
                            smart_scope = "OPERATIONAL"
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
                        auto_hutang = _handle_auto_hutang_payment(text)
                        if auto_hutang:
                            send_reply(auto_hutang)
                            return jsonify({'status': 'auto_hutang_paid'}), 200
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

                        text_lower = (text or "").lower()
                        has_project_context = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
                        has_spending_context = bool(
                            re.search(
                                r"\b(beli|pembelian|bayar|biaya|material|upah|jasa|ongkir|transport|belanja|buat|untuk)\b",
                                text_lower
                            )
                        )

                        # Safety: don't force TRANSFER for project expense text that only mentions a dompet.
                        if has_project_context and has_spending_context and not is_saldo_update(text):
                            intent = "RECORD_TRANSACTION"
                            layer_category_scope = "PROJECT"
                            transfer_dompet = resolve_dompet_from_text(text)
                            secure_log(
                                "INFO",
                                "Transfer intent downgraded to RECORD_TRANSACTION due project expense context"
                            )
                        else:
                            layer_category_scope = "TRANSFER"
                            # Try to resolve dompet directly from text to avoid extra prompts
                            transfer_dompet = resolve_dompet_from_text(text)

                    if intent == "RECORD_TRANSACTION":
                        # Logic continues to Step 8 (Extraction) with refined text/scope
                        if (
                            input_type == 'image'
                            and layer_category_scope in ['UNKNOWN', 'AMBIGUOUS']
                            and recent_scope_hint in {'OPERATIONAL', 'PROJECT'}
                        ):
                            layer_category_scope = recent_scope_hint
                            if not (text or '').strip() and recent_text_for_image:
                                text = recent_text_for_image
                            secure_log(
                                "INFO",
                                f"Applied recent text scope hint for image: {layer_category_scope}"
                            )
                        
                        # PRE-EMPTIVE CONFIRMATION FOR AMBIGUOUS SCOPE
                        # If AI is unsure (AMBIGUOUS) or UNKNOWN, ask user before extraction/saving
                        if layer_category_scope in ['UNKNOWN', 'AMBIGUOUS']:
                            if input_type == 'image' and not _claim_visual_source_once():
                                return jsonify({'status': 'duplicate_visual_reference'}), 200
                            # Extract temporarily to show context
                            inp, media_list, caption = build_extraction_inputs(
                                text, input_type, media_url, local_media_path
                            )
                            temp_txs = safe_extract(
                                inp, input_type, sender_name, media_list, caption
                            )
                            
                            if temp_txs is None:
                                if input_type == 'image':
                                    _release_visual_source_claim()
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
                                response = """🤔 Ini untuk Operational Kantor atau Project?
 
 1️⃣ Operational Kantor
    (Gaji staff, listrik, wifi, ATK, dll)
 
 2️⃣ Project  
    (Material, upah tukang, transport ke site)
 
 Balas 1 atau 2"""
                                sent = send_reply(response)
                                bid = extract_bot_msg_id(sent)
                                if bid:
                                    store_pending_message_ref(bid, f"{chat_jid}:{sender_number}")
                                return jsonify({'status': 'asking_scope'}), 200
            
            # Check visual link
            if input_type == 'text':
                visual_item = quoted_visual_item if quoted_msg_id else None
                if quoted_msg_id and not visual_item:
                    visual_item = get_visual_buffer_by_message(chat_jid, quoted_msg_id)
                if quoted_msg_id and not visual_item and _should_bind_visual_text(text):
                    if is_visual_message_consumed(chat_jid, quoted_msg_id):
                        send_reply("ℹ️ Struk ini sudah diproses. Gunakan /revisi atau /undo jika perlu koreksi.")
                        return jsonify({'status': 'duplicate_visual_reference'}), 200

                if not visual_item:
                    user_buf = get_visual_buffer(sender_number, chat_jid)
                    for item in user_buf:
                        candidate_id = item.get('message_id')
                        if candidate_id and is_visual_message_consumed(chat_jid, candidate_id):
                            continue
                        visual_item = item
                        break

                if visual_item and _should_bind_visual_text(text):
                    candidate_id = str(visual_item.get('message_id') or "")
                    if candidate_id and is_visual_message_consumed(chat_jid, candidate_id):
                        send_reply("ℹ️ Struk ini sudah diproses. Gunakan /revisi atau /undo jika perlu koreksi.")
                        return jsonify({'status': 'duplicate_visual_reference'}), 200

                    media_url = visual_item.get('media_url')
                    local_media_path = visual_item.get('media_path')
                    buf_caption = visual_item.get('caption') or ''

                    # If user says "catat diatas" and caption exists, use caption as text
                    ref_phrase = re.search(r'\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b', (text or '').lower())
                    if ref_phrase and buf_caption.strip():
                        text = buf_caption.strip()

                    input_type = 'image'
                    if candidate_id:
                        bound_visual_message_id = candidate_id

        # 5. REVISION HANDLER (New)
        clean_text = (text or "").strip().lower()
        digit_count = sum(ch.isdigit() for ch in clean_text)
        is_quick_control_reply = (
            bool(re.fullmatch(r"\d{1,2}", clean_text)) or
            clean_text in {
                'ya', 'y', 'iya', 'yes', 'ok', 'oke',
                'tidak', 'no', 'bukan', 'batal', 'cancel', '/cancel', 'simpan'
            }
        )
        has_revision_keyword = any(
            kw in clean_text for kw in {
                'revisi', 'ubah', 'ganti', 'koreksi', 'salah',
                'operasional', 'operational', 'project', 'projek'
            }
        )
        is_likely_amount_revision = (digit_count >= 2 and not is_quick_control_reply)
        should_try_quoted_revision = (
            bool(quoted_msg_id) and
            (not has_pending) and
            (has_revision_keyword or is_likely_amount_revision)
        )

        if should_try_quoted_revision or is_command_match(text, Commands.UNDO, is_group) or is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
            from handlers.revision_handler import handle_revision_command, handle_undo_command
            
            revision_result = None
            
            # Check for standard commands
            if is_command_match(text, Commands.UNDO, is_group):
                 revision_result = handle_undo_command(sender_number, chat_jid)
            
            # Check for /revisi command or reply revision
            elif should_try_quoted_revision or is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
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
            # Keep text-merge strict so short replies like "3" are not treated as new transactions.
            clean_pending_reply = (text or "").strip().lower()
            is_short_numeric_reply = bool(re.fullmatch(r"\d{1,2}", clean_pending_reply))
            is_quick_control_reply = (
                is_short_numeric_reply or
                clean_pending_reply in {
                    'ya', 'y', 'iya', 'yes', 'ok', 'oke',
                    'tidak', 'no', 'bukan', 'batal', 'cancel', '/cancel', 'simpan'
                }
            )
            is_potential_text_tx = (
                intent in {'UNKNOWN', 'RECORD_TRANSACTION'}
                and bool(text)
                and bool(has_amount_pattern(text))
                and not is_short_numeric_reply
            )
            expects_selection_reply = ptype in {
                'selection',
                'select_source_wallet',
                'confirmation_project',
                'confirmation_new_project',
                'confirmation_dupe',
                'needs_project',
            }

            # Guard stale pending entries (e.g., confirmation state missing after restart/replica drift).
            if ptype is None and is_quick_control_reply:
                _pending_transactions.pop(pending_pkey, None)
                send_reply("⚠️ Tidak ada pertanyaan aktif untuk balasan itu. Balas ke prompt bot terbaru atau kirim ulang transaksi.")
                return jsonify({'status': 'stale_pending'}), 200
            
            if (
                input_type == 'image'
                or (
                    not expects_selection_reply
                    and (
                        # Keep text-merge strict during pending to avoid group chatter being queued.
                        is_potential_text_tx
                        or (
                            explicit_catat
                            and bool(text)
                            and not is_short_numeric_reply
                        )
                    )
                )
            ):
                if input_type == 'image' and not _claim_visual_source_once():
                    return jsonify({'status': 'duplicate_visual_reference'}), 200
                inp, media_list, caption = build_extraction_inputs(
                    text, input_type, media_url, local_media_path
                )
                new_txs = safe_extract(
                    inp, input_type, sender_name, media_list, caption
                )
                
                if new_txs is None:
                    if input_type == 'image':
                        _release_visual_source_claim()
                    return jsonify({'status': 'rate_limit'}), 200
                if new_txs:
                    merged_txs, merge_meta = _merge_transaction_queue(
                        pending.get('transactions', []),
                        new_txs
                    )
                    pending['transactions'] = merged_txs

                    if merge_meta.get('added', 0) > 0 or merge_meta.get('upgraded', 0) > 0:
                        send_reply("Menambahkan ke antrian transaksi...")
                    else:
                        send_reply("Item terdeteksi duplikat. Antrian tidak berubah.")

                    if merge_meta.get('duplicates', 0) > 0 or merge_meta.get('upgraded', 0) > 0:
                        secure_log(
                            "INFO",
                            (
                                f"Pending merge {pending_pkey}: "
                                f"added={merge_meta.get('added', 0)}, "
                                f"upgraded={merge_meta.get('upgraded', 0)}, "
                                f"duplicates={merge_meta.get('duplicates', 0)}"
                            )
                        )

                    state_manager_module.set_pending_transaction(pending_pkey, pending)
                    if claimed_visual_source_id:
                        remove_visual_buffer_by_message(chat_jid, claimed_visual_source_id)

                    missing_tx = _first_missing_amount_tx(merged_txs)
                    if missing_tx:
                        pending['pending_type'] = 'needs_amount'
                        state_manager_module.set_pending_transaction(pending_pkey, pending)
                        item = missing_tx.get('keterangan', 'Transaksi')
                        send_reply(f"Nominal untuk \"{item}\" berapa? (contoh: 150rb)")
                        return jsonify({'status': 'asking_amount'}), 200

                    # Re-send updated prompt
                    reply = build_selection_prompt(merged_txs)
                    if is_group: reply += "\n\n↩️ Reply angka 1-5"
                    send_reply(reply)
                    return jsonify({'status': 'merged'}), 200
                
                # If image provided no transaction data during pending state, IGNORE it.
                # Don't let it fall through to 'selection' validation which would error.
                if input_type == 'image':
                    _release_visual_source_claim()
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
                    # In busy groups, ignore normal chatter while waiting nominal.
                    # Reply only when user is clearly interacting with this pending flow.
                    if is_group:
                        explicit_call = False
                        try:
                            explicit_call = is_explicit_bot_call(text)
                        except Exception:
                            explicit_call = False

                        is_pending_interaction = bool(
                            is_reply_to_bot
                            or explicit_call
                            or has_amount_pattern(text)
                            or is_command_match(text, Commands.CANCEL, is_group)
                        )
                        if not is_pending_interaction:
                            return jsonify({'status': 'ignored_pending_chatter'}), 200

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
                if pending.get('new_project_first_expense'):
                    if clean in ['1', 'ya', 'y', 'ok', 'siap', 'lanjut']:
                        pending['project_confirmed'] = True
                        pending['is_new_project'] = True
                        pending['project_validated'] = True
                        pending['new_project_first_expense_confirmed'] = True
                        pending.pop('new_project_first_expense', None)
                        return finalize_transaction_workflow(pending, pending_pkey)
                    if clean in ['2', 'operasional', 'kantor']:
                        pending['pending_type'] = 'select_source_wallet'
                        pending['is_operational'] = True
                        pending['operational_category'] = pending.get('operational_category', 'Lain Lain')
                        pending['project_confirmed'] = False
                        pending.pop('new_project_first_expense', None)
                        prompt = format_wallet_selection_prompt()
                        send_reply(f"🏢 Diganti ke Operasional Kantor\n\n{prompt}".replace('*', ''))
                        return jsonify({'status': 'switch_to_operational'}), 200
                    if clean in ['3', 'batal', 'cancel', 'tidak', 'no']:
                        _pending_transactions.pop(pending_pkey, None)
                        send_reply("❌ Dibatalkan.")
                        return jsonify({'status': 'cancelled'}), 200
                    # Treat input as new project name
                    final_proj = sanitize_input(text.strip())
                    if len(final_proj) < 3:
                        send_reply("⚠️ Nama terlalu pendek.")
                        return jsonify({'status': 'invalid'}), 200
                    res_check = resolve_project_name(strip_company_prefix(final_proj))
                    if res_check.get('final_name'):
                        final_proj = res_check['final_name']
                    if res_check.get('status') == 'NEW':
                        pending['is_new_project'] = True
                    pending['new_project_first_expense_confirmed'] = True
                    for t in pending['transactions']:
                        t['nama_projek'] = final_proj
                    pending['project_confirmed'] = True
                    pending['project_validated'] = True
                    pending.pop('new_project_first_expense', None)
                    return finalize_transaction_workflow(pending, pending_pkey)
                if clean.isdigit() and len(clean) <= 2 and clean not in ['1']:
                    send_reply("Balas 'Ya' untuk membuat project baru, atau ketik nama project yang benar.")
                    return jsonify({'status': 'invalid'}), 200

                if clean in ['1', 'ya', 'y', 'ok', 'siap', 'buat', 'lanjut']:
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
                    send_reply(f"🏢 Diganti ke Operasional Kantor\n\n{prompt}".replace('*', ''))
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
                    
                    result = process_undo_deletion(
                        pending.get('transactions', []),
                        pending.get('original_message_id')
                    )
                    
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
        
        if is_prefix_match(text, Commands.LUNAS_PREFIXES, is_group):
            try:
                match = re.search(r"\b(\d+)\b", text)
                if not match:
                    send_reply("Format: /lunas NO_HUTANG (contoh: /lunas 3)")
                    return jsonify({'status': 'command_lunas_invalid'}), 200
                no = int(match.group(1))
                info = update_hutang_status_by_no(no, "PAID")
                if not info:
                    send_reply("No hutang tidak ditemukan.")
                    return jsonify({'status': 'command_lunas_not_found'}), 200
                invalidate_dashboard_cache()
                msg = (
                    f"Hutang #{info['no']} ditandai PAID.\n"
                    f"{info.get('keterangan', '-')}\n"
                    f"{info.get('yang_hutang', '-')} -> {info.get('yang_dihutangi', '-')}\n"
                    f"Rp {info.get('amount', 0):,}"
                )
                send_reply(msg.replace(',', '.'))
                return jsonify({'status': 'command_lunas'}), 200
            except Exception as e:
                send_reply(f"Error: {str(e)}")
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
 
        # Group image grace period: give users time to type after sending image
        if (
            input_type == 'image'
            and is_group
            and not has_pending
            and not deferred
        ):
            caption_text = (text or "").strip()
            caption_should_process = False
            if caption_text:
                caption_should_process, _ = should_respond_in_group(
                    caption_text,
                    is_group,
                    has_media=False,
                    has_pending=False,
                    is_mentioned=is_explicit_bot_call(caption_text)
                )
            if not caption_should_process:
                schedule_group_image_grace()
                return jsonify({'status': 'queued_image'}), 200

        # 8. PROCESS NEW INPUT (AI)
        transactions = []
        try:
            if input_type == 'image' and not (media_url or local_media_path):
                if (text or '').strip():
                    secure_log("WARNING", "Image input without media payload; fallback to text-only extraction")
                    input_type = 'text'
                else:
                    send_reply("❗ Gambar tidak bisa diunduh. Tolong kirim ulang struk atau tambahkan caption transaksi.")
                    return jsonify({'status': 'image_missing_media'}), 200

            if input_type == 'image' and not _claim_visual_source_once():
                return jsonify({'status': 'duplicate_visual_reference'}), 200
            if not processing_ack_sent:
                send_reply("🔍 Scan...")
            
            inp, media_list, caption = build_extraction_inputs(
                text, input_type, media_url, local_media_path
            )
            transactions = safe_extract(inp, input_type, sender_name, media_list, caption)
            if transactions is None:
                if input_type == 'image':
                    _release_visual_source_claim()
                return jsonify({'status': 'rate_limit'}), 200

            transactions, extracted_meta = _merge_transaction_queue([], transactions or [])
            if extracted_meta.get('duplicates', 0) > 0 or extracted_meta.get('upgraded', 0) > 0:
                secure_log(
                    "INFO",
                    (
                        f"Extract normalization: "
                        f"added={extracted_meta.get('added', 0)}, "
                        f"upgraded={extracted_meta.get('upgraded', 0)}, "
                        f"duplicates={extracted_meta.get('duplicates', 0)}"
                    )
                )
            
            if not transactions:
                if input_type == 'image':
                    _release_visual_source_claim()
                if message_id:
                    clear_message_duplicate(message_id)
                if input_type == 'image': send_reply("❓ Tidak terbaca.")
                return jsonify({'status': 'no_tx'}), 200
            
            # Clear visual buffer on successful extraction to avoid double-binding
            if input_type == 'image':
                if claimed_visual_source_id:
                    remove_visual_buffer_by_message(chat_jid, claimed_visual_source_id)
                else:
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

            # OCR safety: ask confirmation for single-transaction images (strict mode only)
            if (not FAST_MODE) and input_type == 'image' and len(transactions) == 1:
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
            missing_tx = _first_missing_amount_tx(transactions)
            if missing_tx:
                for t in transactions:
                    try:
                        if int(t.get('jumlah', 0) or 0) <= 0:
                            t['needs_amount'] = True
                    except Exception:
                        t['needs_amount'] = True
                _pending_transactions[sender_pkey]['pending_type'] = 'needs_amount'
                item = missing_tx.get('keterangan', 'Transaksi')
                send_reply(f"❗ Nominal untuk \"{item}\" berapa? (contoh: 150rb)")
                return jsonify({'status': 'asking_amount'}), 200

            if all(t.get('nama_projek') and not t.get('needs_project') for t in transactions):
                _pending_transactions[sender_pkey]['project_confirmed'] = True
            
            # Check for Needs Project (Manual override from AI)
            if layer_category_scope == 'TRANSFER':
                text_lower = (text or "").lower()
                has_project_context = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
                has_non_saldo_project = any(
                    (t.get('nama_projek') or '').strip()
                    and (t.get('nama_projek') or '').strip().lower() not in {'saldo umum', 'umum', 'operasional kantor'}
                    for t in transactions
                )
                if has_project_context or has_non_saldo_project:
                    layer_category_scope = 'PROJECT'
                elif not is_saldo_update(text):
                    layer_category_scope = 'UNKNOWN'

            if layer_category_scope == 'TRANSFER':
                # Force "Saldo Umum" for explicit wallet updates
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
            if input_type == 'image':
                _release_visual_source_claim()
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
            if input_type == 'image':
                _release_visual_source_claim()
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
