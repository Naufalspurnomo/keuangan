"""
parsers.py - Input Parsing Utilities

Contains:
- parse_selection: Parse 1-5 company selection
- parse_revision_amount: Parse amount for revision
- should_respond_in_group: Check if bot should respond in group
- pending_key: Generate unique pending transaction key
- pending_is_expired: Check if pending transaction expired
"""

import re
from datetime import datetime

from config.constants import Timeouts, GROUP_TRIGGERS, OPERATIONAL_KEYWORDS

ACTION_VERBS = [
    'beli', 'bayar', 'transfer', 'kirim', 'terima', 'dp',
    'lunasin', 'kasih', 'isi', 'topup', 'top up', 'tarik',
    'catat', 'simpan', 'input', 'masukin', 'tambah'
]
ACTION_VERBS.append('fee')

QUERY_WORDS = [
    'berapa', 'gimana', 'bagaimana', 'apa', 'kapan', 'kenapa',
    'cek', 'check', 'lihat', 'tunjukkan', 'berdasarkan', 'analisa', 'analisis'
]
QUERY_FINANCE_HINTS = [
    'saldo', 'dompet', 'pemasukan', 'pengeluaran', 'omset', 'profit',
    'hutang', 'piutang', 'lunas', 'laporan', 'status', 'rekap', 'total'
]

# Use centralized timeouts
PENDING_TTL_SECONDS = Timeouts.PENDING_TRANSACTION


def pending_key(sender_number: str, chat_jid: str) -> str:
    """Generate unique key for pending transactions per chat/user."""
    if chat_jid and sender_number:
        return f"{chat_jid}:{sender_number}"
    return sender_number


def pending_is_expired(pending: dict) -> bool:
    """Check if pending transaction has expired (TTL exceeded)."""
    created = pending.get("created_at")
    if created is None:
        return False
    return (datetime.now() - created).total_seconds() > PENDING_TTL_SECONDS


def calculate_financial_score(message: str, has_media: bool = False, is_mentioned: bool = False) -> int:
    """
    Calculate Financial Signal Score (0-100) per Grand Design Layer 0.
    
    Factors:
    - Numeric Pattern (+40): 150rb, 1.5jt, 50.000
    - Action Verb (+30): beli, bayar, transfer, terima, lunasin
    - Media Attachment (+20): Evidence of transaction
    - Bot Mention (+60): Explicit invocation
    """
    score = 0
    message_lower = message.lower().strip()
    
    # Factor 5: Bot Mention (+60)
    if is_mentioned:
        score += 60
        
    # Factor 3: Media Attachment
    # If media comes with ANY text/caption, it's a strong signal (+50)
    # If media only (no text), it's a weak signal (+20) -> waits for follow-up text
    if has_media:
        if message and len(message.strip()) > 0:
            score += 50
        else:
            score += 20
        
    # Factor 1: Numeric Pattern (+40)
    # Check for amount patterns like 150rb, 1.5jt, 50.000, 5 juta (allow space)
    if re.search(r'\b\d+(?:[.,]\d+)*\s*(?:rb|ribu|k|jt|juta)\b', message_lower):
         score += 40
    elif re.search(r'\b\d{3,}\b', message_lower.replace('.', '').replace(',', '')):
         # Only count pure numbers if >= 1000 (likely amount, not date/hour)
         score += 40
             
    # Factor 2: Action Verb Pattern (+30)
    if any(verb in message_lower for verb in ACTION_VERBS):
        score += 30
        
    # Grand Design Threshold Logic:
    # < 50: SILENT (Ignore)
    # 50-69: TENTATIVE (Process)
    # >= 70: CONFIDENT (Process)
    return score


