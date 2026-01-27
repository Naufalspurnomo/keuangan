"""
layers/__init__.py - 7-Layer Intelligence Pipeline Orchestrator

This module orchestrates the complete message processing pipeline
through all 7 layers of the intelligent architecture.

Architecture:
    Layer 0: Spam Filter & Rate Limiter
    Layer 1: Semantic Intent Classifier
    Layer 2: Context Assembly Engine  
    Layer 3: Adaptive AI Processor & Validation (uses ai_helper)
    Layer 4: State Machine Orchestrator
    Layer 5: Duplicate Detection Engine
    Layer 6: Storage & Wallet Mapping (uses sheets_helper)
    Layer 7: Feedback & Response Generation
"""

from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

# Configure logging
logger = logging.getLogger(__name__)


class ProcessingMode(Enum):
    """Message processing modes based on financial signal score."""
    SILENT = "silent"           # Score < 50: Ignore message
    TENTATIVE = "tentative"     # Score 50-69: Process with extra validation
    CONFIDENT = "confident"     # Score >= 70: Process with confidence


class Intent(Enum):
    """User intent categories."""
    RECORD_TRANSACTION = "record"
    REVISION_REQUEST = "revision"
    QUERY_STATUS = "query"
    ANSWER_PENDING = "answer"
    CANCEL_TRANSACTION = "cancel"
    CHITCHAT = "chitchat"
    CONVERSATIONAL_QUERY = "conversational"


@dataclass
class MessageContext:
    """Context object passed through the pipeline."""
    # Raw input
    user_id: str
    message_id: str
    text: str
    media_url: Optional[str] = None
    caption: Optional[str] = None
    is_group: bool = False
    chat_id: Optional[str] = None
    sender_name: Optional[str] = None
    quoted_message_id: Optional[str] = None
    quoted_message_text: Optional[str] = None  # Content of quoted message (for context analysis)
    
    # Context Detection (Stage 1) - from context_detector.py
    is_reply_to_bot: bool = False
    reply_context_type: Optional[str] = None  # 'TRANSACTION_REPORT', 'PENDING_QUESTION', etc
    addressed_score: int = 0  # 0-100 how likely message is for bot
    
    # Pre-filter result (Stage 2)
    pre_filter_result: Optional[Dict] = None
    skip_ai: bool = False  # True if pre-filter confident enough
    
    # Layer 0 output
    financial_score: int = 0
    processing_mode: ProcessingMode = ProcessingMode.SILENT
    
    # Layer 1 output
    intent: Optional[Intent] = None
    intent_confidence: float = 0.0
    
    # Layer 2 output
    linked_photo: Optional[Dict] = None
    pending_question: Optional[Dict] = None
    pending_context: Optional[Dict] = None  # For resuming pending transactions
    
    # Layer 3 output
    extracted_data: Optional[list] = None  # List of transactions
    validation_flags: list = field(default_factory=list)
    detected_company: Optional[str] = None
    extraction_error: Optional[str] = None
    
    # Layer 4 output
    current_state: Optional[str] = None
    selected_company: Optional[str] = None
    selected_dompet: Optional[str] = None
    
    # Layer 5 output
    duplicate_info: Optional[Dict] = None
    
    # Layer 6 output
    saved_transaction: Optional[Dict] = None
    save_error: Optional[str] = None
    
    # Layer 7 output
    response_message: Optional[str] = None


