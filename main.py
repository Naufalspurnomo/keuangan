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
from services.project_service import resolve_project_name, add_new_project_to_cache

# Load environment variables
load_dotenv()

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

# 7-Layer Intelligent Architecture (optional, controlled by USE_LAYER_ARCHITECTURE env var)
from layer_integration import process_with_layers, USE_LAYERS

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
from config.constants import Commands, Timeouts, GROUP_TRIGGERS, SPREADSHEET_ID
from config.errors import UserErrors
from config.allowlist import is_sender_allowed

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



# ===================== GROUP & SELECTION HELPERS =====================
# All parsing functions now imported from utils.parsers
# Functions: parse_selection, parse_revision_amount, should_respond_in_group
# State functions imported from services.state_manager
# Functions: store_bot_message_ref, get_original_message_id


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
            display_name = normalize_project_display_name(t['nama_projek'])
            if display_name:
                nama_projek_set.add(display_name)
    
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
            display_name = normalize_project_display_name(t['nama_projek'])
            if display_name:
                nama_projek_set.add(display_name)
    
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
        is_group = '@g.us' in chat_jid

        if not is_sender_allowed([sender_number]):
            reply_target = chat_jid if (is_group and chat_jid) else sender_number
            send_wuzapi_reply(
                reply_target,
                "❌ Anda tidak diizinkan menggunakan bot ini. "
                "Hubungi admin untuk akses."
            )
            return jsonify({'status': 'forbidden'}), 200
        
        # Get the actual message text
        message_obj = event.get('Message', {})
        text = ''
        input_type = 'text'
        media_url = None
        quoted_msg_id = ''
        quoted_message_text = ''
        
        # DEBUG: Log full message object structure to find quote info
        secure_log("DEBUG", f"WuzAPI message_obj keys: {list(message_obj.keys())}")
        secure_log("DEBUG", f"WuzAPI message_obj full: {json.dumps(message_obj)[:500]}")
        
        # Extract quoted message info (for context-aware processing)
        # Try to find contextInfo in various locations (extendedTextMessage or top-level)
        ext_text = message_obj.get('extendedTextMessage', {}) or message_obj.get('ExtendedTextMessage', {})
        context_info = message_obj.get('contextInfo', {}) or message_obj.get('ContextInfo', {})
        
        if ext_text:
            context_info = ext_text.get('contextInfo', {}) or ext_text.get('ContextInfo', {})
            
        if context_info:
            quoted_msg_id = context_info.get('stanzaID', '') or context_info.get('stanzaId', '') or context_info.get('StanzaId', '')
            # Extract quoted message text
            quoted_msg_obj = context_info.get('quotedMessage', {}) or context_info.get('QuotedMessage', {})
            if quoted_msg_obj:
                quoted_message_text = (
                    quoted_msg_obj.get('conversation', '') or 
                    quoted_msg_obj.get('Conversation', '') or
                    quoted_msg_obj.get('extendedTextMessage', {}).get('text', '') or
                    quoted_msg_obj.get('ExtendedTextMessage', {}).get('Text', '')
                )
            if quoted_msg_id:
                secure_log("DEBUG", f"WuzAPI Quoted Info Found: id='{quoted_msg_id}', text='{quoted_message_text[:50]}'")

        if msg_type == 'text':
            # Text message - check various fields
            text = message_obj.get('conversation', '') or \
                   message_obj.get('Conversation', '') or \
                   message_obj.get('extendedTextMessage', {}).get('text', '') or \
                   message_obj.get('ExtendedTextMessage', {}).get('Text', '')
        elif msg_type == 'media':
            # Media with caption
            caption = message_obj.get('imageMessage', {}).get('caption', '') or \
                     message_obj.get('ImageMessage', {}).get('Caption', '') or \
                     message_obj.get('caption', '')
            text = caption
            input_type = 'image'
            
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
            # Unknown message type (e.g. ChatPresence)
            pass
        
        # For text messages without any text, skip
        if not text and input_type == 'text':
            secure_log("DEBUG", f"WuzAPI: No text in message. Type={msg_type}, Msg={json.dumps(message_obj)[:200]}")
            return jsonify({'status': 'no_text'}), 200
        
        secure_log("INFO", f"WuzAPI message from {sender_number}: {text[:50] if text else '[image]'}, has_media={media_url is not None}, quoted={quoted_msg_id}, msg_id={message_id}")

        # DEDUP: Skip if message already processed (multi-worker safe)
        if is_message_duplicate(message_id):
            secure_log("DEBUG", f"WuzAPI: Duplicate message_id={message_id}, skipping")
            return jsonify({'status': 'duplicate'}), 200

        # Process the message (with image URL and message IDs)
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
        sender_jid: Full sender JID for @mention (format: 628xxx@s.whatsapp.net)
        quoted_message_text: Text content of the message being replied to
    """
    try:
        # Determine reply destination: for groups, reply to group; for personal, reply to sender
        reply_to = chat_jid if (is_group and chat_jid) else sender_number
        
        # Track if visual buffer was linked in this session
        was_visual_link = False

        # Helper function to send reply with @mention in groups
        def send_reply_with_mention(body: str, with_mention: bool = True) -> dict:
            """Send reply, adding @mention for groups if requested.
            
            Uses sender's display name for visible @mention text.
            Cleans JID to remove device suffix for proper WhatsApp tagging.
            """
            if is_group and with_mention and sender_jid:
                # Clean JID to remove :XX device suffix (e.g., 628xxx:72 -> 628xxx)
                clean_jid = get_clean_jid(sender_jid)
                # Format body with @DisplayName and send with clean MentionedJID
                body_with_mention = format_mention_body(body, sender_name, sender_jid)
                return send_wuzapi_reply(reply_to, body_with_mention, clean_jid)
            else:
                return send_wuzapi_reply(reply_to, body)

        def extract_bot_msg_id(sent_msg: dict) -> str:
            """Extract bot message ID from WuzAPI response payload."""
            if not sent_msg or not isinstance(sent_msg, dict):
                return None
            return (sent_msg.get('data', {}).get('Id') or
                    sent_msg.get('data', {}).get('id') or
                    sent_msg.get('key', {}).get('id') or
                    sent_msg.get('Key', {}).get('ID') or
                    sent_msg.get('ID') or
                    sent_msg.get('id') or
                    sent_msg.get('MessageID') or
                    sent_msg.get('Info', {}).get('ID'))

        def record_pending_prompt(pkey: str, pending: dict, sent_msg: dict) -> None:
            """Store mapping from bot prompt message to pending key for delegation."""
            bot_msg_id = extract_bot_msg_id(sent_msg)
            if not bot_msg_id:
                return
            store_pending_message_ref(bot_msg_id, pkey)
            prompt_ids = pending.setdefault('prompt_message_ids', [])
            prompt_ids.append(str(bot_msg_id))

        def clear_pending_prompt_refs(pending: dict) -> None:
            """Clear all stored prompt refs for a pending transaction."""
            for msg_id in pending.get('prompt_message_ids', []):
                clear_pending_message_ref(msg_id)

        def finalize_transaction_workflow(pending: dict, pkey: str):
            """Unified workflow for transaction finalization (Save or Selection)."""
            txs = pending.get('transactions', [])
            if not txs:
                return jsonify({'status': 'error_no_tx'}), 200
            
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

                # SAVE
                clear_pending_prompt_refs(pending)
                _pending_transactions.pop(pkey, None)
                tx_msg_id = pending.get('message_id', '')
                for t in txs: t['message_id'] = tx_msg_id
                
                result = append_transactions(txs, pending['sender_name'], pending['source'], 
                                           dompet_sheet=dompet, company=detected_company)
                
                if result['success']:
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
                    send_wuzapi_reply(reply_to, f"❌ Gagal: {result.get('company_error', 'Error')}")
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
        
        # ============ VISUAL BUFFER (Grand Design Layer 2) ============
        # Handle photo + text linking across separate messages
        
        # Case 1: Photo without text → Store in visual buffer
        if input_type == 'image' and media_url and not text.strip():
            store_visual_buffer(sender_number, chat_jid, media_url, message_id)
            secure_log("INFO", f"Visual buffer: Stored photo from {sender_number}, waiting for text")
            # Don't respond yet - wait for text command
            return jsonify({'status': 'photo_buffered'}), 200
        
        # Check visual buffer for context (Stage 1 Decision Signal)
        has_visual = has_visual_buffer(sender_number, chat_jid)
        
        # ============ LAYER 1: SEMANTIC ENGINE (Hybrid AI) ============
        if USE_LAYERS:
            # Try to process with new smart engine first
            action, layer_response, intent = process_with_layers(
                user_id=sender_number,
                message_id=message_id,
                text=text,
                sender_name=sender_name,
                media_url=media_url,
                caption=text if input_type == 'image' else None,
                is_group=is_group,
                chat_id=chat_jid,
                quoted_message_id=quoted_msg_id,
                quoted_message_text=quoted_message_text,
                sender_jid=sender_jid,
                has_visual=has_visual
            )
            
            if action == "IGNORE":
                secure_log("DEBUG", f"Message IGNORED by Semantic Engine (Intent: {intent})")
                return jsonify({'status': 'ignored_by_layer'}), 200
                
            if action == "REPLY" and layer_response:
                # Engine handled it and wants to reply (e.g. Revision Success or Chitchat)
                send_reply_with_mention(layer_response)
                return jsonify({'status': 'handled_by_layer'}), 200
            
            if action == "PROCESS":
                # Engine wants to process. If it's a query, we handle it here.
                if intent == "QUERY_STATUS" and layer_response:
                    secure_log("INFO", f"Smart Query detected: '{layer_response}'")
                    send_wuzapi_reply(reply_to, "🤔 Menganalisis...")
                    try:
                        data_context = format_data_for_ai(days=30)
                        answer = query_data(layer_response, data_context)
                        send_wuzapi_reply(reply_to, answer.replace('*', '').replace('_', ''))
                        return jsonify({'status': 'queried_by_layer'}), 200
                    except Exception as e:
                        secure_log("ERROR", f"Smart Query failed: {e}")
                
                # Default process: Update text with normalized version and fall through
                if layer_response:
                    text = layer_response
                    secure_log("INFO", f"Semantic Engine normalized text to: '{text}'")
        
        # Case 2: Text without photo → Check if we have buffered photo to link
        # Case 2: Text without photo → Check if we have buffered photo(s) to link
        media_urls_from_buffer = []

        if input_type == 'text' and not media_url:
            buffered_items = get_visual_buffer(sender_number, chat_jid)
            if buffered_items:
                # Link buffered photos
                # Handle both list (new) and dict (legacy safety)
                if isinstance(buffered_items, list):
                     media_urls_from_buffer = [item.get('media_url') for item in buffered_items]
                else:
                     # Fallback if somehow dict returned (should not happen with new state_manager)
                     media_urls_from_buffer = [buffered_items.get('media_url')]
                
                if media_urls_from_buffer:
                    media_url = media_urls_from_buffer[0] # Set primary for legacy compatibility
                    input_type = 'image'  # Now treat as image message
                    secure_log("INFO", f"Visual buffer: Linked {len(media_urls_from_buffer)} photo(s) to text '{text[:30]}...'")
                    clear_visual_buffer(sender_number, chat_jid)
                    was_visual_link = True
        
        # No more Layer 2-7 redundant block here, already handled by Semantic Engine at the start
        
        # Sanitize
        text = sanitize_input(text or '')
        
        # GROUP CHAT FILTER: Only respond if triggered or command
        # Triggers: +catat, +bot, +input, /catat, or any / command
        # EXCEPTION: If user has pending transaction IN THIS CHAT, allow through
        sender_pkey = pending_key(sender_number, chat_jid)
        pending_pkey = sender_pkey
        if is_group and quoted_msg_id:
            mapped_pkey = get_pending_key_from_message(quoted_msg_id)
            if mapped_pkey:
                pending_pkey = mapped_pkey

        pending_data = _pending_transactions.get(pending_pkey)
        
        # Check if pending exists and not expired
        pending_was_expired = False
        if pending_data and pending_is_expired(pending_data):
            clear_pending_prompt_refs(pending_data)
            _pending_transactions.pop(pending_pkey, None)
            pending_data = None
            pending_was_expired = True
            secure_log("DEBUG", f"Pending expired for {pending_pkey}")
        elif is_group and quoted_msg_id and not pending_data:
            # Clean up stale mapping if no pending found
            clear_pending_message_ref(quoted_msg_id)
        
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
            secure_log("DEBUG", f"Group msg from {sender_number}: pkey={pending_pkey}, has_pending={has_pending}, text='{text[:30]}...'")
        
        # Check visual buffer (already calculated earlier for context)

        if not USE_LAYERS:
            # LEGACY FILTER (Only if Layer 1 disabled)
            should_respond, cleaned_text = should_respond_in_group(
                message=text or "", 
                is_group=is_group,
                has_media=media_url is not None,
                has_pending=has_pending or has_visual or was_visual_link,
                is_mentioned=False
            )
            
            if not should_respond:
                secure_log("DEBUG", f"{'Group' if is_group else 'Private'} msg IGNORED (Legacy Filter)")
                return jsonify({'status': 'ignored'}), 200
            
            text = cleaned_text if cleaned_text else text
        
        
        
        # GUARD: Check for "revisi" without reply
        if is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
            if not quoted_msg_id:
                send_wuzapi_reply(reply_to, UserErrors.REVISION_NO_QUOTE)
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
            
            # GUARD: strict revision command handling
            # If text starts with /revisi but original_tx is NOT found, fail here.
            # Do NOT fall through to AI.
            if not original_tx and is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
                 send_wuzapi_reply(reply_to, "❌ Gagal revisi: Tidak dapat menemukan data transaksi asli pada pesan yang di-reply.")
                 return jsonify({'status': 'revision_tx_not_found'}), 200

            if original_tx:
                # Check directly if text starts with /revisi
                if not is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
                    send_wuzapi_reply(reply_to, UserErrors.REVISION_FORMAT_WRONG)
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
                        now = now_wib().strftime("%d %b %Y, %H:%M")
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
                        send_reply_with_mention(reply)
                        return jsonify({'status': 'revised'}), 200
                    else:
                        send_reply_with_mention(UserErrors.REVISION_FAILED)
                        return jsonify({'status': 'revision_error'}), 200
                else:
                    send_wuzapi_reply(reply_to, UserErrors.REVISION_INVALID_AMOUNT)
                    return jsonify({'status': 'invalid_revision'}), 200
        

        
        # Check for pending transaction - selection handler
        # We already got pending_data and pending_pkey from group filter above
        if has_pending:
            pending = pending_data  # Already retrieved above
            pending_type = pending.get('pending_type', 'selection')
            requires_reply = pending.get('requires_reply', False)

            if is_group and requires_reply and not quoted_msg_id:
                send_wuzapi_reply(
                    reply_to,
                    "↩️ Mohon *reply* pesan bot yang menanyakan projek/company agar tidak tertukar."
                )
                return jsonify({'status': 'reply_required'}), 200
            
            # Handle cancel for all pending types
            if is_command_match(text, Commands.CANCEL, is_group):
                clear_pending_prompt_refs(pending)
                _pending_transactions.pop(pending_pkey, None)
                send_wuzapi_reply(reply_to, UserErrors.CANCELLED)
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
                            clear_pending_prompt_refs(pending)
                            _pending_transactions.pop(pending_pkey, None)
                            send_wuzapi_reply(reply_to, UserErrors.ALL_REMOVED)
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
            
            # ===== HANDLE DUPLICATE CONFIRMATION (Layer 5) =====
            if pending_type == 'confirmation_dupe':
                if text.lower().strip() == 'y':
                    # User confirmed to save duplicate
                    option = pending.get('selected_option')
                    if not option:
                        # Fallback if option lost
                         send_wuzapi_reply(reply_to, "❌ Error state. Silakan ulangi transaksi.")
                         _pending_transactions.pop(pending_pkey, None)
                         return jsonify({'status': 'error'}), 200
                         
                    dompet_sheet = option['dompet']
                    company = option['company']
                    
                    # Inject message_id
                    tx_message_id = pending.get('message_id', '')
                    for t in pending['transactions']:
                        t['message_id'] = tx_message_id
                        
                    # Save
                    result = append_transactions(
                        pending['transactions'], 
                        pending['sender_name'], 
                        pending['source'],
                        dompet_sheet=dompet_sheet,
                        company=company
                    )
                    
                    if result['success']:
                        _pending_transactions.pop(pending_pkey, None) # Clear pending
                        clear_pending_prompt_refs(pending)
                        
                        invalidate_dashboard_cache()
                        reply = format_success_reply_new(pending['transactions'], dompet_sheet, company).replace('*', '')
                        reply += "\n\n💡 Reply pesan ini dengan `/revisi [jumlah]` untuk ralat"
                        sent_msg = send_reply_with_mention(reply)
                        
                        # Store bot ref
                        bot_msg_id = None
                        if sent_msg and isinstance(sent_msg, dict):
                             bot_msg_id = (sent_msg.get('data', {}).get('Id') or sent_msg.get('ID'))
                        if bot_msg_id and tx_message_id:
                            store_bot_message_ref(bot_msg_id, tx_message_id)
                    else:
                        send_wuzapi_reply(reply_to, f"❌ Gagal: {result.get('company_error', 'Error')}")
                        # Keep pending if save failed? No, clear it to avoid stuck.
                        _pending_transactions.pop(pending_pkey, None)
                        
                    return jsonify({'status': 'processed_dupe'}), 200
                else:
                    # User declined
                    send_wuzapi_reply(reply_to, "❌ Transaksi dibatalkan.")
                    clear_pending_prompt_refs(pending)
                    _pending_transactions.pop(pending_pkey, None)
                    return jsonify({'status': 'cancelled_dupe'}), 200

            # ===== HANDLE PROJECT CONFIRMATION =====
            if pending_type == 'confirmation_project':
                text_clean = text.lower().strip()
                suggested = pending.get('suggested_project')
                
                final_project = ""
                
                # 1. POSITIVE CONFIRMATION (User setuju)
                if text_clean in ['ya', 'y', 'ok', 'yes', 'sip', 'benar', 'betul', 'lanjut', 'gas', 'bener', 'yoi', 'oke', 'okay', 'iyh', 'iya', 'iy', 'yup', 'yap', 'lanjutkan', 'gaspol', 'setuju', 'acc', 'confirm', 'okeh', 'mantap']:
                    final_project = suggested
                    send_wuzapi_reply(reply_to, f"✅ Sip, masuk ke projek **{final_project}**.")
                
                # 2. NEGATIVE REJECTION (User menolak tanpa kasih nama)
                elif text_clean in ['tidak', 'bukan', 'no', 'salah', 'ga', 'gak', 'nggak', 'g', 'tdk', 'bkn', 'nope', 'nah', 'kaga', 'kagak', 'ndak', 'ora', 'mboten', 'ngak', 'ngga', 'gag', 'males']:
                    # Bot salah tebak -> Tanya user maunya apa
                    send_wuzapi_reply(reply_to, "Oalah, maaf salah tebak. 🙏\n\nKalau begitu, nama projek yang benar apa?")
                    # Kembalikan state ke 'needs_project' agar input berikutnya dianggap nama projek
                    pending['pending_type'] = 'needs_project'
                    return jsonify({'status': 'asking_correct_name'}), 200
                
                # 3. DIRECT CORRECTION (User langsung mengetik nama yang benar)
                # Contoh: Bot tanya "Maksudnya Purana?", User jawab "Bukan, tapi Villa Baru" atau cuma "Villa Baru"
                else:
                    # Anggap input user adalah nama projek yang sebenarnya
                    final_project = sanitize_input(text.strip())
                    
                    # Validasi minimal agar tidak input sampah
                    if len(final_project) < 3:
                        send_wuzapi_reply(reply_to, "⚠️ Nama projek terlalu pendek. Mohon ketik nama yang jelas.")
                        return jsonify({'status': 'invalid_name_length'}), 200

                    # [PENTING] Ajari bot nama baru ini agar besok tidak ditanya lagi
                    from services.project_service import add_new_project_to_cache
                    add_new_project_to_cache(final_project)
                    
                    send_wuzapi_reply(reply_to, f"👌 Oke, mencatat projek baru: **{final_project}**")

                # --- APPLY & FINALIZE ---
                # Update semua transaksi di pending list
                for t in pending['transactions']:
                    t['nama_projek'] = final_project
                    t.pop('needs_project', None) # Bersihkan flag
                
                # Lanjut ke alur penyimpanan (Cek Company -> Save)
                return finalize_transaction_workflow(pending, pending_pkey)

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
                from services.project_service import resolve_project_name
                resolved = resolve_project_name(project_name)
                
                # Intercept Ambiguous Match
                if resolved.get('status') == 'AMBIGUOUS':
                    pending['pending_type'] = 'confirmation_project'
                    pending['suggested_project'] = resolved['final_name']
                    
                    msg = (f"🤔 Maksud Anda untuk projek *{resolved['final_name']}*?\n\n"
                           f"✅ Balas *Ya* jika benar\n"
                           f"❌ Ketik nama projek lain jika salah")
                    send_wuzapi_reply(reply_to, msg)
                    return jsonify({'status': 'waiting_project_confirm'}), 200
                
                # Auto-Apply Exact or Typo matches
                if resolved.get('status') in ['EXACT', 'AUTO_FIX']:
                    project_name = resolved['final_name']
                
                # Finalize project assignment
                for t in pending['transactions']:
                    t['nama_projek'] = project_name
                    t.pop('needs_project', None)
                
                # FINALISASI (Save/Selection)
                return finalize_transaction_workflow(pending, pending_pkey)
            
            # ===== HANDLE COMPANY SELECTION =====
            is_valid, selection, error_msg = parse_selection(text)
            
            if error_msg == "cancel":
                clear_pending_prompt_refs(pending)
                _pending_transactions.pop(pending_pkey, None)
                send_wuzapi_reply(reply_to, UserErrors.CANCELLED)
                return jsonify({'status': 'cancelled'}), 200
            
            if not is_valid:
                # Send error feedback
                send_wuzapi_reply(reply_to, f"❌ {error_msg}")
                return jsonify({'status': 'invalid_selection'}), 200
            
            # Valid selection 1-5
            pending = _pending_transactions.get(pending_pkey) # Use get to keep state if dupe check fails
            
            option = get_selection_by_idx(selection)
            if not option:
                 send_wuzapi_reply(reply_to, UserErrors.SELECTION_OUT_OF_RANGE)
                 return jsonify({'status': 'error'}), 200
            
            dompet_sheet = option['dompet']
            company = option['company']
            
            # Transition to finalization
            pending['selected_option'] = option # Useful for confirmation_dupe
            # Update transactions with the explicitly selected company
            for t in pending['transactions']:
                t['company'] = company
            
            # Use unified finalization workflow
            return finalize_transaction_workflow(pending, pending_pkey)
        
        
        # /start
        if is_command_match(text, Commands.START, is_group):
            reply = START_MESSAGE.replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        # /help
        if is_command_match(text, Commands.HELP, is_group):
            reply = HELP_MESSAGE.replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
            
        # /link
        if is_command_match(text, Commands.LINK, is_group):
            link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
            send_wuzapi_reply(reply_to, f"🔗 Link Spreadsheet:\n{link}")
            return jsonify({'status': 'ok'}), 200
        
        # /status
        if is_command_match(text, Commands.STATUS, is_group):
            invalidate_dashboard_cache()
            send_wuzapi_reply(reply_to, "⏳ Sedang mengambil data status...")
            status_msg = get_status_message().replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, status_msg)
            return jsonify({'status': 'ok'}), 200
        
        # /laporan & /laporan30
        if is_command_match(text, Commands.LAPORAN, is_group) or is_command_match(text, Commands.LAPORAN_30, is_group):
            # Check for /laporan30 or laporan30
            days = 30 if '30' in text else 7
            send_wuzapi_reply(reply_to, f"⏳ Membuat laporan {days} hari...")
            report = generate_report(days=days)
            reply = format_report_message(report).replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        # /saldo
        if is_command_match(text, Commands.SALDO, is_group):
            reply = get_wallet_balances().replace('*', '').replace('_', '')
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        # /kategori
        if is_command_match(text, Commands.KATEGORI, is_group):
            reply = "📁 Kategori:\n" + '\n'.join(f"• {cat}" for cat in ALLOWED_CATEGORIES)
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        # /dompet
        if is_command_match(text, Commands.DOMPET, is_group):
            reply = (
                "🗂️ *Dompet & Company*:\n\n"
                "📁 *Dompet Holja*\n"
                "  1. HOLLA\n"
                "  2. HOJJA\n\n"
                "📁 *Dompet Texturin Sby*\n"
                "  3. TEXTURIN-Surabaya\n\n"
                "📁 *Dompet Evan*\n"
                "  4. TEXTURIN-Bali\n"
                "  5. KANTOR\n\n"
                "💡 _Kirim transaksi, lalu pilih nomor (1-5)._"
            )
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        
        # /list - Recent transactions
        if is_command_match(text, Commands.LIST, is_group):
            from sheets_helper import get_all_data
            data = get_all_data(days=7)
            if data:
                lines = ["📋 Transaksi Terakhir (7 hari):\n"]
                for item in data[-10:]:  # Last 10
                    emoji = "💸" if item['tipe'] == 'Pengeluaran' else "💰"
                    nama = item.get('nama_projek', '')
                    nama_str = f" ({nama})" if nama else ""
                    lines.append(f"{emoji} {item['keterangan'][:20]}{nama_str} - Rp {item['jumlah']:,}".replace(',', '.'))
                reply = '\n'.join(lines)
            else:
                reply = "📋 Tidak ada transaksi dalam 7 hari terakhir."
            send_wuzapi_reply(reply_to, reply)
            return jsonify({'status': 'ok'}), 200
        
        # /tanya [question] - AI Query
        if is_prefix_match(text, Commands.TANYA_PREFIXES, is_group):
            # Extract question by removing prefix
            question = ""
            for prefix in Commands.TANYA_PREFIXES:
                if text.lower().startswith(prefix):
                    question = text[len(prefix):].strip()
                    break
            
            if not question:
                send_wuzapi_reply(reply_to, 
                    "❓ Format: /tanya [pertanyaan]\n\n"
                    "Contoh:\n"
                    "• /tanya total pengeluaran bulan ini\n"
                    "• /tanya kategori terbesar")
            else:
                send_wuzapi_reply(reply_to, "🤔 Menganalisis...")
                try:
                    # Get data context for AI query
                    data_context = format_data_for_ai(days=30)
                    answer = query_data(question, data_context)
                    send_wuzapi_reply(reply_to, answer.replace('*', '').replace('_', ''))
                except Exception as e:
                    send_wuzapi_reply(reply_to, f"❌ Gagal: {str(e)}")
            return jsonify({'status': 'ok'}), 200
        
        # /exportpdf - Export monthly PDF report
        if is_prefix_match(text, Commands.EXPORT_PDF_PREFIXES, is_group):
            # Extract month argument
            month_arg = ""
            for prefix in Commands.EXPORT_PDF_PREFIXES:
                if text.lower().startswith(prefix):
                    month_arg = text[len(prefix):].strip()
                    break
            
            if not month_arg:
                now = datetime.now()
                month_arg = f"{now.year}-{now.month:02d}"
            
            try:
                # Step 1: Parse and validate period
                year, month = parse_month_input(month_arg)
                
                # Step 2: Check if data exists
                has_data, tx_count, period_name = validate_period_data(year, month)
                
                if not has_data:
                    send_wuzapi_reply(reply_to, UserErrors.PDF_NO_DATA.format(period=period_name))
                    return jsonify({'status': 'ok'}), 200
                
                # Step 3: Notify and generate
                send_wuzapi_reply(reply_to, 
                    f"✅ Ditemukan {tx_count} transaksi untuk {period_name}\n"
                    f"📊 Generating PDF...")
                
                # Step 4: Generate PDF
                pdf_path = generate_pdf_from_input(month_arg)
                
                file_size = os.path.getsize(pdf_path) / 1024  # KB
                
                reply = (
                    f"📊 Laporan Keuangan Bulanan\n"
                    f"📅 Periode: {period_name}\n"
                    f"📝 Total: {tx_count} transaksi\n"
                    f"📦 Ukuran: {file_size:.1f} KB\n\n"
                    f"✅ PDF berhasil dibuat!\n\n"
                    f"⚠️ Untuk download PDF, gunakan Telegram bot atau minta admin kirimkan file."
                )
                send_wuzapi_reply(reply_to, reply)
                
            except ValueError as e:
                send_wuzapi_reply(reply_to, UserErrors.PDF_FORMAT_ERROR)
            except ImportError:
                send_wuzapi_reply(reply_to, UserErrors.PDF_NOT_INSTALLED)
            except Exception as e:
                secure_log("ERROR", f"PDF export failed (WuzAPI): {type(e).__name__}")
                send_wuzapi_reply(reply_to, UserErrors.PDF_FAILED)
            
            return jsonify({'status': 'ok'}), 200 

        # /cancel (No pending transaction)
        if is_command_match(text, Commands.CANCEL, is_group):
             send_wuzapi_reply(reply_to, "Info: Tidak ada transaksi pending yang perlu dibatalkan.")
             return jsonify({'status': 'ok'}), 200

        # GUARD: Stop Unknown Slash Commands from hitting AI
        # Allow: /catat, /revisi
        if text.strip().startswith('/') and not any(text.lower().startswith(p) for p in ['/catat', '/revisi', '/tanya', '/input']):
             # If we reached here, it's an unknown command like /wefwf or /test
             # Just ignore it to save AI tokens, OR reply 'Unknown Command'
             secure_log("INFO", f"Ignored unknown command: {text}")
             return jsonify({'status': 'ignored_command'}), 200

 

        # AI Extraction for transactions
        transactions = []
        try:
            # === UX: Processing indicator (shorter for groups) ===
            if input_type == 'image':
                send_wuzapi_reply(reply_to, "🔍 Scan..." if is_group else "🔍 Memindai struk...")
            elif text and len(text) > 20 and not is_group:
                # Only show for private chat (reduce group spam)
                send_wuzapi_reply(reply_to, "🔍 Menganalisis...")
            
            # Prepare media urls (handle single or multi-image buffer)
            final_media_list = media_urls_from_buffer if media_urls_from_buffer else ([media_url] if media_url else [])
            
            transactions = extract_financial_data(
                input_data=text or '', 
                input_type=input_type,
                sender_name=sender_name,
                media_urls=final_media_list,
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

            # GUARD: Zero Amount Check
            zero_tx = [t for t in transactions if t.get('jumlah', 0) <= 0]
            if zero_tx:
                # Only show error if it looks like a real transaction or came with an image
                # Otherwise it's likely AI misinterpreting noise
                from utils.parsers import calculate_financial_score
                score = calculate_financial_score(text or "", has_media=(input_type == 'image'))
                
                if score >= 40 or input_type == 'image':
                    desc = zero_tx[0].get('keterangan', 'Item')
                    if len(desc) > 40: desc = desc[:37] + "..."
                    
                    send_wuzapi_reply(reply_to, 
                        f"⚠️ Transaksi terdeteksi tapi nominal belum ada (Rp 0).\n\n"
                        f"📝 {desc}\n\n"
                        f"Mohon ulangi dengan menyertakan nominal angka.\n"
                        f"Contoh: 'Beli semen 50rb'")
                    return jsonify({'status': 'zero_amount'}), 200
                else:
                    secure_log("INFO", f"Zero amount transaction from low signal ({score}), staying silent")
                    return jsonify({'status': 'silent_ignore_zero'}), 200

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
            
# ==================================================================
            # 🔥 SMART INTERCEPT: CEK KEMIRIPAN PROJEK SEBELUM LANJUT 🔥
            # ==================================================================
            ambiguous_project = None
            
            for t in transactions:
                p_name = t.get('nama_projek')
                # Skip jika kosong atau Saldo Umum (Wallet Update)
                if not p_name or p_name.lower() == "saldo umum": 
                    continue
                
                # Cek ke database projek
                res = resolve_project_name(p_name)
                
                if res['status'] == 'EXACT':
                    # Perfect match, normalkan casing (misal: "purana" -> "Purana")
                    t['nama_projek'] = res['final_name']
                    
                elif res['status'] == 'AUTO_FIX':
                    # Typo dikit, auto benerin
                    secure_log("INFO", f"Auto-fix project: {p_name} -> {res['final_name']}")
                    t['nama_projek'] = res['final_name']
                    
                elif res['status'] == 'NEW':
                    # Projek baru, tidak perlu aksi apa-apa, nanti disimpan as-is
                    pass
                    
                elif res['status'] == 'AMBIGUOUS':
                    # STOP! Ada keraguan. Simpan info untuk ditanyakan ke user.
                    ambiguous_project = res
                    break # Handle satu per satu biar ga pusing
            
            # Jika ada yang ambigu, TAHAN proses dan tanya user
            if ambiguous_project:
                # Buat pending state khusus konfirmasi
                _pending_transactions[sender_pkey] = {
                    'transactions': transactions,
                    'sender_name': sender_name,
                    'source': source,
                    'created_at': datetime.now(),
                    'message_id': message_id,
                    'chat_jid': chat_jid,
                    'pending_type': 'confirmation_project', # State konfirmasi
                    'suggested_project': ambiguous_project['final_name'],
                    'original_project': ambiguous_project['original'], # Simpan nama asli user
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

        except RateLimitException as e:
            secure_log("WARNING", f"Groq Rate Limit Reached: {e.wait_time}")
            send_wuzapi_reply(reply_to, 
                f"⏳ *AI Sedang Istirahat*\n\n"
                f"Limit penggunaan tercapai. Tunggu sekitar *{e.wait_time}*.\n"
                f"Silakan coba lagi nanti atau gunakan command manual.")
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
        user_id = str(message['from'].get('id', chat_id))
        sender_name = message['from'].get('first_name', 'User')
        username = message['from'].get('username')

        if not is_sender_allowed([user_id, str(chat_id), username]):
            send_telegram_reply(
                chat_id,
                "❌ Anda tidak diizinkan menggunakan bot ini. "
                "Hubungi admin untuk akses."
            )
            return jsonify({'ok': True}), 200
        
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
        is_group = False  # Telegram handler treats all chats as private
        
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
                    # update_user_activity removed
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
            if is_command_match(text, Commands.START, is_group):
                send_telegram_reply(chat_id, START_MESSAGE)
                return jsonify({'ok': True}), 200
            
            # /help
            if is_command_match(text, Commands.HELP, is_group):
                send_telegram_reply(chat_id, HELP_MESSAGE)
                return jsonify({'ok': True}), 200
            
            # /status
            if is_command_match(text, Commands.STATUS, is_group):
                invalidate_dashboard_cache()  # Force fresh data from Google Sheets
                reply = get_status_message()
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /saldo
            if is_command_match(text, Commands.SALDO, is_group):
                reply = get_wallet_balances()
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /kategori
            if is_command_match(text, Commands.KATEGORI, is_group):
                reply = f"📁 *Kategori Tersedia:*\n\n{CATEGORIES_DISPLAY}"
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /company, /project, /dompet - List available dompet & company sheets
            if is_command_match(text, Commands.DOMPET, is_group):
                reply = f"""🗂️ *Dompet & Company:*

