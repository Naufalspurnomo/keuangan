"""
layer_2_context_engine.py - Context Assembly Engine

Layer 2 of the 7-layer architecture. Manages context buffers to link
related messages (photos + commands, questions + answers).

Features:
- Visual Buffer: Photo/document memory with TTL
- Conversation Buffer: Q&A tracking
- Pending Transaction Stack: Multi-step transaction state
- Concurrent user isolation

Based on Grand Design Ultimate lines 327-590.
"""

import os
import json
import time
import threading
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

# Buffer TTLs
VISUAL_BUFFER_TTL = 300       # 5 minutes for photos
CONVERSATION_BUFFER_TTL = 180  # 3 minutes for pending questions
PENDING_STACK_TTL = 900       # 15 minutes for incomplete transactions

# Persistence
DATA_DIR = Path(os.getenv('DATA_DIR', 'data'))
BUFFER_FILE = DATA_DIR / 'context_buffers.json'


# ===================== DATA STRUCTURES =====================

@dataclass
class PhotoContext:
    """Stored photo metadata."""
    message_id: str
    media_url: str
    caption: Optional[str]
    timestamp: float
    processed: bool = False
    ocr_text: Optional[str] = None
    user_id: str = ""
    
    def is_expired(self) -> bool:
        return time.time() - self.timestamp > VISUAL_BUFFER_TTL


@dataclass
class PendingQuestion:
    """Bot's question awaiting user answer."""
    question_type: str  # SELECT_COMPANY, INPUT_PROJECT, CONFIRM_AMOUNT, etc.
    bot_message_id: str
    expected_pattern: str  # Regex for validation
    options: Optional[Dict[str, str]] = None
    context_data: Optional[Dict] = None
    timestamp: float = 0
    retry_count: int = 0
    
    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = time.time()
    
    def is_expired(self) -> bool:
        return time.time() - self.timestamp > CONVERSATION_BUFFER_TTL


@dataclass
class PendingTransaction:
    """Incomplete transaction state."""
    session_id: str
    user_id: str
    state: str  # WAITING_AMOUNT, WAITING_PROJECT, WAITING_COMPANY, etc.
    partial_data: Dict = field(default_factory=dict)
    original_message_id: str = ""
    state_history: List[str] = field(default_factory=list)
    timestamp_created: float = 0
    timestamp_updated: float = 0
    retry_count: int = 0
    max_retry: int = 3
    
    def __post_init__(self):
        now = time.time()
        if self.timestamp_created == 0:
            self.timestamp_created = now
        if self.timestamp_updated == 0:
            self.timestamp_updated = now
    
    def is_expired(self) -> bool:
        return time.time() - self.timestamp_updated > PENDING_STACK_TTL


# ===================== BUFFER STORAGE =====================

