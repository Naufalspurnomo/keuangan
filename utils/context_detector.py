"""
utils/context_detector.py - Multi-Layer Context Detection Engine

ULTRA-ROBUST context analysis untuk membedakan:
- OPERATIONAL (gaji staff kantor, listrik, wifi, dll)
- PROJECT (gaji tukang lapangan, material, fee, dll)

System ini menggunakan 4 LAYERS:
1. Keyword Detection (Strong Signals)
2. Context Clue Extraction (Role, Project Name, Temporal, Preposition)
3. AI Semantic Analysis (Groq Llama)
4. Confidence-Based Routing (Auto / Confirm / Ask)

Author: Naufal
Version: 1.0 - Ultra-Robust Context Awareness
"""

import re
import logging
from typing import Dict, Tuple, Optional, List

logger = logging.getLogger(__name__)

# ===================== LAYER 1: KEYWORD DETECTION =====================

# Strong OPERATIONAL signals (Score 90-100 = Auto-classify)
OPERATIONAL_STRONG_KEYWORDS = {
    # Gaji kantor (office payroll)
    "gaji admin": 100,
    "gaji staff": 100,
    "gaji karyawan": 100,
    "gaji sekretaris": 100,
    "gaji receptionist": 100,
    "gaji cs": 100,
    "gaji accounting": 100,
    "gaji akuntan": 100,
    
    # Utilities
    "listrik": 100,
    "pln": 100,
    "bayar listrik": 100,
    "tagihan listrik": 100,
    
    "air": 95,  # Could be амбиг ("air mineral" vs "PDAM")
    "pdam": 100,
    "tagihan air": 100,
    "bayar air": 95,
    
    "wifi": 100,
    "internet": 95,
    "internet kantor": 100,
    "wifi kantor": 100,
    
    # Office supplies
    "atk": 100,
    "alat tulis": 100,
    "printer": 90,
    "toner": 90,
    "kertas kantor": 100,
    
    # Office consumption
    "konsumsi kantor": 100,
    "snack kantor": 100,
    "makan kantor": 100,
    "kopi kantor": 95,
    
    # Other operational
    "pulsa kantor": 90,
    "parkir kantor": 90,
    "keamanan": 85,
    "cleaning service": 90,
    "lain-lain": 70,  # Low confidence, needs context
}

# Strong PROJECT signals (Score 90-100)
PROJECT_STRONG_KEYWORDS = {
    # Labor
    "bayar tukang": 100,
    "upah tukang": 100,
    "fee tukang": 100,
    "gaji tukang": 95,  # Ambigu, needs context
    "bon tukang": 100,
    "ongkos tukang": 100,
    "jasa tukang": 100,
    "tukang bangunan": 100,
    "tukang cat": 100,
    "tukang listrik": 100,
    "tukang kayu": 100,
    "mandor": 100,
    "pekerja lapangan": 100,
    
    # Materials
    "material": 100,
    "bahan bangunan": 100,
    "cat": 85,
    "semen": 90,
    "pasir": 90,
    "batu bata": 90,
    "besi": 85,
    "kayu": 85,
    "triplek": 90,
    "keramik": 90,
    "pipa": 85,
    "kabel": 80,
    
    # Logistics
    "ongkir": 90,
    "kirim barang": 85,
    "transport material": 95,
    "sewa truk": 90,
    
    # Services
    "jasa renovasi": 100,
    "jasa design": 90,
    "survei lapangan": 95,
}

# AMBIGUOUS words yang BUTUH analisis deep
AMBIGUOUS_KEYWORDS = {
    "gaji": "AMBIGUOUS_PAYROLL",
    "gajian": "AMBIGUOUS_PAYROLL",
    "bon": "AMBIGUOUS_BON",
    "bayar orang": "AMBIGUOUS_PAYMENT",
    "fee": "AMBIGUOUS_FEE",
    "upah": "AMBIGUOUS_WAGE",
    "bayar": "AMBIGUOUS_PAYMENT",
}

# ===================== LAYER 2: CONTEXT CLUE EXTRACTION =====================

# Office roles (indikator OPERATIONAL)
OFFICE_ROLES = {
    "admin", "administrator", "staff", "karyawan", 
    "sekretaris", "secretary", "receptionist", 
    "cs", "customer service", "akuntan", "accounting",
    "kasir", "cashier", "manager kantor", "supervisor kantor"
}

