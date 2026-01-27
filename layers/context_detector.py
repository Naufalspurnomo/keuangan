"""
context_detector.py - Context Detection Module (Stage 1)

This module handles the first stage of the 3-stage Context-Aware
Intent Classification system.

Features:
- Reply context analysis (detect if replying to bot's message)
- Mention detection (bot name, @bot, /command)
- Conversation continuity tracking
- Addressed score calculation

Part of Context-Aware Intent Classification v2.0
"""

import re
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

# Confidence boosts for different contexts
BOOST_REPLY_TRANSACTION = 60   # Reply to ✅ Transaksi Tercatat
BOOST_REPLY_PENDING = 70       # Reply to ❓ Simpan ke company mana?
BOOST_REPLY_ERROR = 50         # Reply to ❌ Error message
BOOST_MENTION = 50             # @bot or /command
BOOST_CONVERSATION_1MIN = 30   # Last interaction < 1 min
BOOST_CONVERSATION_3MIN = 15   # Last interaction < 3 min
BOOST_MEDIA = 20               # Has image/document
BOOST_VISUAL_BUFFER = 50       # Has buffered photos waiting for text

# Conversation TTL
CONVERSATION_TTL_SECONDS = 180  # 3 minutes


# ===================== PATTERNS =====================

# Bot report signatures
BOT_REPORT_SIGNATURES = [
    "✅ Transaksi Tercatat",
    "✅ Transaksi tercatat",
    "✅ Revisi Berhasil",
]

BOT_PENDING_SIGNATURES = [
    "❓ Simpan ke company mana?",
    "❓ Untuk projek apa?",
    "Pilih 1-5",
    "Balas dengan nama projek",
]

BOT_ERROR_SIGNATURES = [
    "❌",
    "⚠️",
]

# Mention patterns
MENTION_PATTERNS = [
    re.compile(r'^bot[,:\s]', re.IGNORECASE),      # "bot, berapa?"
    re.compile(r'\bhalo bot\b', re.IGNORECASE),    # "halo bot"
    re.compile(r'\bhai bot\b', re.IGNORECASE),     # "hai bot"
    re.compile(r'@bot\b', re.IGNORECASE),          # "@bot"
]

# Command pattern (always addressed to bot)
COMMAND_PATTERN = re.compile(r'^/')                 # "/saldo", "/laporan"


# ===================== CONVERSATION TRACKING =====================

# Track last interaction per user per chat
# Format: {"chat:user": datetime}
_last_interactions: Dict[str, datetime] = {}


def _interaction_key(user_id: str, chat_id: str) -> str:
    """Generate key for interaction tracking."""
    if chat_id:
        return f"{chat_id}:{user_id}"
    return user_id


def record_interaction(user_id: str, chat_id: str = None) -> None:
    """Record that user interacted with bot."""
    key = _interaction_key(user_id, chat_id)
    _last_interactions[key] = datetime.now()
    
    # Cleanup old entries (keep max 1000)
    if len(_last_interactions) > 1000:
        # Remove oldest 500
        keys = list(_last_interactions.keys())[:500]
        for k in keys:
            _last_interactions.pop(k, None)


def get_last_interaction(user_id: str, chat_id: str = None) -> Optional[datetime]:
    """Get last interaction time for user."""
    key = _interaction_key(user_id, chat_id)
    return _last_interactions.get(key)


# ===================== CONTEXT ANALYSIS =====================

def analyze_reply_context(
    quoted_message_text: str = None,
    is_from_bot: bool = False
) -> Dict:
    """
    Analyze reply context to understand if user is replying to bot.
    
    Args:
        quoted_message_text: Text content of the quoted message
        is_from_bot: Whether the quoted message was sent by bot
        
    Returns:
        Dict with:
            - is_reply_to_bot: bool
            - reply_context_type: str ('TRANSACTION_REPORT', 'PENDING_QUESTION', 'ERROR', 'OTHER')
            - confidence_boost: int
    """
    result = {
        'is_reply_to_bot': False,
        'reply_context_type': None,
        'confidence_boost': 0
    }
    
    if not is_from_bot or not quoted_message_text:
        return result
    
    result['is_reply_to_bot'] = True
    
    # Check reply type based on signatures
    for sig in BOT_REPORT_SIGNATURES:
        if sig in quoted_message_text:
            result['reply_context_type'] = 'TRANSACTION_REPORT'
            result['confidence_boost'] = BOOST_REPLY_TRANSACTION
            logger.debug("Reply context: TRANSACTION_REPORT")
            return result
    
    for sig in BOT_PENDING_SIGNATURES:
        if sig in quoted_message_text:
            result['reply_context_type'] = 'PENDING_QUESTION'
            result['confidence_boost'] = BOOST_REPLY_PENDING
            logger.debug("Reply context: PENDING_QUESTION")
            return result
    
    for sig in BOT_ERROR_SIGNATURES:
        if sig in quoted_message_text:
            result['reply_context_type'] = 'ERROR'
            result['confidence_boost'] = BOOST_REPLY_ERROR
            logger.debug("Reply context: ERROR")
            return result
    
    # Generic bot reply
    result['reply_context_type'] = 'OTHER'
    result['confidence_boost'] = 30
    logger.debug("Reply context: OTHER (generic bot message)")
    
    return result


