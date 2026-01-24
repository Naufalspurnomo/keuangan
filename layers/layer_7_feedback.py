"""
layer_7_feedback.py - Feedback & Learning Engine

Layer 7 of the 7-layer architecture. Provides clear feedback to users
and learns from interaction patterns.

Features:
- Response templates (success, waiting, error, duplicate)
- Error pattern tracking with persistence
- Category auto-learning
- User behavior adaptation
- Dynamic AI prompt strengthening

Based on Grand Design Ultimate lines 1393-1571.
"""

import os
import json
import time
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

DATA_DIR = Path(os.getenv('DATA_DIR', 'data'))
LEARNING_FILE = DATA_DIR / 'learning_data.json'

# Error thresholds for prompt strengthening
ERROR_THRESHOLD_24H = 5  # If > 5 errors in 24h, strengthen prompt


# ===================== LEARNING DATA STRUCTURES =====================

# Error pattern tracking (Grand Design lines 1457-1496)
_error_log = {
    "truncation_errors": {
        "count": 0,
        "examples": [],
        "last_24h_count": 0,
        "last_reset": time.time()
    },
    "semantic_errors": {
        "count": 0,
        "examples": [],
        "last_24h_count": 0,
        "last_reset": time.time()
    },
    "user_confusion_events": {
        "count": 0,
        "examples": []
    }
}

# Category auto-learning (Grand Design lines 1498-1547)
_learned_patterns: Dict[str, Dict] = {}

# User behavior profiles (Grand Design lines 1549-1570)
_user_profiles: Dict[str, Dict] = {}


# ===================== PERSISTENCE =====================