# Field roles (indikator PROJECT)
FIELD_ROLES = {
    "tukang", "pekerja lapangan", "pelukis", 
    "designer lapangan", "mandor", "helper",
    "sopir proyek", "surveyor", "kontraktor",
    "tukang bangunan", "tukang cat", "tukang listrik"
}

# Temporal patterns
OPERATIONAL_TEMPORAL = [
    r"bulan (ini|lalu|januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)",
    r"gaji bulan",
    r"bulanan",
    r"per bulan",
    r"setiap bulan",
    r"recurring"
]

PROJECT_TEMPORAL = [
    r"(hari|hr) ini",
    r"kemarin",
    r"tadi",
    r"barusan",
    r"minggu (ini|lalu|kemarin)",
    r"untuk (hari|hr) ini"
]

# Preposition indicators
PROJECT_PREPOSITIONS = [
    r"untuk ([A-Z][A-Za-z\s]+)",  # "untuk Wooftopia"
    r"buat ([A-Z][A-Za-z\s]+)",   # "buat Taman Indah"
    r"di ([A-Z][A-Za-z\s]+)",     # "di Project Kopi"
    r"([A-Z][A-Za-z\s]+) project", # "Wooftopia project"
]

OPERATIONAL_PREPOSITIONS = [
    r"(di|untuk|buat) kantor",
    r"(di|untuk) office",
    r"keperluan kantor",
    r" kantor$",  # "..., kantor" at end of sentence
    r"^kantor ",  # "kantor ..." at start
]


