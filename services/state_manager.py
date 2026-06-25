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
import copy
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, Tuple
import json
import os
import re
import shutil
from sheets_helper import save_state_to_cloud, load_state_from_cloud
from config.constants import Timeouts
from security import secure_log
from services.state_store import external_state_required, get_configured_state_store

# Use centralized timeouts
PENDING_TTL_SECONDS = Timeouts.PENDING_TRANSACTION
DEDUP_TTL_SECONDS = Timeouts.DEDUP_WINDOW
MAX_BOT_REFS = Timeouts.BOT_REFS_MAX
PROJECT_LOCK_TRUST_SECONDS = int(os.getenv("PROJECT_LOCK_TRUST_SECONDS", "21600"))

# Visual Buffer TTL (2 minutes - photos expire quickly)
VISUAL_BUFFER_TTL_SECONDS = 120
VISUAL_CONSUMED_TTL_SECONDS = 6 * 60 * 60

# Thread lock for dedup operations
_dedup_lock = threading.Lock()
_visual_lock = threading.Lock()
_pending_lock = threading.Lock()
_refs_lock = threading.Lock()
_registry_lock = threading.Lock()
_confirmation_lock = threading.Lock()
_user_message_lock = threading.Lock()

# ===================== VISUAL BUFFER (Grand Design Layer 2) =====================
# Stores unprocessed photos for linking with later text commands
# Format: {user_key: [ {'media_url': str, 'caption': str, ...}, ... ]}
# user_key = "chat_jid:sender_number" for groups OR sender_number for DM
_visual_buffer: Dict[str, list] = {}
_consumed_visual_messages: Dict[str, datetime] = {}

# ===================== PENDING CONFIRMATIONS (NEW) =====================
# For AI Ambiguity Checks (Step 0 & Step 2)
PENDING_CONFIRMATIONS: Dict[str, Dict] = {}


def visual_buffer_key(sender_number: str, chat_jid: str) -> str:
    """Generate key for visual buffer per user per chat."""
    if chat_jid and "@g.us" in chat_jid:
        return f"{chat_jid}:{sender_number}"
    return sender_number


def _visual_item_is_valid(item: dict, now: Optional[datetime] = None) -> bool:
    created = item.get('created_at') if isinstance(item, dict) else None
    if not isinstance(created, datetime):
        return False
    now = now or datetime.now()
    return (now - created).total_seconds() <= VISUAL_BUFFER_TTL_SECONDS


def _prune_visual_buffer_locked(now: Optional[datetime] = None) -> None:
    now = now or datetime.now()
    for key, items in list(_visual_buffer.items()):
        if not isinstance(items, list):
            _visual_buffer.pop(key, None)
            continue
        valid_items = [item for item in items if _visual_item_is_valid(item, now)]
        if valid_items:
            _visual_buffer[key] = valid_items
        else:
            _visual_buffer.pop(key, None)


def _visual_consumed_key(chat_jid: str, message_id: str) -> str:
    mid = str(message_id or "").strip()
    if not mid:
        return ""
    chat = str(chat_jid or "").strip()
    return f"{chat}:{mid}" if chat else mid


def _prune_consumed_visual_locked(now: Optional[datetime] = None) -> None:
    now = now or datetime.now()
    expired = []
    for key, ts in _consumed_visual_messages.items():
        if not isinstance(ts, datetime):
            expired.append(key)
            continue
        if (now - ts).total_seconds() > VISUAL_CONSUMED_TTL_SECONDS:
            expired.append(key)
    for key in expired:
        _consumed_visual_messages.pop(key, None)


def store_visual_buffer(sender_number: str, chat_jid: str, media_url: str,
                        message_id: str, caption: str = None,
                        media_path: str = None, context: Optional[dict] = None) -> None:
    """Store photo in visual buffer for later linking (Appends to list)."""
    key = visual_buffer_key(sender_number, chat_jid)
    safe_context = context if isinstance(context, dict) else {}
    item = {
        'media_url': media_url,
        'media_path': media_path,
        'message_id': message_id,
        'caption': caption,
        'context': safe_context,
        'chat_jid': chat_jid,
        'sender_number': sender_number,
        'created_at': datetime.now()
    }
    with _visual_lock:
        _prune_visual_buffer_locked()
        if key not in _visual_buffer:
            _visual_buffer[key] = []

        replaced = False
        if message_id:
            for idx, existing in enumerate(_visual_buffer[key]):
                if existing.get('message_id') == message_id:
                    _visual_buffer[key][idx] = item
                    replaced = True
                    break
        if not replaced:
            _visual_buffer[key].append(item)

        _visual_buffer[key].sort(key=lambda x: x.get('created_at') or datetime.min)


def get_visual_buffer(sender_number: str, chat_jid: str) -> list:
    """
    Get ALL unexpired photos from visual buffer.
    Returns list of dicts.
    """
    key = visual_buffer_key(sender_number, chat_jid)
    with _visual_lock:
        _prune_visual_buffer_locked()
        items = _visual_buffer.get(key, [])
        return list(items) if items else []


def get_visual_buffer_by_message(chat_jid: str, message_id: str) -> Optional[dict]:
    """
    Find buffered visual item by message ID across users in the same chat.
    Useful for group reply flows (A sends image, B replies with text).
    """
    if not message_id:
        return None
    target_msg_id = str(message_id)
    target_chat = str(chat_jid or "")
    with _visual_lock:
        _prune_visual_buffer_locked()
        for items in _visual_buffer.values():
            for item in items:
                if str(item.get('message_id') or "") != target_msg_id:
                    continue
                item_chat = str(item.get('chat_jid') or "")
                if target_chat and item_chat != target_chat:
                    continue
                return dict(item)
    return None


def remove_visual_buffer_by_message(chat_jid: str, message_id: str) -> bool:
    """Remove a buffered visual item by message ID."""
    if not message_id:
        return False
    removed = False
    target_msg_id = str(message_id)
    target_chat = str(chat_jid or "")
    with _visual_lock:
        _prune_visual_buffer_locked()
        for key, items in list(_visual_buffer.items()):
            kept = []
            for item in items:
                same_msg = str(item.get('message_id') or "") == target_msg_id
                same_chat = not target_chat or str(item.get('chat_jid') or "") == target_chat
                if same_msg and same_chat:
                    removed = True
                    continue
                kept.append(item)
            if kept:
                _visual_buffer[key] = kept
            else:
                _visual_buffer.pop(key, None)
    return removed


