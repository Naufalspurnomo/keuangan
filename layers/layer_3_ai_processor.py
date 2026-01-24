"""
layer_3_ai_processor.py - Adaptive AI Processor & Validation Engine

Layer 3 of the 7-layer architecture. Extracts financial data from
input and validates for semantic correctness.

Features:
- Context enrichment & noise reduction
- Dynamic AI prompts with error correction
- Post-AI validation (truncation, semantic type, amount sanity)
- Multi-transaction detection from OCR

Based on Grand Design Ultimate lines 593-885.
"""

import re
import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

logger = logging.getLogger(__name__)


# ===================== CONFIGURATION =====================

GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Known companies for validation
KNOWN_COMPANIES = {
    'holla', 'hojja', 'texturin-bali', 'texturin-surabaya', 'texturin sby', 'kantor', 'umum'
}

# Stopwords to remove during noise reduction
STOPWORDS = {
    'tolong', 'dong', 'ya', 'nih', 'deh', 'sih', 'aja', 'untuk', 'makasih', 'thanks',
    'please', 'bisa', 'mohon', 'coba', 'sebentar', 'dulu'
}

# Action verbs that should NOT be project names
ACTION_VERBS = {
    'revisi', 'update', 'ganti', 'koreksi', 'beli', 'bayar', 'transfer', 'kirim',
    'terima', 'catat', 'input', 'tambah', 'kurang', 'hapus', 'delete'
}


# ===================== AMOUNT NORMALIZATION =====================

def normalize_amount(text: str) -> Optional[int]:
    """
    Convert various amount formats to integer.
    
    Handles: 150.000, 150rb, 1.5jt, seratus ribu, Rp 500000
    """
    if not text:
        return None
    
    text = text.lower().strip()
    
    # Remove "rp" prefix
    text = re.sub(r'^rp\.?\s*', '', text)
    
    # Handle "rb" / "ribu" suffix
    match = re.match(r'^(\d+(?:[.,]\d+)?)\s*(?:rb|ribu|k)$', text)
    if match:
        num = float(match.group(1).replace(',', '.'))
        return int(num * 1000)
    
    # Handle "jt" / "juta" / "m" suffix
    match = re.match(r'^(\d+(?:[.,]\d+)?)\s*(?:jt|juta|m)$', text)
    if match:
        num = float(match.group(1).replace(',', '.'))
        return int(num * 1_000_000)
    
    # Handle standard number with thousand separators
    # Could be 1.500.000 or 1,500,000
    text_clean = re.sub(r'[.,](?=\d{3})', '', text)  # Remove thousand separators
    text_clean = re.sub(r'[,.](\d{1,2})$', r'.\1', text_clean)  # Keep decimal
    
    try:
        return int(float(text_clean))
    except ValueError:
        pass
    
    # Handle written numbers (basic)
    written_numbers = {
        'seratus': 100, 'dua ratus': 200, 'tiga ratus': 300,
        'empat ratus': 400, 'lima ratus': 500, 'enam ratus': 600,
        'tujuh ratus': 700, 'delapan ratus': 800, 'sembilan ratus': 900,
        'seribu': 1000, 'sejuta': 1_000_000,
    }
    
    for word, value in written_numbers.items():
        if word in text:
            multiplier = 1
            if 'ribu' in text and 'ratus' in text:
                multiplier = 1000
            elif 'juta' in text and 'ratus' in text:
                multiplier = 1_000_000
            return value * multiplier if multiplier > 1 else value
    
    return None


