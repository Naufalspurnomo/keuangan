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

# TTL for pending transactions (15 minutes)
PENDING_TTL_SECONDS = 15 * 60

# Dedup window (5 minutes)
DEDUP_TTL_SECONDS = 5 * 60

# Thread lock for dedup operations
_dedup_lock = threading.Lock()

# ===================== PENDING TRANSACTIONS =====================
# Format: {pkey: {'transactions': [...], 'sender_name': str, 'source': str, 'created_at': datetime, 'chat_jid': str}}
# pkey = chat_jid:sender_number (to isolate per chat per user)
_pending_transactions: Dict[str, Dict] = {}


def pending_key(sender_number: str, chat_jid: str) -> str:
    """Generate unique key for pending transactions per chat per user."""
    return f"{chat_jid or sender_number}:{sender_number}"


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

# Maximum refs to keep in cache
MAX_BOT_REFS = 1000


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