def mark_visual_message_consumed(chat_jid: str, message_id: str) -> bool:
    """
    Mark a visual message as consumed once processing starts.
    Returns False if already consumed within TTL.
    """
    key = _visual_consumed_key(chat_jid, message_id)
    if not key:
        return True
    now = datetime.now()
    with _visual_lock:
        _prune_consumed_visual_locked(now)
        if key in _consumed_visual_messages:
            return False
        _consumed_visual_messages[key] = now
    return True


def clear_visual_message_consumed(chat_jid: str, message_id: str) -> None:
    """Clear consumed mark (used when processing fails and should be retryable)."""
    key = _visual_consumed_key(chat_jid, message_id)
    if not key:
        return
    with _visual_lock:
        _consumed_visual_messages.pop(key, None)


def is_visual_message_consumed(chat_jid: str, message_id: str) -> bool:
    """Check whether a visual message has been consumed recently."""
    key = _visual_consumed_key(chat_jid, message_id)
    if not key:
        return False
    now = datetime.now()
    with _visual_lock:
        _prune_consumed_visual_locked(now)
        return key in _consumed_visual_messages


def clear_visual_buffer(sender_number: str, chat_jid: str) -> None:
    """Clear photos from visual buffer after processing."""
    key = visual_buffer_key(sender_number, chat_jid)
    with _visual_lock:
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

# Bot prompt message ID -> pending key mapping
# Format: {bot_msg_id: "chat@g.us:628xxx" or "628xxx"}
_pending_message_refs: Dict[str, str] = {}


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

    chat_key = str(chat_jid or "")
    with _pending_lock:
        # Search all pending transactions for this chat
        for pkey, pending in list(_pending_transactions.items()):
            if not isinstance(pkey, str):
                _pending_transactions.pop(pkey, None)
                continue
            # Match by chat_jid prefix and bot_msg_id
            if pkey.startswith(chat_key) or pkey == chat_key:
                if pending.get("bot_msg_id") == bot_msg_id:
                    if pending_is_expired(pending):
                        _pending_transactions.pop(pkey, None)
                        continue
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
    if not isinstance(pkey, str) or not pkey.strip():
        return None
    with _pending_lock:
        pending = _pending_transactions.get(pkey)
        if pending and pending_is_expired(pending):
            _pending_transactions.pop(pkey, None)
            return None
        return pending


def set_pending_transaction(pkey: str, data: Dict) -> None:
    """Set pending transaction data."""
    if not isinstance(pkey, str):
        return
    key = pkey.strip()
    if not key:
        return
    with _pending_lock:
        _pending_transactions[key] = data


def clear_pending_transaction(pkey: str) -> None:
    """Clear pending transaction for a key."""
    if not isinstance(pkey, str) or not pkey.strip():
        return
    with _pending_lock:
        _pending_transactions.pop(pkey, None)


def has_pending_transaction(pkey: str) -> bool:
    """Check if there's a non-expired pending transaction."""
    return get_pending_transactions(pkey) is not None


# ===================== PENDING MESSAGE REFS =====================


def store_pending_message_ref(bot_msg_id: str, pending_key_ref: str) -> None:
    """Store mapping from bot prompt message ID to pending key."""
    bid = str(bot_msg_id or "").strip()
    pref = str(pending_key_ref or "").strip()
    if not bid or not pref:
        return
    with _pending_lock:
        _pending_message_refs[bid] = pref

        # Keep cache bounded to avoid unbounded growth.
        if len(_pending_message_refs) > MAX_BOT_REFS:
            keys_to_remove = list(_pending_message_refs.keys())[:500]
            for key in keys_to_remove:
                _pending_message_refs.pop(key, None)


def get_pending_key_from_message(bot_msg_id: str) -> str:
    """Resolve pending key from bot prompt message ID."""
    bid = str(bot_msg_id or "").strip()
    if not bid:
        return ""

    with _pending_lock:
        # Fast path: exact key.
        pending_ref = _pending_message_refs.get(bid)
        if pending_ref:
            return str(pending_ref)

        # Fallback for providers that change casing or whitespace around IDs.
        alt = bid.lower()
        if alt != bid:
            pending_ref = _pending_message_refs.get(alt)
            if pending_ref:
                return str(pending_ref)
    return ""


def clear_pending_message_ref(bot_msg_id: str) -> None:
    """Remove a pending message reference."""
    bid = str(bot_msg_id or "").strip()
    if not bid:
        return
    with _pending_lock:
        _pending_message_refs.pop(bid, None)


# ===================== MESSAGE DEDUP =====================
# Format: {message_id: timestamp}
_processed_messages: Dict[str, Any] = {}
_project_registry: Dict[str, str] = {}  # project_name(lower) -> dompet_sheet
_project_knowledge: Dict[str, Any] = {"projects": {}, "aliases": {}}
_audit_log: list = []
_last_state_save: Optional[datetime] = None


def _normalize_dedup_entry(entry: Any) -> Tuple[Optional[datetime], int]:
    """Normalize dedup entry to (timestamp, score)."""
    if isinstance(entry, dict):
        ts = entry.get("ts") or entry.get("timestamp")
        score = int(entry.get("score", 0) or 0)
    else:
        ts = entry
        score = 0

    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            ts = None
    return ts, score


def is_message_duplicate(message_id: str, score: int = 0, allow_upgrade: bool = False) -> bool:
    """Check if message was already processed (dedup). Returns True if duplicate."""
    if not message_id:
        return False
    global _last_state_save
    
    now = datetime.now()
    should_save = False
    with _dedup_lock:
        # Cleanup old entries (older than TTL)
        expired_keys = []
        for k, v in _processed_messages.items():
            ts, _score = _normalize_dedup_entry(v)
            if ts and (now - ts).total_seconds() > DEDUP_TTL_SECONDS:
                expired_keys.append(k)
        for k in expired_keys:
            _processed_messages.pop(k, None)
        
        # Check if already processed
        if message_id in _processed_messages:
            _, prev_score = _normalize_dedup_entry(_processed_messages.get(message_id))
            if allow_upgrade and score > prev_score:
                _processed_messages[message_id] = {"ts": now, "score": int(score or 0)}
                if _last_state_save is None or (now - _last_state_save).total_seconds() > 30:
                    _last_state_save = now
                    should_save = True
                duplicate = False
            else:
                duplicate = True
        else:
            # Mark as processed
            _processed_messages[message_id] = {"ts": now, "score": int(score or 0)}
            # Persist occasionally to survive restarts (idempotency)
            if _last_state_save is None or (now - _last_state_save).total_seconds() > 30:
                _last_state_save = now
                should_save = True
            duplicate = False

    if should_save:
        _save_state()
    return duplicate


