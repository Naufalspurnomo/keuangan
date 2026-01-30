"""
utils/groq_analyzer.py - AI Intent Analyzer v2.0 (Cost Accounting Edition)

Major Improvements:
- Added TRANSFER_FUNDS intent for internal wallet transfers
- Added category_scope extraction (OPERATIONAL/PROJECT/UNKNOWN)
- Strengthened negative constraints for ambient talk filtering
- Improved past vs future tense detection
"""
import json
import logging
import re
from config.constants import Timeouts, OPERATIONAL_KEYWORDS
from utils.context_detector import ContextDetector

logger = logging.getLogger(__name__)


# Pre-AI number pattern detection
AMOUNT_PATTERNS = [
    re.compile(r'rp[\s.]*\d+', re.IGNORECASE),           # Rp 50.000, rp50000
    re.compile(r'\d+[\s]*(rb|ribu|k)', re.IGNORECASE),   # 50rb, 50 ribu, 50k
    re.compile(r'\d+[\s]*(jt|juta)', re.IGNORECASE),     # 1jt, 1 juta
    re.compile(r'\d{4,}'),                                 # 50000 (4+ digits)
]

# Past tense indicators (action already happened)
PAST_TENSE_INDICATORS = [
    'udah', 'sudah', 'barusan', 'tadi', 'kemarin', 
    'habis', 'selesai', 'beres', 'dibayar', 'dibeli',
    'ditransfer', 'dikirim', 'lunas', 'masuk', 'keluar',
    'tercatat', 'totalan', 'total'
]

# Future/plan indicators (NOT actual transactions)
FUTURE_PLAN_INDICATORS = [
    'nanti', 'besok', 'mau', 'kayaknya', 'kali', 'keknya',
    'gimana kalau', 'gmn klo', 'gpp', 'boleh', 'bisa',
    'rencana', 'plan', 'perlu', 'harus', 'tolong beliin',
    'tolong kasih', 'kasih tau', 'cariin'
]

# Command-to-human indicators (NOT for bot recording)
COMMAND_TO_HUMAN = [
    'tolong', 'dong', 'donk', 'ya', 'yuk', 'aja', 'deh',
    'beliin', 'bayarin', 'transferin', 'ambilin', 'kirim ke'
]


def has_amount_pattern(text: str) -> bool:
    """Check if text contains recognizable amount pattern."""
    for pattern in AMOUNT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def is_likely_past_tense(text: str) -> bool:
    """Check if text describes past event (already happened)."""
    text_lower = text.lower()
    return any(ind in text_lower for ind in PAST_TENSE_INDICATORS)


def is_likely_future_plan(text: str) -> bool:
    """Check if text describes future plan (not actual transaction)."""
    text_lower = text.lower()
    return any(ind in text_lower for ind in FUTURE_PLAN_INDICATORS)


def is_command_to_human(text: str) -> bool:
    """Check if text is commanding another human (not reporting to bot)."""
    text_lower = text.lower()
    return any(ind in text_lower for ind in COMMAND_TO_HUMAN)


def detect_operational_keyword(text: str) -> str:
    """Detect if text contains operational keywords. Returns keyword or None."""
    text_lower = text.lower()
    for kw in OPERATIONAL_KEYWORDS:
        if kw in text_lower:
            return kw
    return None


