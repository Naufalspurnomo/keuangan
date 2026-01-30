"""
layer_integration_v2.py - Enhanced Layer Integration with Context Detection

ULTRA-ROBUST integration of:
1. Multi-layer context detection (OPERATIONAL vs PROJECT)
2. Confidence-based routing (Auto / Confirm / Ask)
3. Pattern learning from user confirmations
4. Natural disambiguation prompts

This replaces the old layer_integration.py with enhanced capabilities.

Author: Naufal
Version: 2.0 - Ultra-Robust Context Awareness
"""

import os
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Feature flag
USE_ENHANCED_LAYERS = True

# Import enhanced components
from utils.context_detector import ContextDetector
from utils.confidence_router import ConfidenceRouter, ResponseParser
from services.pattern_learner import check_learned_pattern, record_user_confirmation


class EnhancedLayerProcessor:
    """
    Enhanced layer processor with context detection and confidence routing.
    """
    
    def __init__(self):
        self.context_detector = ContextDetector()
        self.confidence_router = ConfidenceRouter()
        self.response_parser = ResponseParser()
    
    def process_message(
        self,
        text: str,
        user_id: str,
        chat_id: str,
        is_group: bool = False,
        **kwargs
    ) -> Dict:
        """
        Process message through enhanced layers.
        
        Returns:
            {
                "action": "AUTO" | "CONFIRM" | "ASK" | "IGNORE",
                "category_scope": "OPERATIONAL" | "PROJECT" | "AMBIGUOUS",
                "confidence": float,
                "prompt": str or None,  # User prompt if CONFIRM/ASK
                "context_analysis": dict,  # Full context analysis
                "learned_boost": float,  # Boost from learned patterns
            }
        """
        
        # Step 1: Check learned patterns first
        learned = check_learned_pattern(text)
        learned_boost = 0.0
        
        if learned:
            logger.info(f"Pattern match found: {learned['category_scope']} (boost: {learned['confidence_boost']:.2f})")
            learned_boost = learned['confidence_boost']
        
        # Step 2: Multi-layer context detection
        context_analysis = self.context_detector.detect_context(text)
        
        category_scope = context_analysis.get('category_scope')
        base_confidence = context_analysis.get('confidence', 0.0)
        signals = context_analysis.get('signals', {})
        reasoning = context_analysis.get('reasoning', '')
        
        # Step 3: Apply learned pattern boost
        final_confidence = min(1.0, base_confidence + learned_boost)
        
        # If learned pattern overrides ambiguous detection
        if learned and category_scope == "AMBIGUOUS":
            category_scope = learned['category_scope']
            final_confidence = max(final_confidence, 0.70)  # Boost to at least medium
            reasoning += f" [Learned pattern: {learned['pattern']}]"
        
        logger.info(f"Context: {category_scope} (Confidence: {final_confidence:.2f}, Boost: +{learned_boost:.2f})")
        logger.info(f"Reasoning: {reasoning}")
        
        # Step 4: Confidence-based routing
        action, prompt = self.confidence_router.route_decision(
            category_scope,
            final_confidence,
            signals,
            text
        )
        
        return {
            "action": action,
            "category_scope": category_scope,
            "confidence": final_confidence,
            "prompt": prompt,
            "context_analysis": context_analysis,
            "learned_boost": learned_boost,
            "reasoning": reasoning,
        }
    
    def process_user_response(
        self,
        text: str,
        pending_category: str = None
    ) -> Optional[str]:
        """
        Process user response to confirmation/clarification prompt.
        
        Args:
            text: User response text
            pending_category: The category that was suggested (for learning)
        
        Returns:
            "OPERATIONAL", "PROJECT", or None if unclear
        """
        parsed = self.response_parser.parse_response(text)
        
        if parsed:
            logger.info(f"User response parsed: {parsed}")
        
        return parsed
    
    def record_confirmation(
        self,
        original_text: str,
        confirmed_category: str
    ):
        """
        Record user confirmation for pattern learning.
        
        Args:
            original_text: Original transaction text
            confirmed_category: User-confirmed category
        """
        record_user_confirmation(original_text, confirmed_category)
        logger.info(f"Recorded confirmation: '{original_text}' -> {confirmed_category}")


# =============================================================================
# PUBLIC API - Backward Compatible with existing layer_integration.py
# =============================================================================

# Global processor instance
_processor = EnhancedLayerProcessor()


def process_with_enhanced_layers(
    text: str,
    user_id: str,
    chat_id: str,
    is_group: bool = False,
    **kwargs
) -> Dict:
    """
    Process message with enhanced context detection.
    
    This is the NEW enhanced version of process_with_layers().
    
    Returns:
        {
            "action": "AUTO" | "CONFIRM" | "ASK" | "IGNORE",
            "category_scope": "OPERATIONAL" | "PROJECT" | "AMBIGUOUS",
            "confidence": float,
            "prompt": str or None,
            "context_analysis": dict,
        }
    """
    if not USE_ENHANCED_LAYERS:
        return {"action": "IGNORE"}
    
    try:
        return _processor.process_message(
            text=text,
            user_id=user_id,
            chat_id=chat_id,
            is_group=is_group,
            **kwargs
        )
    except Exception as e:
        logger.error(f"Enhanced layer processing failed: {e}", exc_info=True)
        return {"action": "IGNORE"}


