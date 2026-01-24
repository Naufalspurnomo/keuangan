"""
layer_2_context_engine.py - Context Assembly Engine

Layer 2 of the 7-layer architecture. Manages context buffers
and integrates with existing state_manager for pending transactions.

Features:
- Photo buffer for visual context
- Integration with services.state_manager for pending transactions
- Answer matching for pending questions
- Session continuity

Based on Grand Design Ultimate lines 326-474.
"""

import os
import json
import logging
import re
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ===================== BUFFER CONFIGURATION =====================

DATA_DIR = Path(os.getenv('DATA_DIR', 'data'))
CONTEXT_FILE = DATA_DIR / 'context_buffers.json'

PHOTO_TTL_SECONDS = 300  # 5 minutes
PENDING_TTL_SECONDS = 900  # 15 minutes


# ===================== CONTEXT BUFFERS =====================

class ContextBuffers:
    """Manages context buffers for the pipeline."""
    
    def __init__(self):
        self._photo_buffer: Dict[str, Dict] = {}  # user_id -> photo data
        self._pending_stack: Dict[str, Dict] = {}  # pkey -> pending transaction
        self._load_buffers()
    
    def _load_buffers(self):
        """Load buffers from disk."""
        try:
            if CONTEXT_FILE.exists():
                with open(CONTEXT_FILE, 'r') as f:
                    data = json.load(f)
                    self._pending_stack = data.get('pending', {})
                    # Don't restore photo buffer (it's short-lived)
        except Exception as e:
            logger.warning(f"Failed to load context buffers: {e}")
    
    def _save_buffers(self):
        """Save pending stack to disk."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONTEXT_FILE, 'w') as f:
                json.dump({
                    'pending': self._pending_stack,
                    'saved_at': datetime.now().isoformat()
                }, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save context buffers: {e}")
    
    # Photo Buffer
    def add_photo(self, user_id: str, chat_id: str, message_id: str, media_url: str):
        """Add photo to buffer for later processing."""
        key = f"{chat_id}:{user_id}" if chat_id else user_id
        self._photo_buffer[key] = {
            'media_url': media_url,
            'message_id': message_id,
            'timestamp': datetime.now().isoformat()
        }
        logger.info(f"Photo buffered for {key}")
    
    def find_photo(self, user_id: str, chat_id: str) -> Optional[Dict]:
        """Find recent photo from user in chat."""
        key = f"{chat_id}:{user_id}" if chat_id else user_id
        photo = self._photo_buffer.get(key)
        
        if photo:
            # Check TTL
            ts = datetime.fromisoformat(photo['timestamp'])
            if (datetime.now() - ts).total_seconds() < PHOTO_TTL_SECONDS:
                return photo
            else:
                # Expired
                self._photo_buffer.pop(key, None)
        
        return None
    
    def clear_photo(self, user_id: str, chat_id: str):
        """Clear photo from buffer."""
        key = f"{chat_id}:{user_id}" if chat_id else user_id
        self._photo_buffer.pop(key, None)
    
    # Pending Transactions
    def set_pending(self, user_id: str, chat_id: str, data: Dict):
        """Set pending transaction data."""
        key = f"{chat_id}:{user_id}" if chat_id else user_id
        data['created_at'] = datetime.now().isoformat()
        self._pending_stack[key] = data
        self._save_buffers()
        logger.info(f"Pending transaction set for {key}")
    
    def get_pending(self, user_id: str, chat_id: str) -> Optional[Dict]:
        """Get pending transaction if exists and not expired."""
        key = f"{chat_id}:{user_id}" if chat_id else user_id
        pending = self._pending_stack.get(key)
        
        if pending:
            ts_str = pending.get('created_at', '')
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if (datetime.now() - ts).total_seconds() > PENDING_TTL_SECONDS:
                        # Expired
                        self._pending_stack.pop(key, None)
                        self._save_buffers()
                        return None
                except:
                    pass
            return pending
        
        return None
    
    def clear_pending(self, user_id: str, chat_id: str):
        """Clear pending transaction."""
        key = f"{chat_id}:{user_id}" if chat_id else user_id
        self._pending_stack.pop(key, None)
        self._save_buffers()
    
    # Pending Questions
    def set_pending_question(self, user_id: str, question_type: str, 
                            bot_message_id: str, expected_pattern: str = None,
                            context_data: Dict = None):
        """Set pending question waiting for user answer."""
        key = user_id
        self._pending_stack[f"question:{key}"] = {
            'question_type': question_type,
            'bot_message_id': bot_message_id,
            'expected_pattern': expected_pattern,
            'context_data': context_data,
            'created_at': datetime.now().isoformat()
        }
        self._save_buffers()
    
    def get_pending_question(self, user_id: str) -> Optional[Dict]:
        """Get pending question for user."""
        return self._pending_stack.get(f"question:{user_id}")
    
    def clear_pending_question(self, user_id: str):
        """Clear pending question."""
        self._pending_stack.pop(f"question:{user_id}", None)
        self._save_buffers()


# Global buffer instance
_buffers = None


def get_buffers() -> ContextBuffers:
    """Get or create global buffer instance."""
    global _buffers
    if _buffers is None:
        _buffers = ContextBuffers()
    return _buffers


# ===================== ANSWER MATCHING =====================

def match_answer_to_question(text: str, pending_question: Dict) -> bool:
    """Check if text matches expected answer pattern."""
    if not pending_question:
        return False
    
    expected_pattern = pending_question.get('expected_pattern')
    if not expected_pattern:
        return True  # No specific pattern, any text matches
    
    try:
        return bool(re.match(expected_pattern, text.strip(), re.IGNORECASE))
    except:
        return False


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 2 processing: Context Assembly.
    
    Manages photo buffers and pending transaction context.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with context data
    """
    from . import Intent
    
    buffers = get_buffers()
    
    # Check for linked photo (user sent text after image)
    if not ctx.media_url:
        photo = buffers.find_photo(ctx.user_id, ctx.chat_id)
        if photo and ctx.intent == Intent.RECORD_TRANSACTION:
            ctx.linked_photo = photo
            ctx.media_url = photo['media_url']
            buffers.clear_photo(ctx.user_id, ctx.chat_id)
            logger.info("Layer 2: Linked recent photo to text message")
    
    # If message has photo, buffer it
    if ctx.media_url and not ctx.text:
        buffers.add_photo(ctx.user_id, ctx.chat_id, ctx.message_id, ctx.media_url)
        logger.info("Layer 2: Buffered photo, waiting for text")
    
    # Check for pending transaction (resuming flow)
    pending = buffers.get_pending(ctx.user_id, ctx.chat_id)
    if pending:
        logger.info(f"Layer 2: Found pending transaction, state={pending.get('pending_state')}")
        ctx.pending_context = pending
        
        # If user cancelling, clear pending
        if ctx.intent == Intent.CANCEL_TRANSACTION:
            buffers.clear_pending(ctx.user_id, ctx.chat_id)
            ctx.pending_context = None
    
    # Check for pending question
    pending_q = buffers.get_pending_question(ctx.user_id)
    if pending_q:
        ctx.pending_question = pending_q
        if ctx.intent == Intent.ANSWER_PENDING:
            if match_answer_to_question(ctx.text or '', pending_q):
                logger.info("Layer 2: Answer matches pending question")
                buffers.clear_pending_question(ctx.user_id)
    
    # Also integrate with existing state_manager
    try:
        from services.state_manager import (
            get_pending_transactions,
            pending_key as sm_pending_key,
            get_pending_key_from_message
        )
        
        # Check if there's a pending in state_manager
        pkey = sm_pending_key(ctx.user_id, ctx.chat_id)
        sm_pending = get_pending_transactions(pkey)
        
        if sm_pending and not ctx.pending_context:
            # State manager has pending, use it
            ctx.pending_context = sm_pending
            logger.info("Layer 2: Found pending in state_manager")
        
        # Check quoted message for delegation
        if ctx.quoted_message_id and ctx.is_group:
            mapped_pkey = get_pending_key_from_message(ctx.quoted_message_id)
            if mapped_pkey:
                mapped_pending = get_pending_transactions(mapped_pkey)
                if mapped_pending:
                    ctx.pending_context = mapped_pending
                    logger.info("Layer 2: Found pending via quoted message reply")
    
    except ImportError:
        logger.debug("Layer 2: state_manager not available")
    except Exception as e:
        logger.warning(f"Layer 2: state_manager integration error: {e}")
    
    return ctx
