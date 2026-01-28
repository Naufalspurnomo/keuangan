"""
utils/groq_analyzer.py - AI Intent Analyzer
"""
import json
import logging
from config.constants import Timeouts

logger = logging.getLogger(__name__)

class GroqContextAnalyzer:
    def __init__(self, groq_client):
        self.client = groq_client
        self.model = "llama-3.1-8b-instant" # Cepat & Murah

    def analyze_message(self, message: dict, context: dict) -> dict:
        """
        Analyze message intent using Groq Llama 3.1.
        Decides: IGNORE, RECORD, QUERY, or REVISION.
        """
        text = message.get('text', '')
        sender = message.get('sender', 'User')
        is_ambient = context.get('is_ambient', False)
        
        # SYSTEM PROMPT CANGGIH
        system_prompt = f"""You are the brain of "Bot Keuangan".
Your job is to CLASSIFY the user's intent from a chat message.

USER CONTEXT:
- Name: {sender}
- Chat Type: {'Group' if context.get('chat_type') == 'GROUP' else 'Private'}
- Addressed Directly to Bot: {'NO (Ambient Talk)' if is_ambient else 'YES'}

POSSIBLE INTENTS:
1. **IGNORE**: Casual chat, jokes, greetings not for bot, or discussing budget plans (not actual transactions).
   - E.g.: "Besok kita makan sate ya", "Semangat pagi", "Kalau ada biaya langganan AI gpp ya Fal" (This is permission, not reporting).
2. **RECORD_TRANSACTION**: Reporting an expense/income that JUST happened or needs recording.
   - E.g.: "Barusan beli bensin 50rb", "Tolong catat transfer 1jt", "Udah bayar listrik".
3. **QUERY_STATUS**: Asking about financial data/history/advice.
   - E.g.: "Pengeluaran hari ini berapa?", "Sisa saldo ada berapa?", "Boros gak sih kita?".
4. **REVISION_REQUEST**: Correcting a previous entry.
   - E.g.: "Eh salah, harusnya 50rb", "Revisi yang tadi jadi 100k".
5. **CONVERSATIONAL_QUERY**: Greeting the BOT directly.
   - E.g.: "Halo bot", "Pagi min", "Makasih bot".

RULES FOR AMBIENT TALK (When user is NOT talking directly to bot):
- Be STRICT. If it looks like a discussion between humans ("Nanti beli ya", "Harusnya gini"), classify as **IGNORE**.
- ONLY classify as **RECORD_TRANSACTION** if it clearly states an action happened ("Udah transfer", "Habis beli").
- ONLY classify as **QUERY_STATUS** if it's a clear question about data ("Totalnya berapa?").

OUTPUT FORMAT (JSON ONLY):
{{
  "should_respond": boolean,
  "intent": "STRING_INTENT",
  "confidence": float (0.0-1.0),
  "extracted_data": {{ ... specific data ... }},
  "conversational_response": "String (Only for CONVERSATIONAL_QUERY)"
}}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=256
            )
            
            result = json.loads(response.choices[0].message.content)
            return result
            
        except Exception as e:
            logger.error(f"Groq Analyzer Failed: {e}")
            # Fallback safe: Ignore if AI fails
            return {"should_respond": False, "intent": "ERROR"}

def should_quick_filter(message: dict) -> str:
    """Pre-AI filter to save tokens."""
    text = message.get('text', '').lower()
    
    # 1. Ignore very short messages (unless specific commands)
    if len(text) < 3 and text not in ['hi', 'tes', 'cek']:
        return "IGNORE"
        
    # 2. Ignore laughter/agreement
    ignore_starts = ['wkwk', 'haha', 'hihi', 'oke', 'siap', 'yoi', 'mantap', 'ok', 'sip', 'betul']
    if text in ignore_starts:
        return "IGNORE"
        
    return "PROCESS"