def parse_user_response(text: str, pending_category: str = None) -> Optional[str]:
    """
    Parse user response to confirmation/clarification.
    
    Returns:
        "OPERATIONAL", "PROJECT", or None
    """
    return _processor.process_user_response(text, pending_category)


def learn_from_confirmation(original_text: str, confirmed_category: str):
    """
    Record user confirmation for future pattern learning.
    """
    _processor.record_confirmation(original_text, confirmed_category)


def get_enhanced_layer_status() -> Dict[str, Any]:
    """Get status of enhanced layer system."""
    return {
        "enabled": USE_ENHANCED_LAYERS,
        "engine": "Enhanced Context Detection v2.0",
        "components": [
            "Multi-Layer Context Detector",
            "Confidence Router",
            "Pattern Learner",
            "Natural Disambiguation"
        ]
    }


# =============================================================================
# BACKWARD COMPATIBILITY WRAPPER (for main.py)
# =============================================================================

def process_with_layers(
    user_id: str,
    message_id: str,
    text: str,
    sender_name: str = "User",
    media_url: str = None,
    caption: str = None,
    is_group: bool = False,
    chat_id: str = None,
    quoted_message_id: str = None,
    quoted_message_text: str = None,
    sender_jid: str = None,
    has_visual: bool = False
) -> Tuple[str, str, str, Dict]:
    """
    BACKWARD COMPATIBLE wrapper for old process_with_layers signature.
    
    Now uses Enhanced Context Detection v2.0 under the hood.
    
    Returns: (action, response, intent, extra_data)
    - action: "IGNORE", "REPLY", "PROCESS" 
    - response: str (the text to reply with, or normalized text for PROCESS)
    - intent: str (The intent detected - for now just "RECORD_TRANSACTION")
    - extra_data: dict (category_scope, context_analysis, etc.)
    """
    if not USE_ENHANCED_LAYERS:
        return ("PROCESS", text, "RECORD_TRANSACTION", {})
    
    try:
        # Process with enhanced layers
        result = process_with_enhanced_layers(
            text=text or caption or "",
            user_id=user_id,
            chat_id=chat_id or user_id,
            is_group=is_group
        )
        
        action_map = {
            "AUTO": "PROCESS",      # High confidence -> proceed
            "CONFIRM": "REPLY",     # Ask confirmation
            "ASK": "REPLY",         # Ask clarification
            "IGNORE": "IGNORE"
        }
        
        enhanced_action = result.get('action', 'IGNORE')
        compat_action = action_map.get(enhanced_action, "PROCESS")
        
        # Build response
        prompt = result.get('prompt')
        
        # Extra data for routing
        extra_data = {
            "category_scope": result.get('category_scope', 'UNKNOWN'),
            "confidence": result.get('confidence', 0.0),
            "context_analysis": result.get('context_analysis', {}),
            "enhanced_action": enhanced_action,  # Original action
        }
        
        if compat_action == "REPLY" and prompt:
            # Need user interaction
            return (compat_action, prompt, "NEED_CLARIFICATION", extra_data)
        
        # Default: PROCESS
        return ("PROCESS", text, "RECORD_TRANSACTION", extra_data)
        
    except Exception as e:
        logger.error(f"Layer processing failed: {e}", exc_info=True)
        return ("PROCESS", text, "RECORD_TRANSACTION", {})



# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    
    print("=" * 80)
    print("ENHANCED LAYER INTEGRATION TEST")
    print("=" * 80)
    print()
    
    test_cases = [
        ("Gaji admin bulan Januari 5jt", "Should AUTO OPERATIONAL"),
        ("Gajian tukang Wooftopia 2jt", "Should AUTO/CONFIRM PROJECT"),
        ("Gajian 5jt", "Should ASK (ambiguous)"),
        ("Bon 500rb", "Should ASK (ambiguous)"),
        ("Bayar PLN 1.5jt", "Should AUTO OPERATIONAL"),
        ("Beli semen buat Taman Indah 500rb", "Should AUTO PROJECT"),
    ]
    
    for text, expected in test_cases:
        print(f"Input: '{text}'")
        print(f"Expected: {expected}")
        
        result = process_with_enhanced_layers(
            text=text,
            user_id="test_user",
            chat_id="test_chat"
        )
        
        print(f"  -> Action: {result['action']}")
        print(f"  -> Category: {result['category_scope']} (Confidence: {result['confidence']:.2f})")
        print(f"  -> Reasoning: {result.get('reasoning', 'N/A')}")
        
        if result.get('prompt'):
            print(f"  -> Prompt:\n{result['prompt']}")
        
        print("\n" + "="*80 + "\n")
    
    # Test user response parsing
    print("USER RESPONSE PARSING TEST\n")
    
    test_responses = [
        ("1", "OPERATIONAL"),
        ("2", "PROJECT"),
        ("ya", "OPERATIONAL"),
    ]
    
    for response, expected in test_responses:
        parsed = parse_user_response(response)
        status = "✓" if parsed == expected else "✗"
        print(f"{status} '{response}' -> {parsed} (Expected: {expected})")
