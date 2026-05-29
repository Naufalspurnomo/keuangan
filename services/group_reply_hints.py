"""
Throttle repetitive group reply guidance messages.
"""

import os
import threading
from datetime import datetime
from typing import Dict


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
        # Lightweight cleanup to keep cache bounded in long-running process.
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
