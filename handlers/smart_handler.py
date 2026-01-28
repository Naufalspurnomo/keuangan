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
             # KECUALI jika ada gambar, jangan di-ignore walau caption pendek
             if not has_media:
                 return {"action": "IGNORE"}
             
        # ============================================================
        # 🔥 SMART FILTER V2: Deteksi Obrolan Keuangan Tanpa Mention 🔥
        # ============================================================
        
        is_group = chat_jid.endswith("@g.us")
        score = context.get('addressed_score', 0)
        
        # LIST KEYWORD DIPERLUAS (Termasuk kata kerja perintah)
        finance_keywords = [
            # Transaksi
            "beli", "bayar", "transfer", "lunas", "dp", "biaya", "ongkir", 
            "saldo", "uang", "dana", "keluar", "masuk", "total", "rekap", 
            "hutang", "tagihan", "invoice", "nota", "struk", "jajan",
            "mahal", "murah", "boros", "hemat", "budget", "anggaran",
            # Perintah Kerja (Ini yang kemarin kurang!)
            "catat", "tulis", "input", "rekam", "masukin", "simpan",
            "cek", "lihat", "tanya", "info", "help"
        ]
        
        is_finance_talk = False
        text_lower = text.lower()
        
        # Cek keyword keuangan
        # Syarat: Ada keyword DAN (kalimat > 1 kata ATAU itu adalah gambar)
        if any(k in text_lower for k in finance_keywords):
            if len(text.split()) >= 2 or has_media:
                is_finance_talk = True

        # LOGIKA SAKTI (DIPERBAIKI):
        # Ignore jika:
        # 1. Di grup
        # 2. Skor rendah (tidak dipanggil)
        # 3. Quick filter bukan PROCESS
        # 4. Bukan ngomongin keuangan
        # 5. DAN TIDAK ADA GAMBAR (Penting!)
        if is_group and score < 40:
             if quick != "PROCESS" and not is_finance_talk and not has_media:
                 secure_log("DEBUG", f"Group Ignore: {text[:20]}...")
                 return {"action": "IGNORE"}
             
             if is_finance_talk or has_media:
                 secure_log("INFO", f"👀 Auto-Sambar: Mendeteksi potensi transaksi...")

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
            
        elif intent == "RECORD_TRANSACTION":
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