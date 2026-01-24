"""
layer_7_feedback.py - Feedback & Response Generation Layer

Layer 7 of the 7-layer architecture. Handles final response generation
and learning from user interactions.

Features:
- Response formatting based on current state
- Error message generation
- Pattern learning for future improvements
- Feedback tracking

Based on Grand Design Ultimate lines 1459-1614.
"""

import os
import json
import logging
import re
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

DATA_DIR = Path(os.getenv('DATA_DIR', 'data'))
LEARNING_FILE = DATA_DIR / 'learning_data.json'


# ===================== LEARNING DATA =====================

_learned_patterns: Dict[str, any] = {
    'corrections': [],      # User corrections for learning
    'category_hints': {},   # Description -> category mapping
    'error_patterns': [],   # Patterns that caused errors
}


def _load_learning_data():
    """Load learning data from disk."""
    global _learned_patterns
    try:
        if LEARNING_FILE.exists():
            with open(LEARNING_FILE, 'r') as f:
                _learned_patterns = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load learning data: {e}")


def _save_learning_data():
    """Save learning data to disk."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LEARNING_FILE, 'w') as f:
            json.dump(_learned_patterns, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save learning data: {e}")


def record_correction(original: Dict, corrected: Dict, field: str):
    """Record a user correction for learning."""
    _learned_patterns['corrections'].append({
        'original': original,
        'corrected': corrected,
        'field': field,
        'timestamp': datetime.now().isoformat()
    })
    # Keep only last 100 corrections
    _learned_patterns['corrections'] = _learned_patterns['corrections'][-100:]
    _save_learning_data()


def record_error(pattern: str, error_type: str, context: Dict = None):
    """Record an error pattern for analysis."""
    _learned_patterns['error_patterns'].append({
        'pattern': pattern,
        'error_type': error_type,
        'context': context,
        'timestamp': datetime.now().isoformat()
    })
    # Keep only last 50 errors
    _learned_patterns['error_patterns'] = _learned_patterns['error_patterns'][-50:]
    _save_learning_data()


def suggest_category(description: str) -> Optional[str]:
    """Suggest category based on learned patterns."""
    if not description:
        return None
    
    normalized = _normalize_description(description)
    return _learned_patterns['category_hints'].get(normalized)


def _normalize_description(desc: str) -> str:
    """Normalize description for pattern matching."""
    # Remove amounts
    text = re.sub(r'rp\.?\s*[\d.,]+', '', desc.lower())
    text = re.sub(r'[\d.,]+\s*(?:rb|ribu|jt|juta|k)', '', text)
    return ' '.join(text.split())


# ===================== RESPONSE FORMATTERS =====================

def format_success_response(ctx) -> str:
    """Format success response after transaction saved."""
    try:
        from utils.formatters import format_success_reply_new
        from security import now_wib
        
        result = ctx.saved_transaction or {}
        dompet = getattr(ctx, 'selected_dompet', 'Unknown')
        company = getattr(ctx, 'selected_company', 'Unknown')
        
        response = format_success_reply_new(
            ctx.extracted_data or [],
            dompet,
            company,
            ""
        ).replace('*', '')
        
        # Add revision hint
        response += "\n\n💡 Reply /revisi [jumlah] untuk ralat"
        
        return response
        
    except Exception as e:
        logger.error(f"Format success failed: {e}")
        total = sum(t.get('jumlah', 0) for t in (ctx.extracted_data or []))
        return f"""✅ Transaksi Tercatat!
📊 Total: Rp {total:,}
💡 Reply /revisi untuk ralat""".replace(',', '.')


def format_error_response(ctx, error_type: str = None) -> str:
    """Format error response."""
    error_type = error_type or getattr(ctx, 'save_error', 'Unknown error')
    
    error_messages = {
        'EXTRACTION_ERROR': "❌ Gagal memproses input. Coba kirim ulang dengan format yang lebih jelas.",
        'NO_TRANSACTIONS': "❓ Tidak ada transaksi terdeteksi. Kirim dalam format:\n• beli semen 500rb\n• bayar tukang 1.5jt",
        'SAVE_ERROR': f"❌ Gagal menyimpan: {error_type}",
        'RATE_LIMITED': "⏳ Terlalu banyak request. Tunggu sebentar.",
    }
    
    return error_messages.get(error_type, f"❌ Error: {error_type}")


def format_waiting_response(ctx) -> str:
    """Format response for waiting states."""
    state = ctx.current_state
    
    if state == 'WAITING_COMPANY':
        return ctx.response_message or "❓ Pilih company (1-5)"
    
    if state == 'WAITING_PROJECT':
        return ctx.response_message or "❓ Ketik nama projek"
    
    if state == 'CONFIRM_DUPLICATE':
        return ctx.response_message or "⚠️ Transaksi mirip terdeteksi. Y=Batal, N=Tetap simpan"
    
    return ctx.response_message or ""


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 7 processing: Response Generation & Feedback.
    
    Generates final response based on current state.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        MessageContext with response_message set
    """
    current_state = getattr(ctx, 'current_state', 'INITIAL')
    
    logger.info(f"Layer 7: Generating response for state={current_state}")
    
    # Generate response based on final state
    if current_state == 'SAVED':
        ctx.response_message = format_success_response(ctx)
        
        # Record successful patterns for learning
        for t in (ctx.extracted_data or []):
            desc = t.get('keterangan', '')
            cat = t.get('kategori', '')
            if desc and cat:
                normalized = _normalize_description(desc)
                _learned_patterns['category_hints'][normalized] = cat
        _save_learning_data()
    
    elif current_state in ['WAITING_COMPANY', 'WAITING_PROJECT', 'CONFIRM_DUPLICATE']:
        ctx.response_message = format_waiting_response(ctx)
    
    elif current_state == 'ERROR':
        ctx.response_message = format_error_response(ctx)
        
        # Record error for learning
        record_error(
            pattern=ctx.text or '',
            error_type=getattr(ctx, 'extraction_error', 'unknown'),
            context={'intent': str(ctx.intent)}
        )
    
    elif current_state == 'SAVE_ERROR':
        ctx.response_message = format_error_response(ctx, 'SAVE_ERROR')
    
    elif current_state == 'CANCELLED':
        ctx.response_message = ctx.response_message or "❌ Dibatalkan"
    
    elif current_state == 'NO_TRANSACTION':
        # No transactions detected - return None (stay silent or ask)
        if ctx.is_group:
            # In groups, stay silent for non-transaction messages
            ctx.response_message = None
        else:
            ctx.response_message = format_error_response(ctx, 'NO_TRANSACTIONS')
    
    # If response is still None, generate generic
    if ctx.response_message is None and current_state == 'INITIAL':
        # Layer processing completed but no clear action
        ctx.response_message = None
    
    logger.info(f"Layer 7: Response generated, length={len(ctx.response_message or '')}")
    
    return ctx


# Initialize on module load
_load_learning_data()
