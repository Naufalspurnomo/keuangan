"""
utils/confidence_router.py - Confidence-Based Decision Routing

Handles routing based on confidence levels:
- HIGH (>= 0.85): Auto-classify
- MEDIUM (0.60-0.84): Confirm with user
- LOW (< 0.60): Ask clarifying questions

Author: Naufal
Version: 1.0 - Intelligent Routing
"""

import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# Confidence thresholds
CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.60


class ConfidenceRouter:
    """
    Routes decisions based on confidence scores.
    """
    
    def __init__(self):
        pass
    
    def route_decision(
        self, 
        category_scope: str,
        confidence: float,
        signals: Dict,
        text: str
    ) -> Tuple[str, Optional[str]]:
        """
        Route decision based on confidence level.
        
        Args:
            category_scope: "OPERATIONAL", "PROJECT", or "AMBIGUOUS"
            confidence: Confidence score (0.0-1.0)
            signals: Context signals from detection
            text: Original text
        
        Returns:
            Tuple of (action, prompt):
            - action: "AUTO", "CONFIRM", or "ASK"
            - prompt: Message to send to user (None for AUTO)
        """
        
        # HIGH CONFIDENCE: Auto-classify
        if confidence >= CONFIDENCE_HIGH and category_scope in ["OPERATIONAL", "PROJECT"]:
            logger.info(f"HIGH confidence ({confidence:.2f}) -> AUTO classify as {category_scope}")
            return ("AUTO", None)
        
        # MEDIUM CONFIDENCE: Confirm with user
        if CONFIDENCE_MEDIUM <= confidence < CONFIDENCE_HIGH and category_scope in ["OPERATIONAL", "PROJECT"]:
            logger.info(f"MEDIUM confidence ({confidence:.2f}) -> CONFIRM with user")
            prompt = self._generate_confirmation_prompt(category_scope, signals, text)
            return ("CONFIRM", prompt)
        
        # LOW CONFIDENCE or AMBIGUOUS: Ask for clarification
        logger.info(f"LOW confidence ({confidence:.2f}) or AMBIGUOUS -> ASK user")
        prompt = self._generate_clarification_prompt(category_scope, signals, text)
        return ("ASK", prompt)
    
    def _generate_confirmation_prompt(
        self, 
        category_scope: str,
        signals: Dict,
        text: str
    ) -> str:
        """
        Generate natural confirmation prompt.
        
        Example:
            "✅ Ini untuk *Operational Kantor* (gaji staff/overhead), kan?
            
            Balas:
            1️⃣ Ya, Operational
            2️⃣ Bukan, untuk Project"
        """
        role = signals.get('role_detected', 'None')
        project_name = signals.get('project_name', 'None')
        
        if category_scope == "OPERATIONAL":
            context_hint = ""
            if 'OFFICE' in str(role):
                context_hint = f" (gaji {role.split(':')[-1]})" if ':' in str(role) else ""
            
            return f"""✅ Ini untuk *Operational Kantor*{context_hint}, kan?
(Gaji staff, listrik, wifi, dll)

Balas:
1️⃣ Ya, Operational
2️⃣ Bukan, untuk Project"""
        
        elif category_scope == "PROJECT":
            context_hint = ""
            if project_name and project_name != 'None':
                context_hint = f" (Project: {project_name})"
            elif 'FIELD' in str(role):
                context_hint = f" (fee tukang lapangan)"
            
            return f"""✅ Ini untuk *Project*{context_hint}, kan?
(Material, upah tukang, dll)

Balas:
1️⃣ Ya, Project
2️⃣ Bukan, Operational"""
        
        return "Confirm?"
    
    def _generate_clarification_prompt(
        self,
        category_scope: str,
        signals: Dict,
        text: str
    ) -> str:
        """
        Generate natural clarification prompt.
        
        Example:
            "🤔 Ini maksudnya gaji staff kantor atau bayar tukang project?
            
            1️⃣ Gaji Staff Kantor
               (Operational - gaji bulanan admin/karyawan)
            
            2️⃣ Fee/Upah Project
               (Butuh nama project)"
        """
        keyword = signals.get('keyword_match', {}).get('keyword', '')
        
        # Different prompts based on ambiguity type
        if 'gaji' in text.lower():
            return """🤔 Ini maksudnya gaji staff kantor atau bayar orang project?

1️⃣ *Gaji Staff Kantor*
   (Operational - gaji bulanan admin/karyawan)

2️⃣ *Fee/Upah Project*
   (Bayar tukang/pekerja lapangan)

Atau kasih detail lebih: _"gaji admin"_ atau _"gaji tukang Project X"_"""
        
        elif 'bon' in text.lower():
            return """🤔 Bon untuk apa nih?

1️⃣ *Kasbon Tukang Project*
   (Butuh nama project)

2️⃣ *Bon Kantor*
   (Konsumsi/keperluan kantor)

Atau jelaskan: _"bon tukang buat Project X"_ atau _"bon makan kantor"_"""
        
        elif 'bayar' in text.lower() or 'fee' in text.lower():
            return """🤔 Bayar untuk apa?

1️⃣ *Operational Kantor*
   (Listrik, wifi, gaji staff, dll)

2️⃣ *Project*
   (Material, upah tukang, ongkir)

Kasih detail: _"bayar PLN"_ atau _"bayar tukang Project X"_"""
        
        # Generic fallback
        return """🤔 Ini untuk *Operational Kantor* atau *Project*?

1️⃣ *Operational Kantor*
   (Gaji staff, listrik, wifi, ATK, dll)

2️⃣ *Project*
   (Material, upah tukang, transport ke site)

Balas 1 atau 2, atau kasih detail lebih"""


