"""
layer_4_state_machine.py - State Machine Orchestrator

Layer 4 of the 7-layer architecture. Manages flow decision and
state transitions for incomplete transactions.

States:
- IDLE: No active transaction
- INTENT_DETECTED: Intent classified, ready for extraction
- DATA_EXTRACTED: Financial data extracted, need validation
- WAITING_AMOUNT: Partial data, missing amount
- WAITING_PROJECT: Partial data, missing project name
- WAITING_COMPANY: Partial data, missing company selection
- CONFIRM_DUPLICATE: Duplicate detected, need confirmation
- READY_TO_SAVE: All data complete and valid
- CONFIRMED_SAVE: User confirmed, proceed to save
- SUCCESS: Transaction saved
- ERROR: Fatal error occurred
- CANCELLED: User cancelled transaction

Based on Grand Design Ultimate lines 888-1082.
"""

import logging
from typing import Dict, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ===================== STATE DEFINITIONS =====================

class State(Enum):
    IDLE = "idle"
    INTENT_DETECTED = "intent_detected"
    DATA_EXTRACTED = "data_extracted"
    WAITING_AMOUNT = "waiting_amount"
    WAITING_PROJECT = "waiting_project"
    WAITING_COMPANY = "waiting_company"
    CONFIRM_DUPLICATE = "confirm_duplicate"
    READY_TO_SAVE = "ready_to_save"
    CONFIRMED_SAVE = "confirmed_save"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


# ===================== COMPANY SELECTION =====================

COMPANY_OPTIONS = {
    "1": "HOLLA",
    "2": "HOJJA",
    "3": "TEXTURIN-Surabaya",
    "4": "TEXTURIN-Bali",
    "5": "KANTOR"
}

COMPANY_TO_WALLET = {
    "HOLLA": "Dompet Holja",
    "HOJJA": "Dompet Holja",
    "TEXTURIN-Surabaya": "Dompet Texturin Sby",
    "TEXTURIN-Bali": "Dompet Evan",
    "KANTOR": "Dompet Evan",
    "UMUM": None  # For wallet updates, wallet is detected from description
}

# Wallet update keywords
WALLET_KEYWORDS = ['dompet', 'saldo', 'update saldo', 'isi ulang', 'top up', 'topup']


# ===================== HELPER FUNCTIONS =====================

def is_wallet_update(description: str) -> bool:
    """Check if this is a wallet balance update (not project transaction)."""
    if not description:
        return False
    desc_lower = description.lower()
    return any(kw in desc_lower for kw in WALLET_KEYWORDS)


def detect_wallet_from_description(description: str) -> Optional[str]:
    """Detect wallet name from description text."""
    if not description:
        return None
    
    desc_lower = description.lower()
    
    if 'evan' in desc_lower:
        return "Dompet Evan"
    if 'holja' in desc_lower or 'holla' in desc_lower:
        return "Dompet Holja"
    if 'texturin' in desc_lower and ('sby' in desc_lower or 'surabaya' in desc_lower):
        return "Dompet Texturin Sby"
    
    return None


def get_missing_fields(data: Dict) -> list:
    """Get list of missing required fields."""
    missing = []
    
    if not data.get('amount'):
        missing.append('amount')
    
    # Check if wallet update (no project needed)
    desc = data.get('description', '')
    if not is_wallet_update(desc):
        if not data.get('project_name'):
            missing.append('project_name')
        if not data.get('company'):
            missing.append('company')
    
    return missing


def format_company_selection_message() -> str:
    """Format the company selection prompt."""
    lines = ["📂 Simpan ke company mana?\n"]
    for num, company in COMPANY_OPTIONS.items():
        lines.append(f"{num}️⃣ {company}")
    lines.append("\n💡 Reply nomor 1-5")
    return '\n'.join(lines)


def format_confirmation_message(data: Dict) -> str:
    """Format transaction confirmation message."""
    amount = data.get('amount', 0)
    desc = data.get('description', '')
    project = data.get('project_name', 'N/A')
    company = data.get('company', 'N/A')
    txn_type = data.get('type', 'Pengeluaran')
    
    return f"""📝 Konfirmasi Transaksi:

💸 {desc}: Rp {amount:,}
📍 {company} → {project}
📊 Tipe: {txn_type}

✅ Simpan? (Y/N)"""


# ===================== STATE HANDLERS =====================

