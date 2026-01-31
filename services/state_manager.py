"""
state_manager.py - State Management Service

Manages in-memory state for:
- Pending transactions waiting for company selection
- Message deduplication cache
- Bot message references for revision tracking

NOTE: For Koyeb free tier (ephemeral filesystem), this uses in-memory storage.
State will be lost on restart. For production, consider external storage (Redis/DB).
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import json
import os
from sheets_helper import save_state_to_cloud, load_state_from_cloud
from config.constants import Timeouts

# Use centralized timeouts
PENDING_TTL_SECONDS = Timeouts.PENDING_TRANSACTION
DEDUP_TTL_SECONDS = Timeouts.DEDUP_WINDOW
MAX_BOT_REFS = Timeouts.BOT_REFS_MAX

# Visual Buffer TTL (2 minutes - photos expire quickly)
VISUAL_BUFFER_TTL_SECONDS = 120

# Thread lock for dedup operations
_dedup_lock = threading.Lock()

# ===================== VISUAL BUFFER (Grand Design Layer 2) =====================
# Stores unprocessed photos for linking with later text commands
# Format: {user_key: [ {'media_url': str, 'caption': str, ...}, ... ]}
# user_key = "chat_jid:sender_number" for groups OR sender_number for DM
_visual_buffer: Dict[str, list] = {}

# ===================== PENDING CONFIRMATIONS (NEW) =====================
# For AI Ambiguity Checks (Step 0 & Step 2)
PENDING_CONFIRMATIONS: Dict[str, Dict] = {}


def visual_buffer_key(sender_number: str, chat_jid: str) -> str:
    """Generate key for visual buffer per user per chat."""
    if chat_jid and "@g.us" in chat_jid:
        return f"{chat_jid}:{sender_number}"
    return sender_number


def store_visual_buffer(sender_number: str, chat_jid: str, media_url: str, 
                        message_id: str, caption: str = None) -> None:
    """Store photo in visual buffer for later linking (Appends to list)."""
    key = visual_buffer_key(sender_number, chat_jid)
    
    # Initialize list if not exists
    if key not in _visual_buffer:
        _visual_buffer[key] = []
        
    # Append new item
    _visual_buffer[key].append({
        'media_url': media_url,
        'message_id': message_id,
        'caption': caption,
        'chat_jid': chat_jid,
        'sender_number': sender_number,
        'created_at': datetime.now()
    })
    
    # Sort by created_at to ensure order
    _visual_buffer[key].sort(key=lambda x: x['created_at'])


def get_visual_buffer(sender_number: str, chat_jid: str) -> list:
    """
    Get ALL unexpired photos from visual buffer.
    Returns list of dicts.
    """
    key = visual_buffer_key(sender_number, chat_jid)
    items = _visual_buffer.get(key, [])
    
    if not items:
        return []
        
    # Filter expired items
    valid_items = []
    now = datetime.now()
    
    for item in items:
        created = item.get('created_at')
        if created and (now - created).total_seconds() <= VISUAL_BUFFER_TTL_SECONDS:
            valid_items.append(item)
            
    # Update buffer with only valid items (cleanup)
    if not valid_items:
        _visual_buffer.pop(key, None)
    else:
        _visual_buffer[key] = valid_items
        
    return valid_items


def clear_visual_buffer(sender_number: str, chat_jid: str) -> None:
    """Clear photos from visual buffer after processing."""
    key = visual_buffer_key(sender_number, chat_jid)
    _visual_buffer.pop(key, None)


def has_visual_buffer(sender_number: str, chat_jid: str) -> bool:
    """Check if user has unexpired photo in buffer."""
    return len(get_visual_buffer(sender_number, chat_jid)) > 0


# ===================== PENDING TRANSACTIONS =====================
# Format: {pkey: {'transactions': [...], 'sender_name': str, 'source': str, 'created_at': datetime, 
#                 'chat_jid': str, 'sender_number': str, 'bot_msg_id': str}}
# pkey = "chat_jid:sender_number" for groups OR sender_number for DM
# This allows multiple pending transactions per group (one per user)
_pending_transactions: Dict[str, Dict] = {}


def pending_key(sender_number: str, chat_jid: str) -> str:
    """
    Generate unique key for pending transactions.
    - Group: "group@g.us:6281xxx" (per user per group)
    - DM: sender_number only
    """
    if chat_jid and "@g.us" in chat_jid:
        # Group chat: key includes both group and sender for uniqueness
        return f"{chat_jid}:{sender_number}"
    return sender_number


def pending_key_from_chat(chat_jid: str) -> str:
    """Generate base key for chat (without sender - for lookups)."""
    return chat_jid if chat_jid else ""


def find_pending_by_bot_msg(chat_jid: str, bot_msg_id: str) -> tuple:
    """
    Find pending transaction by the bot's question message ID.
    Returns (pkey, pending_data) or (None, None) if not found.
    
    This allows any group member to reply to a specific bot question.
    """
    if not bot_msg_id:
        return None, None
    
    # Search all pending transactions for this chat
    for pkey, pending in _pending_transactions.items():
        # Match by chat_jid prefix and bot_msg_id
        if pkey.startswith(chat_jid) or pkey == chat_jid:
            if pending.get("bot_msg_id") == bot_msg_id:
                if not pending_is_expired(pending):
                    return pkey, pending
    
    return None, None


def find_pending_for_user(sender_number: str, chat_jid: str) -> tuple:
    """
    Find pending transaction for a specific user in chat.
    Returns (pkey, pending_data) or (None, None) if not found.
    """
    pkey = pending_key(sender_number, chat_jid)
    pending = get_pending_transactions(pkey)
    if pending:
        return pkey, pending
    return None, None


def pending_is_expired(pending: dict) -> bool:
    """Check if pending transaction has expired (TTL exceeded)."""
    created = pending.get("created_at")
    if created is None:
        return False
    return (datetime.now() - created).total_seconds() > PENDING_TTL_SECONDS


def get_pending_transactions(pkey: str) -> Optional[Dict]:
    """Get pending transaction data for a key, checking expiry."""
    pending = _pending_transactions.get(pkey)
    if pending and pending_is_expired(pending):
        _pending_transactions.pop(pkey, None)
        return None
    return pending


def set_pending_transaction(pkey: str, data: Dict) -> None:
    """Set pending transaction data."""
    _pending_transactions[pkey] = data


def clear_pending_transaction(pkey: str) -> None:
    """Clear pending transaction for a key."""
    _pending_transactions.pop(pkey, None)


def has_pending_transaction(pkey: str) -> bool:
    """Check if there's a non-expired pending transaction."""
    return get_pending_transactions(pkey) is not None


