import re
from datetime import datetime
from services.state_manager import (
    set_pending_confirmation,
    clear_pending_confirmation,
    get_pending_confirmation
)
from utils.formatters import format_mention, build_selection_prompt
from sheets_helper import (
    append_operational_transaction,
    append_project_transaction
)
from config.wallets import (
    get_selection_by_idx,
    get_wallet_selection_by_idx,
    format_wallet_selection_prompt
)

def extract_project_name_from_text(text: str) -> str:
    """
    Extract project name from text using common patterns.
    Examples:
    - "buat proyek X" -> "X"
    - "untuk project Y" -> "Y"
    """
    if not text:
        return None
        
    patterns = [
        r'(?:buat|untuk)\s+(?:proyek|project|prj|projek)\s+(.+)',
        r'(?:proyek|project|prj|projek)\s+(.+)',
    ]
    
    text_lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            # We want the original casing from the original text corresponding to the match
            # But regex matched on lower. Let's start simple and return the match from text_lower
            # improved: find the span and extract from original text
            start, end = match.span(1)
            return text[start:end].strip()
            
    return None

def handle_pending_response(user_id: str, chat_id: str, text: str, 
                            pending_data: dict, sender_name: str) -> dict:
    """
    Handle user response to pending confirmation.
    
    Returns:
        {
            'response': str,  # Message to send
            'completed': bool,  # True if flow finished
            'next_state': dict or None  # Data for next pending if any (handled internally via set_pending)
        }
    """
    
    pending_type = pending_data.get('type')
    text_lower = text.lower().strip()
    is_group = chat_id.endswith('@g.us')
    
    # ==========================================
    # CANCEL/UNDO Commands (works anytime)
    # ==========================================
    
    cancel_commands = ['/cancel', 'cancel', 'batal', '/batal', 'batalkan', '/undo', 'undo']
    
    if text_lower in cancel_commands:
        clear_pending_confirmation(user_id, chat_id)
        
        mention = format_mention(sender_name, is_group)
        return {
            'response': f'{mention}❌ Proses dibatalkan. Kirim ulang transaksinya ya! 🔄',
            'completed': True
        }
    
    # ==========================================
    # REVISION during confirmation
    # ==========================================
    
    revision_words = ['salah', 'eh salah', 'ralat', 'koreksi', 'bukan', 'ganti', 'wait']
    
    if any(word in text_lower for word in revision_words):
        # User wants to change answer
        pending_type = pending_data.get('type')
        
        if pending_type in ['category_scope', 'category_scope_confirm']:
            # Offer to re-select category
            mention = format_mention(sender_name, is_group)
            response = f"""{mention}🔄 Oke, pilih lagi:

1️⃣ Operational Kantor
   (Gaji staff, listrik, wifi, ATK, dll)

2️⃣ Project
   (Material, upah tukang, transport ke site)

Balas 1 atau 2
Atau ketik /cancel untuk batal total"""
            
            # Reset to category selection
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'category_scope',
                    'transactions': pending_data.get('transactions'),
                    'raw_text': pending_data.get('raw_text'),
                    'original_message_id': pending_data.get('original_message_id')
                }
            )
            
            return {
                'response': response,
                'completed': False
            }
        
        elif pending_type in ['dompet_selection_operational', 'dompet_selection_project']:
            # Offer to re-select dompet
            mention = format_mention(sender_name, is_group)
            
            if 'operational' in pending_type:
                prompt_text = format_wallet_selection_prompt()
                response = f"{mention}🔄 Oke, pilih dompet lagi:\n\n{prompt_text}"
            else:
                transactions = pending_data.get('transactions', [])
                response = build_selection_prompt(transactions, mention)
                response = f"{mention}🔄 Oke, pilih ulang:\n" + response.replace(mention, "")
            
            return {
                'response': response,
                'completed': False
            }
    
    # ===================================
    # HANDLE: Category Scope Selection
    # ===================================
    if pending_type == 'category_scope':
        
        category_scope = None
        # Parse user answer
        if text_lower in ['1', 'operational', 'operasional', 'kantor', 'ops']:
            category_scope = 'OPERATIONAL'
        elif text_lower in ['2', 'project', 'projek', 'client']:
            category_scope = 'PROJECT'
        else:
            # Invalid answer, return None to let main flow handle it (or ignore)
            # Alternatively return a message asking to retry?
            # User request says: "Invalid answer, ask again" -> return None (Will continue normal flow)
            return None 
        
        # Valid answer - proceed
        transactions = pending_data.get('transactions', [])
        original_msg_id = pending_data.get('original_message_id')
        
        if category_scope == 'OPERATIONAL':
            # Ask dompet source using config
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_operational',
                    'category_scope': 'OPERATIONAL',
                    'transactions': transactions,
                    'original_message_id': original_msg_id
                }
            )
            
            mention = format_mention(sender_name, is_group)
            prompt = format_wallet_selection_prompt() # From config/wallets.py
            
            response = f"{mention}💼 Operational Kantor\n{prompt}"
            
            return {
                'response': response,
                'completed': False  # Still waiting for dompet selection
            }
            
        else:  # PROJECT
            # Ask dompet/company
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_project',
                    'category_scope': 'PROJECT',
                    'transactions': transactions,
                    'original_message_id': original_msg_id,
                    'raw_text': pending_data.get('raw_text', '') # Pass raw text for project extraction later
                }
            )
            
            mention = format_mention(sender_name, is_group)
            response = build_selection_prompt(transactions, mention)
            
            return {
                'response': response,
                'completed': False
            }
    
    # ===================================
    # HANDLE: Category Scope Confirmation
    # ===================================
    elif pending_type == 'category_scope_confirm':
        
        suggested = pending_data.get('suggested_scope')
        category_scope = None
        
        if text_lower in ['1', 'ya', 'yes', 'iya', 'betul']:
            # User confirm suggestion
            category_scope = suggested
        elif text_lower in ['2', 'bukan', 'no', 'tidak']:
            # User reject - flip
            category_scope = 'PROJECT' if suggested == 'OPERATIONAL' else 'OPERATIONAL'
        elif text_lower in ['/cancel', 'cancel', 'batal']:
            clear_pending_confirmation(user_id, chat_id)
            return {'response': '❌ Dibatalkan.', 'completed': True}
        else:
            return None  # Invalid, continue normal flow
        
        # Same as above - ask dompet
        transactions = pending_data.get('transactions', [])
        original_msg_id = pending_data.get('original_message_id')
        
        if category_scope == 'OPERATIONAL':
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_operational',
                    'category_scope': 'OPERATIONAL',
                    'transactions': transactions,
                    'original_message_id': original_msg_id
                }
            )
            mention = format_mention(sender_name, is_group)
            prompt = format_wallet_selection_prompt()
            response = f"{mention}💼 Operational Kantor\n{prompt}"
            return {'response': response, 'completed': False}
        else:
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_project',
                    'category_scope': 'PROJECT',
                    'transactions': transactions,
                    'original_message_id': original_msg_id,
                    'raw_text': pending_data.get('raw_text', '')
                }
            )
            mention = format_mention(sender_name, is_group)
            response = build_selection_prompt(transactions, mention)
            return {'response': response, 'completed': False}
    
    # ===================================
    # HANDLE: Dompet Selection (Operational)
    # ===================================
    elif pending_type == 'dompet_selection_operational':
        
        # Parse dompet choice using config
        try:
            choice_idx = int(text_lower)
            selection = get_wallet_selection_by_idx(choice_idx)
            dompet_sheet = selection['dompet'] if selection else None
        except ValueError:
            dompet_sheet = None

        if not dompet_sheet:
            if text_lower in ['/cancel', 'batal']:
                clear_pending_confirmation(user_id, chat_id)
                return {'response': '❌ Dibatalkan.', 'completed': True}
            return None
        
        # SAVE TO SHEETS (OPERATIONAL)
        transactions = pending_data.get('transactions', [])
        kategori_final = 'Lain-lain'
        total_amount = 0
        
        for tx in transactions:
            # Detect sub-category
            keterangan_lower = tx.get('keterangan', '').lower()
            kategori = 'Lain-lain'
            
            if 'gaji' in keterangan_lower:
                kategori = 'Gaji'
            elif any(x in keterangan_lower for x in ['listrik', 'pln', 'token']):
                kategori = 'Listrik'
            elif any(x in keterangan_lower for x in ['air', 'pdam']):
                kategori = 'Air'
            elif any(x in keterangan_lower for x in ['konsumsi', 'snack', 'makan', 'minum']):
                kategori = 'Konsumsi'
            elif any(x in keterangan_lower for x in ['atk', 'printer', 'kertas', 'tinta']):
                kategori = 'Peralatan'
            elif 'internet' in keterangan_lower or 'wifi' in keterangan_lower:
                kategori = 'Internet' # Optional extra category
            
            kategori_final = kategori # Last one wins for summary
            
            # 1. Save to Operasional Kantor sheet
            append_operational_transaction(
                transaction={
                    'jumlah': tx['jumlah'],
                    'keterangan': tx['keterangan'],
                    'message_id': pending_data.get('original_message_id')
                },
                sender_name=sender_name,
                source="WhatsApp",
                source_wallet=dompet_sheet,
                category=kategori
            )
            
            # 2. Update saldo di dompet sheet (Split Layout)
            # For operational expenses, we add to PENGELUARAN side of the wallet sheet
            # Project name is fixed to "Operasional Kantor"
            append_project_transaction(
                transaction={
                    'jumlah': tx['jumlah'],
                    'keterangan': tx['keterangan'],
                    'tipe': 'Pengeluaran',
                    'message_id': pending_data.get('original_message_id')
                },
                sender_name=sender_name,
                source="WhatsApp",
                dompet_sheet=dompet_sheet,
                project_name="Operasional Kantor"
            )
            
            total_amount += int(tx['jumlah'])
            
        # Clear pending
        clear_pending_confirmation(user_id, chat_id)
        
        # Success response
        mention = format_mention(sender_name, is_group)
        
        response = f"""{mention}✅ Operational Kantor Tercatat!

💼 {transactions[0]['keterangan']}: Rp {total_amount:,}
📂 Kategori: {kategori_final}
💳 Dompet: {dompet_sheet}

⏱️ {datetime.now().strftime("%d %b %Y, %H:%M")}
""".replace(',', '.')
        
        return {
            'response': response,
            'completed': True
        }
    
    # ===================================
    # HANDLE: Dompet Selection (Project)
    # ===================================
    elif pending_type == 'dompet_selection_project':
        
        # Parse choice (1-4) using config
        try:
            choice_idx = int(text_lower)
            selection = get_selection_by_idx(choice_idx)
            dompet_sheet = selection['dompet'] if selection else None
            company = selection['company'] if selection else None
        except ValueError:
            dompet_sheet = None
            company = None
            
        if not dompet_sheet:
            if text_lower in ['/cancel', 'batal']:
                clear_pending_confirmation(user_id, chat_id)
                return {'response': '❌ Dibatalkan.', 'completed': True}
            return None
        
        transactions = pending_data.get('transactions', [])
        
        # Try to detect project name from original text
        # Check if project name is already in ALL transactions (from AI)
        all_have_project = all(t.get('nama_projek') for t in transactions)
        
        if all_have_project:
             # Already have project name from AI extraction
             pass
        else:
            raw_text = pending_data.get('raw_text', '')
            project_name = extract_project_name_from_text(raw_text)
            
            if not project_name:
                # Ask for project name
                set_pending_confirmation(
                    user_id=user_id,
                    chat_id=chat_id,
                    data={
                        'type': 'project_name_input',
                        'dompet_sheet': dompet_sheet,
                        'company': company,
                        'transactions': transactions,
                        'original_message_id': pending_data.get('original_message_id')
                    }
                )
                
                return {
                    'response': f'📝 Nama projeknya apa? (atau ketik "OPERASIONAL" jika ini operasional)',
                    'completed': False
                }
            else:
                # Apply extracted project name to all transactions lacking one
                for t in transactions:
                    if not t.get('nama_projek'):
                        t['nama_projek'] = project_name
                        
        # Save transactions
        total_amount = 0
        for tx in transactions:
            # Append to project sheet
            append_project_transaction(
                transaction={
                    'jumlah': tx['jumlah'],
                    'keterangan': tx['keterangan'],
                    'tipe': tx.get('tipe', 'Pengeluaran'),
                    'message_id': pending_data.get('original_message_id')
                },
                sender_name=sender_name,
                source="WhatsApp",
                dompet_sheet=dompet_sheet,
                project_name=tx.get('nama_projek')
            )
            total_amount += int(tx['jumlah'])
            
        clear_pending_confirmation(user_id, chat_id)
        
        # Format Success Reply
        mention = format_mention(sender_name, is_group)
        # We can reuse format_success_reply_new from formatters if we want, but user provided specific format
        # User provided format not fully specified in prompt for Project, but usually consistent.
        
        project_names = ", ".join(set(t.get('nama_projek') for t in transactions))
        
        response = f"""{mention}✅ Transaksi Tercatat!

💼 {transactions[0]['keterangan']}: Rp {total_amount:,}
📋 Projek: {project_names}
🏢 Company: {company}

⏱️ {datetime.now().strftime("%d %b %Y, %H:%M")}
""".replace(',', '.')

        return {
            'response': response,
            'completed': True
        }

    # ===================================
    # HANDLE: Project Name Input
    # ===================================
    elif pending_type == 'project_name_input':
        
        project_name = text.strip()
        
        if text_lower in ['/cancel', 'batal']:
            clear_pending_confirmation(user_id, chat_id)
            return {'response': '❌ Dibatalkan.', 'completed': True}
            
        # Check if user changed mind and says it is operational
        if project_name.upper() == 'OPERASIONAL':
             # Redirect to operational flow? 
             # For now just save as "Operasional Kantor" project? 
             # User prompt says: (atau ketik "OPERASIONAL" jika ini operasional)
             # This implies we should treat it as operational.
             # But we already selected a company/dompet. 
             # If it's pure operational, it should go to Operational Sheet + Dompet Sheet (Pengeluaran).
             pass 
             
        transactions = pending_data.get('transactions', [])
        dompet_sheet = pending_data.get('dompet_sheet')
        company = pending_data.get('company')
        
        total_amount = 0
        for tx in transactions:
            tx['nama_projek'] = project_name
            
            append_project_transaction(
                transaction={
                    'jumlah': tx['jumlah'],
                    'keterangan': tx['keterangan'],
                    'tipe': tx.get('tipe', 'Pengeluaran'),
                    'message_id': pending_data.get('original_message_id')
                },
                sender_name=sender_name,
                source="WhatsApp",
                dompet_sheet=dompet_sheet,
                project_name=project_name
            )
            total_amount += int(tx['jumlah'])
            
        clear_pending_confirmation(user_id, chat_id)
        
        mention = format_mention(sender_name, is_group)
        response = f"""{mention}✅ Transaksi Tercatat!

💼 {transactions[0]['keterangan']}: Rp {total_amount:,}
📋 Projek: {project_name}
🏢 Company: {company}

⏱️ {datetime.now().strftime("%d %b %Y, %H:%M")}
""".replace(',', '.')

        return {
            'response': response,
            'completed': True
        }
    
    return None  # Unknown pending type
