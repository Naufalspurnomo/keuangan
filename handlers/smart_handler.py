"""
handlers/smart_handler.py - Smart Message Handler v2.0
Orchestrates all intelligence layers (Semantic Engine).

v2.0 Improvements:
- Added amount pattern detection for smarter triggers
- Handles TRANSFER_FUNDS intent
- Improved ambient talk filtering with rule-based overrides
- Better integration with ContextDetector for addressed_score
"""

import logging
import re
from difflib import SequenceMatcher
from config.constants import Commands, OPERATIONAL_KEYWORDS

from utils.amounts import has_amount_pattern
from utils.groq_analyzer import (
    GroqContextAnalyzer, should_quick_filter,
    is_likely_past_tense, is_likely_future_plan,
    is_casual_bot_mention
)
from utils.semantic_matcher import find_matching_item, extract_revision_entities
from layers.context_detector import get_full_context, record_interaction
from security import secure_log
from ai_helper import groq_client
from sheets_helper import update_transaction_amount  # Fixed missing import

logger = logging.getLogger(__name__)


def pending_key(user_id: str, chat_id: str = None) -> str:
    if chat_id:
        return f"{chat_id}:{user_id}"
    return user_id


class SmartHandler:
    def __init__(self, state_manager):
        self.state_manager = state_manager
        
    def process(self, text: str, chat_jid: str, sender_number: str, 
                reply_message_id: str = None, has_media: bool = False,
                sender_name: str = "User", quoted_message_text: str = None,
                has_visual: bool = False) -> dict:
        
        # 0. EXPLICIT COMMAND BYPASS
        if text.strip().startswith('/'):
            return {"action": "PROCESS", "intent": "COMMAND", "normalized_text": text}

        # 1. Reply Logic
        original_tx_id = None
        is_reply_to_bot = False
        if reply_message_id:
            original_tx_id = self.state_manager.get_original_message_id(reply_message_id)
            if original_tx_id:
                is_reply_to_bot = True
        
        # 2. Build Context (Enhanced with ContextDetector)
        full_ctx = get_full_context(
            text=text,
            quoted_message_text=quoted_message_text,
            is_quoted_from_bot=is_reply_to_bot,
            user_id=sender_number,
            chat_id=chat_jid,
            has_media=has_media,
            has_pending=self.state_manager.has_pending_transaction(pending_key(sender_number, chat_jid)),
            has_visual=has_visual
        )
        
        context = {
            "chat_type": "GROUP" if chat_jid.endswith("@g.us") else "PRIVATE",
            "is_reply_to_bot": is_reply_to_bot,
            "addressed_score": full_ctx.get('addressed_score', 0),
            "mention_type": full_ctx.get('mention_type'),
            "reply_context_type": full_ctx.get('reply_context_type'),
        }
        
        message = {
            "text": text,
            "sender": sender_name,
            "has_media": has_media,
            "is_reply_to_bot": is_reply_to_bot
        }

        # 3. Quick Filter (Rule Based)
        quick = should_quick_filter(message)
        if quick == "IGNORE":
            if not has_media:
                return {"action": "IGNORE"}
             

        # ============================================================
        # 🔥 SMART FILTER V4: Enhanced Anti-Spam
        # ============================================================
        
        is_group = chat_jid.endswith("@g.us")
        score = context.get('addressed_score', 0)
        
        # CHECK 1: Casual bot mention?
        if is_casual_bot_mention(text):
            secure_log("DEBUG", f"Casual bot mention, ignoring: {text[:30]}...")
            return {"action": "IGNORE"}
        
        # CHECK 2: Does message have amount pattern?
        has_amount = has_amount_pattern(text)
        
        # CHECK 3: Is it past tense (action happened)?
        is_past = is_likely_past_tense(text)
        
        # CHECK 4: Is it future plan (NOT a transaction)?
        is_future = is_likely_future_plan(text)
        
        # CHECK 5: Finance keywords
        finance_keywords = [
            "beli", "bayar", "transfer", "lunas", "dp", "biaya", "ongkir", 
            "saldo", "uang", "dana", "keluar", "masuk", "total", "rekap", 
            "hutang", "tagihan", "invoice", "nota", "struk", "jajan",
            "catat", "tulis", "input", "rekam", "masukin", "simpan",
            "cek", "lihat", "tanya", "info", "help",
            "fee", "gaji", "honor", "upah", "project", "projek", "anggaran"
        ]
        
        text_lower = text.lower()
        
        # Combined keywords
        all_keywords = finance_keywords + list(OPERATIONAL_KEYWORDS)
        has_finance_keyword = any(k in text_lower for k in all_keywords)
        
        # Is this likely a financial transaction report?
        is_likely_transaction = (
            has_amount and 
            (is_past or has_finance_keyword) and 
            not is_future
        )
        
        # In Group + Low Score: Apply stricter filter
        if is_group and score < 40:
            # STRICT RULE: Must have amount pattern OR be high-value query
            if not has_amount and not has_media:
                # Check if this is a valid query (like "/status", "/saldo")
                if not text.startswith('/') and not any(q in text_lower for q in ['status', 'saldo', 'laporan', 'cek']):
                    if quick != "PROCESS":
                        secure_log("DEBUG", f"Group Ignore (no transactional signal): {text[:30]}...")
                        return {"action": "IGNORE"}
            
            # Log when we "auto-sambar"
            if is_likely_transaction:
                secure_log("INFO", f"💎 Auto-Sambar: amount={has_amount}, past={is_past}")
        else:
            # Private or addressed chat: still ignore low-signal chatter
            if not has_amount and not has_media and not has_finance_keyword and not text.startswith('/'):
                if quick != "PROCESS" and score < 20:
                    secure_log("DEBUG", f"Ignore low-signal message: {text[:30]}...")
                    return {"action": "IGNORE"}

        # ============================================================

        # 4. AI Analysis (Groq)
        analyzer = GroqContextAnalyzer(groq_client)
        
        # Send context hints to AI
        context['is_ambient'] = (score < 40)
        
        analysis = analyzer.analyze_message(message, context)
        
        if not analysis.get('should_respond', False):
            return {"action": "IGNORE"}
             
        intent = analysis.get('intent', 'UNKNOWN')
        extracted = analysis.get('extracted_data', {})
        category_scope = analysis.get('category_scope', 'UNKNOWN')
        
        # Record Interaction only if we respond
        record_interaction(sender_number, chat_jid)
        self.state_manager.record_bot_interaction(sender_number, chat_jid, intent)

        # 5. Routing Intents (EXPANDED)
        if intent == "RATE_LIMIT":
            return {"action": "IGNORE"}

        elif intent == "IGNORE":
            return {"action": "IGNORE"}

        elif intent == "REVISION_REQUEST":
            hint = extracted.get('item_hint')
            amount = extracted.get('new_amount')
            return self.handle_revision_ai(hint, amount, reply_message_id, original_tx_id, chat_jid)

        elif intent == "QUERY_STATUS":
            return {
                "action": "PROCESS",
                "intent": "QUERY_STATUS",
                "normalized_text": text,
                "layer_response": extracted.get('search_query', text)
            }
        
        elif intent == "TRANSFER_FUNDS":
            # NEW: Handle internal wallet transfers
            return {
                "action": "PROCESS",
                "intent": "TRANSFER_FUNDS",
                "normalized_text": text,
                "layer_response": text,
                "extracted_data": {
                    "source_wallet": extracted.get('source_wallet'),
                    "destination_wallet": extracted.get('destination_wallet'),
                    "amount": extracted.get('amount')
                }
            }
            
        elif intent == "RECORD_TRANSACTION":
            clean_text = extracted.get('clean_text', text)
            if clean_text:
                similarity = SequenceMatcher(None, clean_text.lower(), text.lower()).ratio()
                if clean_text.lower() not in text.lower() and similarity < 0.35:
                    secure_log(
                        "WARNING",
                        f"Clean text mismatch ('{clean_text[:30]}...'), fallback to original text"
                    )
                    clean_text = text
            
            return {
                "action": "PROCESS",
                "intent": "RECORD_TRANSACTION",
                "normalized_text": clean_text,
                "layer_response": clean_text,
                "category_scope": category_scope  # Pass to main.py for routing
            }

        elif intent == "CONVERSATIONAL_QUERY":
            return {
                "action": "REPLY",
                "response": analysis.get('conversational_response', "Halo! Ada yang bisa saya bantu?")
            }
             
        # Default: Process anyway
        return {
            "action": "PROCESS",
            "intent": intent, 
            "normalized_text": text,
            "category_scope": category_scope
        }

    def handle_revision_ai(self, hint, amount, reply_message_id, original_tx_id, chat_jid) -> dict:
        """Handle AI-detected revision request."""
        # If no original_tx_id from reply, try to get last bot message
        if not original_tx_id:
            from services.state_manager import get_last_bot_report, get_original_message_id
            last_bot_msg_id = get_last_bot_report(chat_jid)
            if last_bot_msg_id:
                original_tx_id = get_original_message_id(last_bot_msg_id)
                 
        if not original_tx_id:
            return {"action": "REPLY", "response": "💡 Reply pesan laporan untuk merevisi."}
        
        from sheets_helper import find_all_transactions_by_message_id
        items = find_all_transactions_by_message_id(original_tx_id)
        
        if not items:
            return {"action": "REPLY", "response": "❌ Data transaksi lama tidak ditemukan."}

        match_result = find_matching_item(items, hint, amount)
        
        if not match_result:
            return {"action": "REPLY", "response": f"⚠️ Bingung item '{hint}'. Bisa lebih spesifik?"}
             
        target = match_result['matched_item']
        
        if not amount:
            return {"action": "REPLY", "response": "⚠️ Nominal barunya berapa?"}
             
        success = update_transaction_amount(target['dompet'], target['row'], amount)
        if success:
            return {"action": "REPLY", "response": f"✅ Revisi: {target.get('keterangan')} → Rp {amount:,}"}
        else:
            return {"action": "REPLY", "response": "❌ Gagal update spreadsheet."}