# ===================== PENDING MESSAGE REFS =====================
# Store bot prompt message IDs -> pending key mapping
# Format: {bot_msg_id: pending_key}
_pending_message_refs: Dict[str, str] = {}


def store_pending_message_ref(bot_msg_id: str, pkey: str) -> None:
    """Store reference from bot's prompt message ID to pending key."""
    if not bot_msg_id or not pkey:
        return
    _pending_message_refs[str(bot_msg_id)] = str(pkey)


def get_pending_key_from_message(bot_msg_id: str) -> str:
    """Get pending key from bot's prompt message ID."""
    return _pending_message_refs.get(str(bot_msg_id), '')


def clear_pending_message_ref(bot_msg_id: str) -> None:
    """Remove a pending message reference."""
    _pending_message_refs.pop(str(bot_msg_id), None)


# ===================== MESSAGE DEDUP =====================
# Format: {message_id: timestamp}
_processed_messages: Dict[str, datetime] = {}


def is_message_duplicate(message_id: str) -> bool:
    """Check if message was already processed (dedup). Returns True if duplicate."""
    if not message_id:
        return False
    
    now = datetime.now()
    with _dedup_lock:
        # Cleanup old entries (older than TTL)
        expired_keys = [k for k, v in _processed_messages.items() 
                       if (now - v).total_seconds() > DEDUP_TTL_SECONDS]
        for k in expired_keys:
            _processed_messages.pop(k, None)
        
        # Check if already processed
        if message_id in _processed_messages:
            return True
        
        # Mark as processed
        _processed_messages[message_id] = now
        return False