def _load_learning_data():
    """Load learning data from disk."""
    global _error_log, _learned_patterns, _user_profiles
    
    try:
        if LEARNING_FILE.exists():
            with open(LEARNING_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            _error_log = data.get('error_log', _error_log)
            _learned_patterns = data.get('learned_patterns', {})
            _user_profiles = data.get('user_profiles', {})
            
            logger.info("Loaded learning data")
    except Exception as e:
        logger.warning(f"Failed to load learning data: {e}")


def _save_learning_data():
    """Save learning data to disk."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        data = {
            'error_log': _error_log,
            'learned_patterns': _learned_patterns,
            'user_profiles': _user_profiles,
            'last_saved': time.time()
        }
        
        with open(LEARNING_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        logger.error(f"Failed to save learning data: {e}")


# ===================== ERROR TRACKING =====================

def track_error(error_type: str, original: str, extracted: str):
    """
    Track an error for pattern learning.
    
    Args:
        error_type: Type of error (truncation, semantic, etc.)
        original: Original user input
        extracted: What AI extracted (incorrectly)
    """
    global _error_log
    
    if error_type not in _error_log:
        _error_log[error_type] = {
            "count": 0,
            "examples": [],
            "last_24h_count": 0,
            "last_reset": time.time()
        }
    
    entry = _error_log[error_type]
    entry["count"] += 1
    entry["last_24h_count"] += 1
    
    # Keep last 10 examples
    entry["examples"].append({
        "original": original[:200],
        "extracted": extracted[:100],
        "timestamp": time.time()
    })
    entry["examples"] = entry["examples"][-10:]
    
    _save_learning_data()
    logger.info(f"Tracked {error_type} error (24h count: {entry['last_24h_count']})")


def reset_24h_counters():
    """Reset 24-hour error counters (call daily)."""
    global _error_log
    
    current_time = time.time()
    for error_type, entry in _error_log.items():
        if isinstance(entry, dict) and 'last_reset' in entry:
            if current_time - entry['last_reset'] > 86400:  # 24 hours
                entry['last_24h_count'] = 0
                entry['last_reset'] = current_time
    
    _save_learning_data()


def get_error_addendum() -> str:
    """
    Generate error correction addendum for AI prompt.
    
    If certain error patterns are frequent, generate instructions
    to prevent them.
    """
    reset_24h_counters()
    
    addendum_parts = []
    
    # Check truncation errors
    truncation = _error_log.get('truncation_errors', {})
    if truncation.get('last_24h_count', 0) > ERROR_THRESHOLD_24H:
        examples = truncation.get('examples', [])[-3:]
        if examples:
            addendum_parts.append("""
ERROR PATTERN DETECTED: Project name truncation
In the last 24 hours, you truncated proper nouns multiple times.

CRITICAL OVERRIDE:
When user provides multi-word proper noun (Title Case, specific name),
you MUST preserve it EXACTLY. No abbreviation, no summarization.
""")
            for ex in examples:
                addendum_parts.append(f"- '{ex['original']}' was truncated to '{ex['extracted']}' ❌")
    
    # Check semantic errors
    semantic = _error_log.get('semantic_errors', {})
    if semantic.get('last_24h_count', 0) > ERROR_THRESHOLD_24H:
        addendum_parts.append("""
ERROR PATTERN DETECTED: Invalid project names
You have been extracting action verbs or generic nouns as project names.

CRITICAL OVERRIDE:
Project names should be proper nouns or specific descriptions.
Words like 'revisi', 'update', 'beli', 'dompet' are NOT project names.
""")
    
    return '\n'.join(addendum_parts)


# ===================== CATEGORY LEARNING =====================

def _normalize_description(description: str) -> str:
    """Normalize description for pattern matching."""
    # Remove amounts and specific text, keep action + category
    import re
    
    text = description.lower()
    text = re.sub(r'\d+', '', text)  # Remove numbers
    text = re.sub(r'rp\.?\s*', '', text)  # Remove Rp
    text = ' '.join(text.split())  # Normalize whitespace
    
    return text


def learn_from_transaction(txn: Dict):
    """
    Learn category patterns from saved transaction.
    Grand Design lines 1503-1536.
    """
    global _learned_patterns
    
    description = txn.get('description', '')
    category = txn.get('category', '')
    
    if not description or not category:
        return
    
    pattern_key = _normalize_description(description)
    if not pattern_key or len(pattern_key) < 3:
        return
    
    if pattern_key not in _learned_patterns:
        _learned_patterns[pattern_key] = {
            "category": category,
            "count": 1,
            "confidence": 0.5
        }
    else:
        learned = _learned_patterns[pattern_key]
        if learned["category"] == category:
            # Same category, increase confidence
            learned["count"] += 1
            learned["confidence"] = min(0.95, 0.5 + (learned["count"] * 0.05))
        # If different category, don't update (conflict)
    
    _save_learning_data()


def suggest_category(description: str) -> Optional[Dict]:
    """
    Suggest category based on learned patterns.
    
    Returns:
        Dict with suggestion or None
    """
    pattern_key = _normalize_description(description)
    
    if pattern_key in _learned_patterns:
        learned = _learned_patterns[pattern_key]
        if learned["confidence"] > 0.8 and learned["count"] > 5:
            return {
                "category": learned["category"],
                "confidence": learned["confidence"],
                "auto_fill": True
            }
        elif learned["confidence"] > 0.6:
            return {
                "category": learned["category"],
                "confidence": learned["confidence"],
                "auto_fill": False,
                "ask_confirm": True
            }
    
    return None


# ===================== USER BEHAVIOR =====================

def update_user_profile(user_id: str, event: str, data: Dict = None):
    """Update user behavior profile."""
    global _user_profiles
    
    if user_id not in _user_profiles:
        _user_profiles[user_id] = {
            "error_count": 0,
            "success_count": 0,
            "error_rate": 0.0,
            "common_mistakes": [],
            "average_amount": 0,
            "frequent_categories": [],
            "response_time_samples": []
        }
    
    profile = _user_profiles[user_id]
    
    if event == "error":
        profile["error_count"] += 1
        if data and data.get("mistake_type"):
            if data["mistake_type"] not in profile["common_mistakes"]:
                profile["common_mistakes"].append(data["mistake_type"])
    
    elif event == "success":
        profile["success_count"] += 1
        if data:
            # Update average amount
            if data.get("amount"):
                old_avg = profile["average_amount"]
                count = profile["success_count"]
                profile["average_amount"] = (old_avg * (count-1) + data["amount"]) / count
            
            # Track categories
            if data.get("category"):
                cats = profile["frequent_categories"]
                if data["category"] not in cats:
                    cats.append(data["category"])
                profile["frequent_categories"] = cats[-5:]  # Keep last 5
    
    # Update error rate
    total = profile["error_count"] + profile["success_count"]
    if total > 0:
        profile["error_rate"] = profile["error_count"] / total
    
    _save_learning_data()


def get_feedback_style(user_id: str) -> str:
    """
    Get feedback style based on user profile.
    
    Returns:
        'DETAILED' for high-error users, 'CONCISE' for experienced
    """
    profile = _user_profiles.get(user_id, {})
    error_rate = profile.get("error_rate", 0)
    
    if error_rate > 0.2:
        return "DETAILED"
    return "CONCISE"


# ===================== RESPONSE TEMPLATES =====================

def format_success_response(txn: Dict, wallet: str, style: str = "CONCISE") -> str:
    """Format success response message."""
    amount = txn.get('amount', 0)
    desc = txn.get('description', '')
    company = txn.get('company', '')
    project = txn.get('project_name', '')
    
    timestamp = datetime.now().strftime('%H:%M')
    
    if style == "DETAILED":
        return f"""✅ Transaksi Tercatat!

💸 {desc}: Rp {amount:,}
📍 {wallet} → {company} → {project}
⏱️ {timestamp}

💡 Tips:
- Revisi: reply pesan ini + /revisi [jumlah]
- Lihat laporan: /laporan
- Cek saldo: /saldo"""
    else:
        return f"""✅ Tercatat!
💸 {desc}: Rp {amount:,}
📍 {wallet} → {company} → {project}
💡 Revisi: reply + /revisi [jumlah]"""


def format_waiting_response(waiting_for: str, txn: Dict, style: str = "CONCISE") -> str:
    """Format waiting for input response."""
    amount = txn.get('amount', 0)
    desc = txn.get('description', '')
    
    base = f"""⏳ Transaksi terdeteksi:
💸 {desc}: Rp {amount:,}
"""
    
    if waiting_for == "project":
        return base + "\n❓ Untuk projek apa?"
    elif waiting_for == "company":
        return base + "\n❓ Simpan ke company mana? (1-5)"
    elif waiting_for == "amount":
        return base + "\n❓ Berapa nominalnya?"
    
    return base


def format_error_response(error_type: str, details: str, style: str = "CONCISE") -> str:
    """Format error response with guidance."""
    if style == "DETAILED":
        return f"""❌ {details}

📍 Cara yang benar:
1. Ketik transaksi dengan format lengkap
2. Contoh: "beli semen 500rb projek Renovasi"
3. Atau kirim foto struk + ketik "catat"

💡 Bantuan: /help"""
    else:
        return f"❌ {details}"


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 7 processing: Feedback & Learning.
    
    Generates appropriate response and updates learning data.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with response_message
    """
    user_id = ctx.user_id
    style = get_feedback_style(user_id)
    
    # Handle different states
    if ctx.current_state == "SUCCESS":
        txn = ctx.extracted_data or {}
        wallet = txn.get('wallet', 'N/A')
        
        # Generate success response
        ctx.response_message = format_success_response(txn, wallet, style)
        
        # Learn from transaction
        learn_from_transaction(txn)
        update_user_profile(user_id, "success", txn)
    
    elif ctx.current_state == "ERROR":
        # Track error
        error_msg = ctx.response_message or "Unknown error"
        update_user_profile(user_id, "error", {"mistake_type": "unknown"})
        
        # Format with guidance if needed
        if style == "DETAILED" and ctx.response_message:
            ctx.response_message = format_error_response("error", error_msg, style)
    
    elif ctx.current_state in ["WAITING_AMOUNT", "WAITING_PROJECT", "WAITING_COMPANY"]:
        # Response already set by state machine
        pass
    
    elif ctx.current_state == "CONFIRM_DUPLICATE":
        # Response already set by duplicate detection
        pass
    
    elif ctx.current_state == "CANCELLED":
        update_user_profile(user_id, "error", {"mistake_type": "cancelled"})
    
    # Track validation errors for learning
    for flag, msg in ctx.validation_flags or []:
        if flag == "TRUNCATION":
            track_error("truncation_errors", ctx.text or "", msg)
        elif flag in ["SEMANTIC_TYPE", "ACTION_VERB"]:
            track_error("semantic_errors", ctx.text or "", msg)
    
    logger.info(f"Layer 7: Generated response, style={style}")
    
    return ctx


# Initialize learning data on module load
_load_learning_data()