class LayerPipeline:
    """
    Main orchestrator for the 7-layer processing pipeline.
    
    Each layer processes the MessageContext and enriches it
    with additional data for downstream layers.
    """
    
    def __init__(self):
        # Lazy imports to avoid circular dependencies
        self._layer_0 = None
        self._layer_1 = None
        self._layer_2 = None
        self._layer_3 = None
        self._layer_4 = None
        self._layer_5 = None
        self._layer_6 = None
        self._layer_7 = None
    
    @property
    def layer_0(self):
        if self._layer_0 is None:
            from . import layer_0_spam_filter
            self._layer_0 = layer_0_spam_filter
        return self._layer_0
    
    @property
    def layer_1(self):
        if self._layer_1 is None:
            from . import layer_1_intent_classifier
            self._layer_1 = layer_1_intent_classifier
        return self._layer_1
    
    @property
    def layer_2(self):
        if self._layer_2 is None:
            from . import layer_2_context_engine
            self._layer_2 = layer_2_context_engine
        return self._layer_2
    
    @property
    def layer_3(self):
        if self._layer_3 is None:
            from . import layer_3_ai_processor
            self._layer_3 = layer_3_ai_processor
        return self._layer_3
    
    @property
    def layer_4(self):
        if self._layer_4 is None:
            from . import layer_4_state_machine
            self._layer_4 = layer_4_state_machine
        return self._layer_4
    
    @property
    def layer_5(self):
        if self._layer_5 is None:
            from . import layer_5_duplicate_detection
            self._layer_5 = layer_5_duplicate_detection
        return self._layer_5
    
    @property
    def layer_6(self):
        if self._layer_6 is None:
            from . import layer_6_storage
            self._layer_6 = layer_6_storage
        return self._layer_6
    
    @property
    def layer_7(self):
        if self._layer_7 is None:
            from . import layer_7_feedback
            self._layer_7 = layer_7_feedback
        return self._layer_7
    
    def process(self, ctx: MessageContext) -> Tuple[Optional[str], MessageContext]:
        """
        Process message through all layers with 3-stage context-aware pipeline.
        
        Args:
            ctx: MessageContext with raw input data
            
        Returns:
            Tuple of (response_message, enriched_context)
            response_message is None if bot should stay silent
        """
        try:
            # ============= STAGE 1: Context Detection =============
            # Import context detector
            from . import context_detector
            
            # Check if we have pending transaction for this user
            from services import state_manager
            pkey = state_manager.pending_key(ctx.user_id, ctx.chat_id)
            has_pending = state_manager.has_pending_transaction(pkey)
            
            # Determine if quoted message is from bot
            # For now, we check if quoted_message_text contains bot signatures
            is_quoted_from_bot = False
            if ctx.quoted_message_text:
                bot_signatures = ['✅', '❓', '❌', '⚠️', 'Transaksi Tercatat']
                is_quoted_from_bot = any(sig in ctx.quoted_message_text for sig in bot_signatures)
            
            # Get full context analysis
            full_context = context_detector.get_full_context(
                text=ctx.text,
                quoted_message_text=ctx.quoted_message_text,
                is_quoted_from_bot=is_quoted_from_bot,
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
                has_media=ctx.media_url is not None,
                has_pending=has_pending
            )
            
            # Populate context fields in ctx
            ctx.is_reply_to_bot = full_context['is_reply_to_bot']
            ctx.reply_context_type = full_context['reply_context_type']
            ctx.addressed_score = full_context['addressed_score']
            
            logger.debug(f"Context: is_reply_to_bot={ctx.is_reply_to_bot}, "
                        f"reply_type={ctx.reply_context_type}, addressed_score={ctx.addressed_score}")
            
            # Layer 0: Spam Filter
            ctx = self.layer_0.process(ctx)
            if ctx.processing_mode == ProcessingMode.SILENT:
                logger.debug(f"Layer 0: Message filtered (score={ctx.financial_score})")
                return None, ctx
            
            # Layer 1: Intent Classification
            ctx = self.layer_1.process(ctx)
            logger.info(f"Layer 1: Intent={ctx.intent}, Confidence={ctx.intent_confidence:.2f}")
            
            # Check for SILENT action from pre-filter (chitchat not addressed)
            if ctx.pre_filter_result and ctx.pre_filter_result.get('action') == 'SILENT':
                logger.info("Pre-filter: SILENT action (chitchat not addressed to bot)")
                return None, ctx
            
            # Layer 2: Context Assembly
            ctx = self.layer_2.process(ctx)
            
            # Check if this is resuming a pending transaction
            if ctx.pending_context:
                # Restore extracted data from pending
                ctx.extracted_data = ctx.pending_context.get('transactions', [])
                ctx.current_state = ctx.pending_context.get('pending_state', 'WAITING_COMPANY')
                logger.info(f"Layer 2: Resuming pending transaction, state={ctx.current_state}")
            
            # Layer 3: AI Extraction & Validation (only for new transactions)
            if not ctx.extracted_data and ctx.intent == Intent.RECORD_TRANSACTION:
                ctx = self.layer_3.process(ctx)
            
            # Layer 4: State Machine
            ctx = self.layer_4.process(ctx)
            
            # Layer 5: Duplicate Detection (if ready to save)
            if ctx.current_state == "READY_TO_SAVE":
                ctx = self.layer_5.process(ctx)
                # If no duplicate, move to confirmed
                if ctx.current_state == "READY_TO_SAVE":
                    ctx.current_state = "CONFIRMED_SAVE"
            
            # Layer 6: Storage (if confirmed)
            if ctx.current_state == "CONFIRMED_SAVE":
                ctx = self.layer_6.process(ctx)
            
            # Layer 7: Response Generation & Feedback
            ctx = self.layer_7.process(ctx)
            
            return ctx.response_message, ctx
            
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            # Generate error response
            ctx.response_message = f"❌ Terjadi kesalahan: {str(e)}"
            return ctx.response_message, ctx


# Global pipeline instance
_pipeline = None

def get_pipeline() -> LayerPipeline:
    """Get or create the global pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = LayerPipeline()
    return _pipeline


def process_message(
    user_id: str,
    message_id: str,
    text: str,
    media_url: str = None,
    caption: str = None,
    is_group: bool = False,
    chat_id: str = None,
    sender_name: str = None,
    quoted_message_id: str = None,
    quoted_message_text: str = None  # For context-aware classification
) -> Optional[str]:
    """
    Main entry point for message processing.
    
    Returns response message or None if bot should stay silent.
    """
    ctx = MessageContext(
        user_id=user_id,
        message_id=message_id,
        text=text,
        media_url=media_url,
        caption=caption,
        is_group=is_group,
        chat_id=chat_id,
        sender_name=sender_name,
        quoted_message_id=quoted_message_id,
        quoted_message_text=quoted_message_text
    )
    
    pipeline = get_pipeline()
    response, _ = pipeline.process(ctx)
    return response
