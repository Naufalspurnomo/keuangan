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
from datetime import datetime
from typing import Dict, Optional, Any

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
# Format: {user_key: {'media_url': str, 'caption': str, 'message_id': str, 
#                    'created_at': datetime, 'chat_jid': str}}
# user_key = "chat_jid:sender_number" for groups OR sender_number for DM
_visual_buffer: Dict[str, Dict] = {}


def visual_buffer_key(sender_number: str, chat_jid: str) -> str:
    """Generate key for visual buffer per user per chat."""
    if chat_jid and "@g.us" in chat_jid:
        return f"{chat_jid}:{sender_number}"
    return sender_number


def store_visual_buffer(sender_number: str, chat_jid: str, media_url: str, 
                        message_id: str, caption: str = None) -> None:
    """Store photo in visual buffer for later linking."""
    key = visual_buffer_key(sender_number, chat_jid)
    _visual_buffer[key] = {
        'media_url': media_url,
        'message_id': message_id,
        'caption': caption,
        'chat_jid': chat_jid,
        'sender_number': sender_number,
        'created_at': datetime.now()
    }


def get_visual_buffer(sender_number: str, chat_jid: str) -> Optional[Dict]:
    """Get photo from visual buffer if exists and not expired."""
    key = visual_buffer_key(sender_number, chat_jid)
    photo = _visual_buffer.get(key)
    
    if photo:
        created = photo.get('created_at')
        if created and (datetime.now() - created).total_seconds() > VISUAL_BUFFER_TTL_SECONDS:
            # Expired
            _visual_buffer.pop(key, None)
            return None
        return photo
    return None


def clear_visual_buffer(sender_number: str, chat_jid: str) -> None:
    """Clear photo from visual buffer after processing."""
    key = visual_buffer_key(sender_number, chat_jid)
    _visual_buffer.pop(key, None)


def has_visual_buffer(sender_number: str, chat_jid: str) -> bool:
    """Check if user has unexpired photo in buffer."""
    return get_visual_buffer(sender_number, chat_jid) is not None


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


# ===================== STATS =====================

def get_state_stats() -> Dict[str, Any]:
    """Get statistics about current state (for debugging)."""
    return {
        'pending_count': len(_pending_transactions),
        'processed_count': len(_processed_messages),
        'bot_refs_count': len(_bot_message_refs),
        'pending_message_refs_count': len(_pending_message_refs),
    }


# For testing
if __name__ == '__main__':
    print("State Manager Tests")
    
    # Test pending
    pkey = pending_key("6281234567890", "group@g.us")
    print(f"Pending key: {pkey}")
    
    set_pending_transaction(pkey, {
        'transactions': [{'keterangan': 'Test'}],
        'created_at': datetime.now()
    })
    print(f"Has pending: {has_pending_transaction(pkey)}")
    
    # Test dedup
    print(f"Is duplicate (first): {is_message_duplicate('msg123')}")
    print(f"Is duplicate (second): {is_message_duplicate('msg123')}")
    
    # Test refs
    store_bot_message_ref('bot123', 'tx456')
    print(f"Original for bot123: {get_original_message_id('bot123')}")
    
    print(f"Stats: {get_state_stats()}")