def clear_message_duplicate(message_id: str) -> None:
    """Remove message id from dedup cache (allow retry)."""
    if not message_id:
        return
    with _dedup_lock:
        _processed_messages.pop(message_id, None)
    _save_state()


# ===================== BOT MESSAGE REFS =====================
# Store bot's confirmation message IDs -> original message ID mapping
# Format: {bot_msg_id: original_tx_msg_id}
_bot_message_refs: Dict[str, str] = {}

# MAX_BOT_REFS imported from config.constants.Timeouts


def store_bot_message_ref(bot_msg_id: str, original_tx_msg_id: str) -> None:
    """Store reference from bot's confirmation message to original transaction message ID."""
    with _refs_lock:
        _bot_message_refs[str(bot_msg_id)] = str(original_tx_msg_id)

        # Limit cache size to prevent memory issues
        if len(_bot_message_refs) > MAX_BOT_REFS:
            # Remove oldest entries (first 500)
            keys_to_remove = list(_bot_message_refs.keys())[:500]
            for key in keys_to_remove:
                _bot_message_refs.pop(key, None)


def get_original_message_id(bot_msg_id: str) -> str:
    """Get original transaction message ID from bot's confirmation message ID."""
    with _refs_lock:
        return _bot_message_refs.get(str(bot_msg_id), '')


# Track last bot report per chat
_last_bot_reports: Dict[str, str] = {}

# Track last transaction event per user/chat (for /revisi fallback)
_last_tx_events: Dict[str, str] = {}


def store_last_bot_report(chat_id: str, bot_msg_id: str) -> None:
    """Track the most recent bot report ID for a chat."""
    if not chat_id or not bot_msg_id:
        return
    with _refs_lock:
        _last_bot_reports[str(chat_id)] = str(bot_msg_id)
    _save_state()


def get_last_bot_report(chat_id: str) -> Optional[str]:
    """Get the most recent bot report ID for a chat."""
    with _refs_lock:
        return _last_bot_reports.get(str(chat_id))


def _last_tx_key(user_id: str, chat_id: str) -> str:
    return f"{chat_id}:{user_id}" if chat_id else user_id


def store_last_tx_event(user_id: str, chat_id: str, event_id: str) -> None:
    """Track last transaction event ID per user/chat for revision fallback."""
    if not user_id or not event_id:
        return
    key = _last_tx_key(user_id, chat_id)
    with _refs_lock:
        _last_tx_events[str(key)] = str(event_id)
    _save_state()


def get_last_tx_event(user_id: str, chat_id: str) -> Optional[str]:
    """Get last transaction event ID per user/chat."""
    if not user_id:
        return None
    key = _last_tx_key(user_id, chat_id)
    with _refs_lock:
        return _last_tx_events.get(str(key))


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

    with _refs_lock:
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
    with _refs_lock:
        return _bot_interactions.get(key)


# ===================== STATS =====================

def get_state_stats() -> Dict[str, Any]:
    """Get statistics about current state (for debugging)."""
    with _pending_lock:
        pending_count = len(_pending_transactions)
        pending_message_refs_count = len(_pending_message_refs)
    with _dedup_lock:
        processed_count = len(_processed_messages)
    with _refs_lock:
        bot_refs_count = len(_bot_message_refs)
    return {
        'pending_count': pending_count,
        'processed_count': processed_count,
        'bot_refs_count': bot_refs_count,
        'pending_message_refs_count': pending_message_refs_count,
    }


# ===================== PERSISTENCE =====================
PERSISTENCE_FILE = "data/user_state.json"
PERSISTENCE_BACKUP_FILE = f"{PERSISTENCE_FILE}.bak"
CLOUD_STATE_MAX_CHARS = 500000
_state_lock = threading.Lock()
_cloud_save_lock = threading.Lock()
_cloud_save_latest: Optional[str] = None
_cloud_save_thread_running = False

_STATE_SECTION_TYPES = {
    "pending_transactions": dict,
    "bot_message_refs": dict,
    "pending_message_refs": dict,
    "processed_messages": dict,
    "project_registry": dict,
    "project_knowledge": dict,
    "audit_log": list,
    "bot_interactions": dict,
    "visual_buffer": dict,
    "last_bot_reports": dict,
    "last_tx_events": dict,
    "pending_confirmations": dict,
}

def _sanitize_keys(obj):
    """Ensure all dict keys are JSON-serializable strings."""
    if isinstance(obj, dict):
        return {str(k): _sanitize_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_keys(v) for v in obj]
    return obj


def _validate_state_payload(payload: Any, source_label: str) -> Optional[Dict[str, Any]]:
    """Validate and sanitize top-level persisted state sections."""
    if not isinstance(payload, dict):
        secure_log("ERROR", "Persisted state is not a JSON object", source=source_label, actual_type=type(payload).__name__)
        return None

    sanitized = {}
    for key, value in payload.items():
        expected_type = _STATE_SECTION_TYPES.get(key)
        if expected_type is None:
            # Keep unknown sections for forward compatibility, but only when
            # they are ordinary JSON containers/scalars.
            sanitized[key] = value
            continue
        if not isinstance(value, expected_type):
            secure_log(
                "WARNING",
                "Skipping invalid persisted state section",
                source=source_label,
                section=key,
                actual_type=type(value).__name__,
                expected_type=expected_type.__name__,
            )
            continue
        sanitized[key] = value
    return sanitized