def handle_data_extracted(ctx, data: Dict) -> Tuple[str, Optional[str], Optional[Dict]]:
    """
    Handle DATA_EXTRACTED state.
    
    Returns:
        (next_state, response_message, question_data)
    """
    # Check for validation errors
    fatal_flags = ['ZERO_AMOUNT']
    for flag, msg in ctx.validation_flags or []:
        if flag in fatal_flags:
            return State.ERROR.value, f"❌ {msg}", None
    
    # Check if this is a wallet update
    desc = data.get('description', '')
    if is_wallet_update(desc):
        # Auto-fill for wallet update
        data['company'] = 'UMUM'
        data['project_name'] = 'Saldo Umum'
        
        wallet = detect_wallet_from_description(desc)
        if wallet:
            data['wallet'] = wallet
            return State.READY_TO_SAVE.value, None, None
        else:
            return State.WAITING_COMPANY.value, "❓ Untuk dompet mana? (Evan/Holja/Texturin Sby)", {
                'question_type': 'SELECT_WALLET',
                'expected_pattern': r'.+',
            }
    
    # Check missing fields
    missing = get_missing_fields(data)
    
    if 'amount' in missing:
        return State.WAITING_AMOUNT.value, "💰 Berapa nominalnya?", {
            'question_type': 'INPUT_AMOUNT',
            'expected_pattern': r'[\d.,]+\s*(?:rb|ribu|jt|juta|k|m)?',
        }
    
    if 'project_name' in missing:
        return State.WAITING_PROJECT.value, "📁 Untuk projek apa?", {
            'question_type': 'INPUT_PROJECT',
            'expected_pattern': r'.+',
        }
    
    if 'company' in missing:
        return State.WAITING_COMPANY.value, format_company_selection_message(), {
            'question_type': 'SELECT_COMPANY',
            'expected_pattern': r'^[1-5]$',
            'options': COMPANY_OPTIONS,
        }
    
    # All data complete
    return State.READY_TO_SAVE.value, None, None


def handle_waiting_amount(ctx, answer: str, data: Dict) -> Tuple[str, Optional[str], Optional[Dict]]:
    """Handle WAITING_AMOUNT state when answer received."""
    from .layer_3_ai_processor import normalize_amount
    
    amount = normalize_amount(answer)
    if amount and amount > 0:
        data['amount'] = amount
        # Re-check for other missing fields
        return handle_data_extracted(ctx, data)
    else:
        retry_count = data.get('_retry_amount', 0) + 1
        data['_retry_amount'] = retry_count
        
        if retry_count > 3:
            return State.CANCELLED.value, "❌ Terlalu banyak percobaan. Transaksi dibatalkan.", None
        
        return State.WAITING_AMOUNT.value, "⚠️ Format tidak valid. Contoh: 500000, 500rb, 1.5jt", {
            'question_type': 'INPUT_AMOUNT',
            'expected_pattern': r'[\d.,]+\s*(?:rb|ribu|jt|juta|k|m)?',
        }


def handle_waiting_project(ctx, answer: str, data: Dict) -> Tuple[str, Optional[str], Optional[Dict]]:
    """Handle WAITING_PROJECT state when answer received."""
    from .layer_3_ai_processor import validate_semantic_type
    
    project_name = answer.strip()
    
    # Validate semantically
    valid, msg = validate_semantic_type(project_name)
    if valid:
        data['project_name'] = project_name
        return handle_data_extracted(ctx, data)
    else:
        return State.WAITING_PROJECT.value, f"⚠️ '{project_name}' sepertinya bukan nama projek.\n💡 Contoh: Renovasi Gedung A, Villa Canggu", {
            'question_type': 'INPUT_PROJECT',
            'expected_pattern': r'.+',
        }


def handle_waiting_company(ctx, answer: str, data: Dict) -> Tuple[str, Optional[str], Optional[Dict]]:
    """Handle WAITING_COMPANY state when answer received."""
    answer = answer.strip()
    
    # Check if numeric selection
    if answer in COMPANY_OPTIONS:
        company = COMPANY_OPTIONS[answer]
        wallet = COMPANY_TO_WALLET.get(company)
        
        data['company'] = company
        data['wallet'] = wallet
        
        return State.READY_TO_SAVE.value, None, None
    
    # Try fuzzy match company name
    answer_lower = answer.lower()
    for company in COMPANY_OPTIONS.values():
        if company.lower() in answer_lower or answer_lower in company.lower():
            wallet = COMPANY_TO_WALLET.get(company)
            data['company'] = company
            data['wallet'] = wallet
            return State.READY_TO_SAVE.value, None, None
    
    # Invalid
    return State.WAITING_COMPANY.value, f"⚠️ Pilihan tidak valid.\n{format_company_selection_message()}", {
        'question_type': 'SELECT_COMPANY',
        'expected_pattern': r'^[1-5]$',
        'options': COMPANY_OPTIONS,
    }


