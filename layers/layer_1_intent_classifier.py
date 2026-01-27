"""
layer_1_intent_classifier.py - Semantic Intent Classification

Layer 1 of the 7-layer architecture. Determines user intent using
semantic understanding rather than keyword matching.

Intents:
- RECORD_TRANSACTION: User wants to log new transaction
- REVISION_REQUEST: User wants to correct existing transaction
- QUERY_STATUS: User wants information/report
- ANSWER_PENDING: User answering bot's question
- CANCEL_TRANSACTION: User wants to cancel pending transaction
- CHITCHAT: Casual conversation, not financial

Based on Grand Design Ultimate lines 193-325.
"""

import re
import os
import json
import logging
from typing import Optional, Dict, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

# Groq API for semantic classification
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Confidence thresholds
CONFIDENCE_HIGH = 0.8      # Proceed with intent
CONFIDENCE_MEDIUM = 0.6    # Proceed with extra validation
CONFIDENCE_LOW = 0.4       # Ask for clarification


# ===================== INTENT PATTERNS =====================

# Pattern-based pre-classification (before AI call) for efficiency
RECORD_PATTERNS = [
    re.compile(r'\b(?:beli|bayar|transfer|kirim|setor|tarik)\b.*\d', re.IGNORECASE),
    re.compile(r'\b(?:catat|input|record)\b', re.IGNORECASE),
    re.compile(r'\brp\.?\s*\d+', re.IGNORECASE),
]

REVISION_PATTERNS = [
    re.compile(r'\b(?:revisi|ralat|ganti|koreksi|update|salah|harusnya)\b', re.IGNORECASE),
    re.compile(r'/revisi\b', re.IGNORECASE),
]

QUERY_PATTERNS = [
    re.compile(r'\b(?:saldo|laporan|status|total|berapa|cek)\b', re.IGNORECASE),
    re.compile(r'/(?:saldo|laporan|status|list|riwayat)\b', re.IGNORECASE),
    re.compile(r'\?$'),  # Ends with question mark
]

CANCEL_PATTERNS = [
    re.compile(r'\b(?:batal|cancel|jangan|lupakan|ga jadi|tidak jadi)\b', re.IGNORECASE),
]

# Interrogative patterns - questions, NOT transactions
INTERROGATIVE_PATTERNS = [
    re.compile(r'^berapa\b', re.IGNORECASE),       # "berapa saldo?"
    re.compile(r'^apa\b', re.IGNORECASE),          # "apa aja transaksi?"
    re.compile(r'^kapan\b', re.IGNORECASE),        # "kapan terakhir?"
    re.compile(r'^gimana\b', re.IGNORECASE),       # "gimana pengeluaran?"
    re.compile(r'^siapa\b', re.IGNORECASE),        # "siapa yang input?"
    re.compile(r'^mana\b', re.IGNORECASE),         # "mana yang paling besar?"
    re.compile(r'^apakah\b', re.IGNORECASE),       # "apakah sudah dicatat?"
    re.compile(r'\?$'),                            # Ends with ?
]

# Financial query keywords (differentiate query vs transaction)
FINANCIAL_QUERY_KEYWORDS = [
    'saldo', 'transaksi', 'pengeluaran', 'pemasukan',
    'total', 'laporan', 'ringkasan', 'status', 'riwayat',
    'tercatat', 'hari ini', 'kemarin', 'bulan ini', 'minggu ini'
]

# Chitchat patterns - casual conversation
CHITCHAT_PATTERNS = [
    re.compile(r'^halo\b', re.IGNORECASE),
    re.compile(r'^hai\b', re.IGNORECASE),
    re.compile(r'^hi\b', re.IGNORECASE),
    re.compile(r'^selamat\s+(pagi|siang|sore|malam)', re.IGNORECASE),
    re.compile(r'^apa kabar', re.IGNORECASE),
    re.compile(r'^gimana kabar', re.IGNORECASE),
    re.compile(r'udah makan', re.IGNORECASE),
    re.compile(r'^makasih\b', re.IGNORECASE),
    re.compile(r'^terima\s*kasih', re.IGNORECASE),
    re.compile(r'^thanks\b', re.IGNORECASE),
    re.compile(r'^ok\b', re.IGNORECASE),
    re.compile(r'^oke\b', re.IGNORECASE),
    re.compile(r'^sip\b', re.IGNORECASE),
    re.compile(r'^wkwk', re.IGNORECASE),
    re.compile(r'^haha', re.IGNORECASE),
]

# Revision keywords for context-aware detection
REVISION_KEYWORDS = ['revisi', 'ralat', 'ganti', 'koreksi', 'salah', 'harusnya', 'ubah', 'update']