def _load_state_file(path: str, source_label: str) -> Optional[Dict[str, Any]]:
    """Load one JSON state file and return validated payload or None."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        loaded = _validate_state_payload(raw_data, source_label)
        if loaded is not None:
            secure_log("INFO", f"State loaded from {source_label}.")
        return loaded
    except (OSError, json.JSONDecodeError) as e:
        secure_log("ERROR", f"Failed to load {source_label} state: {type(e).__name__}: {e}")
        return None


def _write_state_file_atomic(path: str, contents: str) -> None:
    """Write state with same-directory atomic replace and previous-file backup."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    backup_path = f"{path}.bak"

    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(contents)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(path):
            try:
                shutil.copy2(path, backup_path)
            except OSError as e:
                secure_log("WARNING", f"Failed to refresh state backup: {type(e).__name__}: {e}")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as e:
                secure_log("WARNING", f"Failed to remove temporary state file: {type(e).__name__}: {e}")


def _external_state_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare state for durable external storage."""
    external_data = copy.deepcopy(data)
    # Visual buffers contain short-lived media references/base64 and are not
    # critical after restart. Keeping them out avoids unnecessary DB bloat.
    external_data.pop("visual_buffer", None)
    sanitized = _sanitize_keys(external_data)
    # psycopg JSONB adaptation is stricter than local json.dumps(default=str).
    # Normalize nested datetime/date-like values before handing payload to Postgres.
    return json.loads(json.dumps(sanitized, default=str))


def _save_state_to_external(data: Dict[str, Any]) -> bool:
    """Save state to configured external store. Returns True when used."""
    store = get_configured_state_store()
    if not store:
        if external_state_required():
            raise RuntimeError("External state store is required but not configured")
        return False
    try:
        store.save(_external_state_payload(data))
        return True
    except Exception as e:
        secure_log("ERROR", f"Failed to save external state: {type(e).__name__}: {e}")
        if external_state_required():
            raise
        return False


def _load_state_from_external() -> Optional[Dict[str, Any]]:
    """Load validated state from configured external store."""
    store = get_configured_state_store()
    if not store:
        if external_state_required():
            raise RuntimeError("External state store is required but not configured")
        return None
    try:
        payload = store.load()
        if not payload:
            secure_log("INFO", "External state store is empty.")
            return None
        loaded = _validate_state_payload(payload, "EXTERNAL state store")
        if loaded is not None:
            secure_log("INFO", "State loaded from EXTERNAL state store.")
        return loaded
    except Exception as e:
        secure_log("ERROR", f"Failed to load external state: {type(e).__name__}: {e}")
        if external_state_required():
            raise
        return None


def _cloud_save_worker() -> None:
    """Drain pending cloud-save payloads with at most one worker thread."""
    global _cloud_save_latest, _cloud_save_thread_running

    while True:
        with _cloud_save_lock:
            payload = _cloud_save_latest
            _cloud_save_latest = None
            if payload is None:
                _cloud_save_thread_running = False
                return

        try:
            save_state_to_cloud(payload)
        except Exception as e:
            secure_log("ERROR", f"Cloud state save worker failed: {type(e).__name__}: {e}")


def _schedule_cloud_state_save(cloud_json: str) -> None:
    """Schedule a cloud backup, coalescing rapid state changes."""
    global _cloud_save_latest, _cloud_save_thread_running

    with _cloud_save_lock:
        _cloud_save_latest = cloud_json
        if _cloud_save_thread_running:
            return
        _cloud_save_thread_running = True

    threading.Thread(target=_cloud_save_worker, daemon=True).start()


def _save_state():
    """Save state to local JSON AND Google Sheets (Background)."""
    with _state_lock:
        try:
            # Normalize processed_messages for persistence
            with _dedup_lock:
                processed_items = list(_processed_messages.items())
            processed_dump = {}
            for k, v in processed_items:
                ts, score = _normalize_dedup_entry(v)
                if isinstance(ts, datetime):
                    processed_dump[k] = {"ts": ts.isoformat(), "score": int(score or 0)}
                elif ts:
                    processed_dump[k] = {"ts": str(ts), "score": int(score or 0)}
                else:
                    processed_dump[k] = {"ts": None, "score": int(score or 0)}

            with _pending_lock:
                pending_transactions_dump = copy.deepcopy(_pending_transactions)
                pending_message_refs_dump = dict(_pending_message_refs)

            with _refs_lock:
                bot_message_refs_dump = dict(_bot_message_refs)
                bot_interactions_dump = copy.deepcopy(_bot_interactions)
                last_bot_reports_dump = dict(_last_bot_reports)
                last_tx_events_dump = dict(_last_tx_events)

            with _visual_lock:
                visual_buffer_dump = copy.deepcopy(_visual_buffer)

            with _registry_lock:
                project_registry_dump = dict(_project_registry)
                project_knowledge_dump = copy.deepcopy(_project_knowledge)
                audit_log_dump = list(_audit_log)

            with _confirmation_lock:
                pending_confirmations_dump = copy.deepcopy(PENDING_CONFIRMATIONS)

            data = {
                "pending_transactions": pending_transactions_dump,
                "bot_message_refs": bot_message_refs_dump,
                "pending_message_refs": pending_message_refs_dump,
                "processed_messages": processed_dump,
                "project_registry": project_registry_dump,
                "project_knowledge": project_knowledge_dump,
                "audit_log": audit_log_dump,
                "bot_interactions": {
                    k: {**v, 'timestamp': v['timestamp'].isoformat() if isinstance(v.get('timestamp'), datetime) else str(v.get('timestamp', ''))}
                    for k, v in bot_interactions_dump.items() if isinstance(v, dict)
                },
                "visual_buffer": {k: [
                    {**item, 'created_at': item['created_at'].isoformat() if isinstance(item.get('created_at'), datetime) else item.get('created_at')} 
                    for item in v
                ] for k, v in visual_buffer_dump.items()},
                "last_bot_reports": last_bot_reports_dump,
                "last_tx_events": last_tx_events_dump,
                "pending_confirmations": {
                    k: {
                        **v,
                        'timestamp': v['timestamp'].isoformat() if isinstance(v.get('timestamp'), datetime) else str(v.get('timestamp', '')),
                        'expires_at': v['expires_at'].isoformat() if isinstance(v.get('expires_at'), datetime) else str(v.get('expires_at', ''))
                    }
                    for k, v in pending_confirmations_dump.items() if isinstance(v, dict)
                }
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(PERSISTENCE_FILE), exist_ok=True)
            safe_data = _sanitize_keys(data)
            json_str = json.dumps(safe_data, default=str)
            _write_state_file_atomic(PERSISTENCE_FILE, json_str)
            external_state_saved = _save_state_to_external(data)

            if external_state_saved and os.getenv("ENABLE_GOOGLE_STATE_BACKUP", "").strip().lower() not in {"1", "true", "yes"}:
                return

            # 3. BACKUP KE GOOGLE SHEETS (Asynchronous / Fire-and-Forget)
            # Pakai thread biar bot tidak lemot nungguin Google API
            # EXCLUDE visual_buffer from cloud backup (too large for base64 images)
            cloud_data = copy.deepcopy(data)
            cloud_data.pop("visual_buffer", None)
            # Prune large fields for cloud backup to stay under cell limit (~50k chars)
            def _trim_dict(d: dict, max_items: int) -> dict:
                if not isinstance(d, dict):
                    return d
                if len(d) <= max_items:
                    return d
                # Keep newest items by insertion order
                return dict(list(d.items())[-max_items:])

            def _prune_transactions(transactions: Any) -> Any:
                if not isinstance(transactions, list):
                    return transactions
                for tx in transactions:
                    if not isinstance(tx, dict):
                        continue
                    for noisy_key in ("ocr_text", "raw_ocr", "base64_images", "image_data", "raw_image"):
                        tx.pop(noisy_key, None)
                    ket = tx.get("keterangan")
                    if isinstance(ket, str) and len(ket) > 500:
                        tx["keterangan"] = ket[:500]
                return transactions

            def _prune_pending_entry(entry: Any) -> Any:
                if not isinstance(entry, dict):
                    return entry
                entry["transactions"] = _prune_transactions(entry.get("transactions"))
                attachments = entry.get("attachments")
                if isinstance(attachments, dict):
                    media_url = attachments.get("media_url")
                    if isinstance(media_url, str) and media_url.startswith("data:"):
                        attachments["media_url"] = ""
                for text_key in ("original_text", "normalized_text", "caption", "raw_text"):
                    value = entry.get(text_key)
                    if isinstance(value, str) and len(value) > 500:
                        entry[text_key] = value[:500]
                return entry

            cloud_data["processed_messages"] = _trim_dict(cloud_data.get("processed_messages", {}), 500)
            cloud_data["bot_message_refs"] = _trim_dict(cloud_data.get("bot_message_refs", {}), 200)
            cloud_data["pending_message_refs"] = _trim_dict(cloud_data.get("pending_message_refs", {}), 200)
            cloud_data["bot_interactions"] = _trim_dict(cloud_data.get("bot_interactions", {}), 200)
            cloud_data["last_bot_reports"] = _trim_dict(cloud_data.get("last_bot_reports", {}), 200)
            cloud_data["last_tx_events"] = _trim_dict(cloud_data.get("last_tx_events", {}), 200)
            cloud_data["pending_transactions"] = _trim_dict(cloud_data.get("pending_transactions", {}), 80)
            cloud_data["pending_confirmations"] = _trim_dict(cloud_data.get("pending_confirmations", {}), 80)
            cloud_data["audit_log"] = []  # Skip audit log for cloud to save space

            if isinstance(cloud_data.get("pending_transactions"), dict):
                for key, pending in list(cloud_data["pending_transactions"].items()):
                    cloud_data["pending_transactions"][key] = _prune_pending_entry(pending)

            if isinstance(cloud_data.get("pending_confirmations"), dict):
                for key, pending_conf in list(cloud_data["pending_confirmations"].items()):
                    cloud_data["pending_confirmations"][key] = _prune_pending_entry(pending_conf)

            cloud_json = json.dumps(_sanitize_keys(cloud_data), default=str, separators=(",", ":"))
            # Chunked Google Sheets backup supports larger state than one cell.
            # If it is still very large, drop non-critical caches before pending state.
            if len(cloud_json) > CLOUD_STATE_MAX_CHARS:
                cloud_data["processed_messages"] = {}
                cloud_data["bot_message_refs"] = {}
                cloud_data["pending_message_refs"] = {}
                cloud_data["bot_interactions"] = {}
                cloud_data["last_bot_reports"] = {}
                cloud_data["last_tx_events"] = {}
                cloud_json = json.dumps(_sanitize_keys(cloud_data), default=str, separators=(",", ":"))
            if len(cloud_json) > CLOUD_STATE_MAX_CHARS:
                cloud_data["pending_transactions"] = {}
                cloud_data["pending_confirmations"] = {}
                cloud_json = json.dumps(_sanitize_keys(cloud_data), default=str, separators=(",", ":"))
            
            _schedule_cloud_state_save(cloud_json)
                
        except Exception as e:
            secure_log("ERROR", f"Failed to save state: {type(e).__name__}: {e}")
            if external_state_required():
                raise

def _load_state():
    """Load state from JSON file."""
    global _pending_transactions, _bot_message_refs, _pending_message_refs, _visual_buffer, _bot_interactions
    
    loaded_data = None

    # 1. Coba load dari external store (Postgres) jika dikonfigurasi.
    loaded_data = _load_state_from_external()

    # 2. Coba load dari Local File, lalu backup file.
    for path, label in (
        (PERSISTENCE_FILE, "LOCAL storage"),
        (PERSISTENCE_BACKUP_FILE, "LOCAL backup storage"),
    ):
        if loaded_data:
            break
        if not os.path.exists(path):
            continue
        loaded_data = _load_state_file(path, label)
        if loaded_data:
            break
            
    # 3. Jika Local gagal (misal baru Restart Koyeb), Load dari Google Sheets.
    if not loaded_data:
        secure_log("INFO", "Local state missing (Koyeb Restart?). Fetching from Google Sheets...")
        try:
            cloud_json = load_state_from_cloud() # Ini synchronous gpp, karena cuma sekali pas start
            if cloud_json:
                loaded_data = _validate_state_payload(json.loads(cloud_json), "GOOGLE SHEETS backup")
                if loaded_data:
                    secure_log("INFO", "State restored from GOOGLE SHEETS backup.")
        except Exception as e:
            secure_log("WARNING", f"Could not restore state from cloud: {type(e).__name__}: {e}")

    # 3. Terapkan Data ke Variable Memory
    if loaded_data:
        try:
            data = loaded_data
            
            if "pending_transactions" in data:
                with _pending_lock:
                    _pending_transactions.update(data["pending_transactions"])
                    # Restore datetime objects
                    for pkey, pending in _pending_transactions.items():
                        if "created_at" in pending and isinstance(pending["created_at"], str):
                            try:
                                pending["created_at"] = datetime.fromisoformat(pending["created_at"])
                            except (TypeError, ValueError) as e:
                                secure_log("WARNING", "Invalid pending transaction timestamp", pending_key=pkey, error_type=type(e).__name__)
                            
            if "bot_message_refs" in data:
                with _refs_lock:
                    _bot_message_refs.update(data["bot_message_refs"])
                
            if "pending_message_refs" in data:
                with _pending_lock:
                    _pending_message_refs.update(data["pending_message_refs"])

            if "processed_messages" in data:
                with _dedup_lock:
                    for k, v in data["processed_messages"].items():
                        try:
                            if isinstance(v, dict):
                                ts_raw = v.get("ts")
                                score = int(v.get("score", 0) or 0)
                            else:
                                ts_raw = v
                                score = 0
                            ts = datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else ts_raw
                            if ts and (datetime.now() - ts).total_seconds() <= DEDUP_TTL_SECONDS:
                                _processed_messages[k] = {"ts": ts, "score": score}
                        except (TypeError, ValueError) as e:
                            secure_log("WARNING", "Invalid processed message state entry", message_key=k, error_type=type(e).__name__)

            if "project_registry" in data:
                if isinstance(data["project_registry"], dict):
                    with _registry_lock:
                        _project_registry.update(data["project_registry"])

            if "project_knowledge" in data:
                if isinstance(data["project_knowledge"], dict):
                    projects = data["project_knowledge"].get("projects", {})
                    aliases = data["project_knowledge"].get("aliases", {})
                    if isinstance(projects, dict) and isinstance(aliases, dict):
                        with _registry_lock:
                            _project_knowledge["projects"].update(projects)
                            _project_knowledge["aliases"].update(aliases)

            if "audit_log" in data:
                if isinstance(data["audit_log"], list):
                    with _registry_lock:
                        _audit_log.extend(data["audit_log"][:500])
                
            if "bot_interactions" in data:
                 with _refs_lock:
                     for k, v in data["bot_interactions"].items():
                         try:
                             v['timestamp'] = datetime.fromisoformat(v['timestamp'])
                             _bot_interactions[k] = v
                         except (KeyError, TypeError, ValueError) as e:
                             secure_log("WARNING", "Invalid bot interaction state entry", interaction_key=k, error_type=type(e).__name__)

            if "visual_buffer" in data:
                 with _visual_lock:
                     for k, v in data["visual_buffer"].items():
                         reconstructed = []
                         for item in v:
                             if "created_at" in item and isinstance(item["created_at"], str):
                                 try:
                                     item["created_at"] = datetime.fromisoformat(item["created_at"])
                                 except (TypeError, ValueError) as e:
                                     secure_log("WARNING", "Invalid visual buffer timestamp", visual_key=k, error_type=type(e).__name__)
                             reconstructed.append(item)
                         _visual_buffer[k] = reconstructed
                     
            if "last_bot_reports" in data:
                with _refs_lock:
                    _last_bot_reports.update(data["last_bot_reports"])

            if "last_tx_events" in data:
                if isinstance(data["last_tx_events"], dict):
                    with _refs_lock:
                        _last_tx_events.update(data["last_tx_events"])

            if "pending_confirmations" in data:
                with _confirmation_lock:
                    for k, v in data["pending_confirmations"].items():
                        try:
                            v['timestamp'] = datetime.fromisoformat(v['timestamp'])
                            v['expires_at'] = datetime.fromisoformat(v['expires_at'])
                            PENDING_CONFIRMATIONS[k] = v
                        except (KeyError, TypeError, ValueError) as e:
                            secure_log("WARNING", "Invalid pending confirmation state entry", confirmation_key=k, error_type=type(e).__name__)
                
        except Exception as e:
             secure_log("ERROR", f"Error parsing loaded state: {type(e).__name__}: {e}")

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
    with _confirmation_lock:
        PENDING_CONFIRMATIONS[key] = {
            **data,
            'timestamp': datetime.now(),
            'expires_at': datetime.now() + timedelta(minutes=15)
        }
    _save_state()

def get_pending_confirmation(user_id: str, chat_id: str) -> dict:
    """Get pending confirmation data."""
    key = f"{chat_id}:{user_id}"
    should_save = False
    with _confirmation_lock:
        pending = PENDING_CONFIRMATIONS.get(key)

        # Check expiry
        if pending and pending.get('expires_at'):
            if datetime.now() > pending['expires_at']:
                # Expired, remove
                PENDING_CONFIRMATIONS.pop(key, None)
                should_save = True
                pending = None

    if should_save:
        _save_state()
    return pending
    
def clear_pending_confirmation(user_id: str, chat_id: str):
    """Clear pending state."""
    key = f"{chat_id}:{user_id}"
    with _confirmation_lock:
        removed = PENDING_CONFIRMATIONS.pop(key, None) is not None
    if removed:
        _save_state()
        
def has_pending_confirmation(user_id: str, chat_id: str) -> bool:
    """Check if user has pending confirmation."""
    return get_pending_confirmation(user_id, chat_id) is not None


def find_pending_confirmation_in_chat(chat_id: str):
    """
    Find a single pending confirmation in a chat (any user).
    Returns (key, pending) if exactly one active pending exists.
    """
    if not chat_id:
        return None, None
    now = datetime.now()
    matches = []
    expired_removed = False
    with _confirmation_lock:
        for key, pending in list(PENDING_CONFIRMATIONS.items()):
            if not key.startswith(f"{chat_id}:"):
                continue
            expires = pending.get('expires_at')
            if expires and now > expires:
                # Clean expired entry
                PENDING_CONFIRMATIONS.pop(key, None)
                expired_removed = True
                continue
            matches.append((key, pending))
    if expired_removed:
        _save_state()
    if len(matches) == 1:
        return matches[0]
    return None, None


# ===================== PROJECT REGISTRY =====================
def _normalize_project_key(name: str) -> str:
    if not name:
        return ""
    clean = name.strip()
    # Remove (Start)/(Finish)/(Selesai) markers
    clean = clean.replace("(Start)", "").replace("(Finish)", "").replace("(Selesai)", "")
    clean = clean.replace("(start)", "").replace("(finish)", "").replace("(selesai)", "")
    return clean.strip().lower()


def _normalize_project_alias(name: str) -> str:
    if not name:
        return ""
    try:
        from config.wallets import strip_company_prefix
        name = strip_company_prefix(str(name))
    except Exception:
        name = str(name)
    clean = _normalize_project_key(name)
    clean = re.sub(r"\b(?:projek|project|proyek|prj)\b", " ", clean)
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _project_aliases_for_name(project_name: str) -> list:
    try:
        from config.wallets import strip_company_prefix
        base_name = strip_company_prefix(project_name)
    except Exception:
        base_name = project_name or ""

    aliases = []
    for raw in (project_name, base_name):
        alias = _normalize_project_alias(raw)
        if alias and alias not in aliases:
            aliases.append(alias)

    words = _normalize_project_alias(base_name).split()
    if len(words) >= 2:
        tail = " ".join(words[-2:])
        if tail and tail not in aliases:
            aliases.append(tail)
    if len(words) >= 3:
        acronym = "".join(w[0] for w in words if w)
        if len(acronym) >= 3 and acronym not in aliases:
            aliases.append(acronym)

    for token in re.findall(r"[A-Za-z0-9]+", str(base_name or "")):
        if len(token) >= 3 and token.upper() == token and token.lower() not in aliases:
            aliases.append(token.lower())

    return aliases[:12]


def _knowledge_entry_in_scope(entry: dict, dompet_sheet: str = None, company: str = None) -> bool:
    if not isinstance(entry, dict):
        return False
    if dompet_sheet and entry.get("dompet") != dompet_sheet:
        return False
    if company and str(entry.get("company") or "").upper() != str(company).upper():
        return False
    return True


def remember_project_knowledge(
    project_name: str,
    dompet_sheet: str,
    company: str = None,
    aliases: list = None,
    actor: str = None,
    source: str = None,
    status: str = None,
) -> None:
    """Persist lightweight project knowledge for fast future routing."""
    key = _normalize_project_key(project_name)
    if not key or not dompet_sheet:
        return

    try:
        from config.wallets import extract_company_prefix, strip_company_prefix
        base_name = strip_company_prefix(project_name)
        company = company or extract_company_prefix(project_name)
    except Exception:
        base_name = project_name

    alias_values = _project_aliases_for_name(project_name)
    for alias in aliases or []:
        normalized = _normalize_project_alias(alias)
        if normalized and normalized not in alias_values:
            alias_values.append(normalized)

    now_text = datetime.now().isoformat()
    with _registry_lock:
        entry = dict(_project_knowledge.get("projects", {}).get(key) or {})
        entry.update({
            "name": project_name,
            "base_name": base_name,
            "dompet": dompet_sheet,
            "company": company,
            "status": status or entry.get("status") or "active",
            "updated_at": now_text,
            "last_actor": actor,
            "last_source": source,
        })
        entry.setdefault("created_at", now_text)
        existing_aliases = list(entry.get("aliases") or [])
        for alias in alias_values:
            if alias and alias not in existing_aliases:
                existing_aliases.append(alias)
        entry["aliases"] = existing_aliases[:20]

        _project_knowledge.setdefault("projects", {})[key] = entry
        _project_registry[key] = dompet_sheet
        base_key = _normalize_project_key(base_name)
        if base_key:
            _project_registry[base_key] = dompet_sheet

        alias_map = _project_knowledge.setdefault("aliases", {})
        for alias in entry["aliases"]:
            keys = alias_map.get(alias) or []
            if isinstance(keys, str):
                keys = [keys]
            if key not in keys:
                keys.append(key)
            alias_map[alias] = keys[:10]

    _save_state()


def resolve_project_knowledge(query: str, dompet_sheet: str = None, company: str = None) -> Optional[dict]:
    """Resolve a project from persisted bot knowledge before reading Sheets."""
    alias = _normalize_project_alias(query)
    if not alias or len(alias) < 3:
        return None

    with _registry_lock:
        projects = copy.deepcopy(_project_knowledge.get("projects", {}))
        alias_map = copy.deepcopy(_project_knowledge.get("aliases", {}))

    def _entry_for_key(project_key: str) -> Optional[dict]:
        entry = projects.get(project_key)
        if entry and _knowledge_entry_in_scope(entry, dompet_sheet, company):
            return entry
        return None

    exact_keys = alias_map.get(alias) or []
    if isinstance(exact_keys, str):
        exact_keys = [exact_keys]
    exact_matches = [entry for key in exact_keys if (entry := _entry_for_key(key))]
    if len(exact_matches) == 1:
        entry = exact_matches[0]
        return {
            "status": "EXACT",
            "final_name": entry.get("name"),
            "dompet": entry.get("dompet"),
            "company": entry.get("company"),
            "project_status": entry.get("status"),
            "updated_at": entry.get("updated_at"),
            "confidence": 1.0,
            "source": "project_knowledge",
            "match_count": 1,
        }
    if len(exact_matches) > 1:
        return {
            "status": "AMBIGUOUS",
            "final_name": exact_matches[0].get("name"),
            "matches": [m.get("name") for m in exact_matches],
            "confidence": 0.75,
            "source": "project_knowledge",
            "match_count": len(exact_matches),
        }

    fuzzy_matches = []
    for entry in projects.values():
        if not _knowledge_entry_in_scope(entry, dompet_sheet, company):
            continue
        candidates = set(entry.get("aliases") or [])
        candidates.add(_normalize_project_alias(entry.get("name") or ""))
        candidates.add(_normalize_project_alias(entry.get("base_name") or ""))
        if any(alias in c or c in alias for c in candidates if c):
            fuzzy_matches.append(entry)

    unique = []
    seen = set()
    for entry in fuzzy_matches:
        key = _normalize_project_key(entry.get("name") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(entry)

    if len(unique) == 1:
        entry = unique[0]
        return {
            "status": "AUTO_FIX",
            "final_name": entry.get("name"),
            "dompet": entry.get("dompet"),
            "company": entry.get("company"),
            "project_status": entry.get("status"),
            "updated_at": entry.get("updated_at"),
            "confidence": 0.9,
            "source": "project_knowledge",
            "match_count": 1,
        }
    if len(unique) > 1:
        return {
            "status": "AMBIGUOUS",
            "final_name": unique[0].get("name"),
            "matches": [m.get("name") for m in unique],
            "confidence": 0.7,
            "source": "project_knowledge",
            "match_count": len(unique),
        }

    return None


def _is_recent_project_knowledge(result: dict) -> bool:
    if not result:
        return False
    updated_at = result.get("updated_at")
    if not updated_at:
        return False
    try:
        updated = datetime.fromisoformat(str(updated_at))
    except (TypeError, ValueError):
        return False
    return (datetime.now() - updated).total_seconds() <= PROJECT_LOCK_TRUST_SECONDS


def get_project_lock(project_name: str) -> Optional[str]:
    """Get locked dompet for a project.

    Guardrail:
    - If registry has a lock but the project no longer exists in that dompet
      (or resolves elsewhere), invalidate stale lock first.
    - If missing, lazily resolve from sheets.
    """
    key = _normalize_project_key(project_name)
    if not key:
        return None
    with _registry_lock:
        locked_dompet = _project_registry.get(key)
    if locked_dompet:
        knowledge = resolve_project_knowledge(project_name, dompet_sheet=locked_dompet)
        if knowledge and knowledge.get("dompet") == locked_dompet and _is_recent_project_knowledge(knowledge):
            return locked_dompet

        # Validate persisted lock against current spreadsheet state to avoid
        # stale/misassigned dompet forcing future transactions.
        try:
            from sheets_helper import find_company_for_project_exact
            found_dompet, _ = find_company_for_project_exact(project_name)
            if found_dompet and found_dompet == locked_dompet:
                return locked_dompet
            if found_dompet and found_dompet != locked_dompet:
                with _registry_lock:
                    _project_registry[key] = found_dompet
                _save_state()
                add_audit_event({
                    "type": "project_lock_auto_correct",
                    "project": key,
                    "from": locked_dompet,
                    "to": found_dompet,
                    "reason": "sheet_exact_match"
                })
                return found_dompet
            # No exact project found anywhere -> clear stale lock.
            with _registry_lock:
                _project_registry.pop(key, None)
            _save_state()
            add_audit_event({
                "type": "project_lock_auto_clear",
                "project": key,
                "from": locked_dompet,
                "to": None,
                "reason": "sheet_no_exact_match"
            })
        except Exception as e:
            # Fallback to persisted lock when validation lookup fails.
            secure_log("WARNING", f"Project lock validation failed: {type(e).__name__}: {e}")
            return locked_dompet
    # Lazy resolve from sheets if exists
    try:
        from sheets_helper import find_company_for_project_exact
        found_dompet, _ = find_company_for_project_exact(project_name)
        if found_dompet:
            with _registry_lock:
                _project_registry[key] = found_dompet
            _save_state()
            return found_dompet
    except Exception as e:
        secure_log("WARNING", f"Project lock lazy resolve failed: {type(e).__name__}: {e}")
    return None


def add_audit_event(event: dict) -> None:
    """Append audit event (bounded)."""
    try:
        event['ts'] = datetime.now().isoformat()
        with _registry_lock:
            _audit_log.append(event)
            # Keep last 500 events
            if len(_audit_log) > 500:
                _audit_log[:] = _audit_log[-500:]
        _save_state()
    except Exception as e:
        secure_log("WARNING", f"Failed to add audit event: {type(e).__name__}: {e}")


def set_project_lock(project_name: str, dompet_sheet: str, actor: str = None,
                     reason: str = None, previous_dompet: str = None) -> None:
    """Lock project to a dompet (persisted) and write audit log if changed."""
    key = _normalize_project_key(project_name)
    if not key or not dompet_sheet:
        return
    with _registry_lock:
        prev = _project_registry.get(key)
        if prev == dompet_sheet:
            return
        _project_registry[key] = dompet_sheet
    _save_state()
    
    if prev != dompet_sheet:
        add_audit_event({
            "type": "project_lock",
            "project": key,
            "from": previous_dompet or prev,
            "to": dompet_sheet,
            "actor": actor,
            "reason": reason or ("new" if not prev else "move")
        })


def get_project_registry() -> Dict[str, str]:
    """Get full project registry mapping."""
    with _registry_lock:
        return _project_registry.copy()


# ===================== USER MESSAGE CONTEXT =====================
# Store user's last message for multi-message context (e.g. split text)
# Format: {key: {'text': str, 'timestamp': datetime}}
# key = "chat_id:user_id"
USER_LAST_MESSAGES = {}

def store_user_message(user_id: str, chat_id: str, text: str):
    """Store user's last message for context."""
    from datetime import datetime
    
    key = f"{chat_id}:{user_id}"
    with _user_message_lock:
        USER_LAST_MESSAGES[key] = {
            'text': text,
            'timestamp': datetime.now()
        }

