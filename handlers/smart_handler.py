
"""
handlers/smart_handler.py - Smart Message Handler
Orchestrates all intelligence layers (Semantic Engine).

Features:
- Context detection (addressed to bot?)
- Normalization (slang/typo fix)
- Intent classification
- Routing to specialized handlers
"""

import logging
from config.constants import Commands
from utils.groq_analyzer import GroqContextAnalyzer, should_quick_filter
from utils.semantic_matcher import find_matching_item, extract_revision_entities
from layers.context_detector import get_full_context, record_interaction
from sheets_helper import find_transaction_by_message_id, update_transaction_amount
from security import secure_log
from ai_helper import groq_client
import asyncio

logger = logging.getLogger(__name__)
 
def pending_key(user_id: str, chat_id: str = None) -> str:
    """Standardize key for pending transactions."""
    if chat_id:
        return f"{chat_id}:{user_id}"
    return user_id

class SmartHandler:
    def __init__(self, state_manager):
        self.state_manager = state_manager
        # No more manual context detector or normalizer needed!
        # self.context_detector = ContextDetector(state_manager)
        
    def process(self, text: str, chat_jid: str, sender_number: str, 
                reply_message_id: str = None, has_media: bool = False,
                sender_name: str = "User", quoted_message_text: str = None) -> dict:
        """
        Main intelligence pipeline (Hybrid AI).
        """
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
        
        # 2. Build Context using ContextDetector
        full_ctx = get_full_context(
            text=text,
            quoted_message_text=quoted_message_text,
            is_quoted_from_bot=is_reply_to_bot,
            user_id=sender_number,
            chat_id=chat_jid,
            has_media=has_media,
            has_pending=self.state_manager.has_pending_transaction(pending_key(sender_number, chat_jid))
        )
        
        # Enrich Context for AI
        context = {
            "chat_type": "GROUP" if chat_jid.endswith("@g.us") else "PRIVATE",
            "is_reply_to_bot": is_reply_to_bot,
            "replied_message_type": "TRANSACTION_REPORT" if is_reply_to_bot else None,
            "addressed_score": full_ctx.get('addressed_score', 0),
            "mention_type": full_ctx.get('mention_type'),
            "in_conversation": full_ctx.get('in_conversation', False)
        }
        
        # Prepare Message Object for AI
        message = {
            "text": text,
            "sender": sender_name,
            "has_media": has_media,
            "is_reply_to_bot": is_reply_to_bot
        }

        # Record interaction for continuity
        record_interaction(sender_number, chat_jid)
        
        # 3. NORMALIZATION
        try:
            from utils.normalizer import normalize_nyeleneh_text
            original_text = text
            text = normalize_nyeleneh_text(text)
            if text != original_text:
                logger.info(f"[SmartHandler] Normalized: '{original_text}' -> '{text}'")
                message['text'] = text # Update for AI
        except Exception:
            pass

        # 4. Quick Filter
        quick = should_quick_filter(message)
        if quick == "IGNORE":
             return {"action": "IGNORE"}
             
        # 4b. Address Check (Silent Filter for Groups)
        # If in group and score is low (< 40), ignore to save AI tokens and prevent 
        # rate-limit spam for messages not addressed to the bot.
        if chat_jid.endswith("@g.us") and context.get('addressed_score', 0) < 40:
             # Exception: if quick filter said PROCESS, we keep going
             if quick != "PROCESS":
                 logger.info(f"[SmartHandler] Low addressed score ({context.get('addressed_score')}) in group - ignoring")
                 return {"action": "IGNORE"}
             
        # 5. AI Analysis
        analyzer = GroqContextAnalyzer(groq_client)
        analysis = analyzer.analyze_message(message, context)
        
        if not analysis['should_respond']:
             return {"action": "IGNORE"}
             
        intent = analysis['intent']
        extracted = analysis.get('extracted_data', {})
        
        # 6. Record Bot Interaction
        self.state_manager.record_bot_interaction(sender_number, chat_jid, intent)

        # 7. ROUTING
        if intent == "RATE_LIMIT":
            wait_time = extracted.get('wait_time', 'beberapa saat')
            return {
                "action": "REPLY",
                "response": f"⏳ *AI Sedang Istirahat*\n\nLimit penggunaan otak AI tercapai. Mohon tunggu sekitar *{wait_time}* sebelum mengirim perintah kompleks lagi."
            }

        elif intent == "REVISION_REQUEST":
            hint = extracted.get('item_hint')
            amount = extracted.get('new_amount')
            return self.handle_revision_ai(hint, amount, reply_message_id, original_tx_id)

        elif intent == "QUERY_STATUS":
            return {
                "action": "PROCESS",
                "intent": "QUERY_STATUS",
                "normalized_text": text
            }
            
        elif intent == "CONVERSATIONAL_QUERY":
             return {
                 "action": "REPLY",
                 "response": "Halo! Saya Bot Keuangan AI. Ketik /help untuk bantuan."
             }
             
        # Default
        return {
            "action": "PROCESS",
            "intent": "STANDARD_TRANSACTION",
            "normalized_text": text 
        }

    def handle_revision_ai(self, hint, amount, reply_message_id, original_tx_id) -> dict:
        """AI-assisted revision handler"""
        if not original_tx_id:
             return {
                 "action": "REPLY",
                 "response": "💡 Untuk merevisi, silakan *Reply* pesan laporan transaksi yang salah."
             }
        
        # Determine items
        from sheets_helper import find_all_transactions_by_message_id
        items = find_all_transactions_by_message_id(original_tx_id)
        
        if not items:
            return {"action": "REPLY", "response": "❌ Data transaksi lama tidak ditemukan."}

        # Semantic Match
        match_result = find_matching_item(items, hint, amount)
        
        if not match_result:
             # If AI gave us a hint but we couldn't match, maybe the hint was "dp" but item is "Down Payment"
             # The semantic matcher already handles this.
             return {
                 "action": "REPLY",
                 "response": f"⚠️ Saya bingung item mana yang dimaksud '{hint}'. Bisa lebih spesifik?"
             }
             
        target = match_result['matched_item']
        
        # Execute
        if not amount:
             return {"action": "REPLY", "response": "⚠️ Nominal barunya berapa?"}
             
        success = update_transaction_amount(target['dompet'], target['row'], amount)
        if success:
            return {
                "action": "REPLY", 
                "response": f"✅ Revisi Berhasil!\n📝 {target.get('keterangan')}\n💸 Rp {target.get('amount',0):,} → Rp {amount:,}"
            }
        else:
             return {"action": "REPLY", "response": "❌ Gagal update spreadsheet."}
        
    def handle_revision(self, text: str, reply_message_id: str, original_tx_id: str, sender: str) -> dict:
        """Smart revision handling with semantic matching."""
        if not original_tx_id:
             return {
                 "action": "REPLY",
                 "response": "💡 Untuk merevisi, silakan *Reply* pesan laporan transaksi yang salah."
             }
             
        # Extract entities
        entities = extract_revision_entities(text)
        if not entities.get('amount') and not entities.get('item_hint'):
             return {
                 "action": "REPLY",
                 "response": "⚠️ Format revisi tidak dikenali. Contoh: 'revisi dp 5jt' atau reply dan ketik '500rb'"
             }
             
        # Fetch original transactions
        from sheets_helper import find_all_transactions_by_message_id
        items = find_all_transactions_by_message_id(original_tx_id)
        
        if not items:
            return {
                 "action": "REPLY",
                 "response": "❌ Data transaksi lama tidak ditemukan."
             }
             
        # Find match
        match_result = find_matching_item(items, entities.get('item_hint'), entities.get('amount'))
        
        if not match_result:
            return {
                 "action": "REPLY",
                 "response": "⚠️ Bingung item mana yang dimaksud. Bisa sebutkan nama itemnya? Contoh: 'revisi semen 50rb'"
             }
             
        if match_result.get('needs_confirmation'):
            # In a full valid flow we would ask confirmation. 
            # For now, let's just do it but warn.
            pass
            
        target = match_result['matched_item']
        
        # Execute Revision
        new_amount = entities.get('amount')
        if not new_amount:
             return {
                 "action": "REPLY",
                 "response": "⚠️ Nominal barunya berapa?"
             }
             
        success = update_transaction_amount(target['dompet'], target['row'], new_amount)
        
        if success:
            return {
                "action": "REPLY", 
                "response": f"✅ Revisi Berhasil!\n📝 {target.get('keterangan')}\n💸 Rp {target.get('amount',0):,} → Rp {new_amount:,}"
            }
        else:
             return {
                 "action": "REPLY",
                 "response": "❌ Gagal update ke spreadsheet."
             }