# Action verbs (indicates transaction, NOT revision)
ACTION_VERBS = ['beli', 'bayar', 'transfer', 'kirim', 'terima', 'setor', 'tarik', 'dp', 'cicil']

# Commands that should bypass AI classification
COMMAND_INTENTS = {
    '/catat': 'RECORD_TRANSACTION',
    '/revisi': 'REVISION_REQUEST',
    '/saldo': 'QUERY_STATUS',
    '/laporan': 'QUERY_STATUS',
    '/laporan30': 'QUERY_STATUS',
    '/status': 'QUERY_STATUS',
    '/list': 'QUERY_STATUS',
    '/riwayat': 'QUERY_STATUS',
    '/dompet': 'QUERY_STATUS',
    '/kategori': 'QUERY_STATUS',
    '/tanya': 'QUERY_STATUS',
    '/batal': 'CANCEL_TRANSACTION',
    '/cancel': 'CANCEL_TRANSACTION',
    '/start': 'CHITCHAT',
    '/help': 'CHITCHAT',
    '/link': 'CHITCHAT',
}


# ===================== AI CLASSIFICATION =====================

def _get_classification_prompt(message: str, context: dict) -> str:
    """
    Generate lightweight prompt for intent classification.
    Target: ~250 tokens total (input + output).
    """
    pending_question = context.get('pending_question_type', 'none')
    prev_message = context.get('previous_message', '')[:50]
    
    return f"""Classify this Indonesian financial message intent.

Message: "{message[:150]}"
Pending question from bot: {pending_question}
Previous message: "{prev_message}"

Categories:
- RECORD: User wants to log NEW transaction (beli, bayar, transfer + amount)
- REVISION: User wants to CORRECT existing transaction (revisi, salah, ganti)
- QUERY: User wants INFO/report (saldo, laporan, berapa, cek)
- ANSWER: User is ANSWERING bot's pending question (number selection, confirmation)
- CANCEL: User wants to CANCEL pending transaction (batal, jangan)
- CHITCHAT: Casual talk, not financial

Reply ONLY with JSON: {{"intent": "...", "confidence": 0.0-1.0}}"""


def classify_with_ai(message: str, context: dict) -> Tuple[str, float]:
    """
    Use Groq AI for semantic intent classification.
    
    Returns:
        Tuple of (intent_name, confidence_score)
    """
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set, falling back to pattern matching")
        return classify_with_patterns(message, context)
    
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        
        prompt = _get_classification_prompt(message, context)
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an intent classifier. Respond only with JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0.1
        )
        
        # Robust null checking - FIX for NoneType error
        if not response or not response.choices or len(response.choices) == 0:
            logger.warning("Empty response from Groq API")
            return classify_with_patterns(message, context)
        
        message_obj = response.choices[0].message
        if not message_obj or not message_obj.content:
            logger.warning("No content in Groq response")
            return classify_with_patterns(message, context)
            
        result_text = message_obj.content.strip()
        
        if not result_text:
            logger.warning("Empty content from Groq")
            return classify_with_patterns(message, context)
        
        # Parse JSON response
        # Handle markdown code blocks
        if "```" in result_text:
            parts = result_text.split("```")
            if len(parts) >= 2:
                result_text = parts[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:].strip()
        
        result = json.loads(result_text)
        intent = result.get('intent', 'CHITCHAT').upper()
        confidence = float(result.get('confidence', 0.5))
        
        # Map to standard intent names
        intent_map = {
            'RECORD': 'RECORD_TRANSACTION',
            'REVISION': 'REVISION_REQUEST',
            'QUERY': 'QUERY_STATUS',
            'ANSWER': 'ANSWER_PENDING',
            'CANCEL': 'CANCEL_TRANSACTION',
            'CHITCHAT': 'CHITCHAT'
        }
        intent = intent_map.get(intent, intent)
        
        logger.info(f"AI classified: intent={intent}, confidence={confidence}")
        return intent, confidence
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse AI response as JSON: {e}")
        return classify_with_patterns(message, context)
    except Exception as e:
        logger.error(f"AI classification failed: {e}")
        return classify_with_patterns(message, context)


def _has_amount(text: str) -> bool:
    """Check if text contains financial amount."""
    amount_patterns = [
        r'\d+(?:[.,]\d+)?\s*(?:rb|ribu|k|jt|juta|m)\b',
        r'rp\.?\s*[\d.,]+',
        r'\b\d{4,}\b',  # Numbers >= 1000
    ]
    for pattern in amount_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _has_action_verb(text: str) -> bool:
    """Check if text contains transaction action verb."""
    text_lower = text.lower()
    return any(verb in text_lower for verb in ACTION_VERBS)


def _is_interrogative(text: str) -> bool:
    """Check if text is a question."""
    return any(p.search(text) for p in INTERROGATIVE_PATTERNS)


