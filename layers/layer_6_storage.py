"""
layer_6_storage.py - Storage & Wallet Mapping Logic

Layer 6 of the 7-layer architecture. Handles saving data to
Google Sheets with correct wallet/company mapping.

Features:
- Wallet structure understanding (3 dompets → 5 companies)
- Transaction type detection (wallet update vs project)
- Message ID tracking for revision
- Recent transaction retrieval for duplicate check

Based on Grand Design Ultimate lines 1204-1390.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ===================== WALLET STRUCTURE =====================

# Grand Design lines 1212-1226
WALLET_STRUCTURE = {
    "Dompet Evan": {
        "companies": ["TEXTURIN-Bali", "KANTOR"],
        "umum_prefix": "Dompet Evan"
    },
    "Dompet Holja": {
        "companies": ["HOLLA", "HOJJA"],
        "umum_prefix": "Dompet Holja"
    },
    "Dompet Texturin Sby": {
        "companies": ["TEXTURIN-Surabaya"],
        "umum_prefix": "Dompet Texturin Sby"
    }
}

# Reverse mapping: company → wallet
COMPANY_TO_WALLET = {}
for wallet, config in WALLET_STRUCTURE.items():
    for company in config["companies"]:
        COMPANY_TO_WALLET[company] = wallet


# ===================== HELPER FUNCTIONS =====================

def get_wallet_for_company(company: str) -> Optional[str]:
    """Get wallet name for a given company."""
    return COMPANY_TO_WALLET.get(company)


def get_all_companies() -> List[str]:
    """Get list of all valid company names."""
    companies = []
    for config in WALLET_STRUCTURE.values():
        companies.extend(config["companies"])
    return companies


def normalize_company_name(company: str) -> Optional[str]:
    """Normalize company name to official format."""
    if not company:
        return None
    
    company_lower = company.lower().strip()
    
    # Map common variations
    mappings = {
        'holla': 'HOLLA',
        'hojja': 'HOJJA',
        'texturin-bali': 'TEXTURIN-Bali',
        'texturin bali': 'TEXTURIN-Bali',
        'texturin-surabaya': 'TEXTURIN-Surabaya',
        'texturin surabaya': 'TEXTURIN-Surabaya',
        'texturin sby': 'TEXTURIN-Surabaya',
        'kantor': 'KANTOR',
        'umum': 'UMUM',
    }
    
    return mappings.get(company_lower, company)


# ===================== GOOGLE SHEETS INTEGRATION =====================

def get_sheets_helper():
    """Get sheets_helper module (lazy import to avoid circular deps)."""
    try:
        import sheets_helper
        return sheets_helper
    except ImportError:
        logger.error("sheets_helper not found")
        return None


def save_transaction(txn_data: Dict, user_id: str, message_id: str) -> Dict:
    """
    Save transaction to Google Sheets.
    
    Args:
        txn_data: Transaction data dict
        user_id: User who submitted
        message_id: Message ID for revision tracking
        
    Returns:
        Dict with result (success, row_number, etc.)
    """
    sheets = get_sheets_helper()
    if not sheets:
        return {"success": False, "error": "Sheets helper not available"}
    
    try:
        # Normalize data
        company = normalize_company_name(txn_data.get('company', 'UMUM'))
        wallet = txn_data.get('wallet') or get_wallet_for_company(company) or "Dompet Holja"
        
        # Use the existing sheets_helper functions
        # This integrates with the current codebase
        result = sheets.add_transaction(
            dompet_sheet=wallet,
            company=company,
            description=txn_data.get('description', ''),
            amount=txn_data.get('amount', 0),
            category=txn_data.get('category', 'Lain-lain'),
            project_name=txn_data.get('project_name', 'Saldo Umum'),
            transaction_type=txn_data.get('type', 'Pengeluaran'),
            date=txn_data.get('date', datetime.now().strftime('%Y-%m-%d')),
            source="WhatsApp",
            sender_name=user_id,
            message_id=message_id
        )
        
        logger.info(f"Saved transaction to {wallet}/{company}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to save transaction: {e}")
        return {"success": False, "error": str(e)}


def get_recent_transactions(
    user_id: str = None,
    days: int = 7,
    limit: int = 10
) -> List[Dict]:
    """
    Get recent transactions for duplicate checking.
    
    Args:
        user_id: Optional user filter
        days: Number of days to look back
        limit: Maximum number of transactions
        
    Returns:
        List of transaction dicts
    """
    sheets = get_sheets_helper()
    if not sheets:
        return []
    
    try:
        # Try to get recent transactions from sheets_helper
        if hasattr(sheets, 'get_recent_transactions'):
            return sheets.get_recent_transactions(days=days, limit=limit)
        
        # Fallback: get from each wallet sheet
        transactions = []
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        for wallet in WALLET_STRUCTURE.keys():
            try:
                # This would need to be implemented in sheets_helper
                wallet_txns = sheets.get_transactions_from_sheet(
                    sheet_name=wallet,
                    since_date=cutoff_date,
                    limit=limit
                )
                transactions.extend(wallet_txns or [])
            except:
                continue
        
        # Sort by date descending and limit
        transactions.sort(key=lambda x: x.get('date', ''), reverse=True)
        return transactions[:limit]
        
    except Exception as e:
        logger.error(f"Failed to get recent transactions: {e}")
        return []


def find_transaction_by_message_id(message_id: str) -> Optional[Dict]:
    """
    Find a transaction by its message ID (for revision).
    
    Returns:
        Transaction dict with sheet location or None
    """
    sheets = get_sheets_helper()
    if not sheets:
        return None
    
    try:
        if hasattr(sheets, 'find_transaction_by_message_id'):
            return sheets.find_transaction_by_message_id(message_id)
        return None
    except Exception as e:
        logger.error(f"Failed to find transaction: {e}")
        return None


def update_transaction_amount(
    message_id: str,
    new_amount: int
) -> Dict:
    """
    Update transaction amount for revision.
    
    Returns:
        Dict with result
    """
    sheets = get_sheets_helper()
    if not sheets:
        return {"success": False, "error": "Sheets helper not available"}
    
    try:
        if hasattr(sheets, 'update_transaction_amount'):
            return sheets.update_transaction_amount(message_id, new_amount)
        return {"success": False, "error": "Update not supported"}
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}")
        return {"success": False, "error": str(e)}


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 6 processing: Storage.
    
    Only runs when state is CONFIRMED_SAVE.
    
    Args:
        ctx: MessageContext from pipeline
        
    Returns:
        Enriched MessageContext with saved_transaction
    """
    from . import layer_2_context_engine
    
    # Only save when confirmed
    if ctx.current_state != "CONFIRMED_SAVE":
        return ctx
    
    txn_data = ctx.extracted_data or {}
    
    # Save transaction
    result = save_transaction(
        txn_data=txn_data,
        user_id=ctx.user_id,
        message_id=ctx.message_id
    )
    
    if result.get('success'):
        ctx.saved_transaction = result
        ctx.current_state = "SUCCESS"
        
        # Complete pending transaction
        buffers = layer_2_context_engine.get_buffers()
        buffers.complete_pending_transaction(ctx.user_id)
        
        logger.info(f"Layer 6: Transaction saved successfully")
    else:
        ctx.current_state = "ERROR"
        ctx.response_message = f"❌ Gagal menyimpan: {result.get('error', 'Unknown error')}"
        logger.error(f"Layer 6: Save failed - {result.get('error')}")
    
    return ctx
