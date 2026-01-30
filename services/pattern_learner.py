"""
services/pattern_learner.py - Adaptive Pattern Learning System

Stores user-confirmed patterns to _BOT_STATE sheet for improving
future classification accuracy.

Features:
- Learn from user confirmations
- Fuzzy pattern matching
- Confidence boosting based on history

Author: Naufal
Version: 1.0 - Adaptive Learning
"""

import logging
import re
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

# In-memory cache (will be synced to sheet)
_pattern_cache = {}
_cache_loaded = False


def _normalize_pattern(text: str) -> str:
    """
    Normalize text to create pattern fingerprint.
    
    Examples:
        "gaji admin januari 5jt" -> "gaji admin {month}"
        "bon tukang wooftopia 2jt" -> "bon tukang {project}"
        "bayar pln 1.5jt" -> "bayar pln"
    """
    text_lower = text.lower()
    
    # Replace amounts with placeholder
    text_lower = re.sub(r'\d+[,.]?\d*\s*(rb|ribu|jt|juta|k)?', '{amount}', text_lower)
    text_lower = re.sub(r'rp[.\s]*\d+', '{amount}', text_lower)
    
    # Replace months with placeholder
    months = ['januari', 'februari', 'maret', 'april', 'mei', 'juni',
              'juli', 'agustus', 'september', 'oktober', 'november', 'desember']
    for month in months:
        text_lower = text_lower.replace(month, '{month}')
    
    # Replace capitalized words (likely project names) with placeholder
    # But keep keywords like "gaji", "bon", "bayar"
    words = text_lower.split()
    normalized = []
    skip_words = {'gaji', 'gajian', 'bon', 'bayar', 'beli', 'fee', 'upah', 
                  'tukang', 'admin', 'staff', 'listrik', 'pln', 'air', 'pdam'}
    
    for word in words:
        if word in skip_words or word == '{amount}' or word == '{month}':
            normalized.append(word)
        elif word.startswith('{'):
            normalized.append(word)
        else:
            # Check if this is likely a project name (not in common words)
            if len(word) > 3 and word not in ['untuk', 'buat', 'dari', 'dengan', 'yang']:
                normalized.append('{project}')
            else:
                normalized.append(word)
    
    # Remove duplicates of {project}
    result = []
    prev = None
    for word in normalized:
        if word != '{project}' or prev != '{project}':
            result.append(word)
        prev = word
    
    return ' '.join(result).strip()


def load_patterns_from_sheet() -> Dict[str, Dict]:
    """
    Load learned patterns from _BOT_STATE sheet.
    
    Returns:
        Dict mapping pattern fingerprint to metadata:
        {
            "pattern_fingerprint": {
                "category_scope": "OPERATIONAL" | "PROJECT",
                "count": int,  # How many times confirmed
                "last_updated": "YYYY-MM-DD HH:MM:SS",
                "examples": ["example 1", "example 2"]  # Up to 3 examples
            }
        }
    """
    global _pattern_cache, _cache_loaded
    
    if _cache_loaded:
        return _pattern_cache
    
    try:
        from sheets_helper import get_sheet
        
        sheet = get_sheet('_BOT_STATE')
        if not sheet:
            logger.warning("_BOT_STATE sheet not found, creating empty cache")
            _cache_loaded = True
            return {}
        
        # Read all pattern data
        # Expected columns: Pattern | Category | Count | LastUpdated | Examples
        data = sheet.get_all_values()
        
        patterns = {}
        for row in data[1:]:  # Skip header
            if len(row) >= 5:
                pattern = row[0]
                category = row[1]
                count = int(row[2]) if row[2].isdigit() else 1
                last_updated = row[3]
                examples = row[4].split('|||') if row[4] else []
                
                patterns[pattern] = {
                    'category_scope': category,
                    'count': count,
                    'last_updated': last_updated,
                    'examples': examples[:3]  # Max 3 examples
                }
        
        _pattern_cache = patterns
        _cache_loaded = True
        logger.info(f"Loaded {len(patterns)} learned patterns from _BOT_STATE")
        return patterns
        
    except Exception as e:
        logger.error(f"Failed to load patterns from sheet: {e}")
        _cache_loaded = True
        return {}


