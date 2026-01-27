"""
layer_integration.py - Integrate 7-Layer Architecture with Existing Bot

This module provides a bridge between the new layer architecture and
the existing main.py logic. Use the USE_LAYER_ARCHITECTURE env var
to enable the new system.

Usage in main.py:
    from layer_integration import process_with_layers, USE_LAYERS
    
    if USE_LAYERS:
        result = process_with_layers(...)
        if result:
            send_reply(result)
            return
    # else fall through to existing logic
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Feature flag - DISABLED by default until layer system is fully tested
# Set USE_LAYER_ARCHITECTURE=true in .env to enable (NOT RECOMMENDED YET)
USE_LAYERS = True  # Enabled Semantic Engine


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
    Process message through 7-layer architecture.
    
    Args:
        user_id: User phone number or ID
        message_id: Message ID for tracking
        text: Message text content
        sender_name: Display name of sender
        media_url: Base64 data URL for images
        caption: Image caption (if media)
        is_group: Whether message is from group
        chat_id: Chat/group ID
        quoted_message_id: ID of quoted message (for replies)
        quoted_message_text: Text content of quoted message (for context analysis)
        sender_jid: Full sender JID for mentions
        
    Returns:
        Response message string, or None if bot should stay silent
    """
    if not USE_LAYERS:
        return None
    
    try:
        from layers import process_message, MessageContext, ProcessingMode, Intent
        
        # Create context and process through pipeline
        response = process_message(
            user_id=user_id,
            message_id=message_id,
            text=text or "",
            media_url=media_url,
            caption=caption,
            is_group=is_group,
            chat_id=chat_id,
            sender_name=sender_name,
            quoted_message_id=quoted_message_id,
            quoted_message_text=quoted_message_text
        )
        
        return response
        
    except ImportError as e:
        logger.error(f"Layer import failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Layer processing failed: {e}")
        # Return None to fall back to existing logic
        return None


def get_layer_status() -> Dict[str, Any]:
    """Get status of layer system for debugging."""
    status = {
        "enabled": USE_LAYERS,
        "layers_loaded": False,
        "buffers_active": False,
        "pending_count": 0,
        "learning_data": False
    }
    
    if not USE_LAYERS:
        return status
    
    try:
        from layers import get_pipeline
        from layers import layer_2_context_engine
        from layers import layer_7_feedback
        
        pipeline = get_pipeline()
        status["layers_loaded"] = pipeline is not None
        
        buffers = layer_2_context_engine.get_buffers()
        status["buffers_active"] = buffers is not None
        status["pending_count"] = len(buffers._pending_stack)
        
        status["learning_data"] = bool(layer_7_feedback._learned_patterns)
        
    except Exception as e:
        status["error"] = str(e)
    
    return status


# Quick test function
def test_layer_integration():
    """Quick test to verify layers are working."""
    print(f"USE_LAYERS = {USE_LAYERS}")
    
    if not USE_LAYERS:
        print("Set USE_LAYER_ARCHITECTURE=true in .env to enable")
        return False
    
    # Test basic flow
    response = process_with_layers(
        user_id="test_user",
        message_id="test_msg_001",
        text="beli semen 500rb",
        sender_name="Test"
    )
    
    print(f"Response: {response}")
    print(f"Status: {get_layer_status()}")
    
    return response is not None


if __name__ == "__main__":
    test_layer_integration()