class ContextDetector:
    """
    Multi-layer context detection engine.
    Analyzes text to determine OPERATIONAL vs PROJECT scope.
    """
    
    def __init__(self):
        self.operational_patterns = [re.compile(p, re.IGNORECASE) for p in OPERATIONAL_TEMPORAL]
        self.project_patterns = [re.compile(p, re.IGNORECASE) for p in PROJECT_TEMPORAL]
        self.project_prep_patterns = [re.compile(p, re.IGNORECASE) for p in PROJECT_PREPOSITIONS]
        self.operational_prep_patterns = [re.compile(p, re.IGNORECASE) for p in OPERATIONAL_PREPOSITIONS]
    
    def detect_context(self, text: str) -> Dict:
        """
        Main entry point for context detection.
        
        Returns:
            {
                "category_scope": "OPERATIONAL" | "PROJECT" | "AMBIGUOUS",
                "confidence": 0.0-1.0,
                "signals": {
                    "keyword_match": {...},
                    "role_detected": str or None,
                    "project_name": str or None,
                    "temporal_pattern": str or None,
                    "preposition_context": str or None,
                },
                "reasoning": str
            }
        """
        text_lower = text.lower()
        
        # LAYER 1: Strong keyword detection
        keyword_result = self._detect_keywords(text_lower)
        
        # LAYER 2: Extract context clues
        role_type, role_name = self._extract_role(text_lower)
        project_name = self._extract_project_name(text)
        temporal_type = self._detect_temporal_pattern(text_lower)
        prep_context = self._detect_preposition_context(text_lower)
        
        # Build signals dict
        signals = {
            "keyword_match": keyword_result,
            "role_detected": f"{role_type}:{role_name}" if role_type else None,
            "project_name": project_name,
            "temporal_pattern": temporal_type,
            "preposition_context": prep_context,
        }
        
        # DECISION LOGIC
        category_scope, confidence, reasoning = self._make_decision(
            keyword_result, role_type, project_name, temporal_type, prep_context
        )
        
        return {
            "category_scope": category_scope,
            "confidence": confidence,
            "signals": signals,
            "reasoning": reasoning
        }
    
    def _detect_keywords(self, text_lower: str) -> Dict:
        """Layer 1: Detect strong keyword signals."""
        # Check OPERATIONAL strong signals
        for keyword, score in OPERATIONAL_STRONG_KEYWORDS.items():
            if keyword in text_lower:
                return {
                    "type": "OPERATIONAL",
                    "keyword": keyword,
                    "score": score / 100.0
                }
        
        # Check PROJECT strong signals
        for keyword, score in PROJECT_STRONG_KEYWORDS.items():
            if keyword in text_lower:
                return {
                    "type": "PROJECT",
                    "keyword": keyword,
                    "score": score / 100.0
                }
        
        # Check AMBIGUOUS
        for keyword, amb_type in AMBIGUOUS_KEYWORDS.items():
            if keyword in text_lower:
                return {
                    "type": "AMBIGUOUS",
                    "keyword": keyword,
                    "ambiguity_type": amb_type,
                    "score": 0.4
                }
        
        return {"type": "UNKNOWN", "score": 0.0}
    
    def _extract_role(self, text_lower: str) -> Tuple[Optional[str], Optional[str]]:
        """Layer 2A: Extract role (office vs field)."""
        # Check office roles
        for role in OFFICE_ROLES:
            if role in text_lower:
                return ("OFFICE", role)
        
        # Check field roles
        for role in FIELD_ROLES:
            if role in text_lower:
                return ("FIELD", role)
        
        return (None, None)
    
    def _extract_project_name(self, text: str) -> Optional[str]:
        """Layer 2B: Extract project name from text."""
        # Blacklist of words that are NOT project names
        blacklist = {
            "gaji", "gajian", "bon", "bayar", "beli", "untuk", "buat",
            "fee", "upah", "ongkos", "jasa", "kirim", "transfer", 
            "project", "proyek", "dari", "dengan", "ke", "di"
        }
        
        # Try preposition patterns first
        for pattern in self.project_prep_patterns:
            match = pattern.search(text)
            if match:
                name = match.group(1).strip()
                # Filter out blacklisted words
                if len(name) > 3 and name.lower() not in blacklist:
                    return name
        
        # Try finding capitalized words (proper nouns)
        words = text.split()
        capitalized = [w for w in words if w and w[0].isupper() and len(w) > 2]
        # Filter out blacklisted words
        filtered = [w for w in capitalized if w.lower() not in blacklist]
        
        if filtered:
            # Take up to 3 consecutive capitalized words
            return " ".join(filtered[:3])
        
        return None
    
    def _detect_temporal_pattern(self, text_lower: str) -> Optional[str]:
        """Layer 2C: Detect temporal patterns."""
        # Check OPERATIONAL temporal
        for pattern in self.operational_patterns:
            if pattern.search(text_lower):
                return "OPERATIONAL_TEMPORAL"
        
        # Check PROJECT temporal
        for pattern in self.project_patterns:
            if pattern.search(text_lower):
                return "PROJECT_TEMPORAL"
        
        return None
    
    def _detect_preposition_context(self, text_lower: str) -> Optional[str]:
        """Layer 2D: Detect preposition context."""
        # Check OPERATIONAL prepositions
        for pattern in self.operational_prep_patterns:
            if pattern.search(text_lower):
                return "OPERATIONAL_PREP"
        
        # Check PROJECT prepositions (already handled in project name extraction)
        # This is redundant but kept for clarity
        return None
    
    def _make_decision(
        self, 
        keyword_result: Dict, 
        role_type: Optional[str],
        project_name: Optional[str],
        temporal_type: Optional[str],
        prep_context: Optional[str]
    ) -> Tuple[str, float, str]:
        """
        Make final decision based on all signals.
        
        Returns: (category_scope, confidence, reasoning)
        """
        reasons = []
        
        # Start with keyword score
        base_confidence = keyword_result.get("score", 0.0)
        category = keyword_result.get("type", "UNKNOWN")
        
        # CASE 1: Strong OPERATIONAL keyword
        if category == "OPERATIONAL" and base_confidence >= 0.90:
            reasons.append(f"Strong operational keyword: '{keyword_result['keyword']}'")
            
            # Boost if has office role
            if role_type == "OFFICE":
                base_confidence = min(1.0, base_confidence + 0.05)
                reasons.append(f"Office role detected: '{role_type}'")
            
            # Boost if has operational temporal
            if temporal_type == "OPERATIONAL_TEMPORAL":
                base_confidence = min(1.0, base_confidence + 0.05)
                reasons.append("Monthly/recurring pattern detected")
            
            return ("OPERATIONAL", base_confidence, "; ".join(reasons))
        
        # CASE 2: Strong PROJECT keyword
        if category == "PROJECT" and base_confidence >= 0.90:
            reasons.append(f"Strong project keyword: '{keyword_result['keyword']}'")
            
            # Boost if has project name
            if project_name:
                base_confidence = min(1.0, base_confidence + 0.05)
                reasons.append(f"Project name detected: '{project_name}'")
            
            # Boost if has field role
            if role_type == "FIELD":
                base_confidence = min(1.0, base_confidence + 0.05)
                reasons.append(f"Field role detected: '{role_type}'")
            
            return ("PROJECT", base_confidence, "; ".join(reasons))
        
        # CASE 3: AMBIGUOUS keyword - use context clues
        if category == "AMBIGUOUS":
            reasons.append(f"Ambiguous keyword: '{keyword_result['keyword']}'")
            
            # Check role
            if role_type == "OFFICE":
                reasons.append(f"Office role: '{role_type}' → OPERATIONAL")
                return ("OPERATIONAL", 0.75, "; ".join(reasons))
            
            if role_type == "FIELD":
                reasons.append(f"Field role: '{role_type}' → PROJECT")
                return ("PROJECT", 0.75, "; ".join(reasons))
            
            # Check project name
            if project_name:
                reasons.append(f"Project name found: '{project_name}' → PROJECT")
                return ("PROJECT", 0.80, "; ".join(reasons))
            
            # Check temporal
            if temporal_type == "OPERATIONAL_TEMPORAL":
                reasons.append("Monthly pattern → OPERATIONAL")
                return ("OPERATIONAL", 0.70, "; ".join(reasons))
            
            if temporal_type == "PROJECT_TEMPORAL":
                reasons.append("Ad-hoc timing → PROJECT")
                return ("PROJECT", 0.65, "; ".join(reasons))
            
            # Still ambiguous
            reasons.append("No context clues found")
            return ("AMBIGUOUS", 0.40, "; ".join(reasons))
        
        # CASE 4: UNKNOWN keyword - rely on context clues
        if category == "UNKNOWN":
            # Has project name?
            if project_name:
                reasons.append(f"Project name detected: '{project_name}'")
                return ("PROJECT", 0.70, "; ".join(reasons))
            
            # Has role?
            if role_type == "OFFICE":
                reasons.append(f"Office role: '{role_type}'")
                return ("OPERATIONAL", 0.65, "; ".join(reasons))
            
            if role_type == "FIELD":
                reasons.append(f"Field role: '{role_type}'")
                return ("PROJECT", 0.65, "; ".join(reasons))
            
            # Has temporal?
            if temporal_type == "OPERATIONAL_TEMPORAL":
                reasons.append("Monthly pattern")
                return ("OPERATIONAL", 0.60, "; ".join(reasons))
            
            # No clues
            reasons.append("No contextual signals detected")
            return ("AMBIGUOUS", 0.30, "; ".join(reasons))
        
        # Default fallback
        return ("AMBIGUOUS", 0.30, "Insufficient information")