def should_respond_in_group(message: str, is_group: bool, has_media: bool = False, 
                           has_pending: bool = False, is_mentioned: bool = False) -> tuple:
    """
    Check if bot should respond to this message in group chat.
    Uses Grand Design Layer 0 "Financial Signal Scoring".
    
    Response Criteria:
    1. Explicit Triggers (+catat, /command) -> ALWAYS RESPOND
    2. Active Session (has_pending) -> ALWAYS RESPOND (context continuation)
    3. Financial Score >= 50 -> RESPOND (Smart Detection)
    
    Returns:
        (should_respond: bool, cleaned_message: str)
    """
    if not is_group:
        # For private chat, we still want to filter out obvious non-financial noise
        # but be more lenient than groups.
        # Threshold: 20 (Allows media-only, but filters "Halo", "Pagi", etc.)
        score = calculate_financial_score(message, has_media, is_mentioned)
        if score < 20 and not message.startswith('/'):
            # Noise (Score < 20 and not a command)
            return False, ""
        return True, message  # Process likely transactions and commands
    
    message_lower = message.lower().strip()

    # 2.5. Wallet balance updates are explicit financial actions
    saldo_update_keywords = [
        "update saldo",
        "update dompet",
        "update saldo dompet",
        "isi saldo",
        "isi dompet",
        "tambah dompet",
        "tambah saldo dompet",
        "topup dompet",
        "top up dompet",
        "masuk dompet",
        "tambah saldo",
        "tarik tunai",
        "tarik dompet",
        "ambil dompet",
    ]
    if any(kw in message_lower for kw in saldo_update_keywords):
        return True, message
    
    # 1. Active Session Bonus (+50 equivalent) -> Always processing pending flow
    if has_pending:
        return True, message

    # 1.5. If media is present (receipt/nota), allow processing even without text
    if has_media and not message_lower:
        return True, message
        
    # 2. Explicit Group Triggers
    for trigger in GROUP_TRIGGERS:
        if message_lower.startswith(trigger.lower()):
            cleaned = message[len(trigger):].strip()
            return True, cleaned
            
    # 3. Slash Commands
    if message_lower.startswith('/'):
        return True, message
        
    # 3.5. Allow action verbs or operational keywords even without amount
    if any(re.search(rf"\b{re.escape(verb)}\b", message_lower) for verb in ACTION_VERBS):
        return True, message
    if any(kw in message_lower for kw in OPERATIONAL_KEYWORDS):
        return True, message
    # 3.6. Project keywords should trigger processing (even without amount)
    if re.search(r"\b(projek|project|proyek|prj)\b", message_lower):
        return True, message
    # 3.7. Financial query should also trigger processing (without /tanya)
    has_query_word = ('?' in message_lower) or any(
        re.search(rf"\b{re.escape(word)}\b", message_lower) for word in QUERY_WORDS
    )
    has_finance_hint = any(hint in message_lower for hint in QUERY_FINANCE_HINTS)
    if has_query_word and has_finance_hint:
        return True, message

    # 4. Smart Financial Scoring
    score = calculate_financial_score(message, has_media, is_mentioned)
    
    # Threshold check
    if score >= 50:
        return True, message
        
    return False, ""  # Ignore low signal messages


def is_command_match(text: str, command_list: list, is_group: bool = False) -> bool:
    """
    Check if text matches any command in the list, respecting group chat rules.
    
    Args:
        text: The message text (lowercase)
        command_list: List of command aliases (e.g., Commands.STATUS)
        is_group: If True, only match slash commands
        
    Returns:
        True if text matches a valid command for the context
    """
    text = text.lower().strip()
    
    if is_group:
        # In groups, only match commands starting with "/"
        for cmd in command_list:
            if cmd.startswith('/') and text == cmd:
                return True
        return False
    else:
        # In private chat, match any alias
        return text in command_list


