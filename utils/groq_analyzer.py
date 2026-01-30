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



# Casual bot mentions (not commands)
CASUAL_BOT_MENTIONS = [
    "bot kamu", "bot lu", "bot ini", "botnya", "bot gw", "si bot",
    "bot canggung", "bot marbot", "bot kece", "bot pintar", "bot bodoh",
    "ajak omong bot", "ngomong sama bot", "chat sama bot", "tanya bot",
]

def is_casual_bot_mention(text: str) -> bool:
    """
    Check if text is just casual mention of bot (not command).
    
    Returns True if:
    - Text mentions "bot" in casual context
    - No amount pattern
    - No finance keywords
    """
    text_lower = text.lower()
    
    # Check casual phrases
    for phrase in CASUAL_BOT_MENTIONS:
        if phrase in text_lower:
            # Make sure it's not a real transaction
            if not has_amount_pattern(text):
                # Basic finance keywords to exempt
                if not any(k in text_lower for k in ['beli', 'bayar', 'transfer', 'gaji', 'dp']):
                    return True
    
    return False


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
        is_saldo = is_saldo_update(text)
        
        # LAYER 3: Multi-layer context detection
        context_analysis = self.context_detector.detect_context(text)
        category_scope = context_analysis.get("category_scope")
        context_confidence = context_analysis.get("confidence", 0.0)
        context_signals = context_analysis.get("signals", {})
        context_reasoning = context_analysis.get("reasoning", "")
        