def save_pattern_to_sheet(pattern: str, category_scope: str, example_text: str):
    """
    Save or update a learned pattern to _BOT_STATE sheet.
    
    Args:
        pattern: Pattern fingerprint (normalized)
        category_scope: "OPERATIONAL" or "PROJECT"
        example_text: Original text example
    """
    global _pattern_cache
    
    try:
        from sheets_helper import get_sheet
        
        sheet = get_sheet('_BOT_STATE')
        if not sheet:
            logger.error("_BOT_STATE sheet not found, cannot save pattern")
            return
        
        # Load current patterns
        patterns = load_patterns_from_sheet()
        
        # Update or create pattern
        if pattern in patterns:
            # Update existing
            patterns[pattern]['count'] += 1
            patterns[pattern]['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Add example if not already present
            if example_text not in patterns[pattern]['examples']:
                patterns[pattern]['examples'].append(example_text)
                patterns[pattern]['examples'] = patterns[pattern]['examples'][:3]  # Keep only 3
        else:
            # Create new
            patterns[pattern] = {
                'category_scope': category_scope,
                'count': 1,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'examples': [example_text]
            }
        
        # Write back to sheet
        # Clear existing data (except header)
        data = sheet.get_all_values()
        if len(data) > 1:
            sheet.delete_rows(2, len(data))
        
        # Write updated patterns
        rows = []
        for pat, meta in patterns.items():
            rows.append([
                pat,
                meta['category_scope'],
                str(meta['count']),
                meta['last_updated'],
                '|||'.join(meta['examples'])
            ])
        
        if rows:
            sheet.append_rows(rows)
        
        # Update cache
        _pattern_cache = patterns
        logger.info(f"Saved pattern: '{pattern}' -> {category_scope}")
        
    except Exception as e:
        logger.error(f"Failed to save pattern to sheet: {e}")


def check_learned_pattern(text: str) -> Optional[Dict]:
    """
    Check if text matches any learned pattern.
    
    Returns:
        {
            "category_scope": "OPERATIONAL" | "PROJECT",
            "confidence_boost": 0.0-0.2,  # Based on count
            "pattern": "matched pattern",
            "examples": ["example 1", ...]
        }
        or None if no match
    """
    patterns = load_patterns_from_sheet()
    
    if not patterns:
        return None
    
    # Normalize input text
    normalized = _normalize_pattern(text)
    
    # Check exact match
    if normalized in patterns:
        meta = patterns[normalized]
        boost = min(0.2, meta['count'] * 0.05)  # Max 0.2 boost
        
        return {
            'category_scope': meta['category_scope'],
            'confidence_boost': boost,
            'pattern': normalized,
            'examples': meta['examples']
        }
    
    # Fuzzy match (check if pattern is subset)
    for pattern, meta in patterns.items():
        pattern_words = set(pattern.split())
        normalized_words = set(normalized.split())
        
        # If 70% of pattern words are in normalized text
        if len(pattern_words & normalized_words) >= len(pattern_words) * 0.7:
            boost = min(0.15, meta['count'] * 0.04)  # Slightly lower for fuzzy
            
            return {
                'category_scope': meta['category_scope'],
                'confidence_boost': boost,
                'pattern': pattern,
                'examples': meta['examples'],
                'match_type': 'fuzzy'
            }
    
    return None


def record_user_confirmation(text: str, category_scope: str):
    """
    Record a user confirmation to learn the pattern.
    
    Args:
        text: Original user text
        category_scope: Confirmed category ("OPERATIONAL" or "PROJECT")
    """
    pattern = _normalize_pattern(text)
    save_pattern_to_sheet(pattern, category_scope, text)
    logger.info(f"Learned pattern from user confirmation: '{text}' -> {category_scope}")


# ===================== TESTING =====================

if __name__ == "__main__":
    # Fix Windows console encoding
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    
    # Test pattern normalization
    print("=== PATTERN NORMALIZATION TEST ===\n")
    
    test_texts = [
        "Gaji admin bulan Januari 5jt",
        "Gaji admin bulan Februari 5jt",
        "Gajian tukang Wooftopia 2jt",
        "Gajian tukang Taman Indah 3jt",
        "Bayar PLN 1.5jt",
        "Bayar listrik 2jt",
        "Bon tukang buat Cafe Kopi 500rb",
    ]
    
    for text in test_texts:
        normalized = _normalize_pattern(text)
        print(f"Original: {text}")
        print(f"Pattern:  {normalized}")
        print()
    
    print("=== PATTERN LEARNING SIMULATION ===\n")
    
    # Simulate learning
    print("Recording confirmations...")
    record_user_confirmation("Gaji admin Januari 5jt", "OPERATIONAL")
    record_user_confirmation("Gaji admin Februari 5jt", "OPERATIONAL")
    record_user_confirmation("Gajian tukang Wooftopia 2jt", "PROJECT")
    
    print("\nChecking learned patterns:")
    
    # Test matching
    test_queries = [
        "Gaji admin Maret 6jt",  # Should match OPERATIONAL
        "Gajian tukang Taman Indah 3jt",  # Should match PROJECT
        "Bayar listrik 1jt",  # Should not match (not learned)
    ]
    
    for query in test_queries:
        result = check_learned_pattern(query)
        print(f"\nQuery: {query}")
        if result:
            print(f"  -> Match! Category: {result['category_scope']}")
            print(f"  -> Boost: +{result['confidence_boost']:.2f}")
            print(f"  -> Pattern: {result['pattern']}")
        else:
            print(f"  -> No match")