class GroqContextAnalyzer:
    def __init__(self, groq_client):
        self.client = groq_client
        self.model = "llama-3.1-8b-instant"  # Fast & cheap
        self.context_detector = ContextDetector()  # Multi-layer context engine

    def analyze_message(self, message: dict, context: dict) -> dict:
        """
        Analyze message intent using Groq Llama 3.1.
        Decides: IGNORE, RECORD_TRANSACTION, TRANSFER_FUNDS, QUERY, REVISION, CONVERSATIONAL.
        
        NEW v2.0:
        - Added TRANSFER_FUNDS for internal wallet transfers
        - Added category_scope for OPERATIONAL vs PROJECT detection
        - Strengthened ambient talk filtering
        """
        text = message.get('text', '')
        sender = message.get('sender', 'User')
        is_ambient = context.get('is_ambient', False)
        has_media = message.get('has_media', False)
        
        # Pre-analysis hints for AI
        has_amount = has_amount_pattern(text)
        is_past = is_likely_past_tense(text)
        is_future = is_likely_future_plan(text)
        is_human_cmd = is_command_to_human(text)
        op_keyword = detect_operational_keyword(text)
        
        # LAYER 3: Multi-layer context detection
        context_analysis = self.context_detector.detect_context(text)
        category_scope = context_analysis.get("category_scope")
        context_confidence = context_analysis.get("confidence", 0.0)
        context_signals = context_analysis.get("signals", {})
        context_reasoning = context_analysis.get("reasoning", "")
        
        # ENHANCED SYSTEM PROMPT WITH NEGATIVE CONSTRAINTS
        system_prompt = f"""You are the intelligent analyzer for "Bot Keuangan" (Finance Bot).
Your goal is to classify the user's intent and extract structured data.

USER CONTEXT:
- Sender: {sender}
- Is Group Chat: {'YES' if context.get('chat_type') == 'GROUP' else 'NO'}
- Is Addressed to Bot: {'NO (Ambient Talk)' if is_ambient else 'YES'}
- Has Image: {'YES' if has_media else 'NO'}

PRE-ANALYSIS HINTS:
- Contains Amount Pattern: {has_amount}
- Likely Past Tense: {is_past}
- Likely Future Plan: {is_future}
- Command to Human: {is_human_cmd}
- Operational Keyword Detected: {op_keyword or 'None'}

AVAILABLE INTENTS:
1. **IGNORE**
   - Casual conversation, jokes, greetings not for bot.
   - Future plans/discussions: "Nanti beli ya", "Besok kita makan dimana?", "Gpp ya Fal" (permission, not reports).
   - Commands to OTHER HUMANS: "Tolong beliin", "Bayarin dulu dong".
   - CRITICAL: If sentence is FUTURE TENSE or a COMMAND to human, classify as IGNORE.
   - If uncertain in Group Chat WITHOUT mention, default to IGNORE.

2. **RECORD_TRANSACTION**
   - Report of expense/income that HAS HAPPENED (past tense).
   - MUST contain: Item description AND Amount (explicit or implicit from context).
   - MUST use PAST tense indicators: "udah", "barusan", "tadi", "habis", "sudah bayar".
   - E.g.: "Barusan beli bensin 50rb", "Udah transfer 1jt", "Tadi bayar parkir 5rb".
   
3. **TRANSFER_FUNDS**
   - Moving money BETWEEN internal wallets (not expense/income).
   - E.g.: "Topup Gopay 100rb dari BCA", "Tarik tunai 500rb", "Transfer ke kas kecil".
   - This is NOT an expense, just money movement.

4. **QUERY_STATUS**
   - Asking about financial data, balance, reports.
   - E.g.: "Saldo berapa?", "Pengeluaran bulan ini?", "Total projek A?".

5. **REVISION_REQUEST**
   - Correcting a PREVIOUS entry (implies context of recent transaction).
   - E.g.: "Eh salah, harusnya 50rb", "Revisi jadi 100k".

6. **CONVERSATIONAL_QUERY**
   - Greeting/thanking the BOT directly.
   - E.g.: "Halo bot", "Makasih ya bot".

CONTEXT ANALYSIS (PRE-DETECTED):
- Category Scope: {category_scope} (Confidence: {context_confidence:.2f})
- Context Reasoning: {context_reasoning}
- Detected Signals:
  * Role: {context_signals.get('role_detected', 'None')}
  * Project Name: {context_signals.get('project_name', 'None')}
  * Temporal Pattern: {context_signals.get('temporal_pattern', 'None')}
  * Keyword Match: {context_signals.get('keyword_match', {}).get('keyword', 'None')} (Type: {context_signals.get('keyword_match', {}).get('type', 'None')})

EXTRACTION RULES FOR TRANSACTIONS:
When intent is RECORD_TRANSACTION, also extract:
- "category_scope": Use the PRE-DETECTED category_scope above as strong guidance.
  - "OPERATIONAL": Fixed office costs (Gaji staff kantor, Listrik, Air, WiFi, Konsumsi, ATK).
  - "PROJECT": Variable costs for client projects (Gaji tukang lapangan, Material, Bahan, Transport).
  - "UNKNOWN": Only if pre-detection is AMBIGUOUS and no clear context.
  
CONTEXT DISAMBIGUATION RULES:
- If pre-detected category has confidence >= 0.85, TRUST IT.
- If AMBIGUOUS (confidence < 0.60), look for:
  * Office roles (admin, staff) → OPERATIONAL
  * Field roles (tukang, pekerja lapangan) → PROJECT
  * Project names in text → PROJECT
  * Monthly patterns ("bulan ini", "gaji bulanan") → OPERATIONAL

CRITICAL NEGATIVE CONSTRAINTS:
- If text is discussing a PLAN or PERMISSION, output IGNORE.
- If text is a COMMAND to another human ("beli dong", "tolong bayarin"), output IGNORE.
- Only output RECORD_TRANSACTION if action clearly already happened (PAST TENSE).
- In Group Chat + Ambient Talk + No Amount Pattern = default IGNORE.

OUTPUT FORMAT (JSON ONLY):
{{
  "should_respond": boolean,
  "intent": "STRING_INTENT",
  "confidence": float (0.0-1.0),
  "category_scope": "OPERATIONAL" | "PROJECT" | "UNKNOWN",
  "extracted_data": {{
    "amount": int or null,
    "item_description": "string",
    "clean_text": "normalized input for further processing",
    "source_wallet": "detected wallet name if TRANSFER_FUNDS",
    "destination_wallet": "detected destination if TRANSFER_FUNDS"
  }},
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
                max_tokens=512
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Inject context analysis metadata for transparency
            result['context_analysis'] = {
                'pre_detected_scope': category_scope,
                'scope_confidence': context_confidence,
                'reasoning': context_reasoning,
                'signals': context_signals
            }
            
            # Post-processing safety: Apply rule-based overrides
            result = self._apply_safety_overrides(result, text, context, has_amount, is_future, is_human_cmd)
            
            return result
            
        except Exception as e:
            logger.error(f"Groq Analyzer Failed: {e}")
            # Fallback safe: Ignore if AI fails
            return {"should_respond": False, "intent": "ERROR"}
    
    def _apply_safety_overrides(self, result: dict, text: str, context: dict,
                                 has_amount: bool, is_future: bool, is_human_cmd: bool) -> dict:
        """Apply rule-based overrides to prevent false positives."""
        
        # Rule 1: In Group + Ambient + No Amount = IGNORE
        is_ambient = context.get('is_ambient', False)
        is_group = context.get('chat_type') == 'GROUP'
        
        if is_group and is_ambient and not has_amount:
            if result.get('intent') in ['RECORD_TRANSACTION', 'TRANSFER_FUNDS']:
                logger.info(f"Safety override: Ambient talk without amount in group -> IGNORE")
                result['should_respond'] = False
                result['intent'] = 'IGNORE'
        
        # Rule 2: Future plan language = IGNORE
        if is_future and result.get('intent') == 'RECORD_TRANSACTION':
            logger.info(f"Safety override: Future plan detected -> IGNORE")
            result['should_respond'] = False
            result['intent'] = 'IGNORE'
        
        # Rule 3: Command to human = IGNORE
        if is_human_cmd and result.get('intent') == 'RECORD_TRANSACTION':
            logger.info(f"Safety override: Command to human -> IGNORE")
            result['should_respond'] = False
            result['intent'] = 'IGNORE'
        
        return result


def should_quick_filter(message: dict) -> str:
    """Pre-AI filter to save tokens. IMPROVED v2.0."""
    text = message.get('text', '').lower()
    has_media = message.get('has_media', False)
    
    # 1. Ignore very short messages (unless commands or has media)
    if len(text) < 3 and text not in ['hi', 'tes', 'cek']:
        if not has_media:
            return "IGNORE"
        
    # 2. Ignore laughter/agreement
    ignore_exact = ['wkwk', 'haha', 'hihi', 'oke', 'siap', 'yoi', 'mantap', 'ok', 'sip', 'betul', 'iya', 'ya']
    if text in ignore_exact:
        return "IGNORE"
    
    # 3. Ignore if starts with laughter
    ignore_starts = ['wkwk', 'haha', 'hihi', 'lol', 'kwkw']
    if any(text.startswith(s) for s in ignore_starts):
        return "IGNORE"
    
    # 4. PROCESS if has amount pattern (likely financial)
    if has_amount_pattern(text):
        return "PROCESS"
    
    # 5. PROCESS if has media (likely receipt/nota)
    if has_media:
        return "PROCESS"
        
    return "PROCESS"