# ENHANCED SYSTEM PROMPT WITH NEGATIVE CONSTRAINTS
        system_prompt = f"""You are the intelligent analyzer for "Bot Keuangan" (Finance Bot) for a creative agency (DKV/Mural company).

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
- Saldo Update Detected: {is_saldo}

===========================================
CRITICAL: OPERATIONAL vs PROJECT CLASSIFICATION
===========================================

**OPERATIONAL (Office Overhead - Fixed Costs):**
These are RECURRING, FIXED expenses for running the office, NOT tied to specific client projects.

STRONG INDICATORS:
1. **Office Location Keywords:**
   - "untuk kantor", "buat kantor", "di kantor", "kantor pusat"
   - "office", "ruangan", "gedung kantor"
   
2. **Office Roles (Non-Field):**
   - "gaji admin", "gaji staff", "gaji karyawan", "gaji sekretaris"
   - "gaji [nama orang] admin/staff"
   
3. **Recurring Temporal Patterns:**
   - "gaji bulan [bulan]", "bulanan", "per bulan"
   - "tagihan rutin", "bayar rutin"
   
4. **Utility & Office Expenses:**
   - "listrik", "PLN", "token listrik"
   - "air", "PDAM", "tagihan air"
   - "wifi", "internet", "indihome", "speedy"
   - "telepon kantor", "pulsa kantor"
   
5. **Office Supplies:**
   - "ATK", "alat tulis", "printer", "tinta", "kertas"
   - "peralatan kantor", "komputer kantor", "laptop kantor"
   - "Iphone buat kantor", "HP untuk kantor"  ← KEY: "buat/untuk kantor"
   
6. **Office Consumption:**
   - "konsumsi kantor", "snack kantor", "makan kantor"
   - "kopi kantor", "air mineral kantor"

**PROJECT (Client Work - Variable Costs):**
These are expenses tied to SPECIFIC client projects (murals, DKV, renovations).

STRONG INDICATORS:
1. **Project Names:**
   - ANY capitalized name: "Wooftopia", "Taman Indah", "Renovasi Cafe"
   - "project [nama]", "untuk [nama project]"
   
2. **Field Worker Roles:**
   - "tukang", "pekerja lapangan", "pelukis mural"
   - "designer lapangan", "tim lapangan"
   
3. **Project-Specific Items:**
   - "material", "bahan bangunan", "cat", "semen", "pasir"
   - "ongkir ke site", "transport ke lokasi"
   
4. **Project Context Prepositions:**
   - "untuk [project name]", "buat [project name]"
   - "di [project name]", "project [name]"
   - "fee tukang [project]", "upah [project]"

===========================================
DISAMBIGUATION RULES (CRITICAL!)
===========================================

**Rule 1: Preposition "buat/untuk + kantor" = OPERATIONAL**
   ❌ WRONG: "Iphone buat kantor" → PROJECT
   ✅ CORRECT: "Iphone buat kantor" → OPERATIONAL
   
   Why? "buat kantor" = for office use = office equipment = OPERATIONAL

**Rule 2: Preposition "buat/untuk + [Project Name]" = PROJECT**
   ✅ "Cat buat Wooftopia" → PROJECT
   ✅ "Material untuk Taman Indah" → PROJECT

**Rule 3: Ambiguous Words Need Context**
   - "gaji" alone → AMBIGUOUS (need role/temporal)
   - "gaji admin" → OPERATIONAL (office role)
   - "gaji tukang Wooftopia" → PROJECT (field role + project name)
   - "bon" alone → AMBIGUOUS
   - "bon tukang buat [project]" → PROJECT
   - "bon kantor" → OPERATIONAL

**Rule 4: Role Disambiguation**
   - Admin, Staff, Karyawan, Sekretaris → Office → OPERATIONAL
   - Tukang, Pekerja Lapangan, Pelukis → Field → PROJECT

**Rule 5: Location Context**
   - "di kantor", "untuk kantor", "buat kantor" → OPERATIONAL
   - "di site", "di lokasi", "ke lapangan" → PROJECT

===========================================
INTENT CLASSIFICATION
===========================================

AVAILABLE INTENTS:
1. **IGNORE**
   - Casual conversation, jokes, greetings not for bot.
   - Future plans: "Nanti beli ya", "Besok kita makan dimana?"
   - Commands to OTHER HUMANS: "Tolong beliin", "Bayarin dulu dong"
   - Mentions of "bot" in non-transactional context: "bot kamu marbot", "botnya canggung"
   - CRITICAL: If sentence is FUTURE TENSE or a COMMAND to human, classify as IGNORE.

2. **RECORD_TRANSACTION**
   - Report of expense/income that HAS HAPPENED (past tense).
   - MUST contain: Item description AND Amount.
   - MUST use PAST tense: "udah", "barusan", "tadi", "habis", "sudah bayar", "abis beli"
   - Examples: 
     * "Barusan beli bensin 50rb"
     * "Udah bayar gaji admin 5jt"
     * "Abis beli Iphone buat kantor 7jt" ← OPERATIONAL
   
3. **TRANSFER_FUNDS**
   - Moving money BETWEEN internal wallets.
   - WALLET BALANCE UPDATES (Isi dompet, isi saldo dompet, topup dompet).
   - Examples: "Transfer ke TX SBY 1jt", "Update saldo dompet TX Bali 10jt", "Update saldo dompet TX SBY 10jt", "Update saldo dompet CV HB (101) 10jt", "Isi dompet"

    CRITICAL: If "Saldo Update Detected: True", ALWAYS classify as TRANSFER_FUNDS!

    CRITICAL RULES:
    - If Saldo Update Detected = True → MUST be TRANSFER_FUNDS
    - "update saldo", "isi dompet" → TRANSFER_FUNDS (NOT OPERATIONAL!)

4. **QUERY_STATUS**
   - Asking about financial data, balance, reports.

5. **REVISION_REQUEST**
   - Correcting a PREVIOUS entry.
   - Examples: "Eh salah", "Revisi jadi 100k"

6. **CONVERSATIONAL_QUERY**
   - Greeting/thanking the BOT directly (and expecting response).
   - Examples: "Halo bot", "Thanks bot"
   - NOT: "bot kamu marbot" (this is casual talk → IGNORE)

===========================================
CRITICAL NEGATIVE CONSTRAINTS
===========================================

1. **Ignore Banter About Bot:**
   - "bot kamu marbot" → IGNORE (not asking bot to do anything)
   - "botnya canggung" → IGNORE (just commenting)
   - "amin bot" → IGNORE (joke/casual response)

2. **Ignore Future Plans:**
   - "Nanti beli" → IGNORE
   - "Besok bayar" → IGNORE

3. **Ignore Commands to Humans:**
   - "Tolong beliin" → IGNORE
   - "Bayarin dulu dong" → IGNORE

4. **Only Respond to PAST Actions:**
   - MUST have past tense: "udah", "tadi", "barusan", "abis", "habis"
   - OR: Clear reporting intent with amount

===========================================
CONFIDENCE SCORING
===========================================

**High Confidence (0.85 - 1.0):** Auto-classify
- Clear keywords + context match
- Examples:
  * "Bayar listrik 200rb" → OPERATIONAL (confidence: 0.95)
  * "Abis beli Iphone buat kantor 7jt" → OPERATIONAL (confidence: 0.90)
  * "Gaji tukang Wooftopia 2jt" → PROJECT (confidence: 0.95)

**Medium Confidence (0.60 - 0.84):** Confirm with user
- Some context but ambiguous
- Examples:
  * "Gajian 5jt" → AMBIGUOUS (confidence: 0.50, ask user)

**Low Confidence (< 0.60):** Ask clarifying question
- Insufficient context
- Examples:
  * "Bon 500rb" → AMBIGUOUS (confidence: 0.40, ask details)

===========================================
OUTPUT FORMAT (JSON ONLY)
===========================================

{{
  "should_respond": boolean,
  "intent": "IGNORE" | "RECORD_TRANSACTION" | "TRANSFER_FUNDS" | "QUERY_STATUS" | "REVISION_REQUEST" | "CONVERSATIONAL_QUERY",
  "confidence": 0.0-1.0,
  "category_scope": "OPERATIONAL" | "PROJECT" | "UNKNOWN",
  "extracted_data": {{
    "amount": int or null,
    "item_description": "string",
    "clean_text": "normalized input",
    "detected_project_name": "if found, else null",
    "detected_category": "Gaji/Listrik/Air/etc if OPERATIONAL",
    "source_wallet": "if TRANSFER_FUNDS",
    "destination_wallet": "if TRANSFER_FUNDS"
  }},
  "reasoning": "Brief explanation of classification decision",
  "conversational_response": "String (Only for CONVERSATIONAL_QUERY)"
}}

===========================================
EXAMPLES (LEARN FROM THESE!)
===========================================

Example 1:
Input: "Abis beli Iphone buat kantor 7jt"
Output:
{{
  "should_respond": true,
  "intent": "RECORD_TRANSACTION",
  "confidence": 0.90,
  "category_scope": "OPERATIONAL",
  "extracted_data": {{
    "amount": 7000000,
    "item_description": "Beli Iphone untuk kantor",
    "clean_text": "Beli Iphone buat kantor 7jt",
    "detected_category": "Peralatan"
  }},
  "reasoning": "Preposition 'buat kantor' indicates office equipment → OPERATIONAL"
}}

Example 2:
Input: "bot kamu marbot ya"
Output:
{{
  "should_respond": false,
  "intent": "IGNORE",
  "reasoning": "Casual banter about bot, not a transaction or query"
}}

Example 3:
Input: "Gaji tukang Wooftopia 2jt"
Output:
{{
  "should_respond": true,
  "intent": "RECORD_TRANSACTION",
  "confidence": 0.95,
  "category_scope": "PROJECT",
  "extracted_data": {{
    "amount": 2000000,
    "item_description": "Gaji tukang",
    "detected_project_name": "Wooftopia"
  }},
  "reasoning": "Role 'tukang' + project name 'Wooftopia' → PROJECT scope"
}}

Example 4:
Input: "Gajian 5jt"
Output:
{{
  "should_respond": true,
  "intent": "RECORD_TRANSACTION",
  "confidence": 0.45,
  "category_scope": "UNKNOWN",
  "extracted_data": {{
    "amount": 5000000,
    "item_description": "Gaji"
  }},
  "reasoning": "Insufficient context - could be office salary or project fee"
}}

Example 5:
Input: "Ah masih canggung botnya"
Output:
{{
  "should_respond": false,
  "intent": "IGNORE",
  "reasoning": "Comment about bot behavior, not financial transaction"
}}

===========================================
REMEMBER:
===========================================
1. "buat kantor" / "untuk kantor" = OPERATIONAL
2. "buat [Project Name]" = PROJECT
3. Ignore casual mentions of "bot" in conversations
4. Only respond to PAST tense transactions or direct queries
5. High confidence → auto-classify, Low confidence → ask user
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

            # ===== POST-PROCESSING: Intent Boosting =====
            # If pre-analysis shows strong signals, boost confidence

            # 1. Saldo update MUST be TRANSFER_FUNDS
            if is_saldo:
                if result.get('intent') != 'TRANSFER_FUNDS':
                    logger.warning(f"AI misclassified saldo update. Forcing TRANSFER_FUNDS.")
                    result['intent'] = 'TRANSFER_FUNDS'
                    result['should_respond'] = True
                    result['confidence'] = 0.95
                    result['category_scope'] = 'TRANSFER'  # Special marker

            # 2. DP/Project keywords MUST be RECORD_TRANSACTION
            if result.get('intent') == 'IGNORE':
                 # Check for DP/term keywords
                 if any(k in text.lower() for k in ['dp', 'termin', 'pelunasan']):
                    logger.warning(f"AI ignored DP transaction. Forcing RECORD_TRANSACTION.")
                    result['intent'] = 'RECORD_TRANSACTION'
                    result['should_respond'] = True
                    result['confidence'] = 0.90
                    result['category_scope'] = 'PROJECT'

            # 3. Project name detected MUST respond
            if has_amount and any(word[0].isupper() for word in text.split()):
                # Has amount + capitalized word (likely project name)
                if result.get('intent') == 'IGNORE':
                    logger.warning(f"AI ignored project transaction. Forcing RECORD_TRANSACTION.")
                    result['intent'] = 'RECORD_TRANSACTION'
                    result['should_respond'] = True
                    result['confidence'] = 0.85
                    result['category_scope'] = 'PROJECT'

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
        
        # Rule 4: Casual bot mention = IGNORE
        if is_casual_bot_mention(text):
            logger.info(f"Safety override: Casual bot mention -> IGNORE")
            result['should_respond'] = False
            result['intent'] = 'IGNORE'

        return result


def should_quick_filter(message: dict) -> str:
    """Pre-AI filter to save tokens. IMPROVED v3.0."""
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
    
    # 4. NEW: Ignore casual bot mentions
    if is_casual_bot_mention(text):
        return "IGNORE"
    
    # 5. PROCESS if has amount pattern (likely financial)
    if has_amount_pattern(text):
        return "PROCESS"
    
    # 6. PROCESS if has media (likely receipt/nota)
    if has_media:
        return "PROCESS"
        
    return "PROCESS"


def is_saldo_update(text: str) -> bool:
    """
    Detect if this is a wallet balance update (not operational expense).
    
    Examples:
    - "Update saldo dompet TX Bali 10jt" → True
    - "Isi dompet holja 5jt" → True
    - "Tarik tunai 2jt" → True
    """
    text_lower = text.lower()
    
    # Keywords yang JELAS ini update saldo
    saldo_update_keywords = [
        "update saldo",
        "update dompet",
        "update saldo dompet",
        "isi saldo",
        "isi dompet",
        "topup dompet",
        "top up dompet",
        "masuk dompet",
        "tambah saldo",
        "tarik tunai",
        "tarik dompet",
        "ambil dompet",
    ]
    
    return any(kw in text_lower for kw in saldo_update_keywords)