def is_prefix_match(text: str, prefix_list: list, is_group: bool = False) -> bool:
    """
    Check if text starts with any prefix in the list, respecting group chat rules.
    
    Args:
        text: The message text (lowercase)
        prefix_list: List of prefixes (e.g., Commands.TANYA_PREFIXES)
        is_group: If True, only match slash prefixes
        
    Returns:
        True if text starts with a valid prefix for the context
    """
    text = text.lower().strip()
    
    if is_group:
        # In groups, only match prefixes starting with "/"
        for prefix in prefix_list:
            if prefix.startswith('/') and text.startswith(prefix):
                return True
        return False
    else:
        # In private chat, match any prefix
        for prefix in prefix_list:
            if text.startswith(prefix):
                return True
        return False



def parse_selection(text: str) -> tuple:
    """
    Parse user selection input (1-4 or company name).
    
    Returns:
        (is_valid: bool, selection: int, error_message: str)
    """
    from config.wallets import SELECTION_OPTIONS
    import difflib
    
    text = text.strip()
    
    # Check for cancel
    if text.lower() in ['/cancel', 'batal', 'cancel', 'stop']:
        return False, 0, "cancel"
    
    # Try to parse as number
    try:
        num = int(text)
        if 1 <= num <= 4:  # Changed from 5 to 4
            return True, num, ""
        else:
            return False, 0, "Pilihan tidak tersedia. Ketik angka 1-4."
    except ValueError:
        # Not a number - try fuzzy match against company names
        text_lower = text.lower()
        best_match = None
        highest_score = 0
        
        for opt in SELECTION_OPTIONS:
            company = opt['company'].lower()
            # Direct substr match (e.g. "bali" in "TEXTURIN-Bali")
            if text_lower in company or company in text_lower:
                score = 0.9 # High score for substr
            else:
                score = difflib.SequenceMatcher(None, text_lower, company).ratio()
            
            if score > highest_score:
                highest_score = score
                best_match = opt['idx']
        
        if highest_score > 0.6: # Threshold for confidence
            return True, best_match, ""
            
        return False, 0, "Balas dengan angka 1-4 atau nama perusahaan untuk memilih."


def parse_revision_amount(text: str) -> int:
    """
    Parse amount from revision text.
    Supports: "/revisi 150rb", "150000", "150rb", "1.5jt", "2 juta", "509,500", etc.
    
    Comma/dot handling:
    - With suffix (jt, rb): comma = decimal (1,5jt = 1.500.000)
    - Without suffix: 
      - 3+ digits after separator = thousand separator (509,500 = 509500)
      - 1-2 digits after separator = decimal (509,5 = 509.5 -> 510)
    
    Returns:
        Amount in Rupiah, or 0 if not parseable
    """
    # Clean the text
    text = text.lower().strip()
    
    # Remove /revisi or revisi prefix
    text = re.sub(r'^[/]?(revisi|ubah|ganti|koreksi|edit)\s*', '', text).strip()
    
    # Handle "2 juta", "500 rb", "1.5jt", "500 perak" - number followed by optional space and suffix
    # Changed from re.match (strict) to re.search (flexible) to allow "revisi dp 7.5jt"
    match = re.search(r'\b([\d]+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta|perak)\b', text)
    if match:
        num_str = match.group(1)
        suffix = match.group(2)
        
        # Has suffix - comma/dot is ALWAYS decimal separator in this context mostly
        # But 1.500 rb is ambiguous. Assume 1.5 -> 1500 if rb.
        num_str = num_str.replace(',', '.')
        try:
            num = float(num_str)
        except ValueError:
            return 0
        
        if suffix in ['rb', 'ribu', 'k']:
            return int(num * 1000)
        elif suffix in ['jt', 'juta']:
            return int(num * 1000000)
        elif suffix == 'perak':
            return int(round(num))
    
    # Try direct number pattern if no suffix found (e.g. 500000)
    # Search for number with potential thousands separators
    # Look for sequence of digits that might have , or .
    # Exclude common date formats?
    # Simple approach: find the standard number format
    
    # Check if user just sent a clean number like "500.000" or "500000"
    # Remove item words first to avoid confusion?
    # Let's try to find potential amount strings
    
    match_clean = re.search(r'\b(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)\b', text)
    if match_clean:
         num_str = match_clean.group(1)
         # Verify it's not a date?
         # Parse logic
         sep_match = re.search(r'[.,](\d+)$', num_str)
         if sep_match:
             digits_after = len(sep_match.group(1))
             if digits_after >= 3:
                 # 3+ digits = thousand separator (509,500 -> 509500)
                 cleaned = num_str.replace('.', '').replace(',', '')
                 return int(cleaned)
             else:
                 # 1-2 digits = decimal separator
                 num_str = num_str.replace(',', '.')
                 return int(round(float(num_str)))
         else:
             return int(num_str.replace('.', '').replace(',', ''))

    
    # Try direct number (just digits after cleaning separators)
    cleaned = text.replace('.', '').replace(',', '').replace(' ', '')
    try:
        return int(cleaned)
    except ValueError:
        return 0



