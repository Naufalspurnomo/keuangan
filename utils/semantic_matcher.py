"""
utils/semantic_matcher.py - Semantic Entity Matching Engine
Part of the Semantic Understanding Engine.

Handles matching user hints ("Dp") to transaction items ("DP dari Beatrix")
using a multi-signal scoring algorithm.
"""

import re
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

def extract_revision_entities(text: str) -> dict:
    """
    Extract item hint and new amount from revision text.
    
    Examples:
    - "revisi Dp 9.750.000" -> {item_hint: "Dp", amount: 9750000}
    - "salah, transfer 500rb" -> {item_hint: "transfer", amount: 500000}
    """
    if not text:
        return {}
        
    # Normalize text
    text_clean = text.lower().strip()
    
    # Remove noise words (revision keywords)
    noise = ["revisi", "ralat", "ganti", "salah", "ubah", "koreksi", 
             "harusnya", "jadi", "ke", "untuk", "nominal", "jumlah"]
    for word in noise:
        text_clean = text_clean.replace(word, " ")
    
    # Extract amount
    from .parsers import parse_revision_amount
    amount = parse_revision_amount(text_clean)
    
    # Extract item hint (remaining text after removing amount strings)
    # Remove amount patterns like 9.750.000, 500rb, 500k, 2jt, 500 rb
    # Improved regex to handle optional space between number and suffix
    text_without_amount = re.sub(r'\b\d+(?:[.,]\d+)*\s*(?:rb|ribu|k|jt|juta|perak)?\b', '', text_clean)
    # Remove standalone numbers
    text_without_amount = re.sub(r'\b\d+(?:[.,]\d+)+\b', '', text_without_amount)
    
    item_hint = text_without_amount.strip()
    
    # Clean up item hint
    item_hint = re.sub(r'\s+', ' ', item_hint)  # Multiple spaces -> single space
    item_hint = item_hint.strip() if len(item_hint) > 1 else None
    
    return {
        "item_hint": item_hint,
        "amount": amount,
        "original_text": text
    }


def find_matching_item(items: list, item_hint: str, original_amount: int=None) -> dict:
    """
    Find which item user wants to revise using semantic matching.
    
    Args:
        items: List of transaction dicts (must have 'keterangan'/'description' and 'amount'/'jumlah')
        item_hint: User's hint about which item
        original_amount: Original amount (for proximity scoring)
    
    Returns:
        {
            "matched_item": Item dict,
            "confidence": 0-100,
            "method": "exact" | "fuzzy" | "semantic" | "amount"
             "needs_confirmation": bool
        }
    """
    if not match_result:
        # FALLBACK: If only 1 item, auto-select
        if len(items) == 1:
            logger.info("Auto-selecting only available item")
            return {
                "matched_item": items[0],
                "confidence": 90,
                "method": "only_available_item"
            }
    
        # If multiple items, need clarification
        return None
    
    if not items or not isinstance(items, list):
        return None
    
    # CASE 1: No hint provided -> Match by amount if only 1 item
    if not item_hint:
        if len(items) == 1:
            return {
                "matched_item": items[0],
                "confidence": 100,
                "method": "single_item"
            }
        elif original_amount:
            # Try to match by amount proximity
            return match_by_amount(items, original_amount)
        else:
            # Ambiguous - no hint, multiple items, no amount match
            return None
            
    # CASE 2: Hint provided -> Multi-stage matching
    scores = []
    
    for item in items:
        score_result = calculate_item_match_score(item, item_hint, original_amount)
        scores.append({
            "item": item,
            "score": score_result["total"],
            "breakdown": score_result
        })
        
    # Sort by score
    scores.sort(key=lambda x: x["score"], reverse=True)
    
    best_match = scores[0]
    
    # Confidence thresholds
    if best_match["score"] >= 70:
        return {
            "matched_item": best_match["item"],
            "confidence": best_match["score"],
            "method": best_match["breakdown"]["best_method"]
        }
    elif best_match["score"] >= 50:
        # Medium confidence - ask confirmation
        return {
            "matched_item": best_match["item"],
            "confidence": best_match["score"],
            "method": best_match["breakdown"]["best_method"],
            "needs_confirmation": True
        }
    else:
        # Low confidence - ask clarification
        return None