📁 *Dompet Holja*
  1️⃣ HOLLA
  2️⃣ HOJJA

📁 *Dompet Texturin Sby*
  3️⃣ TEXTURIN-Surabaya

📁 *Dompet Evan*  
  4️⃣ TEXTURIN-Bali
  5️⃣ KANTOR

_Kirim transaksi, lalu pilih nomor (1-5)._"""
                send_telegram_reply(chat_id, reply)
                return jsonify({'ok': True}), 200
            
            # /list - Show recent transactions
            if is_command_match(text, Commands.LIST, is_group):
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
            if is_command_match(text, Commands.LAPORAN, is_group) or is_command_match(text, Commands.LAPORAN_30, is_group):
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
            if is_prefix_match(text, Commands.TANYA_PREFIXES, is_group):
                # Extract question
                question = ""
                for prefix in Commands.TANYA_PREFIXES:
                    if text.lower().startswith(prefix):
                        question = text[len(prefix):].strip()
                        break
                
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
            if is_prefix_match(text, Commands.EXPORT_PDF_PREFIXES, is_group):
                # Extract month argument
                month_arg = ""
                for prefix in Commands.EXPORT_PDF_PREFIXES:
                    if text.lower().startswith(prefix):
                        month_arg = text[len(prefix):].strip()
                        break
                
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
            
            # /reminder command removed
            
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
        detected_dompet = None
        for t in transactions:
            if t.get('company'):
                detected_company = t['company']
            # For wallet updates, AI extracts which dompet was mentioned
            if t.get('detected_dompet'):
                detected_dompet = t['detected_dompet']
            if detected_company:
                break
        
        # Determine dompet (wallet sheet)
        dompet = None
        if detected_company:
            # Auto-save: Company detected
            if detected_company == "UMUM":
                 if detected_dompet:
                     dompet = detected_dompet
                 else:
                     dompet = None # Force selection
            else:
                dompet = get_dompet_for_company(detected_company)
        
        # Auto-save if BOTH company and dompet are valid
        if detected_company and dompet:
            result = append_transactions(
                transactions, 
                sender_name, 
                source,
                dompet_sheet=dompet,
                company=detected_company
            )
            
            if result['success']:
                # update_user_activity removed
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



def background_retry_worker():
    """Worker to process retry queue periodically (Layer 6)."""
    secure_log("INFO", "Starting background retry worker for offline transactions...")
    
    def retry_callback(tx, meta):
        try:
            # allow_queue=False prevents infinite loop if it fails again
            res = append_transaction(
                tx, 
                meta.get('sender_name'),
                meta.get('source'),
                dompet_sheet=meta.get('dompet_sheet'),
                company=meta.get('company'),
                nama_projek=meta.get('nama_projek'),
                allow_queue=False 
            )
            return bool(res)
        except Exception as e:
            secure_log("WARNING", f"Retry failed for item: {e}")
            return False

    while True:
        try:
            processed = process_retry_queue(retry_callback)
            if processed > 0:
                secure_log("INFO", f"Background worker processed {processed} offline items")
        except Exception as e:
            secure_log("ERROR", f"Background worker error: {e}")
            
        time.sleep(300) # 5 minutes


# ===================== MAIN =====================

if __name__ == '__main__':
    # Layer 6: Start Retry Worker
    retry_thread = threading.Thread(target=background_retry_worker, daemon=True)
    retry_thread.start()

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
    
    # Scheduler removed
    
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)