def extract_all_amounts(text: str) -> List[int]:
    """Extract all amounts from text."""
    amounts = []
    
    # Pattern for amounts
    patterns = [
        r'rp\.?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)',  # Rp 1.500.000
        r'(\d{1,3}(?:[.,]\d{3})*)\s*(?:rb|ribu|k)',  # 500rb
        r'(\d+(?:[.,]\d+)?)\s*(?:jt|juta)',  # 1.5jt
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amt = normalize_amount(match.group(0))
            if amt and amt > 0:
                amounts.append(amt)
    
    return amounts


# ===================== NOISE REDUCTION =====================

def reduce_noise(text: str) -> str:
    """Remove pleasantries without losing information."""
    words = text.split()
    filtered = [w for w in words if w.lower() not in STOPWORDS]
    return ' '.join(filtered)


# ===================== VALIDATION FUNCTIONS =====================

def validate_length_preservation(original: str, extracted_project: str) -> Tuple[bool, str]:
    """
    Check if AI truncated the project name.
    Grand Design lines 718-740.
    """
    if not extracted_project or not original:
        return True, ""
    
    # If extracted is less than 30% of relevant content, likely truncated
    # Find proper noun sequences in original
    words = original.split()
    proper_sequence = []
    current_sequence = []
    
    for word in words:
        if word[0].isupper() if word else False:
            current_sequence.append(word)
        else:
            if current_sequence:
                proper_sequence.append(' '.join(current_sequence))
            current_sequence = []
    if current_sequence:
        proper_sequence.append(' '.join(current_sequence))
    
    # Check if extracted is suspiciously short
    if proper_sequence:
        longest_proper = max(proper_sequence, key=len)
        if len(extracted_project) < len(longest_proper) * 0.5:
            return False, f"TRUNCATED: '{extracted_project}' dari '{longest_proper}'"
    
    return True, ""


def validate_semantic_type(project_name: str) -> Tuple[bool, str]:
    """
    Check if project name is semantically valid (not a verb or generic noun).
    Grand Design lines 742-801.
    """
    if not project_name:
        return True, ""
    
    project_lower = project_name.lower()
    
    # Check if it's an action verb
    if project_lower in ACTION_VERBS:
        return False, f"ACTION_VERB: '{project_name}' adalah kata kerja"
    
    # Check if it's a known company/wallet name (shouldn't be project)
    if project_lower in KNOWN_COMPANIES:
        return False, f"COMPANY_NAME: '{project_name}' adalah nama company"
    
    # Check for "dompet" keywords
    if 'dompet' in project_lower or 'saldo' in project_lower:
        return False, f"WALLET_KEYWORD: '{project_name}' mengandung keyword dompet"
    
    # If single lowercase word, likely generic
    if ' ' not in project_name and project_name.islower():
        return False, f"GENERIC_NOUN: '{project_name}' terlalu generik"
    
    return True, ""


def validate_amount_sanity(amount: int, user_avg: int = None) -> Tuple[bool, str, str]:
    """
    Check if amount is reasonable.
    Grand Design lines 803-842.
    
    Returns:
        (valid, flag, message)
    """
    if amount == 0:
        return False, "ZERO_AMOUNT", "⚠️ Nominal Rp 0 terdeteksi. Lupa input angkanya?"
    
    if amount < 100:
        return False, "UNUSUALLY_LOW", f"⚠️ Nominal Rp {amount}. Yakin benar?"
    
    if amount > 1_000_000_000:  # 1 Miliar
        return False, "UNUSUALLY_HIGH", f"⚠️ Nominal Rp {amount:,}. Yakin benar?"
    
    # Check against user's typical range
    if user_avg and amount > user_avg * 10:
        return True, "UNUSUAL_FOR_USER", f"💡 Transaksi Rp {amount:,} lebih besar dari biasanya."
    
    return True, "", ""


def validate_context_consistency(extracted: Dict) -> Tuple[bool, str]:
    """
    Cross-validate extracted fields.
    Grand Design lines 844-858.
    """
    company = (extracted.get('company') or '').lower()
    project = (extracted.get('project_name') or '').lower()
    
    # Check if project contains company name
    if company and project:
        if company in project or project in company:
            return False, f"PROJECT_CONTAINS_COMPANY: project '{project}' dan company '{company}' overlap"
    
    return True, ""


# ===================== AI EXTRACTION =====================

def get_extraction_prompt(sender_name: str, error_addendum: str = "") -> str:
    """Generate dynamic extraction prompt with error correction."""
    
    base_prompt = f"""You are a financial data extractor for Indonesian business transactions.
Extract structured data from user input.

TODAY'S DATE: {datetime.now().strftime('%Y-%m-%d')}
SENDER: {sender_name}

EXTRACTION RULES:
1. Amount: Must be > 0. If unclear or 0, return null.
2. Description: Clear, concise description of transaction.
3. Category: Classify into: Bahan, Tukang/Vendor, Operasional, Lain-lain
4. Project Name: 
   - If user provides specific proper noun, PRESERVE EXACTLY.
   - Do NOT abbreviate or shorten proper nouns.
   - If generic description, extract essence.
5. Company: Detect if mentioned (HOLLA, HOJJA, TEXTURIN-Surabaya, TEXTURIN-Bali, KANTOR)
6. Type: "Pemasukan" for income, "Pengeluaran" for expense
7. Date: Default today unless specified otherwise.

OUTPUT JSON:
{{
  "transactions": [
    {{
      "amount": number,
      "description": string,
      "category": string,
      "project_name": string or null,
      "company": string or null,
      "type": "Pemasukan" or "Pengeluaran",
      "date": "YYYY-MM-DD"
    }}
  ],
  "confidence": 0.0-1.0
}}
"""
    
    if error_addendum:
        base_prompt += f"\n\nCRITICAL CORRECTIONS:\n{error_addendum}"
    
    return base_prompt


def extract_with_ai(
    text: str, 
    sender_name: str,
    ocr_text: str = None,
    error_addendum: str = ""
) -> Optional[Dict]:
    """
    Use Groq AI to extract financial data.
    
    Returns:
        Dict with transactions list or None
    """
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set")
        return None
    
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        
        # Combine text sources
        full_text = text
        if ocr_text:
            full_text = f"[OCR from image]: {ocr_text}\n[User message]: {text}"
        
        # Reduce noise
        full_text = reduce_noise(full_text)
        
        prompt = get_extraction_prompt(sender_name, error_addendum)
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": full_text[:1000]}  # Limit input
            ],
            max_tokens=500,
            temperature=0.1
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON
        if "```" in result_text:
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        
        result = json.loads(result_text)
        logger.info(f"AI extraction: {len(result.get('transactions', []))} transactions found")
        
        return result
        
    except Exception as e:
        logger.error(f"AI extraction failed: {e}")
        return None


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 3 processing: AI Extraction & Validation.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with extracted_data and validation_flags
    """
    from . import Intent
    
    # Skip if not a recording intent or already has data
    if ctx.intent not in [Intent.RECORD_TRANSACTION, Intent.ANSWER_PENDING]:
        return ctx
    
    text = ctx.text or ""
    ocr_text = None
    
    # Get OCR text from linked photo if available
    if ctx.linked_photo and ctx.linked_photo.get('ocr_text'):
        ocr_text = ctx.linked_photo['ocr_text']
    elif ctx.linked_photo and ctx.linked_photo.get('media_url'):
        # TODO: Perform OCR here if not already done
        pass
    
    # If answering pending question, merge with existing data
    if ctx.intent == Intent.ANSWER_PENDING and ctx.pending_question:
        existing = ctx.extracted_data or {}
        question_type = ctx.pending_question.get('question_type')
        answer = ctx.pending_question.get('answer', '')
        
        if question_type == 'SELECT_COMPANY':
            selected = ctx.pending_question.get('selected_value', answer)
            existing['company'] = selected
        elif question_type == 'INPUT_PROJECT':
            existing['project_name'] = answer
        elif question_type == 'INPUT_AMOUNT':
            existing['amount'] = normalize_amount(answer)
        elif question_type == 'CONFIRM_DUPLICATE':
            existing['duplicate_confirmed'] = answer.lower() in ['y', 'ya', 'yes']
        
        ctx.extracted_data = existing
        return ctx
    
    # Get error addendum from learning engine
    error_addendum = ""
    try:
        from . import layer_7_feedback
        error_addendum = layer_7_feedback.get_error_addendum()
    except ImportError:
        pass
    
    # Extract with AI
    result = extract_with_ai(
        text=text,
        sender_name=ctx.sender_name or "User",
        ocr_text=ocr_text,
        error_addendum=error_addendum
    )
    
    if not result or not result.get('transactions'):
        # Try simple pattern extraction as fallback
        amounts = extract_all_amounts(text)
        if amounts:
            ctx.extracted_data = {
                'amount': amounts[0],
                'description': text[:100],
                'needs_validation': True
            }
        return ctx
    
    # Take first transaction (handle multi later)
    txn = result['transactions'][0]
    
    # Apply validation
    validation_flags = []
    
    # Validate project name
    if txn.get('project_name'):
        valid, msg = validate_length_preservation(text, txn['project_name'])
        if not valid:
            validation_flags.append(('TRUNCATION', msg))
        
        valid, msg = validate_semantic_type(txn['project_name'])
        if not valid:
            validation_flags.append(('SEMANTIC_TYPE', msg))
            txn['project_name'] = None  # Clear invalid
    
    # Validate amount
    if txn.get('amount'):
        valid, flag, msg = validate_amount_sanity(txn['amount'])
        if not valid:
            validation_flags.append((flag, msg))
        elif flag:  # Warning but still valid
            validation_flags.append((flag, msg))
    
    # Validate consistency
    valid, msg = validate_context_consistency(txn)
    if not valid:
        validation_flags.append(('CONSISTENCY', msg))
    
    # Store results
    ctx.extracted_data = txn
    ctx.validation_flags = validation_flags
    
    logger.info(f"Layer 3: Extracted {txn}, flags={[f[0] for f in validation_flags]}")
    
    return ctx