def calculate_item_match_score(item: dict, hint: str, original_amount: int=None) -> dict:
    """
    Calculate match score between item and user's hint.
    """
    # Normalize keys (handle 'keterangan' vs 'description', 'jumlah' vs 'amount')
    description = (item.get('keterangan') or item.get('description') or '').lower()
    amount = item.get('jumlah') if 'jumlah' in item else item.get('amount', 0)
    
    hint = hint.lower()
    
    scores = {}
    
    # 1. EXACT MATCH
    if hint in description or description in hint:
        scores["exact"] = 100
    else:
        scores["exact"] = 0
        
    # 2. FUZZY STRING SIMILARITY
    similarity = SequenceMatcher(None, hint, description).ratio()
    scores["fuzzy"] = int(similarity * 90)
    
    # 3. KEYWORD EXTRACTION MATCH
    stopwords = ["dari", "ke", "untuk", "via", "dengan", "dan", "atau", "pembayaran"]
    hint_keywords = [w for w in hint.split() if w not in stopwords and len(w) > 2]
    desc_keywords = [w for w in description.split() if w not in stopwords and len(w) > 2]
    
    if hint_keywords:
        matching_keywords = sum(1 for kw in hint_keywords if any(kw in dk or dk in kw for dk in desc_keywords))
        keyword_score = (matching_keywords / len(hint_keywords)) * 80
    else:
        keyword_score = 0
    scores["keyword"] = int(keyword_score)
    
    # 4. ABBREVIATION MATCH
    abbreviations = {
        "dp": ["dp", "down payment", "uang muka"],
        "tf": ["transfer", "kirim"],
        "ongkir": ["ongkir", "ongkos", "biaya kirim", "pengiriman"],
        "adm": ["admin", "administrasi", "biaya admin"],
        "topup": ["top up", "isi ulang", "deposit"]
    }
    
    abbrev_score = 0
    for abbrev, full_forms in abbreviations.items():
        if hint == abbrev or hint.startswith(abbrev + " "):
            if any(form in description for form in full_forms):
                abbrev_score = 85
                break
    scores["abbreviation"] = abbrev_score
    
    # 5. AMOUNT PROXIMITY
    if original_amount and amount:
        # Avoid division by zero
        max_amt = max(abs(amount), abs(original_amount))
        if max_amt > 0:
            diff_ratio = abs(amount - original_amount) / max_amt
            amount_score = max(0, int((1 - diff_ratio) * 60))
        else:
            amount_score = 60 if amount == original_amount else 0
    else:
        amount_score = 0
    scores["amount_proximity"] = amount_score
    
    # FINAL SCORE
    best_method = max(scores, key=scores.get)
    total_score = scores[best_method]
    
    return {
        "total": total_score,
        "best_method": best_method,
        "details": scores
    }


def match_by_amount(items: list, target_amount: int) -> dict:
    """Fallback: Match item by amount proximity."""
    best_match = None
    min_diff = float('inf')
    
    for item in items:
        amount = item.get('jumlah') if 'jumlah' in item else item.get('amount', 0)
        diff = abs(amount - target_amount)
        if diff < min_diff:
            min_diff = diff
            best_match = item
            
    if best_match is None:
         return None
         
    # Confidence
    amount = best_match.get('jumlah') if 'jumlah' in best_match else best_match.get('amount', 0)
    if amount == 0: return None # Safety
    
    if min_diff == 0:
        confidence = 100
    elif min_diff < abs(target_amount) * 0.1:
        confidence = 80
    elif min_diff < abs(target_amount) * 0.3:
        confidence = 60
    else:
        confidence = 30
        
    return {
        "matched_item": best_match,
        "confidence": confidence,
        "method": "amount_proximity"
    }
