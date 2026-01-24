"""
layer_0_spam_filter.py - Intelligent Spam Filter & Rate Limiter

Layer 0 of the 7-layer architecture. This is the first gate that determines
whether a message should be processed or silently ignored.

Features:
- Financial Signal Scoring (0-100)
- Rate Limiting (sliding window)
- Message Deduplication (SHA-256 hash)
- Group chat specific logic

Based on Grand Design Ultimate lines 78-191.
"""

import re
import hashlib
import time
from typing import Dict, Optional, Set
from collections import defaultdict
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

# Rate limiting
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_MESSAGES = 10

# Deduplication
DEDUP_CACHE_TTL_SECONDS = 300  # 5 minutes

# Scoring thresholds
SCORE_SILENT_THRESHOLD = 50
SCORE_CONFIDENT_THRESHOLD = 70


# ===================== SCORING PATTERNS =====================

# Numeric amount patterns (Grand Design lines 119-125)
AMOUNT_PATTERNS = [
    re.compile(r'\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?\b'),  # 150.000 or 150,000
    re.compile(r'\b\d+(?:rb|ribu|k)\b', re.IGNORECASE),  # 150rb, 150ribu, 150k
    re.compile(r'\b\d+(?:jt|juta|m)\b', re.IGNORECASE),  # 1.5jt, 1juta, 1m
    re.compile(r'\b(?:seratus|dua\s*ratus|tiga\s*ratus|empat\s*ratus|lima\s*ratus|enam\s*ratus|tujuh\s*ratus|delapan\s*ratus|sembilan\s*ratus)\s*(?:ribu|juta)?\b', re.IGNORECASE),  # Written numbers
    re.compile(r'\brp\.?\s*\d+', re.IGNORECASE),  # Rp 500000
]

