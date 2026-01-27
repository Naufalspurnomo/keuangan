"""
layer_3_ai_processor.py - Adaptive AI Processor & Validation

Layer 3 of the 7-layer architecture. Handles AI extraction and validation
by integrating with the proven ai_helper module.

Features:
- Delegates to ai_helper.extract_financial_data() for OCR/text/audio
- Amount normalization and validation
- Semantic type checking for project names
- Dynamic prompt generation (handled by ai_helper)

Based on Grand Design Ultimate lines 475-699.
"""

import re
import os
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


# ===================== VALIDATION PATTERNS =====================

# Amount patterns for normalization
AMOUNT_PATTERNS = [
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*jt', re.IGNORECASE), 1_000_000),
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*juta', re.IGNORECASE), 1_000_000),
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*rb', re.IGNORECASE), 1_000),
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*ribu', re.IGNORECASE), 1_000),
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*k\b', re.IGNORECASE), 1_000),
]

# Action verbs that SHOULD NOT be project names
ACTION_VERBS = {
    'beli', 'bayar', 'transfer', 'kirim', 'terima', 'catat', 'input',
    'revisi', 'ganti', 'hapus', 'koreksi', 'update', 'tambah',
    'setor', 'tarik', 'ambil', 'isi', 'top up', 'topup'
}


# ===================== AMOUNT PROCESSING =====================

def normalize_amount(amount_str: str) -> int:
    """
    Normalize Indonesian amount strings to integer.
    
    Examples:
        "500rb" -> 500000
        "1.5jt" -> 1500000
        "1.500.000" -> 1500000
    """
    if not amount_str:
        return 0
    
    # If already a number
    if isinstance(amount_str, (int, float)):
        return int(amount_str)
    
    text = str(amount_str).strip().lower()
    
    # Check for jt/rb suffix
    for pattern, multiplier in AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            num_str = match.group(1).replace(',', '.')
            try:
                return int(float(num_str) * multiplier)
            except ValueError:
                continue
    
    # Standard number format (1.500.000 or 1,500,000)
    clean = re.sub(r'[^\d]', '', text)
    try:
        return int(clean) if clean else 0
    except ValueError:
        return 0


def validate_amount_sanity(amount: int) -> Tuple[bool, str, str]:
    """
    Validate amount is within sane ranges.
    
    Returns:
        Tuple of (is_valid, flag_code, message)
    """
    if amount == 0:
        return False, "ZERO_AMOUNT", "Jumlah tidak boleh 0"
    
    if amount < 1000:
        return False, "SUSPICIOUSLY_LOW", f"Jumlah Rp {amount:,} terlalu kecil. Sudah benar?"
    
    if amount > 1_000_000_000:
        return False, "SUSPICIOUSLY_HIGH", f"Jumlah Rp {amount:,} sangat besar. Mohon konfirmasi."
    
    return True, "", ""


# ===================== SEMANTIC VALIDATION =====================

def validate_semantic_type(project_name: str) -> Tuple[bool, str]:
    """
    Validate that project name is semantically valid (not action verb).
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not project_name:
        return True, ""
    
    name_lower = project_name.lower().strip()
    
    # Check if it's an action verb
    first_word = name_lower.split()[0] if name_lower else ""
    if first_word in ACTION_VERBS:
        return False, f"'{project_name}' terlihat seperti kata kerja, bukan nama projek"
    
    # Check minimum length
    if len(name_lower) < 3:
        return False, f"Nama projek '{project_name}' terlalu pendek"
    
    return True, ""


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 3 processing: AI Extraction & Validation.
    
    Integrates with ai_helper.extract_financial_data() for actual extraction.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with extracted_data and validation_flags
    """
    from . import Intent
    
    # Skip if not a transaction intent
    if ctx.intent not in [Intent.RECORD_TRANSACTION, Intent.ANSWER_PENDING]:
        logger.debug(f"Layer 3: Skipping non-transaction intent: {ctx.intent}")
        return ctx
    
    try:
        # Determine input type
        input_type = 'image' if ctx.media_url else 'text'
        
        # Import existing proven extraction logic
        from ai_helper import extract_financial_data
        
        # Call the battle-tested extraction function
        transactions = extract_financial_data(
            input_data=ctx.text or '',
            input_type=input_type,
            sender_name=ctx.sender_name or 'User',
            media_urls=ctx.media_url,
            caption=ctx.caption
        )
        
        if not transactions:
            logger.info("Layer 3: No transactions extracted")
            ctx.validation_flags.append('NO_TRANSACTIONS')
            return ctx
        
        logger.info(f"Layer 3: Extracted {len(transactions)} transactions")
        
        # Validate each transaction
        validated_transactions = []
        for t in transactions:
            amount = t.get('jumlah', 0)
            
            # Normalize amount if string
            if isinstance(amount, str):
                amount = normalize_amount(amount)
                t['jumlah'] = amount
            
            # Validate amount
            valid, flag, msg = validate_amount_sanity(amount)
            if not valid:
                ctx.validation_flags.append(flag)
                t['validation_message'] = msg
            
            # Validate project name if present
            project_name = t.get('nama_projek', '')
            if project_name:
                valid, msg = validate_semantic_type(project_name)
                if not valid:
                    ctx.validation_flags.append('INVALID_PROJECT_NAME')
                    t['project_validation_error'] = msg
            
            validated_transactions.append(t)
        
        ctx.extracted_data = validated_transactions
        
        # Check if needs project name (from ai_helper's detection)
        needs_project = any(t.get('needs_project') for t in validated_transactions)
        if needs_project:
            ctx.validation_flags.append('NEEDS_PROJECT')
        
        # Check if company was auto-detected
        detected_company = None
        for t in validated_transactions:
            if t.get('company'):
                detected_company = t['company']
                break
        
        if detected_company:
            ctx.detected_company = detected_company
        else:
            ctx.validation_flags.append('NEEDS_COMPANY_SELECTION')
        
        logger.info(f"Layer 3: Validation flags: {ctx.validation_flags}")
        
    except Exception as e:
        logger.error(f"Layer 3 extraction failed: {e}", exc_info=True)
        ctx.validation_flags.append('EXTRACTION_ERROR')
        ctx.extraction_error = str(e)
    
    return ctx
