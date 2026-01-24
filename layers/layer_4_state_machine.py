"""
layer_4_state_machine.py - State Machine Orchestrator

Layer 4 of the 7-layer architecture. Manages transaction state
transitions and coordinates the company selection flow.

States:
- INITIAL: Start state
- WAITING_COMPANY: Awaiting company selection (1-5)
- WAITING_PROJECT: Awaiting project name input
- READY_TO_SAVE: Data validated, ready for duplicate check
- CONFIRMED_SAVE: Duplicate check passed, ready to save
- SAVED: Transaction saved successfully
- CANCELLED: Transaction cancelled by user
- ERROR: Error occurred

Based on Grand Design Ultimate lines 700-905.
"""

import re
import os
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


# ===================== COMPANY/WALLET MAPPING =====================

COMPANY_TO_WALLET = {
    'HOLLA': 'Dompet Holja',
    'HOJJA': 'Dompet Holja',
    'TEXTURIN-Surabaya': 'Dompet Texturin Sby',
    'TEXTURIN-Bali': 'Dompet Evan',
    'KANTOR': 'Dompet Evan',
    'UMUM': 'Dompet Holja',
}

SELECTION_MAP = {
    '1': ('Dompet Holja', 'HOLLA'),
    '2': ('Dompet Holja', 'HOJJA'),
    '3': ('Dompet Texturin Sby', 'TEXTURIN-Surabaya'),
    '4': ('Dompet Evan', 'TEXTURIN-Bali'),
    '5': ('Dompet Evan', 'KANTOR'),
}


# ===================== WALLET UPDATE DETECTION =====================

WALLET_UPDATE_PATTERNS = [
    re.compile(r'\b(?:update|isi|top\s*up|setor|tambah)\s+(?:saldo|dompet|wallet)\b', re.IGNORECASE),
    re.compile(r'\b(?:saldo|dompet|wallet)\s+(?:masuk|tambah|plus)\b', re.IGNORECASE),
    re.compile(r'\b(?:terima|dapat|masuk)\s+(?:dana|uang|transfer)\b', re.IGNORECASE),
]

WALLET_NAME_PATTERNS = [
    (re.compile(r'\b(?:dompet\s*)?holja\b', re.IGNORECASE), 'Dompet Holja'),
    (re.compile(r'\b(?:dompet\s*)?texturin\s*sby\b', re.IGNORECASE), 'Dompet Texturin Sby'),
    (re.compile(r'\b(?:dompet\s*)?evan\b', re.IGNORECASE), 'Dompet Evan'),
]


def is_wallet_update(description: str) -> bool:
    """Check if description indicates a wallet balance update."""
    if not description:
        return False
    
    for pattern in WALLET_UPDATE_PATTERNS:
        if pattern.search(description):
            return True
    return False


def detect_wallet_from_description(description: str) -> Optional[str]:
    """Detect wallet name from description text."""
    if not description:
        return None
    
    for pattern, wallet in WALLET_NAME_PATTERNS:
        if pattern.search(description):
            return wallet
    return None


# ===================== STATE HANDLERS =====================

def handle_initial_state(ctx) -> 'MessageContext':
    """Handle INITIAL state - determine next state based on extraction results."""
    from . import Intent
    
    # Check if extraction had data
    if not ctx.extracted_data:
        if 'EXTRACTION_ERROR' in ctx.validation_flags:
            ctx.current_state = 'ERROR'
            ctx.response_message = f"❌ Gagal memproses: {getattr(ctx, 'extraction_error', 'Unknown error')}"
            return ctx
        
        if 'NO_TRANSACTIONS' in ctx.validation_flags:
            # No transactions detected - might be casual chat
            ctx.current_state = 'NO_TRANSACTION'
            return ctx
    
    # Check validation flags
    if 'NEEDS_PROJECT' in ctx.validation_flags:
        ctx.current_state = 'WAITING_PROJECT'
        ctx.response_message = _format_project_ask(ctx)
        return ctx
    
    if 'NEEDS_COMPANY_SELECTION' in ctx.validation_flags:
        ctx.current_state = 'WAITING_COMPANY'
        ctx.response_message = _format_company_ask(ctx)
        return ctx
    
    # Company was auto-detected
    if hasattr(ctx, 'detected_company') and ctx.detected_company:
        ctx.selected_company = ctx.detected_company
        ctx.selected_dompet = COMPANY_TO_WALLET.get(ctx.detected_company, 'Dompet Holja')
        ctx.current_state = 'READY_TO_SAVE'
        return ctx
    
    # Default: need company selection
    ctx.current_state = 'WAITING_COMPANY'
    ctx.response_message = _format_company_ask(ctx)
    return ctx


def handle_waiting_company(ctx) -> 'MessageContext':
    """Handle WAITING_COMPANY state - process selection answer."""
    from . import Intent
    
    if ctx.intent == Intent.CANCEL_TRANSACTION:
        ctx.current_state = 'CANCELLED'
        ctx.response_message = "❌ Dibatalkan"
        return ctx
    
    # Check if answer is a valid selection
    answer = (ctx.text or '').strip()
    
    if answer in SELECTION_MAP:
        dompet, company = SELECTION_MAP[answer]
        ctx.selected_dompet = dompet
        ctx.selected_company = company
        ctx.current_state = 'READY_TO_SAVE'
        logger.info(f"Layer 4: Company selected -> {company} ({dompet})")
        return ctx
    
    # Invalid selection
    ctx.response_message = "❌ Pilih 1-5 untuk company, atau /cancel untuk batal"
    return ctx