def detect_mention(text: str) -> Dict:
    """
    Detect if user mentions bot in text.
    
    Args:
        text: Message text
        
    Returns:
        Dict with:
            - mentioned: bool
            - mention_type: str ('COMMAND', 'DIRECT', None)
            - confidence_boost: int
    """
    result = {
        'mentioned': False,
        'mention_type': None,
        'confidence_boost': 0
    }
    
    if not text:
        return result
    
    # Check command first (highest priority)
    if COMMAND_PATTERN.match(text.strip()):
        result['mentioned'] = True
        result['mention_type'] = 'COMMAND'
        result['confidence_boost'] = BOOST_MENTION
        return result
    
    # Check natural mentions
    for pattern in MENTION_PATTERNS:
        if pattern.search(text):
            result['mentioned'] = True
            result['mention_type'] = 'DIRECT'
            result['confidence_boost'] = BOOST_MENTION
            return result
    
    return result


def check_conversation_continuity(
    user_id: str,
    chat_id: str = None
) -> Dict:
    """
    Check if user is in active conversation with bot.
    
    Args:
        user_id: User ID
        chat_id: Chat/group ID
        
    Returns:
        Dict with:
            - in_conversation: bool
            - time_since_last: float (seconds)
            - confidence_boost: int
    """
    result = {
        'in_conversation': False,
        'time_since_last': None,
        'confidence_boost': 0
    }
    
    last_interaction = get_last_interaction(user_id, chat_id)
    
    # Also check last BOT interaction (to keep conversation alive if bot just replied)
    try:
        from services import state_manager
        last_bot = state_manager.get_last_bot_interaction(user_id, chat_id)
        if last_bot:
            bot_ts = last_bot['timestamp']
            if not last_interaction or bot_ts > last_interaction:
                last_interaction = bot_ts
    except ImportError:
        pass

    if not last_interaction:
        return result
    
    time_diff = (datetime.now() - last_interaction).total_seconds()
    result['time_since_last'] = time_diff
    
    if time_diff > CONVERSATION_TTL_SECONDS:
        return result
    
    result['in_conversation'] = True
    
    if time_diff < 60:  # 1 minute
        result['confidence_boost'] = BOOST_CONVERSATION_1MIN
    elif time_diff < 180:  # 3 minutes
        result['confidence_boost'] = BOOST_CONVERSATION_3MIN
    
    return result


def calculate_addressed_score(
    reply_context: Dict = None,
    mention_context: Dict = None,
    conversation_context: Dict = None,
    has_media: bool = False,
    has_pending: bool = False,
    has_visual: bool = False
) -> int:
    """
    Calculate overall "addressed to bot" score (0-100).
    
    Higher score = more likely the message is intended for bot.
    
    Args:
        reply_context: Result from analyze_reply_context()
        mention_context: Result from detect_mention()
        conversation_context: Result from check_conversation_continuity()
        has_media: Whether message has image/document
        has_pending: Whether user has pending transaction
        
    Returns:
        Score 0-100
    """
    score = 0
    
    # Reply context boost
    if reply_context:
        score += reply_context.get('confidence_boost', 0)
    
    # Mention boost
    if mention_context:
        score += mention_context.get('confidence_boost', 0)
    
    # Conversation continuity boost
    if conversation_context:
        score += conversation_context.get('confidence_boost', 0)
    
    # Media boost (images are often for bot)
    if has_media:
        score += BOOST_MEDIA
    
    # Pending transaction boost (user is in flow with bot)
    if has_pending:
        score += 40
        
    # Visual buffer boost (recent photo uploaded)
    if has_visual:
        score += BOOST_VISUAL_BUFFER
    
    # Cap at 100
    return min(score, 100)


def get_full_context(
    text: str,
    quoted_message_text: str = None,
    is_quoted_from_bot: bool = False,
    user_id: str = None,
    chat_id: str = None,
    has_media: bool = False,
    has_pending: bool = False,
    has_visual: bool = False
) -> Dict:
    """
    Get full context analysis for a message.
    
    Convenience function that calls all analyzers.
    
    Returns:
        Combined context dict with all analysis results
    """
    reply_ctx = analyze_reply_context(quoted_message_text, is_quoted_from_bot)
    mention_ctx = detect_mention(text)
    conversation_ctx = check_conversation_continuity(user_id, chat_id)
    
    addressed_score = calculate_addressed_score(
        reply_context=reply_ctx,
        mention_context=mention_ctx,
        conversation_context=conversation_ctx,
        has_media=has_media,
        has_pending=has_pending,
        has_visual=has_visual
    )
    
    return {
        # Reply context
        'is_reply_to_bot': reply_ctx['is_reply_to_bot'],
        'reply_context_type': reply_ctx['reply_context_type'],
        
        # Mention context
        'mentioned': mention_ctx['mentioned'],
        'mention_type': mention_ctx['mention_type'],
        
        # Conversation context
        'in_conversation': conversation_ctx['in_conversation'],
        'time_since_last': conversation_ctx['time_since_last'],
        
        # Combined
        'addressed_score': addressed_score,
        'has_media': has_media,
        'has_pending': has_pending,
        'has_visual': has_visual,
    }