class ResponseParser:
    """
    Parse user responses to confirmation/clarification prompts.
    """
    
    def __init__(self):
        # Response patterns
        self.operational_patterns = [
            r'\b1\b',
            r'ya.*operational',
            r'operational',
            r'kantor',
            r'ya\b',
            r'benar',
            r'betul',
        ]
        
        self.project_patterns = [
            r'\b2\b',
            r'project',
            r'proyek',
            r'bukan.*operational',
            r'tidak.*operational',
        ]
    
    def parse_response(self, text: str) -> Optional[str]:
        """
        Parse user response to determine choice.
        
        Returns:
            "OPERATIONAL", "PROJECT", or None if unclear
        """
        import re
        text_lower = text.lower().strip()
        
        # Check operational patterns
        for pattern in self.operational_patterns:
            if re.search(pattern, text_lower):
                return "OPERATIONAL"
        
        # Check project patterns
        for pattern in self.project_patterns:
            if re.search(pattern, text_lower):
                return "PROJECT"
        
        return None


# ===================== TESTING =====================

if __name__ == "__main__":
    # Fix Windows console encoding
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    
    router = ConfidenceRouter()
    parser = ResponseParser()
    
    print("=== CONFIDENCE ROUTING TEST ===\n")
    
    test_cases = [
        {
            "name": "HIGH Confidence - Auto",
            "category": "OPERATIONAL",
            "confidence": 0.95,
            "signals": {"role_detected": "OFFICE:admin"},
            "text": "Gaji admin 5jt"
        },
        {
            "name": "MEDIUM Confidence - Confirm",
            "category": "PROJECT",
            "confidence": 0.75,
            "signals": {"role_detected": "FIELD:tukang", "project_name": "Wooftopia"},
            "text": "Gajian tukang Wooftopia 2jt"
        },
        {
            "name": "LOW Confidence - Ask",
            "category": "AMBIGUOUS",
            "confidence": 0.40,
            "signals": {"keyword_match": {"keyword": "gaji"}},
            "text": "Gajian 5jt"
        },
        {
            "name": "AMBIGUOUS Bon - Ask",
            "category": "AMBIGUOUS",
            "confidence": 0.35,
            "signals": {},
            "text": "Bon 500rb"
        }
    ]
    
    for test in test_cases:
        print(f"[{test['name']}]")
        print(f"Input: {test['text']}")
        print(f"Category: {test['category']} (Confidence: {test['confidence']:.2f})")
        
        action, prompt = router.route_decision(
            test['category'], 
            test['confidence'], 
            test['signals'],
            test['text']
        )
        
        print(f"Action: {action}")
        if prompt:
            print(f"Prompt:\n{prompt}")
        print("\n" + "="*70 + "\n")
    
    # Test response parsing
    print("=== RESPONSE PARSING TEST ===\n")
    
    test_responses = [
        ("1", "OPERATIONAL"),
        ("2", "PROJECT"),
        ("ya operational", "OPERATIONAL"),
        ("bukan, untuk project", "PROJECT"),
        ("iya", "OPERATIONAL"),
        ("kantor", "OPERATIONAL"),
        ("proyek", "PROJECT"),
        ("ga jelas", None),
    ]
    
    for response, expected in test_responses:
        result = parser.parse_response(response)
        status = "✓" if result == expected else "✗"
        print(f"{status} Input: '{response}' -> {result} (Expected: {expected})")
