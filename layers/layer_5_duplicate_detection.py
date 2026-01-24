"""
layer_5_duplicate_detection.py - Semantic Duplicate Detection Engine

Layer 5 of the 7-layer architecture. Prevents double-entry using
semantic similarity detection with local MiniLM embeddings.

Features:
- Local embedding generation (sentence-transformers/all-MiniLM-L6-v2)
- Cosine similarity calculation
- Combined scoring (semantic + amount + time)
- Edge case handling (recurring, same vendor different items)

Based on Grand Design Ultimate lines 1084-1202.
"""

import os
import json
import time
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

# Duplicate detection threshold
DUPLICATE_THRESHOLD = 0.75

# Weights for combined scoring
SEMANTIC_WEIGHT = 0.5
AMOUNT_WEIGHT = 0.3
TIME_WEIGHT = 0.2

# Time window for duplicate check
CHECK_WINDOW_DAYS = 7

# Persistence
DATA_DIR = Path(os.getenv('DATA_DIR', 'data'))
EMBEDDINGS_CACHE_FILE = DATA_DIR / 'embeddings_cache.json'


# ===================== EMBEDDING MODEL =====================

_model = None
_embeddings_cache: Dict[str, List[float]] = {}


def _load_model():
    """Load MiniLM model (lazy loading to save memory)."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded MiniLM embedding model")
        except ImportError:
            logger.warning("sentence-transformers not installed. Install with: pip install sentence-transformers")
            _model = False  # Mark as unavailable
        except Exception as e:
            logger.error(f"Failed to load MiniLM model: {e}")
            _model = False
    return _model if _model else None


def _load_embeddings_cache():
    """Load cached embeddings from disk."""
    global _embeddings_cache
    try:
        if EMBEDDINGS_CACHE_FILE.exists():
            with open(EMBEDDINGS_CACHE_FILE, 'r') as f:
                _embeddings_cache = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load embeddings cache: {e}")
        _embeddings_cache = {}


def _save_embeddings_cache():
    """Save embeddings cache to disk."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Keep only recent entries (last 1000)
        if len(_embeddings_cache) > 1000:
            keys = list(_embeddings_cache.keys())[-1000:]
            _embeddings_cache = {k: _embeddings_cache[k] for k in keys}
        
        with open(EMBEDDINGS_CACHE_FILE, 'w') as f:
            json.dump(_embeddings_cache, f)
    except Exception as e:
        logger.error(f"Failed to save embeddings cache: {e}")