# ===================== BOT MESSAGE REFS =====================
# Store bot's confirmation message IDs -> original message ID mapping
# Format: {bot_msg_id: original_tx_msg_id}
_bot_message_refs: Dict[str, str] = {}

# MAX_BOT_REFS imported from config.constants.Timeouts


def store_bot_message_ref(bot_msg_id: str, original_tx_msg_id: str) -> None:
    """Store reference from bot's confirmation message to original transaction message ID."""
    _bot_message_refs[str(bot_msg_id)] = str(original_tx_msg_id)
    
    # Limit cache size to prevent memory issues
    if len(_bot_message_refs) > MAX_BOT_REFS:
        # Remove oldest entries (first 500)
        keys_to_remove = list(_bot_message_refs.keys())[:500]
        for key in keys_to_remove:
            _bot_message_refs.pop(key, None)


def get_original_message_id(bot_msg_id: str) -> str:
    """Get original transaction message ID from bot's confirmation message ID."""
    return _bot_message_refs.get(str(bot_msg_id), '')


# Track last bot report per chat
_last_bot_reports: Dict[str, str] = {}


def store_last_bot_report(chat_id: str, bot_msg_id: str) -> None:
    """Track the most recent bot report ID for a chat."""
    if not chat_id or not bot_msg_id:
        return
    _last_bot_reports[str(chat_id)] = str(bot_msg_id)
    _save_state()


def get_last_bot_report(chat_id: str) -> Optional[str]:
    """Get the most recent bot report ID for a chat."""
    return _last_bot_reports.get(str(chat_id))


# ===================== CONVERSATION TRACKING =====================
# Track last bot interaction per user/chat
# Format: {key: {'timestamp': datetime, 'type': str}}
# key = "chat_id:user_id"
_bot_interactions: Dict[str, Dict] = {}


def record_bot_interaction(user_id: str, chat_id: str, interaction_type: str = 'response') -> None:
    """Record that bot interacted with user."""
    if not user_id:
        return
    
    key = f"{chat_id}:{user_id}" if chat_id else user_id
    
    _bot_interactions[key] = {
        'timestamp': datetime.now(),
        'type': interaction_type
    }
    
    # Cleanup old entries (limit 1000)
    if len(_bot_interactions) > 1000:
        keys = list(_bot_interactions.keys())[:200]
        for k in keys:
             _bot_interactions.pop(k, None)
             
    _save_state()


def get_last_bot_interaction(user_id: str, chat_id: str) -> Optional[Dict]:
    """Get last bot interaction with user."""
    if not user_id:
        return None
        
    key = f"{chat_id}:{user_id}" if chat_id else user_id
    return _bot_interactions.get(key)


# ===================== STATS =====================

def get_state_stats() -> Dict[str, Any]:
    """Get statistics about current state (for debugging)."""
    return {
        'pending_count': len(_pending_transactions),
        'processed_count': len(_processed_messages),
        'bot_refs_count': len(_bot_message_refs),
        'pending_message_refs_count': len(_pending_message_refs),
    }


# ===================== PERSISTENCE =====================
import json
import os

PERSISTENCE_FILE = "data/user_state.json"
_state_lock = threading.Lock()

