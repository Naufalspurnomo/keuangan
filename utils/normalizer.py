"""
utils/normalizer.py - Text Normalization & Intent Extraction
Part of the Semantic Understanding Engine.
"""

import re
from difflib import get_close_matches
import logging

logger = logging.getLogger(__name__)

def normalize_nyeleneh_text(text: str) -> str:
    """
    Clean and normalize informal/slang Indonesian text.
    
    Steps:
    1. Lowercase
    2. Remove excessive repetition (tololll -> tolol)
    3. Remove noise/filler words
    4. Fix common typos
    5. Expand abbreviations
    """
    if not text:
        return ""
        
    text = text.lower().strip()
    
    # Remove Emojis (Regex range for common emojis)
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]', '', text)
    
    # ========================================
    # 1. FIX EXCESSIVE REPETITION
    # ========================================
    # "berapeeee" -> "berape"
    def remove_repetition(match):
        char = match.group(1)
        # Keep max 2 repetitions
        return char * min(2, len(match.group(0)))
    
    text = re.sub(r'(.)\1{2,}', remove_repetition, text)

    # ========================================
    # 2. REMOVE NOISE WORDS
    # ========================================
    noise_words = [
        # Vulgar/slang (keep for log, but remove for processing)
        "anjir", "anjing", "asu", "tolol", "bego", "bangsat",
        # Interjections
        "woi", "oi", "eh", "loh", "kok", "sih", "dong", "min", "bot",
        # Filler
        "banget", "sangat", "sekali", "nih", "tuh",
        # Complaining
        "males", "capek", "bosan"
    ]
    
    # Create single optimized regex logic
    # Compiling a large regex is more efficient than looping many subs
    # Pattern: \b(word1|word2|...)\w*\b
    # Escape words just in case
    escaped_words = [re.escape(w) for w in noise_words]
    pattern_str = r'\b(?:' + '|'.join(escaped_words) + r')\w*\b'
    
    # For repeated use in function, compilation happens here.
    # In Python 3.7+ re module has internal cache, but building the string once is better.
    # However, since we are inside function, we build text every time. 
    # Let's keep it simple but single regex.
    text = re.sub(pattern_str, '', text)
    
    # Clean multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    
    # ========================================
    # 3. FIX COMMON TYPOS WITH FUZZY MATCHING
    # ========================================
    correct_words = {
        # Financial terms (Indonesian)
        "berapa", "pengeluaran", "pemasukan", "saldo", "transaksi",
        "revisi", "ralat", "catat", "simpan", "hapus", "laporan",
        # Time terms (Indonesian)
        "hari", "ini", "kemarin", "bulan", "minggu", "tahun",
        # Actions (Indonesian)
        "beli", "bayar", "transfer", "kirim", "terima", "tarik",
        # English Financial Terms
        "income", "expense", "balance", "profit", "transaction", "payment",
        "how", "much", "deposit", "withdraw", "transfer", "record"
    }
    
    words = text.split()
    corrected_words = []
    
    for word in words:
        if len(word) <= 2: 
            corrected_words.append(word)
            continue
        
        # Check if word is correct
        if word in correct_words:
            corrected_words.append(word)
        else:
            # Try to find close match
            matches = get_close_matches(word, correct_words, n=1, cutoff=0.75)
            if matches:
                 corrected_words.append(matches[0])
            else:
                 corrected_words.append(word)
    
    text = ' '.join(corrected_words)
    
    # ========================================
    # 4. EXPAND ABBREVIATIONS
    # ========================================
    abbreviations = {
        # Indonesian
        "tf": "transfer",
        "dp": "dp",
        "adm": "administrasi",
        "brp": "berapa",
        "hrs": "hari",
        "tgl": "tanggal",
        "kpn": "kapan",
        "sdh": "sudah",
        "blm": "belum",
        "thx": "terima kasih",
        "makasih": "terima kasih",
        "sy": "saya",
        "gw": "saya",
        "aku": "saya",
        # English
        "tx": "transaction",
        "bal": "balance",
        "exp": "expense",
        "inc": "income"
    }
    
    for abbrev, full in abbreviations.items():
        text = re.sub(rf'\b{abbrev}\b', full, text)
        
    return text.strip()


def extract_intent_from_nyeleneh(text: str) -> dict:
    """
    Extract intent from normalized text (Rule-Based Fallback).
    
    Returns: {intent, confidence, normalized_text}
    """
    normalized = normalize_nyeleneh_text(text)
    
    # Pattern 1: QUERY (Interrogative)
    query_patterns = [
        r'\bberapa\b', r'\bapa\b', r'\bgimana\b', 
        r'\bmana\b', r'\bkapan\b', r'\bkenapa\b'
    ]
    
    if any(re.search(p, normalized) for p in query_patterns) or "?" in normalized:
        # Financial data query (highest priority)
        if any(w in normalized for w in ["saldo", "pengeluaran", "pemasukan", "transaksi", "laporan", "duit", "uang", "income", "expense", "profit", "balance"]):
            return {
                "intent": "QUERY_STATUS",
                "confidence": 0.9,
                "normalized_text": normalized
            }
        # Conversational query (asking bot for help/guidance)
        elif any(w in normalized for w in ["gimana", "bagaimana", "cara", "help", "bantuan", "tolong", "kenapa", "kok", "how", "why", "pakai", "gunakan", "export"]):
            return {
                "intent": "CONVERSATIONAL_QUERY",
                "confidence": 0.75,
                "normalized_text": normalized
            }
        # Pure chitchat (not addressed to bot functionality)
        else:
            return {
                "intent": "CHITCHAT",
                "confidence": 0.75,
                "normalized_text": normalized
            }
            
    # Pattern 2: REVISION
    revision_keywords = ["revisi", "ralat", "salah", "ganti", "ubah", "koreksi"]
    if any(w in normalized for w in revision_keywords):
        return {
            "intent": "REVISION_REQUEST",
            "confidence": 0.85,
            "normalized_text": normalized
        }
        
    # Pattern 3: RECORDING
    action_verbs = ["beli", "bayar", "transfer", "kirim", "catat", "terima", "dapat"]
    if any(w in normalized for w in action_verbs):
        return {
            "intent": "RECORD_TRANSACTION",
            "confidence": 0.8,
            "normalized_text": normalized
        }
        
    return {
        "intent": "UNKNOWN",
        "confidence": 0.0,
        "normalized_text": normalized
    }
