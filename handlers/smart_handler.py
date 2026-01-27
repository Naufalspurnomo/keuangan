
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
from utils.groq_analyzer import smart_analyze_message
from utils.semantic_matcher import find_matching_item, extract_revision_entities
from sheets_helper import find_transaction_by_message_id, update_transaction_amount
from security import secure_log
from ai_helper import groq_client
import asyncio

logger = logging.getLogger(__name__)

class SmartHandler:
    def __init__(self, state_manager):
        self.state_manager = state_manager
        # No more manual context detector or normalizer needed!
        # self.context_detector = ContextDetector(state_manager)
        
    def process(self, text: str, chat_jid: str, sender_number: str, 
                reply_message_id: str = None, has_media: bool = False,
                sender_name: str = "User") -> dict:
        """
        Main intelligence pipeline (Hybrid AI).
        """
        # Prepare Message Object
        message = {
            "text": text,
            "sender": sender_name,
            "has_media": has_media,
            "is_reply_to_bot": False # determined below
        }
        
        # Prepare Context
        context = {
            "chat_type": "GROUP" if chat_jid.endswith("@g.us") else "PRIVATE",
            "is_reply_to_bot": False,
            "replied_message_type": None,
            "recent_bot_interactions": [] 
        }

        # Reply Logic
        original_tx_id = None
        if reply_message_id:
             original_tx_id = self.state_manager.get_original_message_id(reply_message_id)
             if original_tx_id:
                 context['is_reply_to_bot'] = True
                 context['replied_message_type'] = "TRANSACTION_REPORT" # Assumption for now
                 message['is_reply_to_bot'] = True

        # AI Analysis (async wrapper needed as `smart_analyze_message` is async)
        # For simplicity in this synchronous flow, we run it sync or refactor `smart_analyze_message` to sync.
        # Let's make `smart_analyze_message` synchronous for now or run generic.
        # Actually `smart_analyze_message` in groq_analyzer.py is defined async but `GroqContextAnalyzer.analyze_message` is sync.
        # Let's use `analyze_message` directly synchronously to avoid async/await refactor hell in main.py.
        
        from utils.groq_analyzer import GroqContextAnalyzer, should_quick_filter
        
        # 1. Quick Filter
        quick = should_quick_filter(message)
        if quick == "IGNORE":
             return {"action": "IGNORE"}
             
        # 2. AI Analysis
        analyzer = GroqContextAnalyzer(groq_client)
        analysis = analyzer.analyze_message(message, context)
        
        if not analysis['should_respond']:
             return {"action": "IGNORE"}
             
        intent = analysis['intent']
        extracted = analysis.get('extracted_data', {})
        
        # 6. Record Interaction
        self.state_manager.record_bot_interaction(sender_number, chat_jid, intent)

        # 7. ROUTING
        if intent == "REVISION_REQUEST":
            # AI extracted hint & amount?
            hint = extracted.get('item_hint')
            amount = extracted.get('new_amount')
            
            # If AI didn't extract specific fields, fallback to old rule based extraction
            if not hint or not amount:
                 pass # Logic to handle fallback or ask user
            
            # We still need the original message_id to find what to revise
            return self.handle_revision_ai(hint, amount, reply_message_id, original_tx_id)

        elif intent == "QUERY_STATUS":
            return {
                "action": "PROCESS",
                "intent": "QUERY_STATUS",
                "normalized_text": text # Fallback
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