# Date patterns to EXCLUDE from amount detection
DATE_PATTERNS = [
    re.compile(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b'),  # 24-01-2026
    re.compile(r'\b(?:tanggal|tgl)\s*\d{1,2}\b', re.IGNORECASE),  # tanggal 24
    re.compile(r'\b\d{1,2}\s*(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)\b', re.IGNORECASE),
]

# Action verb patterns (Grand Design lines 127-131)
ACTION_VERBS = {
    # Standard verbs
    'beli', 'bayar', 'transfer', 'kirim', 'terima', 'setor', 'tarik',
    # Variations
    'dibayarin', 'dibayar', 'dibeli', 'ditransfer', 'dikirim',
    'lunasin', 'lunasi', 'pelunasan', 'lunas',
    'cicil', 'cicilan', 'nyicil',
    'dp', 'uang muka',
    'kasih', 'kasih ke', 'buat',
    # Wallet updates
    'isi', 'topup', 'top up', 'update', 'tambah',
    # Recording
    'catat', 'input', 'masukin', 'record',
}

# Bot mention patterns
BOT_MENTION_PATTERNS = [
    re.compile(r'@bot', re.IGNORECASE),
    re.compile(r'/\w+'),  # Any command like /catat, /status
]


# ===================== IN-MEMORY CACHES =====================

# Rate limiting: {user_id: [timestamp1, timestamp2, ...]}
_rate_limit_cache: Dict[str, list] = defaultdict(list)

# Deduplication: {hash: timestamp}
_dedup_cache: Dict[str, float] = {}

# Active sessions: {user_id: session_data} - populated by state manager
_active_sessions: Dict[str, dict] = {}


# ===================== HELPER FUNCTIONS =====================

def _clean_old_rate_limits(user_id: str) -> None:
    """Remove rate limit entries older than window."""
    current_time = time.time()
    cutoff = current_time - RATE_LIMIT_WINDOW_SECONDS
    _rate_limit_cache[user_id] = [
        ts for ts in _rate_limit_cache[user_id] if ts > cutoff
    ]


def _clean_old_dedup_entries() -> None:
    """Remove expired deduplication entries."""
    current_time = time.time()
    expired = [h for h, ts in _dedup_cache.items() 
               if current_time - ts > DEDUP_CACHE_TTL_SECONDS]
    for h in expired:
        del _dedup_cache[h]


def _generate_message_hash(user_id: str, message_id: str, content: str) -> str:
    """Generate SHA-256 hash for deduplication."""
    data = f"{user_id}:{message_id}:{content[:100]}"
    return hashlib.sha256(data.encode()).hexdigest()


def _has_amount_pattern(text: str) -> bool:
    """Check if text contains financial amount pattern (not date)."""
    # First check for date patterns
    for pattern in DATE_PATTERNS:
        text = pattern.sub('', text)
    
    # Now check for amount patterns
    for pattern in AMOUNT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _has_action_verb(text: str) -> bool:
    """Check if text contains financial action verb."""
    text_lower = text.lower()
    for verb in ACTION_VERBS:
        if verb in text_lower:
            return True
    return False


def _has_bot_mention(text: str) -> bool:
    """Check if text mentions bot or contains command."""
    for pattern in BOT_MENTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _has_active_session(user_id: str) -> bool:
    """Check if user has active pending transaction."""
    return user_id in _active_sessions


# ===================== PUBLIC FUNCTIONS =====================

def set_active_session(user_id: str, session_data: dict) -> None:
    """Register an active session for a user (called by state manager)."""
    _active_sessions[user_id] = session_data


def clear_active_session(user_id: str) -> None:
    """Clear active session for a user."""
    _active_sessions.pop(user_id, None)


def check_rate_limit(user_id: str) -> bool:
    """
    Check if user is within rate limit.
    
    Returns:
        True if allowed, False if rate limited
    """
    _clean_old_rate_limits(user_id)
    
    if len(_rate_limit_cache[user_id]) >= RATE_LIMIT_MAX_MESSAGES:
        logger.warning(f"Rate limit exceeded for user {user_id}")
        return False
    
    _rate_limit_cache[user_id].append(time.time())
    return True


def check_duplicate(user_id: str, message_id: str, content: str) -> bool:
    """
    Check if message is a duplicate.
    
    Returns:
        True if duplicate (should ignore), False if new message
    """
    _clean_old_dedup_entries()
    
    msg_hash = _generate_message_hash(user_id, message_id, content)
    
    if msg_hash in _dedup_cache:
        logger.debug(f"Duplicate message detected for user {user_id}")
        return True
    
    _dedup_cache[msg_hash] = time.time()
    return False


def calculate_financial_score(
    text: str,
    has_media: bool = False,
    user_id: str = None,
    has_bot_mention: bool = None
) -> int:
    """
    Calculate Financial Signal Score (0-100).
    
    Based on Grand Design Ultimate lines 116-154:
    - Numeric Pattern: +40 points
    - Action Verb: +30 points
    - Media Attachment: +20 points
    - Active Session: +50 points
    - Bot Mention: +60 points
    
    Args:
        text: Message text
        has_media: Whether message has photo/document
        user_id: User ID for session check
        has_bot_mention: Override for bot mention detection
        
    Returns:
        Financial signal score (0-100, capped)
    """
    score = 0
    
    # Factor 1: Numeric Pattern (+40)
    if _has_amount_pattern(text):
        score += 40
        logger.debug("Score +40: Amount pattern detected")
    
    # Factor 2: Action Verb (+30)
    if _has_action_verb(text):
        score += 30
        logger.debug("Score +30: Action verb detected")
    
    # Factor 3: Media Attachment (+20)
    if has_media:
        score += 20
        logger.debug("Score +20: Media attachment")
    
    # Factor 4: Active Session (+50)
    if user_id and _has_active_session(user_id):
        score += 50
        logger.debug("Score +50: Active session")
    
    # Factor 5: Bot Mention (+60)
    if has_bot_mention is None:
        has_bot_mention = _has_bot_mention(text)
    if has_bot_mention:
        score += 60
        logger.debug("Score +60: Bot mention")
    
    # Cap at 100
    return min(score, 100)


def process(ctx) -> 'MessageContext':
    """
    Layer 0 processing: Spam Filter & Rate Limiting.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with financial_score and processing_mode
    """
    from . import ProcessingMode
    
    # Check rate limit
    if not check_rate_limit(ctx.user_id):
        ctx.processing_mode = ProcessingMode.SILENT
        ctx.response_message = "⏸️ Terlalu banyak pesan. Tunggu sebentar ya."
        return ctx
    
    # Check duplicate
    if check_duplicate(ctx.user_id, ctx.message_id, ctx.text or ""):
        ctx.processing_mode = ProcessingMode.SILENT
        return ctx
    
    # Calculate financial score
    has_media = ctx.media_url is not None
    has_mention = _has_bot_mention(ctx.text or "")
    
    ctx.financial_score = calculate_financial_score(
        text=ctx.text or "",
        has_media=has_media,
        user_id=ctx.user_id,
        has_bot_mention=has_mention
    )
    
    # Determine processing mode
    if ctx.financial_score < SCORE_SILENT_THRESHOLD:
        ctx.processing_mode = ProcessingMode.SILENT
    elif ctx.financial_score < SCORE_CONFIDENT_THRESHOLD:
        ctx.processing_mode = ProcessingMode.TENTATIVE
    else:
        ctx.processing_mode = ProcessingMode.CONFIDENT
    
    logger.info(f"Layer 0: score={ctx.financial_score}, mode={ctx.processing_mode.value}")
    
    return ctx