def generate_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding for text using MiniLM.
    
    Returns:
        List of floats (embedding vector) or None if unavailable
    """
    if not text:
        return None
    
    # Check cache first
    cache_key = text[:100]  # Use first 100 chars as key
    if cache_key in _embeddings_cache:
        return _embeddings_cache[cache_key]
    
    model = _load_model()
    if not model:
        return None
    
    try:
        embedding = model.encode(text, convert_to_numpy=True).tolist()
        
        # Cache the result
        _embeddings_cache[cache_key] = embedding
        _save_embeddings_cache()
        
        return embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return None


# ===================== SIMILARITY CALCULATIONS =====================

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)


def calculate_amount_similarity(amount1: int, amount2: int) -> float:
    """Calculate similarity between two amounts (0-1)."""
    if amount1 == 0 or amount2 == 0:
        return 0.0
    
    max_amount = max(amount1, amount2)
    diff = abs(amount1 - amount2)
    
    return 1 - (diff / max_amount)


def calculate_time_proximity(time1: datetime, time2: datetime) -> float:
    """
    Calculate time proximity score (0-1).
    Decays over 1 hour, older than 1 hour = 0.
    """
    diff = abs((time1 - time2).total_seconds())
    
    # 1 hour = 3600 seconds
    if diff > 3600:
        return 0.0
    
    return 1 - (diff / 3600)


def calculate_duplicate_score(
    new_txn: Dict,
    old_txn: Dict,
    new_time: datetime = None,
    old_time: datetime = None
) -> float:
    """
    Calculate combined duplicate score.
    
    Grand Design lines 1126-1141:
    - Semantic similarity: 50%
    - Amount similarity: 30%
    - Time proximity: 20%
    
    Returns:
        Duplicate score (0-1)
    """
    new_desc = new_txn.get('description', '')
    old_desc = old_txn.get('description', '')
    
    new_amount = new_txn.get('amount', 0)
    old_amount = old_txn.get('amount', 0)
    
    # Semantic similarity
    new_emb = generate_embedding(new_desc)
    old_emb = generate_embedding(old_desc)
    
    semantic_sim = 0.0
    if new_emb and old_emb:
        semantic_sim = cosine_similarity(new_emb, old_emb)
    else:
        # Fallback: simple text matching
        new_words = set(new_desc.lower().split())
        old_words = set(old_desc.lower().split())
        if new_words and old_words:
            intersection = len(new_words & old_words)
            union = len(new_words | old_words)
            semantic_sim = intersection / union if union > 0 else 0
    
    # Amount similarity
    amount_sim = calculate_amount_similarity(new_amount, old_amount)
    
    # Time proximity
    time_sim = 0.0
    if new_time and old_time:
        time_sim = calculate_time_proximity(new_time, old_time)
    
    # Combined score
    score = (
        semantic_sim * SEMANTIC_WEIGHT +
        amount_sim * AMOUNT_WEIGHT +
        time_sim * TIME_WEIGHT
    )
    
    return score


# ===================== EDGE CASE ADJUSTMENTS =====================

def adjust_for_recurring(
    score: float,
    new_txn: Dict,
    old_txn: Dict,
    new_time: datetime,
    old_time: datetime
) -> float:
    """
    Adjust score for recurring transactions.
    Grand Design lines 1169-1185.
    
    If transactions are similar but > 7 days apart, likely recurring (not duplicate).
    """
    if new_time and old_time:
        days_diff = abs((new_time - old_time).days)
        if days_diff > 7:
            # Likely different occurrence of recurring transaction
            score *= 0.5
            logger.debug(f"Adjusted score for recurring ({days_diff} days apart)")
    
    return score


def adjust_for_same_vendor(
    score: float,
    new_txn: Dict,
    old_txn: Dict
) -> float:
    """
    Adjust score for same vendor different items.
    Grand Design lines 1187-1201.
    
    If high semantic but very different amount, likely different purchases.
    """
    new_amount = new_txn.get('amount', 0)
    old_amount = old_txn.get('amount', 0)
    
    amount_sim = calculate_amount_similarity(new_amount, old_amount)
    
    # If semantic is high but amount is very different
    if score > 0.7 and amount_sim < 0.5:
        score *= 0.6
        logger.debug("Adjusted score for same vendor different items")
    
    return score


# ===================== MAIN DUPLICATE CHECK =====================

def check_duplicate(
    new_transaction: Dict,
    recent_transactions: List[Dict]
) -> Tuple[bool, Optional[Dict], float]:
    """
    Check if new transaction is a duplicate of recent ones.
    
    Args:
        new_transaction: New transaction data
        recent_transactions: List of recent transactions to check against
        
    Returns:
        Tuple of (is_duplicate, matching_transaction, score)
    """
    if not recent_transactions:
        return False, None, 0.0
    
    new_time = datetime.now()
    
    best_match = None
    best_score = 0.0
    
    for old_txn in recent_transactions:
        # Get old transaction time
        old_time_str = old_txn.get('timestamp') or old_txn.get('date')
        old_time = None
        if old_time_str:
            try:
                if 'T' in str(old_time_str):
                    old_time = datetime.fromisoformat(old_time_str)
                else:
                    old_time = datetime.strptime(str(old_time_str), '%Y-%m-%d')
            except:
                pass
        
        # Calculate base score
        score = calculate_duplicate_score(new_txn, old_txn, new_time, old_time)
        
        # Apply adjustments
        score = adjust_for_recurring(score, new_txn, old_txn, new_time, old_time)
        score = adjust_for_same_vendor(score, new_txn, old_txn)
        
        if score > best_score:
            best_score = score
            best_match = old_txn
    
    is_duplicate = best_score > DUPLICATE_THRESHOLD
    
    logger.info(f"Duplicate check: score={best_score:.2f}, is_dup={is_duplicate}")
    
    return is_duplicate, best_match, best_score


def format_duplicate_warning(new_txn: Dict, old_txn: Dict, score: float) -> str:
    """Format duplicate warning message for user."""
    new_amount = new_txn.get('amount', 0)
    new_desc = new_txn.get('description', '')
    
    old_amount = old_txn.get('amount', 0)
    old_desc = old_txn.get('description', '')
    old_date = old_txn.get('date', 'N/A')
    old_project = old_txn.get('project_name', 'N/A')
    
    similarity_pct = int(score * 100)
    
    return f"""⚠️ Transaksi Mirip Terdeteksi ({similarity_pct}% similarity)

🔹 Transaksi Baru:
   💸 {new_desc}: Rp {new_amount:,}

🔹 Transaksi Sebelumnya:
   💸 {old_desc}: Rp {old_amount:,}
   📅 {old_date}
   📂 Projek: {old_project}

❓ Ini transaksi yang sama atau berbeda?
💡 Y = Batal (duplikat) | N = Tetap simpan (beda transaksi)"""


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 5 processing: Duplicate Detection.
    
    Only runs when state is READY_TO_SAVE.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with duplicate_info
    """
    from . import layer_2_context_engine
    
    # Only check when ready to save
    if ctx.current_state != "READY_TO_SAVE":
        return ctx
    
    new_txn = ctx.extracted_data or {}
    
    # Get recent transactions from storage layer
    try:
        from . import layer_6_storage
        recent = layer_6_storage.get_recent_transactions(
            user_id=ctx.user_id,
            days=CHECK_WINDOW_DAYS,
            limit=10
        )
    except:
        recent = []
    
    if not recent:
        ctx.current_state = "CONFIRMED_SAVE"
        return ctx
    
    # Check for duplicates
    is_dup, match, score = check_duplicate(new_txn, recent)
    
    if is_dup:
        ctx.duplicate_info = {
            'is_duplicate': True,
            'matching_transaction': match,
            'score': score
        }
        ctx.current_state = "CONFIRM_DUPLICATE"
        ctx.response_message = format_duplicate_warning(new_txn, match, score)
        
        # Set pending question
        buffers = layer_2_context_engine.get_buffers()
        buffers.set_pending_question(
            user_id=ctx.user_id,
            question_type='CONFIRM_DUPLICATE',
            bot_message_id=ctx.message_id,
            expected_pattern=r'^[yn]|ya|tidak|yes|no$',
            context_data=ctx.extracted_data
        )
    else:
        ctx.current_state = "CONFIRMED_SAVE"
    
    return ctx


# Initialize cache on module load
_load_embeddings_cache()
