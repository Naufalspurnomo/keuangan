"""
layer_6_storage.py - Storage & Wallet Mapping Layer

Layer 6 of the 7-layer architecture. Handles transaction storage
by integrating with proven sheets_helper module.

Features:
- Delegates to sheets_helper.append_transactions() for storage
- Wallet/company mapping using existing DOMPET_COMPANIES
- Recent transaction retrieval for duplicate detection
- Transaction tracking for revisions

Based on Grand Design Ultimate lines 1203-1330.
"""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ===================== WALLET MAPPING =====================

# Import existing mapping from sheets_helper
try:
    from sheets_helper import (
        DOMPET_SHEETS,
        DOMPET_COMPANIES,
        get_dompet_for_company,
        get_all_data,
        invalidate_dashboard_cache
    )
except ImportError:
    # Fallback definitions if sheets_helper not available
    DOMPET_SHEETS = ["Dompet Holja", "Dompet Texturin Sby", "Dompet Evan"]
    DOMPET_COMPANIES = {
        "Dompet Holja": ["HOLLA", "HOJJA"],
        "Dompet Texturin Sby": ["TEXTURIN-Surabaya"],
        "Dompet Evan": ["TEXTURIN-Bali", "KANTOR"]
    }
    
    def get_dompet_for_company(company: str) -> str:
        for dompet, companies in DOMPET_COMPANIES.items():
            if company in companies:
                return dompet
        return "Dompet Holja"  # Default


# Company name normalization
COMPANY_ALIASES = {
    'holla': 'HOLLA',
    'hojja': 'HOJJA',
    'holja': 'HOLLA',  # Common typo
    'texturin': 'TEXTURIN-Surabaya',
    'texturin sby': 'TEXTURIN-Surabaya',
    'texturin surabaya': 'TEXTURIN-Surabaya',
    'texturin bali': 'TEXTURIN-Bali',
    'kantor': 'KANTOR',
    'umum': 'UMUM',
}


def normalize_company_name(name: str) -> str:
    """Normalize company name to canonical form."""
    if not name:
        return ""
    
    key = name.lower().strip()
    return COMPANY_ALIASES.get(key, name)


def get_wallet_for_company(company: str) -> str:
    """Get wallet name for a company."""
    return get_dompet_for_company(company)


# ===================== STORAGE FUNCTIONS =====================

def save_transactions(
    transactions: List[Dict],
    sender_name: str,
    source: str,
    dompet: str,
    company: str,
    message_id: str = None
) -> Dict:
    """
    Save transactions using sheets_helper.
    
    Returns:
        Result dict with success status and details
    """
    try:
        from sheets_helper import append_transactions
        
        # Inject message_id for revision tracking
        if message_id:
            for t in transactions:
                t['message_id'] = message_id
        
        result = append_transactions(
            transactions=transactions,
            sender_name=sender_name,
            source=source,
            dompet_sheet=dompet,
            company=company
        )
        
        if result.get('success'):
            # Invalidate dashboard cache
            try:
                invalidate_dashboard_cache()
            except:
                pass
        
        return result
        
    except Exception as e:
        logger.error(f"Storage failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_recent_transactions(
    user_id: str = None,
    days: int = 7,
    limit: int = 20
) -> List[Dict]:
    """
    Get recent transactions for duplicate detection.
    
    Uses sheets_helper.get_all_data() with day filter.
    """
    try:
        from sheets_helper import get_all_data
        
        data = get_all_data(days=days)
        
        # Filter by user if specified
        if user_id and data:
            # Note: get_all_data returns 'recorded_by' field
            data = [d for d in data if d.get('recorded_by', '').find(user_id) >= 0]
        
        # Limit results
        if data and limit:
            data = data[-limit:]
        
        # Format for duplicate detection
        formatted = []
        for d in (data or []):
            formatted.append({
                'description': d.get('keterangan', ''),
                'amount': d.get('jumlah', 0),
                'date': d.get('tanggal', ''),
                'timestamp': d.get('tanggal', ''),
                'project_name': d.get('nama_projek', ''),
                'company': d.get('company', '')
            })
        
        return formatted
        
    except Exception as e:
        logger.error(f"Failed to get recent transactions: {e}")
        return []


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
    # Only save when confirmed
    if ctx.current_state != "CONFIRMED_SAVE":
        return ctx
    
    if not ctx.extracted_data:
        logger.warning("Layer 6: No extracted data to save")
        return ctx
    
    # Get dompet and company from context
    dompet = getattr(ctx, 'selected_dompet', None)
    company = getattr(ctx, 'selected_company', None)
    
    # Try to get from extracted data if not in context
    if not company and ctx.extracted_data:
        for t in ctx.extracted_data:
            if t.get('company'):
                company = t['company']
                break
    
    # Get dompet from company if not set
    if company and not dompet:
        dompet = get_wallet_for_company(company)
    
    if not dompet or not company:
        logger.warning("Layer 6: Missing dompet or company")
        ctx.current_state = "WAITING_COMPANY"
        return ctx
    
    # Determine source type
    source = "WhatsApp"
    if ctx.media_url:
        source = "WhatsApp Image"
    if ctx.is_group:
        source = f"{source} Group"
    
    # Save transactions
    result = save_transactions(
        transactions=ctx.extracted_data,
        sender_name=ctx.sender_name or "User",
        source=source,
        dompet=dompet,
        company=company,
        message_id=ctx.message_id
    )
    
    ctx.saved_transaction = result
    
    if result.get('success'):
        ctx.current_state = "SAVED"
        logger.info(f"Layer 6: Saved {result.get('rows_added', 0)} transactions to {dompet}/{company}")
    else:
        ctx.current_state = "SAVE_ERROR"
        ctx.save_error = result.get('error', 'Unknown error')
        logger.error(f"Layer 6: Save failed - {ctx.save_error}")
    
    return ctx