def _has_financial_keyword(text: str) -> bool:
    """Check if text contains financial query keyword."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in FINANCIAL_QUERY_KEYWORDS)


def _is_chitchat(text: str) -> bool:
    """Check if text is casual chitchat."""
    return any(p.search(text) for p in CHITCHAT_PATTERNS)


def intent_pre_filter(text: str, context: dict) -> dict:
    """
    Stage 2: Rule-based intent pre-filter.
    
    Quick classification before calling AI. Saves tokens for obvious cases.
    
    Args:
        text: Message text
        context: Context dict from context_detector
        
    Returns:
        Dict with:
            - intent: str
            - confidence: float
            - skip_ai: bool (True if confident enough)
    """
    text_lower = text.lower().strip() if text else ''
    
    # ============= RULE 1: REVISION IN REPLY CONTEXT =============
    # If replying to transaction report + has revision keyword OR has amount without action verb
    is_reply_to_bot = context.get('is_reply_to_bot', False)
    reply_type = context.get('reply_context_type', '')
    
    if is_reply_to_bot and reply_type == 'TRANSACTION_REPORT':
        # Check revision keywords
        has_revision = any(kw in text_lower for kw in REVISION_KEYWORDS)
        has_amount = _has_amount(text)
        has_action = _has_action_verb(text)
        
        if has_revision:
            logger.info("Pre-filter: REVISION_REQUEST (reply + revision keyword)")
            return {'intent': 'REVISION_REQUEST', 'confidence': 0.95, 'skip_ai': True}
        
        # Has amount but no action verb = implicit revision
        if has_amount and not has_action:
            logger.info("Pre-filter: REVISION_REQUEST (reply + amount only)")
            return {'intent': 'REVISION_REQUEST', 'confidence': 0.85, 'skip_ai': True}
    
    # ============= RULE 2: ANSWERING BOT QUESTION =============
    if is_reply_to_bot and reply_type == 'PENDING_QUESTION':
        logger.info("Pre-filter: ANSWER_PENDING (reply to pending question)")
        return {'intent': 'ANSWER_PENDING', 'confidence': 0.95, 'skip_ai': True}
    
    # ============= RULE 3: QUERY DETECTION (Interrogative) =============
    if _is_interrogative(text) and _has_financial_keyword(text):
        logger.info("Pre-filter: QUERY_STATUS (interrogative + financial keyword)")
        return {'intent': 'QUERY_STATUS', 'confidence': 0.90, 'skip_ai': True}
    
    # ============= RULE 4: EXPLICIT COMMANDS =============
    first_word = text_lower.split()[0] if text_lower else ''
    if first_word in COMMAND_INTENTS:
        logger.info(f"Pre-filter: {COMMAND_INTENTS[first_word]} (explicit command)")
        return {'intent': COMMAND_INTENTS[first_word], 'confidence': 0.95, 'skip_ai': True}
    
    # ============= RULE 5: CANCEL =============
    for pattern in CANCEL_PATTERNS:
        if pattern.search(text):
            logger.info("Pre-filter: CANCEL_TRANSACTION")
            return {'intent': 'CANCEL_TRANSACTION', 'confidence': 0.85, 'skip_ai': True}
    
    # ============= RULE 6: CLEAR TRANSACTION =============
    has_amount = _has_amount(text)
    has_action = _has_action_verb(text)
    addressed_score = context.get('addressed_score', 0)
    
    if has_amount and has_action:
        # Strong transaction signal
        logger.info("Pre-filter: RECORD_TRANSACTION (amount + action verb)")
        return {'intent': 'RECORD_TRANSACTION', 'confidence': 0.85, 'skip_ai': True}
    
    # ============= RULE 7: CHITCHAT (Not addressed) =============
    if _is_chitchat(text) and addressed_score < 50:
        logger.info("Pre-filter: CHITCHAT (casual + not addressed)")
        return {'intent': 'CHITCHAT', 'confidence': 0.85, 'skip_ai': True, 'action': 'SILENT'}
    
    # ============= AMBIGUOUS - Need AI =============
    logger.debug("Pre-filter: UNKNOWN (need AI classification)")
    return {'intent': 'UNKNOWN', 'confidence': 0.0, 'skip_ai': False}


def classify_with_patterns(message: str, context: dict) -> Tuple[str, float]:
    """
    Fallback pattern-based classification when AI is unavailable.
    
    Returns:
        Tuple of (intent_name, confidence_score)
    """
    text = message.lower().strip()
    
    # Check if this might be an answer to pending question
    pending = context.get('pending_question_type')
    if pending:
        # If user sends short response while pending question exists
        if len(text) < 20 or text.isdigit() or text in ['y', 'n', 'ya', 'tidak']:
            return 'ANSWER_PENDING', 0.85
    
    # Check explicit commands first
    first_word = text.split()[0] if text else ''
    if first_word in COMMAND_INTENTS:
        return COMMAND_INTENTS[first_word], 0.95
    
    # Pattern matching with confidence
    for pattern in REVISION_PATTERNS:
        if pattern.search(text):
            return 'REVISION_REQUEST', 0.75
    
    for pattern in CANCEL_PATTERNS:
        if pattern.search(text):
            return 'CANCEL_TRANSACTION', 0.75
    
    for pattern in QUERY_PATTERNS:
        if pattern.search(text):
            return 'QUERY_STATUS', 0.70
    
    for pattern in RECORD_PATTERNS:
        if pattern.search(text):
            return 'RECORD_TRANSACTION', 0.70
    
    # Default to chitchat with low confidence
    return 'CHITCHAT', 0.50


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 1 processing: Intent Classification with 3-Stage Pipeline.
    
    Stage 1: Context Detection (handled by context_detector, passed via ctx)
    Stage 2: Intent Pre-Filter (rule-based, FREE)
    Stage 3: AI Classification (only if pre-filter uncertain)
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with intent and intent_confidence
    """
    from . import Intent
    
    text = ctx.text or ""
    
    # 0. Normalization Stage (Nyeleneh Language Handler)
    try:
        from utils.normalizer import normalize_nyeleneh_text, extract_intent_from_nyeleneh
        
        # Keep original text for logging/debugging
        original_text = text
        text = normalize_nyeleneh_text(text)
        
        if text != original_text:
            logger.info(f"Layer 1: Normalized '{original_text}' -> '{text}'")
            # Update ctx.text so downstream layers see the clean version
            ctx.text = text
            # Store original in context_data if not already there
            if not hasattr(ctx, 'context_data'): ctx.context_data = {}
            ctx.context_data['original_text'] = original_text
            
    except ImportError:
        logger.warning("Layer 1: Normalizer utility not found.")
    
    # Build context for classification (includes Stage 1 results)
    context = {
        'pending_question_type': None,
        'previous_message': None,
        # Stage 1: Context detection results (from context_detector)
        'is_reply_to_bot': getattr(ctx, 'is_reply_to_bot', False),
        'reply_context_type': getattr(ctx, 'reply_context_type', None),
        'addressed_score': getattr(ctx, 'addressed_score', 0),
    }
    
    # Populate pending question type if available
    if hasattr(ctx, 'pending_question') and ctx.pending_question:
        context['pending_question_type'] = ctx.pending_question.get('question_type')
    
    # Also check pending_context for company selection flow
    if hasattr(ctx, 'pending_context') and ctx.pending_context:
        context['pending_question_type'] = ctx.pending_context.get('pending_type', 'selection')
    
    # ============= STAGE 2: Intent Pre-Filter (Rule-based) =============
    pre_filter_result = intent_pre_filter(text, context)
    ctx.pre_filter_result = pre_filter_result
    ctx.skip_ai = pre_filter_result.get('skip_ai', False)
    
    if pre_filter_result['skip_ai']:
        # Pre-filter is confident, no need for AI
        intent_name = pre_filter_result['intent']
        confidence = pre_filter_result['confidence']
        logger.info(f"Layer 1: Pre-filter confident: intent={intent_name}, conf={confidence:.2f}")
    else:
        # ============= STAGE 3: AI Classification (if needed) =============
        # Decide classification method based on processing mode
        if ctx.processing_mode.value == 'tentative':
            # Use AI for tentative cases
            intent_name, confidence = classify_with_ai(text, context)
        else:
            # Try pattern matching first, use AI only if low confidence
            intent_name, confidence = classify_with_patterns(text, context)
            
            if confidence < CONFIDENCE_MEDIUM:
                # Fallback to AI
                intent_name, confidence = classify_with_ai(text, context)
    
    # Map string to Intent enum
    intent_map = {
        'RECORD_TRANSACTION': Intent.RECORD_TRANSACTION,
        'REVISION_REQUEST': Intent.REVISION_REQUEST,
        'QUERY_STATUS': Intent.QUERY_STATUS,
        'ANSWER_PENDING': Intent.ANSWER_PENDING,
        'CANCEL_TRANSACTION': Intent.CANCEL_TRANSACTION,
        'CHITCHAT': Intent.CHITCHAT,
    }
    
    ctx.intent = intent_map.get(intent_name, Intent.CHITCHAT)
    ctx.intent_confidence = confidence
    
    logger.info(f"Layer 1: intent={ctx.intent.value}, confidence={confidence:.2f}")
    
    # If confidence is too low, might need clarification
    if confidence < CONFIDENCE_LOW:
        ctx.validation_flags.append('LOW_INTENT_CONFIDENCE')
    
    return ctx