def handle_waiting_project(ctx) -> 'MessageContext':
    """Handle WAITING_PROJECT state - process project name answer."""
    from . import Intent
    
    if ctx.intent == Intent.CANCEL_TRANSACTION:
        ctx.current_state = 'CANCELLED'
        ctx.response_message = "❌ Dibatalkan"
        return ctx
    
    project_name = (ctx.text or '').strip()
    
    if len(project_name) < 2:
        ctx.response_message = "❌ Nama projek terlalu pendek. Ketik nama projek atau /cancel"
        return ctx
    
    # Update transactions with project name
    if ctx.extracted_data:
        for t in ctx.extracted_data:
            t['nama_projek'] = project_name
            t.pop('needs_project', None)
    
    # Move to company selection if no company detected
    if 'NEEDS_COMPANY_SELECTION' in ctx.validation_flags or not hasattr(ctx, 'detected_company'):
        ctx.current_state = 'WAITING_COMPANY'
        ctx.response_message = _format_company_ask(ctx)
    else:
        ctx.selected_company = ctx.detected_company
        ctx.selected_dompet = COMPANY_TO_WALLET.get(ctx.detected_company, 'Dompet Holja')
        ctx.current_state = 'READY_TO_SAVE'
    
    return ctx


# ===================== RESPONSE FORMATTERS =====================

def _format_company_ask(ctx) -> str:
    """Format company selection prompt using existing formatter."""
    try:
        from utils.formatters import build_selection_prompt
        return build_selection_prompt(ctx.extracted_data or [], "").replace('*', '')
    except ImportError:
        # Fallback if formatter not available
        total = sum(t.get('jumlah', 0) for t in (ctx.extracted_data or []))
        count = len(ctx.extracted_data or [])
        return f"""📋 Transaksi ({count} item)
📊 Total: Rp {total:,}

❓ Simpan ke company mana? (1-5)

📁 Dompet Holja: 1️⃣ HOLLA | 2️⃣ HOJJA
📁 Texturin Sby: 3️⃣ TEXTURIN-Surabaya
📁 Dompet Evan: 4️⃣ TEXTURIN-Bali | 5️⃣ KANTOR

⏳ Batas waktu: 15 menit""".replace(',', '.')


def _format_project_ask(ctx) -> str:
    """Format project name request."""
    total = sum(t.get('jumlah', 0) for t in (ctx.extracted_data or []))
    count = len(ctx.extracted_data or [])
    
    tx_lines = []
    for t in (ctx.extracted_data or []):
        emoji = "💰" if t.get('tipe') == 'Pemasukan' else "💸"
        tx_lines.append(f"   {emoji} {t.get('keterangan', '-')}: Rp {t.get('jumlah', 0):,}".replace(',', '.'))
    
    tx_preview = '\n'.join(tx_lines)
    
    return f"""📋 Transaksi ({count} item)
{tx_preview}
📊 Total: Rp {total:,}

❓ Untuk projek apa?
Balas dengan nama projek, contoh:
• Purana Ubud
• Villa Sunset Bali

⏳ Batas waktu: 15 menit
Ketik /cancel untuk batal""".replace(',', '.')


def _format_success_response(ctx) -> str:
    """Format success response after saving."""
    try:
        from utils.formatters import format_success_reply_new
        return format_success_reply_new(
            ctx.extracted_data or [],
            ctx.selected_dompet,
            ctx.selected_company,
            ""
        ).replace('*', '')
    except ImportError:
        # Fallback
        total = sum(t.get('jumlah', 0) for t in (ctx.extracted_data or []))
        return f"""✅ Transaksi Tercatat!

📊 Total: Rp {total:,}
📍 {ctx.selected_dompet} → {ctx.selected_company}

💡 Ralat: reply /revisi 150rb""".replace(',', '.')


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 4 processing: State Machine.
    
    Manages transaction state and coordinates flow.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with current_state and response_message
    """
    from . import Intent
    
    # Get current state (default to INITIAL)
    current_state = getattr(ctx, 'current_state', None) or 'INITIAL'
    
    logger.info(f"Layer 4: State={current_state}, Intent={ctx.intent}")
    
    # State machine routing
    if current_state == 'INITIAL':
        ctx = handle_initial_state(ctx)
    
    elif current_state == 'WAITING_COMPANY':
        ctx = handle_waiting_company(ctx)
    
    elif current_state == 'WAITING_PROJECT':
        ctx = handle_waiting_project(ctx)
    
    # Handle terminal states
    elif current_state == 'SAVED':
        ctx.response_message = _format_success_response(ctx)
    
    elif current_state == 'CANCELLED':
        pass  # Response already set
    
    elif current_state == 'ERROR':
        pass  # Response already set
    
    logger.info(f"Layer 4: New state={ctx.current_state}")
    
    return ctx