def handle_confirm_duplicate(ctx, answer: str, data: Dict) -> Tuple[str, Optional[str], Optional[Dict]]:
    """Handle CONFIRM_DUPLICATE state when answer received."""
    if answer.lower() in ['y', 'ya', 'yes', 'iya']:
        return State.CONFIRMED_SAVE.value, None, None
    else:
        return State.CANCELLED.value, "✅ Transaksi dibatalkan (duplikat).", None


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 4 processing: State Machine Orchestration.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with state transitions
    """
    from . import Intent, layer_2_context_engine
    
    buffers = layer_2_context_engine.get_buffers()
    user_id = ctx.user_id
    data = ctx.extracted_data or {}
    
    # Get or initialize state
    current_state = ctx.current_state or State.IDLE.value
    
    # State transitions based on intent
    if ctx.intent == Intent.RECORD_TRANSACTION:
        if current_state == State.IDLE.value:
            current_state = State.DATA_EXTRACTED.value
    
    elif ctx.intent == Intent.ANSWER_PENDING:
        # User is answering a pending question
        answer = ctx.pending_question.get('answer', '') if ctx.pending_question else ctx.text
        
        if current_state == State.WAITING_AMOUNT.value:
            current_state, response, question = handle_waiting_amount(ctx, answer, data)
        elif current_state == State.WAITING_PROJECT.value:
            current_state, response, question = handle_waiting_project(ctx, answer, data)
        elif current_state == State.WAITING_COMPANY.value:
            current_state, response, question = handle_waiting_company(ctx, answer, data)
        elif current_state == State.CONFIRM_DUPLICATE.value:
            current_state, response, question = handle_confirm_duplicate(ctx, answer, data)
        else:
            response, question = None, None
        
        if response:
            ctx.response_message = response
        if question:
            buffers.set_pending_question(
                user_id=user_id,
                question_type=question['question_type'],
                bot_message_id=ctx.message_id,  # Will be updated after send
                expected_pattern=question['expected_pattern'],
                options=question.get('options'),
                context_data=data
            )
            buffers.update_pending_transaction(
                user_id=user_id,
                new_state=current_state,
                data_updates=data
            )
    
    elif ctx.intent == Intent.CANCEL_TRANSACTION:
        if current_state not in [State.IDLE.value, State.SUCCESS.value]:
            buffers.cancel_pending_transaction(user_id)
            ctx.response_message = "✅ Transaksi dibatalkan."
            current_state = State.CANCELLED.value
    
    elif ctx.intent == Intent.REVISION_REQUEST:
        # Handle revision - requires reply to bot message
        if not ctx.quoted_message_id:
            ctx.response_message = """❌ Perintah revisi harus reply pesan laporan bot.

📍 Cara revisi:
1. Cari pesan laporan bot (ada ✅)
2. Reply pesan itu
3. Ketik: /revisi [jumlah baru]

💡 Contoh: /revisi 500000"""
            current_state = State.ERROR.value
    
    # Handle DATA_EXTRACTED state
    if current_state == State.DATA_EXTRACTED.value:
        new_state, response, question = handle_data_extracted(ctx, data)
        current_state = new_state
        
        if response:
            ctx.response_message = response
        
        if question:
            # Create pending transaction if not exists
            pending = buffers.get_pending_transaction(user_id)
            if not pending:
                pending = buffers.create_pending_transaction(user_id, data)
            
            buffers.set_pending_question(
                user_id=user_id,
                question_type=question['question_type'],
                bot_message_id=ctx.message_id,
                expected_pattern=question['expected_pattern'],
                options=question.get('options'),
                context_data=data
            )
            buffers.update_pending_transaction(
                user_id=user_id,
                new_state=current_state,
                data_updates=data
            )
    
    # Update context
    ctx.current_state = current_state
    ctx.extracted_data = data
    
    logger.info(f"Layer 4: state={current_state}")
    
    return ctx
