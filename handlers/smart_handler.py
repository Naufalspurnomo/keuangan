"""
handlers/smart_handler.py - Smart Message Handler
Orchestrates all intelligence layers (Semantic Engine).
"""

import logging
import re
from config.constants import Commands
from utils.groq_analyzer import GroqContextAnalyzer, should_quick_filter
from utils.semantic_matcher import find_matching_item, extract_revision_entities
from layers.context_detector import get_full_context, record_interaction
from security import secure_log
from ai_helper import groq_client

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
        
        # 2. Build Context
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
            "addressed_score": full_ctx.get('addressed_score', 0)
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
             return {"action": "IGNORE"}
             
        # ============================================================
        # 🔥 SMART FILTER: Deteksi Obrolan Keuangan Tanpa Mention 🔥
        # ============================================================
        # Jika ada di grup dan skor rendah (tidak dipanggil bot),
        # Cek apakah isinya "Daging" (ada keyword keuangan).
        
        is_group = chat_jid.endswith("@g.us")
        score = context.get('addressed_score', 0)
        
        finance_keywords = [
            "beli", "bayar", "transfer", "lunas", "dp", "biaya", "ongkir", 
            "saldo", "uang", "dana", "keluar", "masuk", "total", "rekap", 
            "laporan", "hutang", "tagihan", "invoice", "nota", "struk",
            "mahal", "murah", "boros", "hemat", "budget", "anggaran"
        ]
        
        # Cek keyword keuangan (Hanya jika kalimatnya > 2 kata biar gak false positive)
        is_finance_talk = False
        text_lower = text.lower()
        if len(text.split()) >= 2:
            if any(k in text_lower for k in finance_keywords):
                is_finance_talk = True

        # LOGIKA SAKTI:
        # Ignore jika di grup DAN skor rendah DAN bukan ngomongin keuangan
        if is_group and score < 40:
             if quick != "PROCESS" and not is_finance_talk:
                 secure_log("DEBUG", f"Group Ignore (No Mention & No Finance Keyword): {text[:20]}...")
                 return {"action": "IGNORE"}
             
             if is_finance_talk:
                 secure_log("INFO", f"👀 Auto-Sambar: Mendeteksi obrolan keuangan: {text[:30]}...")

        # ============================================================

        # 4. AI Analysis (Groq)
        analyzer = GroqContextAnalyzer(groq_client)
        
        # Kirim sinyal ke AI bahwa ini mungkin "Ambient Talk"
        context['is_ambient'] = (score < 40)
        
        analysis = analyzer.analyze_message(message, context)
        
        if not analysis['should_respond']:
             return {"action": "IGNORE"}
             
        intent = analysis['intent']
        extracted = analysis.get('extracted_data', {})
        
        # Record Interaction only if we respond
        record_interaction(sender_number, chat_jid)
        self.state_manager.record_bot_interaction(sender_number, chat_jid, intent)

        # 5. Routing Intents
        if intent == "RATE_LIMIT":
            return {"action": "IGNORE"} # Silent for rate limit

        elif intent == "REVISION_REQUEST":
            hint = extracted.get('item_hint')
            amount = extracted.get('new_amount')
            return self.handle_revision_ai(hint, amount, reply_message_id, original_tx_id, chat_jid)

        elif intent == "QUERY_STATUS":
            return {
                "action": "PROCESS",
                "intent": "QUERY_STATUS",
                "normalized_text": text,
                "layer_response": extracted.get('search_query', text) # Use refined query from AI
            }
            
        elif intent == "RECORD_TRANSACTION":
            # Jika AI yakin ini transaksi, normalisasi teksnya
            # (Misal user bilang: "Tolong catat beli bensin", dinormalkan jadi "Beli bensin")
            clean_text = text
            if extracted.get('clean_text'):
                clean_text = extracted['clean_text']
                
            return {
                "action": "PROCESS",
                "intent": "RECORD_TRANSACTION",
                "normalized_text": clean_text,
                "layer_response": clean_text 
            }

        elif intent == "CONVERSATIONAL_QUERY":
             return {
                 "action": "REPLY",
                 "response": analysis.get('conversational_response', "Halo! Ada yang bisa saya bantu?")
             }
             
        # Default
        return {
            "action": "PROCESS",
            "intent": intent, 
            "normalized_text": text 
        }

    def handle_revision_ai(self, hint, amount, reply_message_id, original_tx_id, chat_jid) -> dict:
        # ... (Logika revisi tetap sama, tidak perlu diubah) ...
        # Copy logic handle_revision_ai dari file lama Anda atau gunakan referensi sebelumnya
        # (Bagian ini sepertinya sudah oke di kode lama)
        
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