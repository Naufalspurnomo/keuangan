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
    DOMPET_SHEETS, DOMPET_COMPANIES, SELECTION_OPTIONS,
    get_selection_by_idx, get_dompet_for_company,
    find_transaction_by_message_id, update_transaction_amount,
)
from wuzapi_helper import (
    send_wuzapi_reply,
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
)
from reminder import (
    update_user_activity,
    toggle_reminder,
    start_scheduler,
    get_weekly_summary,
)
from pdf_report import generate_pdf_from_input, parse_month_input, validate_period_data

# Import from new modular services
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
)

from utils.parsers import (
    parse_selection,
    parse_revision_amount,
    should_respond_in_group,
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


# Legacy: Keep reference to _pending_transactions for backward compatibility
# Now managed by services.state_manager
from services import state_manager as _state


# ===================== GROUP & SELECTION HELPERS =====================
# Now imported from utils.parsers and utils.formatters


def parse_selection(text: str) -> tuple:
    """
    Parse user selection input (1-5).
    
    Returns:
        (is_valid: bool, selection: int, error_message: str)
    """
    text = text.strip()
    
    # Check for cancel
    if text.lower() in ['/cancel', 'batal', 'cancel']:
        return False, 0, "cancel"
    
    # Check for multi-selection (not allowed)
    if ',' in text or ' ' in text.strip():
        return False, 0, "Pilih satu saja. Ketik angka 1-5."
    
    # Try to parse as number
    try:
        num = int(text)
        if 1 <= num <= 5:
            return True, num, ""
        else:
            return False, 0, "Pilihan tidak tersedia. Ketik angka 1-5."
    except ValueError:
        return False, 0, "Balas dengan angka 1-5 untuk memilih."


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


# ===================== REVISION HELPERS =====================

# Store bot's confirmation message IDs -> original message ID mapping
# Format: {bot_msg_id: original_tx_msg_id}
_bot_message_refs = {}

def parse_revision_amount(text: str) -> int:
    """
    Parse amount from revision text.
    Supports: "/revisi 150rb", "150000", "150rb", "1.5jt", "2 juta", etc.
    
    Returns:
        Amount in Rupiah, or 0 if not parseable
    """
    import re
    
    # Clean the text
    text = text.lower().strip()
    
    # Remove /revisi or revisi prefix
    text = re.sub(r'^[/]?(revisi|ubah|ganti|koreksi|edit)\s*', '', text).strip()
    
    # Handle "2 juta", "500 rb", "1.5jt" - number followed by optional space and suffix
    match = re.match(r'^([\d]+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta)?$', text)
    if match:
        num_str = match.group(1)
        suffix = match.group(2) or ''
        
        # Replace comma with dot for decimal (Indonesian uses comma as decimal)
        num_str = num_str.replace(',', '.')
        
        try:
            num = float(num_str)
        except ValueError:
            return 0
        
        if suffix in ['rb', 'ribu', 'k']:
            return int(num * 1000)
        elif suffix in ['jt', 'juta']:
            return int(num * 1000000)
        else:
            # No suffix - if it has decimal, it's probably already in full amount
            return int(num)
    
    # Try direct number (just digits after cleaning)
    cleaned = text.replace('.', '').replace(',', '').replace(' ', '')
    try:
        return int(cleaned)
    except ValueError:
        return 0


def store_bot_message_ref(bot_msg_id: str, original_tx_msg_id: str):
    """Store reference from bot's confirmation message to original transaction message ID."""
    global _bot_message_refs
    _bot_message_refs[str(bot_msg_id)] = str(original_tx_msg_id)
    
    # Limit cache size to prevent memory issues
    if len(_bot_message_refs) > 1000:
        # Remove oldest entries (first 500)
        keys_to_remove = list(_bot_message_refs.keys())[:500]
        for key in keys_to_remove:
            _bot_message_refs.pop(key, None)


def get_original_message_id(bot_msg_id: str) -> str:
    """Get original transaction message ID from bot's confirmation message ID."""
    return _bot_message_refs.get(str(bot_msg_id), '')


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
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    lines.append(f"⏱️ {now}")
    
    # Next steps
    lines.append("\n💡 Ralat jumlah: reply /revisi 150rb")
    lines.append("📊 Cek ringkas: /status | /saldo")
    
    return '\n'.join(lines)

# ===================== WUZAPI HANDLERS =====================

@app.route('/webhook_wuzapi', methods=['POST'])
def webhook_wuzapi():
    """Handle incoming messages from WuzAPI.
    
    WuzAPI sends webhooks as URL-encoded form data:
    - instanceName: instance name
    - jsonData: URL-encoded JSON with event data
    - userID: instance ID
    """
    try:
        import json
        from urllib.parse import unquote
        
        # WuzAPI sends form data, not JSON!
        # Format: instanceName=...&jsonData=...&userID=...
        instance_name = request.form.get('instanceName')
        json_data_raw = request.form.get('jsonData')
        user_id_param = request.form.get('userID')
        
        # Debug log
        secure_log("DEBUG", f"WuzAPI Form: instance={instance_name}, userID={user_id_param}")
        
        if not json_data_raw:
            # Fallback block disabled to prevent double-processing / duplicates
            # data = request.get_json(force=True, silent=True)
            # if data and 'data' in data:
            #     # Manual test format
            #     msg_data = data['data']
            #     remote_jid = msg_data.get('key', {}).get('remoteJid', '')
            #     sender_number = remote_jid.split('@')[0] if remote_jid else ''
            #     sender_name = msg_data.get('pushName', 'User')
            #     raw_msg = msg_data.get('message', {})
            #     text = raw_msg.get('conversation', '')
            #     
            #     if text:
            #         secure_log("INFO", f"WuzAPI message from {sender_number}")
            #         return process_wuzapi_message(sender_number, sender_name, text)
            secure_log("WARNING", "WuzAPI: No 'data' parameter found in POST request")
            return jsonify({'status': 'no_data'}), 200
        
        # Parse the URL-encoded JSON data
        try:
            event_data = json.loads(json_data_raw)
        except json.JSONDecodeError:
            secure_log("ERROR", f"WuzAPI JSON parse failed: {json_data_raw[:200]}")
            return jsonify({'status': 'parse_error'}), 200
        
        secure_log("DEBUG", f"WuzAPI Event: {json.dumps(event_data)[:300]}")
        
        # Check if WuzAPI sends base64 image directly in event
        # Format: {"base64": "/9j/4AAQSkZJRg...", "event": {...}}
        base64_image = event_data.get('base64', '')
        
        # Check event type
        event_type = event_data.get('type', '')
        event = event_data.get('event', {})
        
        # Skip non-message events
        if event_type in ['Connected', 'OfflineSyncCompleted', 'OfflineSyncPreview', 'ReadReceipt', 'Receipt']:
            return jsonify({'status': 'ignored_event'}), 200
        
        # Get message info
        info = event.get('Info', event)  # Some events have Info wrapper, some don't
        
        # Skip if IsFromMe (bot's own messages)
        if info.get('IsFromMe', False):
            return jsonify({'status': 'own_message'}), 200
        
        # Get sender - prefer SenderAlt which has the phone@s.whatsapp.net format
        sender_alt = info.get('SenderAlt', '')
        sender_jid = info.get('Sender', '')
        
        # Extract phone number from SenderAlt (format: 6281212042709:72@s.whatsapp.net or 6281212042709@s.whatsapp.net)
        if sender_alt and '@s.whatsapp.net' in sender_alt:
            sender_number = sender_alt.split('@')[0].split(':')[0]
        elif sender_jid and '@' in sender_jid:
            sender_number = sender_jid.split('@')[0].split(':')[0]
        else:
            secure_log("DEBUG", f"WuzAPI: No valid sender found")
            return jsonify({'status': 'no_sender'}), 200
        
        # Get message content
        msg_type = info.get('Type', '')
        push_name = info.get('PushName', 'User')
        message_id = info.get('ID', '')
        chat_jid = info.get('Chat', '')
        
        # Get the actual message text
        message_obj = event.get('Message', {})
        text = ''
        input_type = 'text'
        media_url = None  # Changed from media_path to media_url
        
        # DEBUG: Log full message object structure to find quote info
        secure_log("DEBUG", f"WuzAPI message_obj keys: {list(message_obj.keys())}")
        secure_log("DEBUG", f"WuzAPI message_obj full: {json.dumps(message_obj)[:500]}")
        media_url = None  # Changed from media_path to media_url
        
        if msg_type == 'text':
            # Text message - check various fields
            text = message_obj.get('conversation', '') or \
                   message_obj.get('Conversation', '') or \
                   message_obj.get('extendedTextMessage', {}).get('text', '') or \
                   message_obj.get('ExtendedTextMessage', {}).get('Text', '')
            
            # Extract quoted message ID (for revision feature)
            # WuzAPI sends contextInfo in various formats depending on version
            quoted_msg_id = ''
            
            # Try extendedTextMessage format (most common for replies)
            ext_text = message_obj.get('extendedTextMessage', {}) or message_obj.get('ExtendedTextMessage', {})
            if ext_text:
                context_info = ext_text.get('contextInfo', {}) or ext_text.get('ContextInfo', {})
                # WuzAPI sends 'stanzaID' (uppercase ID), not 'stanzaId'
                quoted_msg_id = context_info.get('stanzaID', '') or context_info.get('stanzaId', '') or context_info.get('StanzaId', '') or context_info.get('quotedMessageId', '')
                secure_log("DEBUG", f"WuzAPI ExtText contextInfo: {json.dumps(context_info)[:200]}")
            
            # Also check top-level contextInfo (some WuzAPI versions)
            if not quoted_msg_id:
                top_context = message_obj.get('contextInfo', {}) or message_obj.get('ContextInfo', {})
                if top_context:
                    quoted_msg_id = top_context.get('stanzaID', '') or top_context.get('stanzaId', '') or top_context.get('StanzaId', '') or top_context.get('quotedMessageId', '')
                    secure_log("DEBUG", f"WuzAPI Top contextInfo: {json.dumps(top_context)[:200]}")
            
            # Check event-level context (another variant)
            if not quoted_msg_id:
                event_context = event.get('ContextInfo', {}) or event.get('contextInfo', {})
                if event_context:
                    quoted_msg_id = event_context.get('stanzaID', '') or event_context.get('stanzaId', '') or event_context.get('StanzaId', '')
                    secure_log("DEBUG", f"WuzAPI Event contextInfo: {json.dumps(event_context)[:200]}")
            
            secure_log("DEBUG", f"WuzAPI quoted_msg_id resolved: '{quoted_msg_id}', message_obj keys: {list(message_obj.keys())}")
            
        elif msg_type == 'media':
            # Media with caption
            caption = message_obj.get('imageMessage', {}).get('caption', '') or \
                     message_obj.get('ImageMessage', {}).get('Caption', '') or \
                     message_obj.get('caption', '')
            text = caption
            input_type = 'image'
            quoted_msg_id = ''  # Initialize for media messages
            
            # Use base64 image directly from event_data if available
            if base64_image:
                secure_log("INFO", f"WuzAPI: Using base64 image from webhook (length: {len(base64_image)})")
                media_url = f"data:image/jpeg;base64,{base64_image}"
            else:
                # Fallback: try to download the image from WuzAPI
                if message_id and chat_jid:
                    secure_log("INFO", f"WuzAPI downloading image: msg={message_id}, chat={chat_jid}")
                    media_path = download_wuzapi_image(message_id, chat_jid)
                    
                    if media_path:
                        secure_log("INFO", f"WuzAPI image downloaded to: {media_path}")
                        # Convert to base64
                        import base64 as b64
                        try:
                            with open(media_path, 'rb') as f:
                                img_data = b64.b64encode(f.read()).decode('utf-8')
                                media_url = f"data:image/jpeg;base64,{img_data}"
                        except Exception as e:
                            secure_log("ERROR", f"Failed to read downloaded image: {str(e)}")
                    else:
                        secure_log("WARNING", "WuzAPI image download failed, using caption only")
                        input_type = 'text'  # Fall back to text-only processing
        else:
            # Unknown message type
            quoted_msg_id = ''
        
        # For text messages without any text, skip
        if not text and input_type == 'text':
            secure_log("DEBUG", f"WuzAPI: No text in message. Type={msg_type}, Msg={json.dumps(message_obj)[:200]}")
            return jsonify({'status': 'no_text'}), 200
        
        secure_log("INFO", f"WuzAPI message from {sender_number}: {text[:50] if text else '[image]'}, has_media={media_url is not None}, quoted={quoted_msg_id}, msg_id={message_id}")

        # DEDUP: Skip if message already processed (multi-worker safe)
        if is_message_duplicate(message_id):
            secure_log("DEBUG", f"WuzAPI: Duplicate message_id={message_id}, skipping")
            return jsonify({'status': 'duplicate'}), 200

        # Determine if it's a group chat
        is_group = '@g.us' in chat_jid
        
        # Process the message (with image URL and message IDs)
        # Pass chat_jid so group messages get replies in the group, not personal chat
        return process_wuzapi_message(sender_number, push_name, text, input_type, media_url, quoted_msg_id, message_id, is_group, chat_jid)
        
    except Exception as e:
        secure_log("ERROR", f"Webhook WuzAPI Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500


def process_wuzapi_message(sender_number: str, sender_name: str, text: str, 
                           input_type: str = 'text', media_url: str = None,
                           quoted_msg_id: str = None, message_id: str = None,
                           is_group: bool = False, chat_jid: str = None):
    """Process a WuzAPI message and return response.
    
    This mirrors the Telegram command handling for consistency.
    Supports both text and image input types.
    
    Args:
        sender_number: Phone number of sender
        sender_name: Display name of sender  
        text: Message text or caption
        input_type: 'text' or 'image'
        media_url: Base64 data URL for images (data:image/jpeg;base64,...)
        quoted_msg_id: ID of quoted/replied message (for revision)
        message_id: ID of the current message (from WuzAPI)
        is_group: Boolean indicating if it's a group chat
        chat_jid: The chat JID (group ID for groups, personal for DM)
    """
    try:
        # Determine reply destination: for groups, reply to group; for personal, reply to sender
        reply_to = chat_jid if (is_group and chat_jid) else sender_number
        
        # Rate Limit
        allowed, wait_time = rate_limit_check(sender_number)
        if not allowed:
            return jsonify({'status': 'rate_limited'}), 200
        
        # Sanitize
        text = sanitize_input(text or '')
        
        # GROUP CHAT FILTER: Only respond if triggered or command
        # Triggers: +catat, +bot, +input, /catat, or any / command
        # EXCEPTION: If user has pending transaction IN THIS CHAT, allow through
        pkey = pending_key(sender_number, chat_jid)
        pending_data = _pending_transactions.get(pkey)
        
        # Check if pending exists and not expired
        pending_was_expired = False
        if pending_data and pending_is_expired(pending_data):
            _pending_transactions.pop(pkey, None)
            pending_data = None
            pending_was_expired = True
            secure_log("DEBUG", f"Pending expired for {pkey}")
        
        has_pending = pending_data is not None
        
        # If user seems to be replying to expired session (selection-like input but no pending)
        if pending_was_expired:
            text_lower = text.strip().lower()
            # Check if input looks like a pending reply (1-5, project name, etc)
            if text_lower in ['1','2','3','4','5'] or (len(text) > 1 and len(text) < 50 and not text.startswith('/')):
                send_wuzapi_reply(reply_to, 
                    "⌛ Sesi sebelumnya sudah kedaluwarsa (lebih dari 15 menit).\n"
                    "Kirim transaksi lagi ya.")
                return jsonify({'status': 'expired_session'}), 200
        
        # Debug logging for group chat
        if is_group:
            secure_log("DEBUG", f"Group msg from {sender_number}: pkey={pkey}, has_pending={has_pending}, text='{text[:30]}...'")
        
        if is_group and not has_pending:
            should_respond, cleaned_text = should_respond_in_group(text, is_group)
            if not should_respond:
                # No trigger - silently ignore this group message
                secure_log("DEBUG", f"Group msg IGNORED (no trigger, no pending)")
                return jsonify({'status': 'ignored_group'}), 200
            # Use cleaned text (trigger prefix removed)
            text = cleaned_text if cleaned_text else text
        
        
        # GUARD: Check for "revisi" without reply
        if text.lower().startswith('revisi') or text.lower().startswith('/revisi'):
            if not quoted_msg_id:
                send_wuzapi_reply(reply_to, 
                    "⚠️ *Gagal Revisi*\n\n"
                    "Untuk merevisi, Anda harus **me-reply** (balas) pesan konfirmasi bot.\n\n"
                    "1. Reply pesan '✅ Transaksi Tercatat!'\n"
                    "2. Ketik `/revisi [jumlah baru]`")
                return jsonify({'status': 'revision_no_quote'}), 200
        
        # ============ REVISION HANDLER ============
        # Check if user is replying to a bot confirmation message
        if quoted_msg_id and text:
            # Try to resolve original message ID from bot's message ID
            original_msg_ref = get_original_message_id(quoted_msg_id)
            
            # If valid reference found, resolve it. If not, maybe user quoted their own message? (Not supported atm)
            target_msg_id = original_msg_ref if original_msg_ref else quoted_msg_id
            
            # Try to find the original transaction
            original_tx = find_transaction_by_message_id(target_msg_id)
            
            if original_tx:
                # Check directly if text starts with /revisi
                if not text.lower().startswith('/revisi'):
                    send_wuzapi_reply(reply_to, 
                        "⚠️ Format Salah.\n\n"
                        "Untuk merevisi, balas pesan ini dengan format:\n"
                        "`/revisi [jumlah]`\n\n"
                        "Contoh: `/revisi 150000`")
                    return jsonify({'status': 'invalid_format'}), 200

                # Parse the new amount
                new_amount = parse_revision_amount(text)
                
                if new_amount > 0:
                    old_amount = original_tx['amount']
                    
                    # Update the transaction
                    success = update_transaction_amount(
                        original_tx['dompet'], 
                        original_tx['row'], 
                        new_amount
                    )
                    
                    if success:
                        invalidate_dashboard_cache()
                        now = datetime.now().strftime("%d %b %Y, %H:%M")
                        diff = new_amount - old_amount
                        diff_str = f"+Rp {diff:,}" if diff > 0 else f"-Rp {abs(diff):,}"
                        
                        reply = (
                            f"✅ Revisi Berhasil!\n\n"
                            f"📊 {original_tx['keterangan']}\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"   Sebelum: Rp {old_amount:,}\n"
                            f"   Sesudah: Rp {new_amount:,}\n"
                            f"   Selisih: {diff_str}\n"
                            f"━━━━━━━━━━━━━━━━━━\n\n"
                            f"📍 {original_tx['dompet']}\n"
                            f"⏱️ {now}"
                        ).replace(',', '.')
                        send_wuzapi_reply(reply_to, reply)
                        return jsonify({'status': 'revised'}), 200
                    else:
                        send_wuzapi_reply(reply_to, 
                            "❌ Gagal update transaksi.\n\n"
                            "Kemungkinan penyebab:\n"
                            "• Transaksi sudah dihapus\n"
                            "• Koneksi ke spreadsheet gagal\n\n"
                            "Coba lagi atau hubungi admin.")
                        return jsonify({'status': 'revision_error'}), 200
                else:
                    send_wuzapi_reply(reply_to, 
                        "❓ Jumlah tidak valid.\n\n"
                        "Gunakan format:\n"
                        "• /revisi 150000\n"
                        "• /revisi 1.5jt\n"
                        "• /revisi 500rb")
                    return jsonify({'status': 'invalid_revision'}), 200
        

        
        # Check for pending transaction - selection handler
        # We already got pending_data and pkey from group filter above
        if has_pending:
            pending = pending_data  # Already retrieved above
            pending_type = pending.get('pending_type', 'selection')
            
            # Handle cancel for all pending types
            if text.lower() == '/cancel':
                _pending_transactions.pop(pkey, None)
                send_wuzapi_reply(reply_to, "❌ Transaksi dibatalkan.")
                return jsonify({'status': 'cancelled'}), 200
            
            # ===== SMART MODIFIER: Detect commands to modify pending transactions =====
            text_lower = text.lower().strip()
            
            # Patterns for removal commands: "tidak usah X", "hapus X", "cancel X", "jangan X"
            remove_patterns = [
                r'^(?:tidak\s*usah|hapus|cancel|jangan|skip|lewati|buang)\s+(.+)$',
                r'^(.+)\s+(?:tidak\s*usah|hapus|jangan|skip)$',
            ]
            
            for pattern in remove_patterns:
                match = re.match(pattern, text_lower)
                if match:
                    remove_keyword = match.group(1).strip()
                    original_count = len(pending['transactions'])
                    
                    # Filter out transactions that match the keyword
                    pending['transactions'] = [
                        t for t in pending['transactions']
                        if remove_keyword not in t.get('keterangan', '').lower()
                    ]
                    
                    removed_count = original_count - len(pending['transactions'])
                    
                    if removed_count > 0:
                        if len(pending['transactions']) == 0:
                            # All transactions removed
                            _pending_transactions.pop(pkey, None)
                            send_wuzapi_reply(reply_to, "❌ Semua transaksi dihapus. Transaksi dibatalkan.")
                            return jsonify({'status': 'cancelled'}), 200
                        else:
                            # Show remaining transactions
                            remaining = pending['transactions']
                            total = sum(t.get('jumlah', 0) for t in remaining)
                            items = "\n".join([f"💸 {t.get('keterangan', 'Item')}: Rp {t.get('jumlah', 0):,}".replace(',', '.') for t in remaining])
                            
                            msg = (f"✅ Dihapus: {remove_keyword}\n\n"
                                   f"📋 Transaksi tersisa:\n{items}\n\n"
                                   f"Total: Rp {total:,}\n\n").replace(',', '.')
                            
                            # Continue with appropriate prompt based on pending_type
                            if pending_type == 'needs_project':
                                msg += "❓ Untuk projek apa ini?\nBalas dengan nama projek atau /cancel"
                            else:
                                msg += "Ketik 1-5 untuk pilih company atau /cancel"
                            
                            send_wuzapi_reply(reply_to, msg)
                            return jsonify({'status': 'item_removed'}), 200
                    else:
                        # No match found
                        send_wuzapi_reply(reply_to, 
                            f"❓ Tidak menemukan '{remove_keyword}' dalam transaksi pending.\n\n"
                            f"Ketik /cancel untuk batal semua, atau lanjutkan dengan input yang diminta.")
                        return jsonify({'status': 'no_match'}), 200
            
            # ===== HANDLE PROJECT NAME INPUT =====
            if pending_type == 'needs_project':
                project_name = sanitize_input(text.strip())[:100]
                
                if not project_name or len(project_name) < 2:
                    send_wuzapi_reply(reply_to, 
                        "❌ Nama projek tidak valid.\n\n"
                        "Ketik nama projek dengan jelas, contoh:\n"
                        "• Purana Ubud\n"
                        "• Villa Sunset Bali\n\n"
                        "Atau ketik /cancel untuk batal")
                    return jsonify({'status': 'invalid_project'}), 200
                
                # Update transactions with project name
                for t in pending['transactions']:
                    t['nama_projek'] = project_name
                    t.pop('needs_project', None)
                
                # Now check if company is detected
                detected_company = None
                for t in pending['transactions']:
                    if t.get('company'):
                        detected_company = t['company']
                        break
                
                if detected_company:
                    # Has company, auto-save
                    _pending_transactions.pop(pkey, None)
                    dompet = get_dompet_for_company(detected_company)
                    tx_message_id = pending.get('message_id', '')
                    
                    for t in pending['transactions']:
                        t['message_id'] = tx_message_id
                    
                    result = append_transactions(
                        pending['transactions'],
                        pending['sender_name'],
                        pending['source'],
                        dompet_sheet=dompet,
                        company=detected_company
                    )
                    
                    if result['success']:
                        update_user_activity(sender_number, 'wuzapi', pending['sender_name'])
                        invalidate_dashboard_cache()
                        reply = format_success_reply_new(pending['transactions'], dompet, detected_company).replace('*', '')
                        reply += "\n\n💡 Reply pesan ini dengan `/revisi [jumlah]` untuk ralat"
                        sent_msg = send_wuzapi_reply(reply_to, reply)
                        bot_msg_id = None
                        if sent_msg and isinstance(sent_msg, dict):
                            bot_msg_id = (sent_msg.get('data', {}).get('Id') or
                                         sent_msg.get('data', {}).get('id') or
                                         sent_msg.get('key', {}).get('id'))
                        if bot_msg_id and tx_message_id:
                            store_bot_message_ref(bot_msg_id, tx_message_id)
                    else:
                        send_wuzapi_reply(reply_to, f"❌ Gagal: {result.get('company_error', 'Error')}")
                    return jsonify({'status': 'processed'}), 200
                else:
                    # No company, continue to selection
                    pending['pending_type'] = 'selection'
                    reply = build_selection_prompt(pending['transactions']).replace('*', '')
                    send_wuzapi_reply(reply_to, reply)
                    return jsonify({'status': 'asking_company'}), 200
            
            # ===== HANDLE COMPANY SELECTION =====
            is_valid, selection, error_msg = parse_selection(text)
            
            if error_msg == "cancel":
                _pending_transactions.pop(pkey, None)
                send_wuzapi_reply(reply_to, "❌ Transaksi dibatalkan.")
                return jsonify({'status': 'cancelled'}), 200
            
            if not is_valid:
                # Send error feedback
                send_wuzapi_reply(reply_to, f"❌ {error_msg}")
                return jsonify({'status': 'invalid_selection'}), 200
            
            # Valid selection 1-5
            pending = _pending_transactions.pop(pkey)
            option = get_selection_by_idx(selection)
            
            if not option:
                send_wuzapi_reply(reply_to, "❌ Pilihan tidak valid.")
                return jsonify({'status': 'error'}), 200
            
            dompet_sheet = option['dompet']
            company = option['company']
            
            # Inject message_id into transactions if available from pending
            tx_message_id = pending.get('message_id', '')
            for t in pending['transactions']:
                t['message_id'] = tx_message_id
            
            result = append_transactions(
                pending['transactions'], 
                pending['sender_name'], 
                pending['source'],
                dompet_sheet=dompet_sheet,
                company=company
            )
            
            if result['success']:
                update_user_activity(sender_number, 'wuzapi', pending['sender_name'])
                invalidate_dashboard_cache()
                reply = format_success_reply_new(pending['transactions'], dompet_sheet, company).replace('*', '')
                reply += "\n\n💡 Reply pesan ini dengan `/revisi [jumlah]` untuk ralat"
                
                # Send reply and capture bot message ID for revision tracking
                sent_msg = send_wuzapi_reply(reply_to, reply)
                secure_log("DEBUG", f"Selection flow - WuzAPI send response: {str(sent_msg)[:200]}")
                
                # WuzAPI returns: {'data': {'Id': 'xxx'}}
                bot_msg_id = None
                if sent_msg and isinstance(sent_msg, dict):
                    bot_msg_id = (sent_msg.get('data', {}).get('Id') or
                                 sent_msg.get('data', {}).get('id') or
                                 sent_msg.get('key', {}).get('id'))
                
                if bot_msg_id and tx_message_id:
                    store_bot_message_ref(bot_msg_id, tx_message_id)
                    secure_log("INFO", f"Selection flow - Stored bot->tx ref: {bot_msg_id} -> {tx_message_id}")
            else:
                send_wuzapi_reply(reply_to, f"❌ Gagal: {result.get('company_error', 'Error')}")
            return jsonify({'status': 'processed'}), 200
        
        # /start
        if text.lower() == '/start':
            reply = START_MESSAGE.replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        # /help
        if text.lower() == '/help':
            reply = HELP_MESSAGE.replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        # /status or /laporan
        if text.lower() in ['/status', '/laporan', '/cek']:
            invalidate_dashboard_cache()
            send_wuzapi_reply(reply_to, "⏳ Sedang mengambil data status...")
            status_msg = get_status_message().replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, status_msg)
            return jsonify({'status': 'ok'}), 200
        
        # /export
        if text.lower() == '/export':
             pass 

        # AI Extraction for transactions
        transactions = []
        try:
            # === UX: Processing indicator (shorter for groups) ===
            if input_type == 'image':
                send_wuzapi_reply(reply_to, "🔍 Scan..." if is_group else "🔍 Memindai struk...")
            elif text and len(text) > 20 and not is_group:
                # Only show for private chat (reduce group spam)
                send_wuzapi_reply(reply_to, "🔍 Menganalisis...")
            
            # media_url is now passed directly from webhook (already a data URL)
            transactions = extract_financial_data(
                input_data=text or '', 
                input_type=input_type,
                sender_name=sender_name,
                media_url=media_url,
                caption=text if input_type == 'image' else None
            )
            
            if not transactions:
                # No transactions detected - could be a question or invalid input
                if input_type == 'image':
                    send_wuzapi_reply(reply_to, 
                        "❓ Tidak ada transaksi terdeteksi dari gambar.\n\n"
                        "Tips:\n"
                        "• Pastikan struk/nota terlihat jelas\n"
                        "• Tambahkan caption seperti: 'Beli material projek X'")
                    return jsonify({'status': 'no_transactions'}), 200
                
                # If text and not transactions, maybe just text chat? Return OK.
                return jsonify({'status': 'no_transactions_text'}), 200

            # Inject message_id into transactions
            for t in transactions:
                t['message_id'] = message_id

            # Determine Source String
            if is_group:
                source = "WhatsApp Group Image" if input_type == 'image' else "WhatsApp Group"
            else:
                source = "WhatsApp Image" if input_type == 'image' else "WhatsApp"
            
            # Check if any transaction needs project name
            needs_project = any(t.get('needs_project') for t in transactions)
            
            if needs_project:
                # Store as pending and ask user for project name
                _pending_transactions[pkey] = {
                    'transactions': transactions,
                    'sender_name': sender_name,
                    'source': source,
                    'created_at': datetime.now(),
                    'message_id': message_id,
                    'pending_type': 'needs_project',
                    'chat_jid': chat_jid
                }
                
                # Build friendly ask message with all transactions
                total = sum(t.get('jumlah', 0) for t in transactions)
                items_str = "\n".join([
                    f"   {'🟢' if t.get('tipe') == 'Pemasukan' else '🔴'} {t.get('keterangan', 'Item')}: Rp {t.get('jumlah', 0):,}".replace(',', '.')
                    for t in transactions
                ])
                
                item_count = len(transactions)
                ask_msg = (
                    f"📋 Transaksi terdeteksi ({item_count} item)\n"
                    f"{items_str}\n"
                    f"📊 Total: Rp {total:,}\n\n"
                    f"❓ Perlu nama projek (biar laporan per projek rapi)\n"
                    f"Balas: nama projek saja\n"
                    f"Contoh: Purana Ubud / Villa Sunset\n\n"
                    f"⏳ Batas waktu: 15 menit\n"
                    f"Ketik /cancel untuk batal"
                ).replace(',', '.')
                
                send_wuzapi_reply(reply_to, ask_msg)
                return jsonify({'status': 'asking_project'}), 200
            
            # Check if AI detected company from input
            detected_company = None
            detected_dompet = None
            for t in transactions:
                if t.get('company'):
                    detected_company = t['company']
                # For wallet updates, AI extracts which dompet was mentioned
                if t.get('detected_dompet'):
                    detected_dompet = t['detected_dompet']
                if detected_company:
                    break
            
            if detected_company:
                # Auto-save: Company detected, find dompet and save directly
                # For wallet updates (UMUM), use detected_dompet if available
                if detected_company == "UMUM" and detected_dompet:
                    dompet = detected_dompet
                else:
                    dompet = get_dompet_for_company(detected_company)
                
                result = append_transactions(
                    transactions, 
                    sender_name, 
                    source,
                    dompet_sheet=dompet,
                    company=detected_company
                )
                
                if result['success']:
                    update_user_activity(sender_number, 'wuzapi', sender_name)
                    invalidate_dashboard_cache()
                    reply = format_success_reply_new(transactions, dompet, detected_company).replace('*', '')
                    reply += "\n\n💡 Reply pesan ini dengan `/revisi [jumlah]` untuk ralat"
                    
                    # Send reply and capture bot message ID for revision tracking
                    sent_msg = send_wuzapi_reply(reply_to, reply)
                    secure_log("DEBUG", f"WuzAPI send response type: {type(sent_msg)}, content: {str(sent_msg)[:300]}")
                    
                    # WuzAPI can return message ID in different structures
                    bot_msg_id = None
                    if sent_msg and isinstance(sent_msg, dict):
                        # WuzAPI returns: {'data': {'Id': 'xxx'}} - this is the main format
                        bot_msg_id = (sent_msg.get('data', {}).get('Id') or
                                     sent_msg.get('data', {}).get('id') or
                                     sent_msg.get('key', {}).get('id') or 
                                     sent_msg.get('Key', {}).get('ID') or
                                     sent_msg.get('ID') or
                                     sent_msg.get('id') or
                                     sent_msg.get('MessageID') or
                                     sent_msg.get('Info', {}).get('ID'))
                        secure_log("DEBUG", f"Extracted bot_msg_id: {bot_msg_id}")
                    
                    if bot_msg_id and message_id:
                        store_bot_message_ref(bot_msg_id, message_id)
                        secure_log("INFO", f"Stored bot->tx ref: {bot_msg_id} -> {message_id}")
                else:
                    send_wuzapi_reply(reply_to, f"❌ Gagal: {result.get('company_error', 'Error')}")
            else:
                # No company detected - ask for selection
                _pending_transactions[pkey] = {
                    'transactions': transactions,
                    'sender_name': sender_name,
                    'source': source,
                    'created_at': datetime.now(),
                    'message_id': message_id,
                    'chat_jid': chat_jid
                }
                
                # Use the new selection prompt format
                reply = build_selection_prompt(transactions).replace('*', '')
                send_wuzapi_reply(reply_to, reply)

        except Exception as e:
            secure_log("ERROR", f"WuzAPI AI Error: {str(e)}")
            send_wuzapi_reply(reply_to, "❌ Terjadi kesalahan sistem.")
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        secure_log("ERROR", f"Process WuzAPI Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500


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
            
            # ============ REVISION HANDLER ============
            reply_to_message = message.get('reply_to_message')
            if reply_to_message and text:
                # Get the Bot's message ID that was replied to
                bot_msg_id = reply_to_message.get('message_id')
                
                # Check if we have a mapping for this bot message
                original_msg_ref = get_original_message_id(bot_msg_id)
                
                # If we tracked it, use the original message ID. If not, maybe use Bot's ID directly?
                # For safety, we only support tracked messages for now.
                if original_msg_ref:
                    # Find the transaction
                    original_tx = find_transaction_by_message_id(original_msg_ref)
                    
                    if original_tx:
                        # Check directly if text starts with /revisi
                        if not text.lower().startswith('/revisi'):
                            send_telegram_reply(chat_id, 
                                "⚠️ Format Salah.\n\n"
                                "Untuk merevisi, balas pesan ini dengan format:\n"
                                "`/revisi [jumlah]`\n\n"
                                "Contoh: `/revisi 150000`")
                            return jsonify({'ok': True}), 200

                        new_amount = parse_revision_amount(text)
                        
                        if new_amount > 0:
                            old_amount = original_tx['amount']
                            
                            # Verify user who is revising is the one who created it (optional strictness)
                            # if str(original_tx['user_id']) != user_id: ...
                            
                            success = update_transaction_amount(
                                original_tx['dompet'], 
                                original_tx['row'], 
                                new_amount
                            )
                            
                            if success:
                                invalidate_dashboard_cache()
                                reply = (f"✅ Jumlah Direvisi!\n\n"
                                        f"💸 {original_tx['keterangan']}\n"
                                        f"   Rp {old_amount:,} → Rp {new_amount:,}\n\n"
                                        f"💼 {original_tx['dompet']}").replace(',', '.')
                                send_telegram_reply(chat_id, reply)
                                return jsonify({'ok': True}), 200
                            else:
                                send_telegram_reply(chat_id, "❌ Gagal update transaksi.")
                                return jsonify({'ok': True}), 200
                        else:
                            send_telegram_reply(chat_id, 
                                "❓ Format revisi tidak valid.\n"
                                "Reply dengan angka baru, misal: `150rb`")
                            return jsonify({'ok': True}), 200

            # Check for pending transaction - selection handler
            if user_id in _pending_transactions:
                is_valid, selection, error_msg = parse_selection(text)
                
                if error_msg == "cancel":
                    _pending_transactions.pop(user_id, None)
                    send_telegram_reply(chat_id, "❌ Transaksi dibatalkan.")
                    return jsonify({'ok': True}), 200
                
                if not is_valid:
                    # Send error feedback
                    send_telegram_reply(chat_id, f"❌ {error_msg}")
                    return jsonify({'ok': True}), 200
                
                # Valid selection 1-5
                pending = _pending_transactions.pop(user_id)
                option = get_selection_by_idx(selection)
                
                if not option:
                    send_telegram_reply(chat_id, "❌ Pilihan tidak valid.")
                    return jsonify({'ok': True}), 200
                
                dompet_sheet = option['dompet']
                company = option['company']
                
                dompet_sheet = option['dompet']
                company = option['company']
                
                # Inject message_id into transactions if available from pending
                tx_message_id = pending.get('message_id', '')
                for t in pending['transactions']:
                    t['message_id'] = tx_message_id
                
                # Save transactions to selected dompet/company
                result = append_transactions(
                    pending['transactions'], 
                    pending['sender_name'], 
                    pending['source'],
                    dompet_sheet=dompet_sheet,
                    company=company
                )
                
                if result['success']:
                    update_user_activity(user_id, 'telegram', pending['sender_name'])
                    invalidate_dashboard_cache()
                    reply = format_success_reply_new(pending['transactions'], dompet_sheet, company)
                    reply += "\n\n💡 Reply pesan ini dengan `/revisi [jumlah]` untuk ralat"
                    
                    # Send reply and capture bot message ID for revision tracking
                    sent_msg = send_telegram_reply(chat_id, reply)
                    if sent_msg and sent_msg.get('ok') and sent_msg.get('result'):
                        bot_msg_id = sent_msg['result']['message_id']
                        if tx_message_id:
                            store_bot_message_ref(bot_msg_id, tx_message_id)
                else:
                    send_telegram_reply(chat_id, f"❌ Gagal menyimpan: {result.get('company_error', 'Error')}")
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
                invalidate_dashboard_cache()  # Force fresh data from Google Sheets
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
            # Determine Source String
            is_group = message['chat']['type'] in ['group', 'supergroup']
            base_source = "Telegram Group" if is_group else "Telegram"
            
            if input_type == 'image':
                source = f"{base_source} Image"
            elif input_type == 'audio':
                source = f"{base_source} Voice"
            else:
                source = base_source
            
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
            
        # Inject message_id into transactions
        if message_id:
            for t in transactions:
                t['message_id'] = message_id
        
        # Check if AI detected company from input
        detected_company = None
        for t in transactions:
            if t.get('company'):
                detected_company = t['company']
                break
        
        if detected_company:
            # Auto-save: Company detected, find dompet and save directly
            dompet = get_dompet_for_company(detected_company)
            
            result = append_transactions(
                transactions, 
                sender_name, 
                source,
                dompet_sheet=dompet,
                company=detected_company
            )
            
            if result['success']:
                update_user_activity(user_id, 'telegram', sender_name)
                invalidate_dashboard_cache()
                reply = format_success_reply_new(transactions, dompet, detected_company)
                reply += "\n\n💡 Reply pesan ini untuk revisi"
                
                # Send reply and capture bot message ID for revision tracking
                sent_msg = send_telegram_reply(chat_id, reply)
                if sent_msg and sent_msg.get('ok') and sent_msg.get('result'):
                    bot_msg_id = sent_msg['result']['message_id']
                    if message_id:
                        store_bot_message_ref(bot_msg_id, message_id)
            else:
                send_telegram_reply(chat_id, f"❌ Gagal: {result.get('company_error', 'Error')}")
        else:
            # No company detected - ask for selection
            _pending_transactions[user_id] = {
                'transactions': transactions,
                'sender_name': sender_name,
                'source': source,
                'timestamp': datetime.now(),
                'message_id': message_id  # Store for later
            }
            
            reply = build_selection_prompt(transactions)
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
            invalidate_dashboard_cache()  # Force fresh data from Google Sheets
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

