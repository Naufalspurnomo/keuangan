import logging
import re
from typing import Dict, List, Optional
from sheets_helper import (
    find_all_transactions_by_message_id,
    update_transaction_amount,
    append_operational_transaction,
    append_project_transaction,
    delete_transaction_row,
    get_dompet_sheet
)
from services.state_manager import (
    set_pending_confirmation,
    clear_pending_confirmation,
    get_last_bot_report,
    get_original_message_id
)
from utils.formatters import build_selection_prompt
from utils.parsers import parse_revision_amount

logger = logging.getLogger(__name__)

def handle_revision_command(user_id: str, chat_id: str, text: str, 
                            quoted_message_id: str = None) -> dict:
    """
    Handle /revisi command or natural language revision.
    
    Supports:
    - /revisi 150rb (change amount)
    - /revisi operational (change category scope)
    - /revisi project Wooftopia (change project name)
    - "eh salah harusnya operational" (natural language)
    """
    
    text_lower = text.lower().strip()
    
    # Get last bot report message if no quoted message
    if not quoted_message_id:
        last_bot_msg = get_last_bot_report(chat_id)
        if last_bot_msg:
            quoted_message_id = last_bot_msg
    
    if not quoted_message_id:
        return {
            'action': 'REPLY',
            'response': '💡 Reply pesan laporan untuk merevisi, atau ketik /undo untuk batalkan transaksi terakhir.'
        }
    
    # Get original transaction ID (this is the original user message ID)
    original_tx_id = get_original_message_id(quoted_message_id)
    if not original_tx_id:
        # Check if quoted_message_id IS the original or if the mapping is stored differently
        # Sometimes quoted_message_id is the bot message ID, which maps to original ID
        original_tx_id = get_original_message_id(quoted_message_id)
        
        if not original_tx_id:
             return {
                'action': 'REPLY',
                'response': '❌ Data transaksi tidak ditemukan (ID mapping missing).'
            }
    
    # Fetch transactions from sheet
    items = find_all_transactions_by_message_id(original_tx_id)
    
    if not items:
        # One last try: maybe the quoted message IS the original message ID (from direct flow)?
        items = find_all_transactions_by_message_id(quoted_message_id)
        if items:
            original_tx_id = quoted_message_id

    if not items:
        return {
            'action': 'REPLY',
            'response': '❌ Data transaksi tidak ditemukan di spreadsheet.'
        }
    
    # ==========================================
    # DETECT REVISION TYPE
    # ==========================================
    
    # 1. Amount revision
    # Check digit char count to ensure it's not "1" or "2" for menu selection
    digit_count = sum(c.isdigit() for c in text)
    if digit_count > 0 and (digit_count > 1 or not text.isdigit()): 
        # Has number - likely amount revision (e.g. 50rb, 10000)
        # Exception: single digits 1-9 might be menu selections elsewhere, but here we assume revision context
        
        new_amount = parse_revision_amount(text)
        
        if new_amount:
            # For now, simplistic approach: update ALL items or ask?
            # User request says: "find matching item"
            # But usually we have 1 transaction per message. Sometime multiple.
            
            if len(items) == 1:
                target = items[0]
                success = update_transaction_amount(
                    target['dompet'], 
                    target['row'], 
                    new_amount
                )
                if success:
                    return {
                        'action': 'REPLY',
                        'response': f"✅ Revisi: {target.get('keterangan')} → Rp {new_amount:,}".replace(',', '.')
                    }
                else:
                    return {'action': 'REPLY', 'response': '❌ Gagal update spreadsheet.'}
            else:
                 # TODO: Match logic. For now, just ask which one.
                 # Simplified for User Request Step 105 compliance
                 pass

    # 2. Category scope revision (OPERATIONAL <-> PROJECT)
    if any(word in text_lower for word in ['operational', 'operasional', 'project', 'projek']):
        
        if 'operational' in text_lower or 'operasional' in text_lower:
            new_scope = 'OPERATIONAL'
        else:
            new_scope = 'PROJECT'
        
        # Check current scope of first item
        first_item = items[0]
        current_project_name = first_item.get('nama_projek', '')
        
        if current_project_name == 'Operasional Kantor':
             current_scope = 'OPERATIONAL'
        else:
             current_scope = 'PROJECT'
        
        if current_scope == new_scope:
            return {
                'action': 'REPLY',
                'response': f'ℹ️ Transaksi ini sudah tercatat sebagai {new_scope}.'
            }
        
        # LOGIC TO MOVE TRANSACTION
        # 1. Delete old rows
        # 2. Re-save as new type
        # But we need user input for the new type (e.g. which wallet? or which project name?)
        
        if new_scope == 'OPERATIONAL':
            # Ask for dompet source
            # First, delete old logic will happen AFTER confirmation? 
            # Or we store "revision_move" pending state
            
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'revision_move_to_operational',
                    'transactions': items,
                    'original_message_id': original_tx_id,
                    'event_id': original_tx_id
                }
            )
            
            return {
                'action': 'REPLY',
                'response': '🔄 Pindah ke Operational Kantor. Gunakan uang dari dompet mana?\n\n1. CV HB (101)\n2. TX SBY (216)\n3. TX BALI (087)\n\nBalas angka 1-3'
            }
        
        else:  # new_scope == 'PROJECT'
             # Ask for project name
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'revision_move_to_project',
                    'transactions': items,
                    'current_dompet': first_item.get('dompet'), # Suggest keeping same dompet?
                    'original_message_id': original_tx_id,
                    'event_id': original_tx_id
                }
            )
            
            return {
                'action': 'REPLY',
                'response': '🔄 Pindah ke Project. Nama projeknya apa?'
            }
            
    # 3. Generic "salah"
    if any(word in text_lower for word in ['salah', 'ralat', 'revisi', 'koreksi']):
        return {
            'action': 'REPLY',
            'response': '''🔄 Mau revisi apa?

1️⃣ Ubah nominal: /revisi 150rb
2️⃣ Pindah ke Operational: /revisi operational
3️⃣ Pindah ke Project: /revisi project
4️⃣ Hapus transaksi: /undo

Atau reply pesan ini dengan detail yang benar.'''
        }

    return None