def extract_project_name_from_text(text: str) -> str:
    """
    Extract project name from text using multiple strategies.
    
    Examples:
    - "DP projek Ririyan 20jt" → "Ririyan"
    - "Material buat Wooftopia" → "Wooftopia"
    - "untuk project Taman Indah" → "Taman Indah"
    """
    if not text:
        return None

    def _clean_project_name(raw_name: str) -> str:
        if not raw_name:
            return ""
        name = raw_name.strip()
        # Stop when debt/source phrases begin.
        name = re.split(
            r"\b(?:utang|hutang|minjam|minjem|pinjam|dari|dr|pakai|via|dompet|wallet|rekening|rek)\b",
            name,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        # Trim any trailing amount fragments.
        name = re.sub(
            r"\b\d[\d\.,]*(?:\s*(?:rb|ribu|k|jt|juta))?\b.*$",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()
        return name
        
    # Strategy 1: After "projek/project/untuk/buat" + capitalized word
    patterns = [
        r'(?:projek|project)\s+([A-Z][a-zA-Z\s]+?)(?:\s+\d|\s*$|,)',
        r'(?:untuk|buat)\s+(?:projek\s+)?([A-Z][a-zA-Z\s]+?)(?:\s+\d|\s*$|,)',
        r'(?:dp|pelunasan)\s+(?:projek\s+)?([A-Z][a-zA-Z\s]+?)(?:\s+\d|\s*$|,)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            project_name = match.group(1).strip()
            # Clean up (remove trailing numbers, etc)
            project_name = re.sub(r'\s+\d+.*$', '', project_name).strip()
            project_name = _clean_project_name(project_name)
            if len(project_name) >= 3:  # Min 3 chars
                return project_name
    
    # Strategy 2: Any capitalized word (2+ words)
    # Example: "Taman Indah Puncak"
    capitalized_phrase = re.search(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text)
    if capitalized_phrase:
        project_name = _clean_project_name(capitalized_phrase.group(1).strip())
        if len(project_name) >= 3:
            return project_name
    
    # Strategy 3: Single capitalized word (not at sentence start)
    words = text.split()
    for i, word in enumerate(words):
        # Skip first word usually (might be action like 'Beli')
        if i > 0 and word[0].isupper() and len(word) >= 4:
            # Check if it's not a common stopword or month
            # (Basic heuristic, improved by list check later)
            project_name = _clean_project_name(word)
            if len(project_name) >= 3:
                return project_name

    return None


# For testing
if __name__ == '__main__':
    print("Parser Tests")
    print(f"parse_selection('3'): {parse_selection('3')}")
    print(f"parse_selection('cancel'): {parse_selection('cancel')}")
    print(f"parse_revision_amount('150rb'): {parse_revision_amount('150rb')}")
    print(f"parse_revision_amount('1.5jt'): {parse_revision_amount('1.5jt')}")
    print(f"should_respond_in_group('+catat beli', True): {should_respond_in_group('+catat beli', True)}")