def get_user_last_message(user_id: str, chat_id: str, max_age_seconds: int = 60) -> str:
    """Get user's last message if recent enough."""
    from datetime import datetime, timedelta
    
    key = f"{chat_id}:{user_id}"
    with _user_message_lock:
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
    with _user_message_lock:
        USER_LAST_MESSAGES.pop(key, None)


# ===================== STATS =====================

def get_state_stats() -> Dict[str, Any]:
    """Get statistics about current state (for debugging)."""
    with _pending_lock:
        pending_count = len(_pending_transactions)
        pending_message_refs_count = len(_pending_message_refs)
    with _confirmation_lock:
        pending_conf_count = len(PENDING_CONFIRMATIONS)
    with _dedup_lock:
        processed_count = len(_processed_messages)
    with _refs_lock:
        bot_refs_count = len(_bot_message_refs)
        last_tx_events_count = len(_last_tx_events)
    return {
        'pending_count': pending_count,
        'pending_conf_count': pending_conf_count,
        'processed_count': processed_count,
        'bot_refs_count': bot_refs_count,
        'pending_message_refs_count': pending_message_refs_count,
        'last_tx_events_count': last_tx_events_count,
    }

# For testing
if __name__ == '__main__':
    print("State Manager Tests")
    # ... tests omitted ...
