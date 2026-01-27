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
    quoted_message_text: str = None,  # For context-aware classification
    sender_jid: str = None
) -> Optional[str]:
    """
    Process message through Smart Handler (Semantic Engine).
    """
    if not USE_LAYERS:
        return None
    
    try:
        # Map arguments to SmartHandler.process
        # process(text, chat_jid, sender_number, reply_message_id, has_media, sender_name)
        
        result = _smart_handler.process(
            text=text or (caption if media_url else ""),
            chat_jid=chat_id,
            sender_number=user_id, # Assuming user_id is sender_number
            reply_message_id=quoted_message_id,
            has_media=bool(media_url),
            sender_name=sender_name
        )
        
        # Analyze result
        action = result.get("action")
        
        if action == "IGNORE":
            return None # Signal main loop to ignore
            
        elif action == "REPLY":
            return result.get("response")
            
        elif action == "PROCESS":
            # If standard process, return None so it falls through to Main Loop logic
            # OR we can return a special signal if SmartHandler modified the text (normalization)
            # For now, let's allow fallthrough but maybe we should expose the normalized text?
            # The current main.py flow calls process_with_layers, if it returns string -> reply & stop.
            # If it returns None -> continue to legacy flow.
            # 
            # If normalizing, we ideally want to pass the normalized text back.
            # But specific signature of process_with_layers returns Optional[str] (response).
            #
            # If the user text was "woi bot catat makan 50rb"
            # Normalized: "catat makan 50rb"
            # If we fall through, main loop sees "woi bot..." and might fail or not be smart.
            # 
            # However, main.py calls ai_helper.extract_financial_data(text).
            # ai_helper.extract_from_text calls sanitize_input.
            # 
            # To truly integrate normalization, we might need to modify main.py to accept normalized text.
            # OR, since we claimed "Phase 1" complete, maybe we just handle complex cases here.
            # 
            # For "REVISION_REQUEST", SmartHandler handles it and returns "REPLY".
            # For "QUERY_STATUS", SmartHandler returns "PROCESS" (fallthrough to main.py /tanya or status).
            # For "STANDARD_TRANSACTION", SmartHandler returns "PROCESS".
            
            return None 

        return None
        
    except Exception as e:
        logger.error(f"Page processing failed: {e}")
        return None


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