# ===================== HELPER FUNCTIONS =====================

def quick_operational_check(text: str) -> bool:
    """
    Quick check if text is likely operational.
    Used for fast filtering before full analysis.
    """
    text_lower = text.lower()
    
    # Check top operational keywords
    quick_keywords = [
        "gaji admin", "gaji staff", "listrik", "pln", 
        "air", "pdam", "wifi", "internet kantor", 
        "atk", "konsumsi kantor"
    ]
    
    return any(kw in text_lower for kw in quick_keywords)


def quick_project_check(text: str) -> bool:
    """
    Quick check if text is likely project-related.
    Used for fast filtering before full analysis.
    """
    text_lower = text.lower()
    
    # Check top project keywords
    quick_keywords = [
        "tukang", "material", "cat", "semen", 
        "bahan bangunan", "pekerja lapangan"
    ]
    
    return any(kw in text_lower for kw in quick_keywords)


# ===================== TESTING =====================

if __name__ == "__main__":
    # Fix Windows console encoding
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass  # Ignore if not available
    
    # Test cases
    detector = ContextDetector()
    
    test_cases = [
        "Gaji admin bulan Januari 5jt",
        "Gajian tukang Wooftopia 2jt",
        "Bon tukang buat Taman Indah 300rb",
        "Bayar PLN 1.5jt",
        "Gajian 5jt",  # Very ambiguous
        "Bon 500rb",   # Very ambiguous
        "Bayar fee designer lapangan untuk Kopi Kenangan 1jt",
        "Bayar listrik kantor 2jt",
    ]
    
    print("=== CONTEXT DETECTION TEST ===\n")
    for text in test_cases:
        result = detector.detect_context(text)
        print(f"Input: '{text}'")
        print(f"  -> Category: {result['category_scope']} (Confidence: {result['confidence']:.2f})")
        print(f"  -> Reasoning: {result['reasoning']}")
        print(f"  -> Signals: {result['signals']}")
        print()