def handle_undo_command(user_id: str, chat_id: str) -> dict:
    """
    Delete the last transaction created by this user.
    """
    
    # Get last bot report for this user/chat
    last_msg_id = get_last_bot_report(chat_id)
    
    if not last_msg_id:
        return {
            'action': 'REPLY',
            'response': '❌ Tidak ada transaksi terbaru untuk di-undo (Bot report not found).'
        }
    
    # Get original transaction ID
    original_tx_id = get_original_message_id(last_msg_id)
    
    if not original_tx_id:
         # Try direct check if user replied to bot message even if not cached as 'last'
         pass
         
    if not original_tx_id:
        return {
            'action': 'REPLY',
            'response': '❌ Data transaksi tidak ditemukan.'
        }
    
    # Fetch transactions
    items = find_all_transactions_by_message_id(original_tx_id)
    
    if not items:
        return {
            'action': 'REPLY',
            'response': '❌ Transaksi tidak ditemukan di spreadsheet (mungkin sudah dihapus manual).'
        }
    
    # Show preview and ask confirmation
    preview = '\n'.join([
        f"• {item.get('keterangan')} - Rp {item.get('amount'):,}"
        for item in items
    ]).replace(',', '.')
    
    total = sum(item.get('amount', 0) for item in items)
    
    # Set pending confirmation
    set_pending_confirmation(
        user_id=user_id,
        chat_id=chat_id,
        data={
            'type': 'undo_confirmation',
            'transactions': items,
            'original_message_id': original_tx_id
        }
    )
    
    return {
        'action': 'REPLY',
        'response': f'''⚠️ Hapus transaksi ini?

{preview}

Total: Rp {total:,}

Balas:
1️⃣ Ya, hapus
2️⃣ Batal

Peringatan: Data yang dihapus tidak bisa dikembalikan!'''
    }

def process_undo_deletion(items: list) -> dict:
    """Helper to execute deletion"""
    deleted_count = 0
    if not items:
        return {
            'response': '❌ Tidak ada transaksi untuk dihapus.',
            'completed': True
        }

    # Delete in descending row order per sheet to avoid row-shift issues
    items_by_dompet = {}
    target_count = 0
    for item in items:
        dompet = item.get('dompet')
        row = item.get('row')
        if not dompet or not row:
            continue
        target_count += 1
        items_by_dompet.setdefault(dompet, []).append(item)

    if target_count == 0:
        return {
            'response': '❌ Tidak ada transaksi yang valid untuk dihapus.',
            'completed': True
        }

    for dompet, dompet_items in items_by_dompet.items():
        dompet_items_sorted = sorted(dompet_items, key=lambda x: int(x.get('row') or 0), reverse=True)
        for item in dompet_items_sorted:
            row = item.get('row')
            success = delete_transaction_row(dompet, row)
            if success:
                deleted_count += 1
    
    if deleted_count == target_count:
        return {
            'response': f'✅ {deleted_count} transaksi berhasil dihapus.',
            'completed': True
        }
    else:
        return {
            'response': f'⚠️ {deleted_count}/{target_count} transaksi dihapus. Ada yang gagal.',
            'completed': True
        }