def _save_state():
    """Save state to local JSON AND Google Sheets (Background)."""
    with _state_lock:
        try:
            data = {
                "pending_transactions": _pending_transactions,
                "bot_message_refs": _bot_message_refs,
                "pending_message_refs": _pending_message_refs,
                "bot_interactions": {k: {**v, 'timestamp': v['timestamp'].isoformat()} for k, v in _bot_interactions.items()},
                "visual_buffer": {k: [
                    {**item, 'created_at': item['created_at'].isoformat() if isinstance(item.get('created_at'), datetime) else item.get('created_at')} 
                    for item in v
                ] for k, v in _visual_buffer.items()},
                "last_bot_reports": _last_bot_reports,
                "pending_confirmations": {k: {**v, 'timestamp': v['timestamp'].isoformat(), 'expires_at': v['expires_at'].isoformat()} for k, v in PENDING_CONFIRMATIONS.items()}
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(PERSISTENCE_FILE), exist_ok=True)
            json_str = json.dumps(data, default=str)

            with open(PERSISTENCE_FILE, 'w') as f:
                f.write(json_str)

            # 3. BACKUP KE GOOGLE SHEETS (Asynchronous / Fire-and-Forget)
            # Pakai thread biar bot tidak lemot nungguin Google API
            # EXCLUDE visual_buffer from cloud backup (too large for base64 images)
            cloud_data = data.copy()
            cloud_data.pop("visual_buffer", None)
            cloud_json = json.dumps(cloud_data, default=str)
            
            threading.Thread(target=save_state_to_cloud, args=(cloud_json,), daemon=True).start()
                
        except Exception as e:
            print(f"[ERROR] Failed to save state: {e}")

def _load_state():
    """Load state from JSON file."""
    global _pending_transactions, _bot_message_refs, _pending_message_refs, _visual_buffer, _bot_interactions
    
    loaded_data = None

    # 1. Coba load dari Local File (Prioritas 1)
    if os.path.exists(PERSISTENCE_FILE):
        try:
            with open(PERSISTENCE_FILE, 'r') as f:
                loaded_data = json.load(f)
                print("[INFO] State loaded from LOCAL storage.")
        except:
            pass
            
    # 2. Jika Local gagal (misal baru Restart Koyeb), Load dari Google Sheets (Prioritas 2)
    if not loaded_data:
        print("[INFO] Local state missing (Koyeb Restart?). Fetching from Google Sheets...")
        try:
            cloud_json = load_state_from_cloud() # Ini synchronous gpp, karena cuma sekali pas start
            if cloud_json:
                loaded_data = json.loads(cloud_json)
                print("[INFO] State restored from GOOGLE SHEETS backup!")
        except Exception as e:
            print(f"[WARNING] Could not restore from cloud: {e}")

    # 3. Terapkan Data ke Variable Memory
    if loaded_data:
        try:
            data = loaded_data
            
            if "pending_transactions" in data:
                _pending_transactions.update(data["pending_transactions"])
                # Restore datetime objects
                for pkey, pending in _pending_transactions.items():
                    if "created_at" in pending and isinstance(pending["created_at"], str):
                        try:
                            pending["created_at"] = datetime.fromisoformat(pending["created_at"])
                        except:
                            pass
                            
            if "bot_message_refs" in data:
                _bot_message_refs.update(data["bot_message_refs"])
                
            if "pending_message_refs" in data:
                _pending_message_refs.update(data["pending_message_refs"])
                
            if "bot_interactions" in data:
                 for k, v in data["bot_interactions"].items():
                     try:
                         v['timestamp'] = datetime.fromisoformat(v['timestamp'])
                         _bot_interactions[k] = v
                     except:
                         pass

            if "visual_buffer" in data:
                 for k, v in data["visual_buffer"].items():
                     reconstructed = []
                     for item in v:
                         if "created_at" in item and isinstance(item["created_at"], str):
                             try:
                                 item["created_at"] = datetime.fromisoformat(item["created_at"])
                             except:
                                 pass
                         reconstructed.append(item)
                     _visual_buffer[k] = reconstructed
                     
            if "last_bot_reports" in data:
                _last_bot_reports.update(data["last_bot_reports"])

            if "pending_confirmations" in data:
                for k, v in data["pending_confirmations"].items():
                    try:
                        v['timestamp'] = datetime.fromisoformat(v['timestamp'])
                        v['expires_at'] = datetime.fromisoformat(v['expires_at'])
                        PENDING_CONFIRMATIONS[k] = v
                    except:
                        pass
                
        except Exception as e:
             print(f"[ERROR] Error parsing loaded state: {e}")

