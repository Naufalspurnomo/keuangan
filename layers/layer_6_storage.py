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
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ===================== WALLET MAPPING =====================

# Import existing mapping from sheets_helper
try:
    from sheets_helper import (
        DOMPET_SHEETS,
        DOMPET_COMPANIES,
        get_dompet_for_company,
        get_all_data,
        invalidate_dashboard_cache,
        append_transactions,
        find_all_transactions_by_message_id,
        update_transaction_amount
    )
except ImportError:
    # Fallback definitions (mock/stub) if imports fail
    DOMPET_SHEETS = ["Dompet Holja", "Dompet Texturin Sby", "Dompet Evan"]
    DOMPET_COMPANIES = {}
    def get_dompet_for_company(c): return "Dompet Holja"
    def get_all_data(**kwargs): return []
    def invalidate_dashboard_cache(): pass
    def append_transactions(**kwargs): return {'success': False, 'error': 'ImportError'}
    def find_all_transactions_by_message_id(mid): return []
    def update_transaction_amount(d, r, a): return False


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


# ===================== PROCESS HANDLERS =====================

def process_revision(ctx) -> 'MessageContext':
    """Handle revision execution."""
    revision_data = getattr(ctx, 'revision_data', {})
    if not revision_data:
        ctx.current_state = 'ERROR'
        ctx.response_message = "❌ Data revisi tidak ditemukan."
        return ctx
        
    keyword = revision_data.get('keyword')
    amount = revision_data.get('amount')
    
    # 1. Find transactions
    txns = find_all_transactions_by_message_id(ctx.quoted_message_id)
    
    if not txns:
        ctx.current_state = 'ERROR'
        ctx.response_message = "❌ Transaksi asli tidak ditemukan di database."
        return ctx

    # 2. Match Item (Semantic Matching)
    try:
        from utils.semantic_matcher import find_matching_item
    except ImportError:
         ctx.current_state = 'ERROR'
         ctx.response_message = "❌ System Error: Matcher missing."
         return ctx
    
    match_result = find_matching_item(txns, keyword)
    
    if not match_result:
        # Ambiguous or no match
        # Provide list
        items_str = ", ".join([f"{t['keterangan']}" for t in txns[:3]])
        ctx.current_state = 'ERROR'
        ctx.response_message = f"❓ Tidak ketemu item yang cocok dengan '{keyword}'.\nOpsi: {items_str}..."
        return ctx
        
    target = match_result['matched_item']
    confidence = match_result['confidence']
    
    if confidence < 50:
        # Too low
        ctx.current_state = 'ERROR'
        ctx.response_message = f"❓ Kurang yakin. Maksudnya '{target['keterangan']}'? Mohon spesifik lagi."
        return ctx
        
    # 3. Execute Update
    success = update_transaction_amount(target['dompet'], target['row'], amount)
    
    if success:
        # Formatting difference
        old_amount_fmt = f"{target.get('jumlah', target.get('amount', 0)):,}".replace(',', '.')
        new_amount_fmt = f"{amount:,}".replace(',', '.')
        
        ctx.current_state = 'REVISION_DONE'
        ctx.response_message = (f"✅ Revisi Berhasil!\n"
                                f"📝 {target['keterangan']}\n"
                                f"💸 Rp {old_amount_fmt} → Rp {new_amount_fmt}")
        # Invalidate cache
        try:
             invalidate_dashboard_cache()
        except: pass
    else:
        ctx.current_state = 'ERROR'
        ctx.response_message = "❌ Gagal mengupdate spreadsheet."
     
    return ctx


def process_query(ctx) -> 'MessageContext':
    """Handle financial query execution."""
    try:
        params = getattr(ctx, 'query_params', {})
        period = params.get('period', 'today')
        q_type = params.get('type', 'summary')
        
        # Calculate Date Range
        now = datetime.now()
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        start_date = cutoff
        end_date = now + timedelta(days=1) # Default: Today to T+1 (cover all today)
        label = "Hari Ini"
        
        if period == 'yesterday':
            start_date = cutoff - timedelta(days=1)
            end_date = cutoff
            label = "Kemarin"
        elif period == 'week':
            start_date = cutoff - timedelta(days=cutoff.weekday()) # Previous Monday
            label = "Minggu Ini"
        elif period == 'month':
            start_date = cutoff.replace(day=1)
            label = "Bulan Ini"
        elif period == '30days':
            start_date = now - timedelta(days=30)
            label = "30 Hari Terakhir"
            
        # Fetch Data (Fetch extra days to be safe)
        days_to_fetch = (now - start_date).days + 5
        data = get_all_data(days=days_to_fetch)
        
        # Filter & Aggregate
        income = 0
        expense = 0
        tx_count = 0
        
        for t in data:
            try:
                # Parse date (sheets_helper returns YYYY-MM-DD usually)
                t_date_str = t.get('tanggal', '')
                try:
                    t_date = datetime.strptime(t_date_str, '%Y-%m-%d')
                except:
                    # Try other formats if needed, or skip
                    continue
                    
                t_date = t_date.replace(hour=0, minute=0, second=0, microsecond=0)
                
                if start_date <= t_date < end_date:
                    amt = int(t.get('jumlah', 0))
                    tipe = t.get('tipe', 'Pengeluaran').lower()
                    
                    if 'pemasukan' in tipe:
                        income += amt
                    else:
                        expense += amt
                    tx_count += 1
            except: continue
            
        profit = income - expense
        
        # Format Output
        msg = f"📊 *Laporan {label}*\n"
        msg += f"📅 {start_date.strftime('%d %b')} - {now.strftime('%d %b %Y')}\n\n"
        
        if q_type == 'income':
            msg += f"📈 Pemasukan: Rp {income:,}".replace(',', '.')
        elif q_type == 'expense':
            msg += f"📉 Pengeluaran: Rp {expense:,}".replace(',', '.')
        else: # Summary/Profit/Balance
            msg += f"📈 Pemasukan: Rp {income:,}\n".replace(',', '.')
            msg += f"📉 Pengeluaran: Rp {expense:,}\n".replace(',', '.')
            msg += f"------------------------\n"
            msg += f"💰 Profit/Loss: Rp {profit:,}".replace(',', '.')
            
        if tx_count == 0:
            msg += "\n\n(Belum ada transaksi)"
            
        ctx.response_message = msg
        ctx.current_state = 'QUERY_DONE'
        return ctx
        
    except Exception as e:
        logger.error(f"Query failed: {e}")
        ctx.current_state = 'ERROR'
        ctx.response_message = "❌ Gagal mengambil data laporan."
        return ctx


# ===================== MAIN PROCESSING =====================

def process(ctx) -> 'MessageContext':
    """
    Layer 6 processing: Storage.
    Only runs when state is CONFIRMED_SAVE, READY_TO_REVISE, or READY_TO_QUERY.
    """
    # 1. Routing
    if ctx.current_state == "READY_TO_REVISE":
        return process_revision(ctx)

    if ctx.current_state == "READY_TO_QUERY":
        return process_query(ctx)

    # 2. Storage Logic (CONFIRMED_SAVE)
    if ctx.current_state != "CONFIRMED_SAVE":
        # If not confirmed, we do nothing and return ctx as is
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