class ContextBuffers:
    """
    Thread-safe context buffer manager with persistence.
    
    Implements isolated buffers per user as per Grand Design.
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        
        # Visual Buffer: {user_id: [PhotoContext, ...]}
        self._visual_buffer: Dict[str, List[PhotoContext]] = {}
        
        # Conversation Buffer: {user_id: PendingQuestion}
        self._conversation_buffer: Dict[str, PendingQuestion] = {}
        
        # Pending Stack: {session_id: PendingTransaction}
        self._pending_stack: Dict[str, PendingTransaction] = {}
        
        # User to session mapping
        self._user_sessions: Dict[str, str] = {}
        
        # Load persisted data
        self._load()
    
    def _load(self) -> None:
        """Load buffers from disk."""
        try:
            if BUFFER_FILE.exists():
                with open(BUFFER_FILE, 'r') as f:
                    data = json.load(f)
                
                # Restore pending transactions (skip expired)
                for session_id, txn_data in data.get('pending_stack', {}).items():
                    txn = PendingTransaction(**txn_data)
                    if not txn.is_expired():
                        self._pending_stack[session_id] = txn
                        self._user_sessions[txn.user_id] = session_id
                
                logger.info(f"Loaded {len(self._pending_stack)} pending transactions")
        except Exception as e:
            logger.warning(f"Failed to load context buffers: {e}")
    
    def _save(self) -> None:
        """Persist buffers to disk."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            
            data = {
                'pending_stack': {
                    sid: asdict(txn) 
                    for sid, txn in self._pending_stack.items()
                    if not txn.is_expired()
                }
            }
            
            with open(BUFFER_FILE, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save context buffers: {e}")
    
    def _cleanup_expired(self) -> None:
        """Remove expired entries from all buffers."""
        with self._lock:
            # Cleanup visual buffer
            for user_id in list(self._visual_buffer.keys()):
                self._visual_buffer[user_id] = [
                    p for p in self._visual_buffer[user_id] if not p.is_expired()
                ]
                if not self._visual_buffer[user_id]:
                    del self._visual_buffer[user_id]
            
            # Cleanup conversation buffer
            for user_id in list(self._conversation_buffer.keys()):
                if self._conversation_buffer[user_id].is_expired():
                    del self._conversation_buffer[user_id]
            
            # Cleanup pending stack
            for session_id in list(self._pending_stack.keys()):
                if self._pending_stack[session_id].is_expired():
                    user_id = self._pending_stack[session_id].user_id
                    del self._pending_stack[session_id]
                    self._user_sessions.pop(user_id, None)
    
    # ===================== VISUAL BUFFER =====================
    
    def add_photo(
        self, 
        user_id: str, 
        message_id: str, 
        media_url: str, 
        caption: str = None
    ) -> None:
        """Store a photo in the visual buffer."""
        with self._lock:
            if user_id not in self._visual_buffer:
                self._visual_buffer[user_id] = []
            
            photo = PhotoContext(
                message_id=message_id,
                media_url=media_url,
                caption=caption,
                timestamp=time.time(),
                user_id=user_id
            )
            self._visual_buffer[user_id].append(photo)
            
            # Keep only last 5 photos per user
            self._visual_buffer[user_id] = self._visual_buffer[user_id][-5:]
            
            logger.debug(f"Added photo to buffer for user {user_id}")
    
    def find_recent_photo(
        self, 
        user_id: str, 
        within_seconds: int = 120,
        unprocessed_only: bool = True
    ) -> Optional[PhotoContext]:
        """
        Find most recent photo for user.
        
        Args:
            user_id: User to search for
            within_seconds: Time window
            unprocessed_only: Only return unprocessed photos
            
        Returns:
            PhotoContext or None
        """
        with self._lock:
            self._cleanup_expired()
            
            photos = self._visual_buffer.get(user_id, [])
            cutoff = time.time() - within_seconds
            
            for photo in reversed(photos):
                if photo.timestamp < cutoff:
                    continue
                if unprocessed_only and photo.processed:
                    continue
                return photo
            
            return None
    
    def find_any_recent_photo(
        self, 
        within_seconds: int = 120
    ) -> List[PhotoContext]:
        """Find all recent unprocessed photos (for ambiguity handling)."""
        with self._lock:
            self._cleanup_expired()
            
            cutoff = time.time() - within_seconds
            results = []
            
            for user_id, photos in self._visual_buffer.items():
                for photo in photos:
                    if photo.timestamp >= cutoff and not photo.processed:
                        results.append(photo)
            
            return results
    
    def mark_photo_processed(self, message_id: str, ocr_text: str = None) -> None:
        """Mark a photo as processed."""
        with self._lock:
            for photos in self._visual_buffer.values():
                for photo in photos:
                    if photo.message_id == message_id:
                        photo.processed = True
                        photo.ocr_text = ocr_text
                        return
    
    # ===================== CONVERSATION BUFFER =====================
    
    def set_pending_question(
        self,
        user_id: str,
        question_type: str,
        bot_message_id: str,
        expected_pattern: str = r'.*',
        options: Dict[str, str] = None,
        context_data: Dict = None
    ) -> None:
        """Store a pending question for user."""
        with self._lock:
            self._conversation_buffer[user_id] = PendingQuestion(
                question_type=question_type,
                bot_message_id=bot_message_id,
                expected_pattern=expected_pattern,
                options=options,
                context_data=context_data
            )
            logger.debug(f"Set pending question for user {user_id}: {question_type}")
    
    def get_pending_question(self, user_id: str) -> Optional[PendingQuestion]:
        """Get pending question for user."""
        with self._lock:
            self._cleanup_expired()
            return self._conversation_buffer.get(user_id)
    
    def clear_pending_question(self, user_id: str) -> None:
        """Clear pending question for user."""
        with self._lock:
            self._conversation_buffer.pop(user_id, None)
    
    def match_answer(self, user_id: str, answer: str) -> Optional[Dict]:
        """
        Try to match user answer with pending question.
        
        Returns:
            Dict with matched data or None if no match
        """
        import re
        
        with self._lock:
            pending = self.get_pending_question(user_id)
            if not pending:
                return None
            
            # Check if answer matches expected pattern
            if re.match(pending.expected_pattern, answer.strip()):
                # Valid answer!
                result = {
                    'question_type': pending.question_type,
                    'answer': answer.strip(),
                    'context_data': pending.context_data,
                }
                
                # If options provided, map answer to value
                if pending.options and answer.strip() in pending.options:
                    result['selected_value'] = pending.options[answer.strip()]
                
                self.clear_pending_question(user_id)
                return result
            
            return None
    
    # ===================== PENDING TRANSACTION STACK =====================
    
    def create_pending_transaction(
        self,
        user_id: str,
        initial_data: Dict = None
    ) -> PendingTransaction:
        """Create a new pending transaction session."""
        import uuid
        
        with self._lock:
            # Clear any existing session for this user
            old_session = self._user_sessions.get(user_id)
            if old_session:
                self._pending_stack.pop(old_session, None)
            
            session_id = str(uuid.uuid4())[:8]
            txn = PendingTransaction(
                session_id=session_id,
                user_id=user_id,
                state='INITIALIZED',
                partial_data=initial_data or {},
                state_history=['INITIALIZED']
            )
            
            self._pending_stack[session_id] = txn
            self._user_sessions[user_id] = session_id
            self._save()
            
            # Notify Layer 0 about active session
            from . import layer_0_spam_filter
            layer_0_spam_filter.set_active_session(user_id, {'session_id': session_id})
            
            logger.info(f"Created pending transaction {session_id} for user {user_id}")
            return txn
    
    def get_pending_transaction(self, user_id: str) -> Optional[PendingTransaction]:
        """Get pending transaction for user."""
        with self._lock:
            self._cleanup_expired()
            session_id = self._user_sessions.get(user_id)
            if session_id:
                return self._pending_stack.get(session_id)
            return None
    
    def update_pending_transaction(
        self,
        user_id: str,
        new_state: str = None,
        data_updates: Dict = None
    ) -> Optional[PendingTransaction]:
        """Update pending transaction state and data."""
        with self._lock:
            txn = self.get_pending_transaction(user_id)
            if not txn:
                return None
            
            if new_state:
                txn.state = new_state
                txn.state_history.append(new_state)
            
            if data_updates:
                txn.partial_data.update(data_updates)
            
            txn.timestamp_updated = time.time()
            self._save()
            
            logger.debug(f"Updated transaction {txn.session_id}: state={txn.state}")
            return txn
    
    def complete_pending_transaction(self, user_id: str) -> Optional[Dict]:
        """
        Complete and remove pending transaction.
        
        Returns:
            Final transaction data or None
        """
        with self._lock:
            txn = self.get_pending_transaction(user_id)
            if not txn:
                return None
            
            data = txn.partial_data.copy()
            
            # Cleanup
            session_id = self._user_sessions.pop(user_id, None)
            if session_id:
                self._pending_stack.pop(session_id, None)
            
            # Clear Layer 0 active session
            from . import layer_0_spam_filter
            layer_0_spam_filter.clear_active_session(user_id)
            
            self._save()
            logger.info(f"Completed transaction for user {user_id}")
            
            return data
    
    def cancel_pending_transaction(self, user_id: str) -> bool:
        """Cancel and remove pending transaction."""
        with self._lock:
            if user_id not in self._user_sessions:
                return False
            
            self.complete_pending_transaction(user_id)
            return True


# ===================== GLOBAL INSTANCE =====================

_buffers = None

def get_buffers() -> ContextBuffers:
    """Get or create global buffer instance."""
    global _buffers
    if _buffers is None:
        _buffers = ContextBuffers()
    return _buffers


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 2 processing: Context Assembly.
    
    Links photos with commands, matches answers with questions,
    and manages pending transaction state.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with linked context
    """
    from . import Intent
    
    buffers = get_buffers()
    user_id = ctx.user_id
    
    # If message has media, store in visual buffer
    if ctx.media_url:
        buffers.add_photo(
            user_id=user_id,
            message_id=ctx.message_id,
            media_url=ctx.media_url,
            caption=ctx.caption
        )
        logger.debug(f"Layer 2: Stored photo for user {user_id}")
    
    # Try to link with recent photo if this is a command without media
    if ctx.intent == Intent.RECORD_TRANSACTION and not ctx.media_url:
        recent_photo = buffers.find_recent_photo(user_id)
        if recent_photo:
            ctx.linked_photo = {
                'message_id': recent_photo.message_id,
                'media_url': recent_photo.media_url,
                'caption': recent_photo.caption,
                'ocr_text': recent_photo.ocr_text,
            }
            logger.info(f"Layer 2: Linked photo {recent_photo.message_id} to command")
    
    # Check for pending question answer
    if ctx.intent == Intent.ANSWER_PENDING or ctx.text:
        match = buffers.match_answer(user_id, ctx.text or "")
        if match:
            ctx.pending_question = match
            ctx.intent = Intent.ANSWER_PENDING
            logger.info(f"Layer 2: Matched answer to pending question: {match['question_type']}")
    
    # Get pending transaction state
    pending_txn = buffers.get_pending_transaction(user_id)
    if pending_txn:
        ctx.current_state = pending_txn.state
        ctx.extracted_data = pending_txn.partial_data.copy()
        logger.debug(f"Layer 2: Found pending transaction in state {pending_txn.state}")
    
    return ctx