# Load state on startup
_load_state()

def set_pending_confirmation(user_id: str, chat_id: str, data: dict):
    """
    Save pending confirmation state.
    
    Args:
        user_id: User yang nunggu konfirmasi
        chat_id: Chat ID
        data: {
            'type': 'category_scope' | 'dompet_selection' | 'project_name',
            'transactions': [...],  # Data transaksi yang pending
            'context': {...},  # Context tambahan
            'timestamp': datetime,
            'original_message_id': str,
        }
    """
    key = f"{chat_id}:{user_id}"
    PENDING_CONFIRMATIONS[key] = {
        **data,
        'timestamp': datetime.now(),
        'expires_at': datetime.now() + timedelta(minutes=15)
    }
    _save_state()

def get_pending_confirmation(user_id: str, chat_id: str) -> dict:
    """Get pending confirmation data."""
    key = f"{chat_id}:{user_id}"
    pending = PENDING_CONFIRMATIONS.get(key)
    
    # Check expiry
    if pending and pending.get('expires_at'):
        if datetime.now() > pending['expires_at']:
            # Expired, remove
            clear_pending_confirmation(user_id, chat_id)
            return None
    
    return pending
    
def clear_pending_confirmation(user_id: str, chat_id: str):
    """Clear pending state."""
    key = f"{chat_id}:{user_id}"
    if key in PENDING_CONFIRMATIONS:
        del PENDING_CONFIRMATIONS[key]
        _save_state()
        
def has_pending_confirmation(user_id: str, chat_id: str) -> bool:
    """Check if user has pending confirmation."""
    return get_pending_confirmation(user_id, chat_id) is not None


# ===================== USER MESSAGE CONTEXT =====================
# Store user's last message for multi-message context (e.g. split text)
# Format: {key: {'text': str, 'timestamp': datetime}}
# key = "chat_id:user_id"
USER_LAST_MESSAGES = {}

def store_user_message(user_id: str, chat_id: str, text: str):
    """Store user's last message for context."""
    from datetime import datetime
    
    key = f"{chat_id}:{user_id}"
    USER_LAST_MESSAGES[key] = {
        'text': text,
        'timestamp': datetime.now()
    }

def get_user_last_message(user_id: str, chat_id: str, max_age_seconds: int = 60) -> str:
    """Get user's last message if recent enough."""
    from datetime import datetime, timedelta
    
    key = f"{chat_id}:{user_id}"
    last_msg = USER_LAST_MESSAGES.get(key)
    
    if not last_msg:
        return None
    
    # Check age
    if datetime.now() - last_msg['timestamp'] > timedelta(seconds=max_age_seconds):
        return None
    
    return last_msg['text']

def clear_user_last_message(user_id: str, chat_id: str):
    """Clear user's message buffer."""
    key = f"{chat_id}:{user_id}"
    if key in USER_LAST_MESSAGES:
        del USER_LAST_MESSAGES[key]


# ===================== STATS =====================

def get_state_stats() -> Dict[str, Any]:
    """Get statistics about current state (for debugging)."""
    return {
        'pending_count': len(_pending_transactions),
        'pending_conf_count': len(PENDING_CONFIRMATIONS),
        'processed_count': len(_processed_messages),
        'bot_refs_count': len(_bot_message_refs),
        'pending_message_refs_count': len(_pending_message_refs),
    }

# For testing
if __name__ == '__main__':
    print("State Manager Tests")
    # ... tests omitted ...

