"""
layer_integration.py - Integrate Semantic Smart Handler with Existing Bot

This module provides a bridge between the new Smart Handler (Semantic Engine) and
the existing main.py logic. Use the USE_LAYER_ARCHITECTURE env var
to enable the new system.
"""

import os
import logging
from typing import Optional, Dict, Any

from handlers.smart_handler import SmartHandler

logger = logging.getLogger(__name__)

# Feature flag
USE_LAYERS = True  # Enabled Semantic Engine

# Initialize Handler
# We need a singleton-like access or init new every time? 
# SmartHandler is lightweight, ok to init.
# But StateManager wrapper needed.
# Since state_manager.py module has global functions, we can create a simple wrapper class 
# if SmartHandler expects an object with methods.
# The SmartHandler expects 'state_manager' object.
# Let's verify what SmartHandler expects:
#   self.state_manager.get_original_message_id(...)
#   self.state_manager.record_bot_interaction(...)
#   self.context_detector = ContextDetector(state_manager) -> detector calls state_manager.get_last_bot_interaction
#
# Our services/state_manager.py works with MODULAR functions.
# So we need a wrapper class to pass into SmartHandler.

class StateManagerWrapper:
    def get_original_message_id(self, bot_msg_id):
        from services.state_manager import get_original_message_id
        return get_original_message_id(bot_msg_id)
        
    def record_bot_interaction(self, user_id, chat_id, interaction_type):
        from services.state_manager import record_bot_interaction
        record_bot_interaction(user_id, chat_id, interaction_type)
        
    def get_last_bot_interaction(self, user_id, chat_id):
        from services.state_manager import get_last_bot_interaction
        return get_last_bot_interaction(user_id, chat_id)
        
    def has_pending_transaction(self, pkey):
        from services.state_manager import has_pending_transaction
        return has_pending_transaction(pkey)

_smart_handler = SmartHandler(StateManagerWrapper())


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
) -> tuple:
    """
    Process message through Smart Handler (Semantic Engine).
    
    Returns: (action, response, intent, extra_data)
    - action: "IGNORE", "REPLY", "PROCESS"
    - response: str (the text to reply with, or normalized text for PROCESS)
    - intent: str (The intent detected by AI)
    - extra_data: dict (category_scope, extracted_data, etc.)
    
    v2.0: Now returns 4-tuple with extra_data for category_scope routing.
    """
    if not USE_LAYERS:
        return None, None, None, {}
    
    try:
        # Map arguments to SmartHandler.process
        result = _smart_handler.process(
            text=text or (caption if media_url else ""),
            chat_jid=chat_id,
            sender_number=user_id,
            reply_message_id=quoted_message_id,
            has_media=bool(media_url),
            sender_name=sender_name,
            quoted_message_text=quoted_message_text,
            has_visual=has_visual
        )
        
        action = result.get("action")
        response = result.get("response")
        intent = result.get("intent")
        
        # Build extra data dict
        extra_data = {
            "category_scope": result.get("category_scope", "UNKNOWN"),
            "extracted_data": result.get("extracted_data", {}),
            "layer_response": result.get("layer_response"),
        }
        
        # If normalizing, return the normalized text for PROCESS
        if action == "PROCESS" and result.get("normalized_text"):
            return "PROCESS", result.get("normalized_text"), intent, extra_data
        
        # If PROCESS but using layer_response
        if action == "PROCESS" and result.get("layer_response"):
            return "PROCESS", result.get("layer_response"), intent, extra_data
            
        return action, response, intent, extra_data
        
    except Exception as e:
        logger.error(f"Layer processing failed: {e}")
        return None, None, None, {}


def get_layer_status() -> Dict[str, Any]:
    """Get status of layer system for debugging."""
    return {
        "enabled": USE_LAYERS,
        "engine": "SmartHandler (Semantic)"
    }


# Quick test function
def test_layer_integration():
    """Quick test."""
    print(f"USE_LAYERS = {USE_LAYERS}")
    
    # Test
    response = process_with_layers(
        user_id="62812345678",
        message_id="msg1",
        text="woi bot pengeluaran hari ini berapee",
        sender_name="Test",
        chat_id="g1@g.us"
    )
    print(f"Test 'woi bot...': Result={response} (Expected None for PROCESS or Reply string)")

if __name__ == "__main__":
    test_layer_integration()
