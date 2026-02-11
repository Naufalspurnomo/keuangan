import re
from typing import Optional
from datetime import datetime
from services.state_manager import (
    set_pending_confirmation,
    clear_pending_confirmation,
    get_pending_confirmation,
    clear_pending_transaction,
    clear_visual_buffer
)
from utils.formatters import (
    build_selection_prompt,
    format_draft_summary_operational, format_draft_summary_project,
    format_success_reply_new, format_success_reply_operational
)
from utils.lifecycle import apply_lifecycle_markers, select_start_marker_indexes
from utils.parsers import parse_revision_amount
from utils.amounts import has_amount_pattern
from services.project_service import add_new_project_to_cache, resolve_project_name
from services.state_manager import set_project_lock
from sheets_helper import (
    append_operational_transaction,
    append_project_transaction,
    append_hutang_entry,
    update_hutang_status_by_no,
    settle_hutang,
    invalidate_dashboard_cache,
    delete_transaction_row
)
from config.wallets import (
    get_selection_by_idx,
    get_wallet_selection_by_idx,
    format_wallet_selection_prompt,
    get_company_name_from_sheet,
    apply_company_prefix,
    extract_company_prefix,
    strip_company_prefix,
    resolve_dompet_from_text
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


def _assign_tx_ids(transactions: list, event_id: str) -> list:
    """Assign deterministic tx_id based on event_id + index."""
    tx_ids = []
    base = event_id or f"evt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    for idx, tx in enumerate(transactions, start=1):
        tx_id = f"{base}|{idx}"
        tx['message_id'] = tx_id
        tx['tx_id'] = tx_id
        tx_ids.append(tx_id)
    return tx_ids


def _extract_debt_source(text: str) -> Optional[str]:
    if not text:
        return None
    lower = text.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", lower).strip()
    debt_pattern = r"\b(utang|hutang|minjem|minjam|pinjam)\b"
    if not re.search(debt_pattern, normalized):
        return None

    # Prefer explicit lender marker to avoid matching project/company words.
    prep_markers = ['dari', 'dr', 'ke', 'kepada', 'kpd', 'pakai', 'pake', 'via']
    for source_text in (lower, normalized):
        for prep in prep_markers:
            m = re.search(rf"\b{prep}\b(.+)", source_text)
            if m:
                candidate = resolve_dompet_from_text(m.group(1))
                if candidate:
                    return candidate

    # Fallback: parse only segment from debt keyword onward.
    for source_text in (lower, normalized):
        m = re.search(debt_pattern, source_text)
        if m:
            candidate = resolve_dompet_from_text(source_text[m.start():])
            if candidate:
                return candidate

    # Last resort full parse.
    return resolve_dompet_from_text(normalized) or resolve_dompet_from_text(lower)


def _format_hutang_paid_response(info: dict) -> str:
    """Format response for a settled hutang with balance details."""
    amount = int(info.get('amount', 0) or 0)
    borrower = info.get('yang_hutang', '-')
    lender = info.get('yang_dihutangi', '-')
    ket = info.get('keterangan', '-')

    lines = [
        f"✅ Hutang #{info['no']} ditandai PAID.",
        f"📝 {ket}",
        f"💰 {borrower} → {lender}",
        f"💵 Rp {amount:,}",
    ]
    if info.get('settled'):
        lines.append("")
        lines.append("📊 Saldo diperbarui:")
        lines.append(f"   💸 {borrower}: Pengeluaran Rp {amount:,}")
        lines.append(f"   💰 {lender}: Pemasukan Rp {amount:,}")

    return "\n".join(lines).replace(',', '.')


def _apply_project_prefix(transactions: list, dompet_sheet: str, company: str) -> None:
    for tx in transactions:
        pname = tx.get('nama_projek')
        if pname:
            tx['nama_projek'] = apply_company_prefix(pname, dompet_sheet, company)


def _continue_project_after_name(transactions: list, dompet_sheet: str, company: str,
                                 user_id: str, sender_name: str, source: str,
                                 original_message_id: str, event_id: str,
                                 is_new_project: bool, is_group: bool,
                                 chat_id: str, debt_source: Optional[str] = None,
                                 skip_first_expense: bool = False) -> dict:
    """Continue project flow after project name is resolved."""
    _apply_project_prefix(transactions, dompet_sheet, company)

    if is_new_project and not skip_first_expense and not any(t.get('tipe') == 'Pemasukan' for t in transactions):
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'new_project_first_expense',
                'transactions': transactions,
                'dompet': dompet_sheet,
                'company': company,
                'sender_name': sender_name,
                'source': source,
                'original_message_id': original_message_id,
                'event_id': event_id
            }
        )
        msg = (
            "\U0001F4C1 *PROJECT BARU*\n"
            "--------------------\n\n"
            f"Project *{transactions[0].get('nama_projek', '-') }* belum terdaftar.\n"
            "\U0001F4B8 *Transaksi: Pengeluaran*\n\n"
            "\U0001F4A1 Biasanya project baru dimulai dari *DP (Pemasukan)*\n\n"
            "--------------------\n"
            "Pilih tindakan:\n\n"
            "\u0031\ufe0f\u20e3 Lanjutkan sebagai project baru\n"
            "\u0032\ufe0f\u20e3 Ubah jadi Operasional Kantor\n"
            "\u0033\ufe0f\u20e3 Batal"
        )
        return {'response': msg, 'completed': False}

    set_pending_confirmation(
        user_id=user_id,
        chat_id=chat_id,
        data={
            'type': 'confirm_commit_project',
            'transactions': transactions,
            'dompet': dompet_sheet,
            'company': company,
            'debt_source_dompet': debt_source,
            'sender_name': sender_name,
            'source': source,
            'original_message_id': original_message_id,
            'event_id': event_id,
            'is_new_project': is_new_project
        }
    )

    response = format_draft_summary_project(
        transactions, dompet_sheet, company, "", debt_source or ""
    )
    return {'response': response, 'completed': False}


def _detect_operational_category(keterangan: str) -> str:
    keterangan_lower = (keterangan or "").lower()
    if 'gaji' in keterangan_lower:
        return 'Gaji'
    if any(x in keterangan_lower for x in ['listrik', 'pln', 'token']):
        return 'ListrikAir'
    if any(x in keterangan_lower for x in ['air', 'pdam']):
        return 'ListrikAir'
    if any(x in keterangan_lower for x in ['konsumsi', 'snack', 'makan', 'minum']):
        return 'Konsumsi'
    if any(x in keterangan_lower for x in ['atk', 'printer', 'kertas', 'tinta']):
        return 'Peralatan'
    if 'internet' in keterangan_lower or 'wifi' in keterangan_lower:
        return 'ListrikAir'
    return 'Lain Lain'


def _first_invalid_amount_tx(transactions: list) -> Optional[dict]:
    for tx in transactions or []:
        try:
            amt = int(tx.get('jumlah', 0) or 0)
        except Exception:
            amt = 0
        if tx.get('needs_amount') or amt <= 0:
            return tx
    return None


def _commit_project_transactions(pending_data: dict, sender_name: str, user_id: str, chat_id: str, is_group: bool) -> dict:
    """Commit project transactions with lifecycle markers and cleanup."""
    transactions = pending_data.get('transactions', [])
    dompet_sheet = pending_data.get('dompet')
    company = pending_data.get('company')
    event_id = pending_data.get('event_id') or pending_data.get('original_message_id')
    is_new_project = pending_data.get('is_new_project', False)
    finish_decision = pending_data.get('finish_decision')
    allow_finish = finish_decision != 'SKIP'
    debt_source = pending_data.get('debt_source_dompet')

    missing_tx = _first_invalid_amount_tx(transactions)
    if missing_tx:
        item = missing_tx.get('keterangan', 'Transaksi')
        return {
            'response': f"❗ Nominal untuk \"{item}\" belum valid. Balas nominal dulu (contoh: 150rb).",
            'completed': False
        }

    _assign_tx_ids(transactions, event_id)

    is_new_project_batch = bool(is_new_project)
    start_marker_indexes = (
        select_start_marker_indexes(transactions) if is_new_project_batch else set()
    )

    for idx, tx in enumerate(transactions):
        p_name = tx.get('nama_projek', '') or 'Umum'
        p_name = apply_company_prefix(p_name, dompet_sheet, company)
        p_name = apply_lifecycle_markers(
            p_name,
            tx,
            is_new_project=is_new_project_batch,
            allow_finish=allow_finish,
            allow_start=(not is_new_project_batch) or (idx in start_marker_indexes),
        )

        append_project_transaction(
            transaction={
                'jumlah': tx['jumlah'],
                'keterangan': tx['keterangan'],
                'tipe': tx.get('tipe', 'Pengeluaran'),
                'message_id': tx.get('message_id')
            },
            sender_name=sender_name,
            source=pending_data.get('source', 'WhatsApp'),
            dompet_sheet=dompet_sheet,
            project_name=p_name
        )

    # If transaction is funded by another dompet (utang), record source outflow
    if debt_source and debt_source != dompet_sheet:
        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in transactions)
        if total_amount > 0:
            debt_desc = f"Hutang ke dompet {dompet_sheet}"
            append_project_transaction(
                transaction={
                    'jumlah': total_amount,
                    'keterangan': debt_desc,
                    'tipe': 'Pengeluaran',
                    'message_id': f"{event_id}|UTANG"
                },
                sender_name=sender_name,
                source=pending_data.get('source', 'WhatsApp'),
                dompet_sheet=debt_source,
                project_name="Saldo Umum"
            )
            append_hutang_entry(
                amount=total_amount,
                keterangan=transactions[0].get('keterangan', '') if transactions else '',
                yang_hutang=dompet_sheet,
                yang_dihutangi=debt_source,
                message_id=f"{event_id}|HUTANG"
            )

    # If this is a revision move, delete old rows after re-save
    if pending_data.get('revision_delete'):
        for item in pending_data.get('revision_delete', []):
            delete_transaction_row(item.get('dompet'), item.get('row'))

    # Update project cache if new
    if is_new_project:
        raw_proj = transactions[0].get('nama_projek')
        if raw_proj:
            add_new_project_to_cache(raw_proj)

    invalidate_dashboard_cache()
    clear_pending_confirmation(user_id, chat_id)
    if pending_data.get('pending_key'):
        clear_pending_transaction(pending_data.get('pending_key'))

    response = format_success_reply_new(transactions, dompet_sheet, company, "").replace('*', '')
    tx_ids = [t.get('tx_id') for t in transactions if t.get('tx_id')]
    if tx_ids:
        response += f"\nðŸ†” TX: {', '.join(tx_ids)}"
    if debt_source and debt_source != dompet_sheet:
        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in transactions)
        response += f"\nðŸ’³ Utang dicatat: {debt_source} â†’ {dompet_sheet} (Rp {total_amount:,})".replace(',', '.')

    # Lock project to dompet for consistency
    for t in transactions:
        pname = t.get('nama_projek')
        if pname and pname.lower() not in ['saldo umum', 'operasional kantor', 'umum', 'unknown']:
            set_project_lock(pname, dompet_sheet, actor=sender_name, reason="commit")

    return {'response': response, 'completed': True, 'bot_ref_event_id': event_id}

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
    event_id = pending_data.get('event_id') or pending_data.get('original_message_id')

    def _format_hutang_selection(candidates: list) -> str:
        items = candidates or []
        lines = ["🤔 Ketemu beberapa hutang OPEN. Pilih yang mau dilunasi:"]
        for idx, item in enumerate(items, start=1):
            amount = int(item.get('amount', 0) or 0)
            no = str(item.get('no', '-') or '-')
            borrower = str(item.get('yang_hutang', '-') or '-')
            lender = str(item.get('yang_dihutangi', '-') or '-')
            ket = str(item.get('keterangan', '-') or '-')
            lines.append(f"{idx}. #{no} {borrower} → {lender} Rp {amount:,} ({ket})")
        lines.append("")
        if len(items) == 1:
            lines.append("Balas Ya atau angka 1 untuk lunasi.")
            lines.append("Balas Batal untuk cancel.")
        else:
            lines.append(f"Balas angka 1-{len(items)} (langsung lunas).")
            lines.append("Ketik /cancel untuk batal.")
        return "\n".join(lines).replace(',', '.')
    
    # ==========================================
    # CANCEL/UNDO Commands (works anytime)
    # ==========================================
    
    cancel_commands = ['/cancel', 'cancel', 'batal', '/batal', 'batalkan', '/undo', 'undo']
    
    if text_lower in cancel_commands:
        clear_pending_confirmation(user_id, chat_id)
        clear_visual_buffer(user_id, chat_id)
        
        return {
            'response': '❌ Proses dibatalkan. Kirim ulang transaksinya ya! 🔄',
            'completed': True
        }

    # ==========================================
    # HANDLE: Undo Confirmation
    # ==========================================
    if pending_type == 'undo_confirmation':
        clean = text_lower.replace('.', '').replace(',', '').strip()
        clean = re.sub(r"\s+", " ", clean)
        confirm_words = {'1', 'ya', 'iya', 'y', 'yes', 'hapus', 'ok', 'oke'}
        cancel_words = {'2', 'batal', 'cancel', 'tidak', 'no'}

        if clean in cancel_words or any(word in clean for word in ['batal', 'cancel', 'tidak', 'no']):
            clear_pending_confirmation(user_id, chat_id)
            return {
                'response': 'Batal hapus.',
                'completed': True
            }

        if clean in confirm_words or clean.startswith('ya ') or clean.startswith('iya ') or 'hapus' in clean:
            from handlers.revision_handler import process_undo_deletion

            result = process_undo_deletion(
                pending_data.get('transactions', []),
                pending_data.get('original_message_id')
            )
            clear_pending_confirmation(user_id, chat_id)
            return {
                'response': result.get('response', 'Transaksi dihapus.'),
                'completed': True
            }

        return {
            'response': 'Balas *1* untuk hapus atau *2* untuk batal.',
            'completed': False
        }

    # ==========================================
    # HANDLE: Hutang Payment Selection (Quick pick)
    # ==========================================
    if pending_type == 'hutang_payment_selection':
        candidates = pending_data.get('candidates') or []
        if not candidates:
            clear_pending_confirmation(user_id, chat_id)
            return {
                'response': '⚠️ Daftar hutang sudah tidak tersedia. Ulangi perintah bayar hutang.',
                'completed': True
            }

        clean = re.sub(r"\s+", " ", text_lower.replace('.', '').replace(',', '').strip())
        confirm_words = {'ya', 'iya', 'y', 'yes', 'ok', 'oke', 'lanjut', 'lunas', '1'}
        cancel_words = {'batal', 'cancel', 'tidak', 'no', 'gak', 'enggak'}
        if clean in cancel_words or any(w in clean for w in ['batal', 'cancel', 'tidak', 'no']):
            clear_pending_confirmation(user_id, chat_id)
            return {
                'response': 'Pelunasan hutang dibatalkan.',
                'completed': True
            }

        if len(candidates) == 1 and (clean in confirm_words or clean.startswith('ya ') or clean.startswith('iya ')):
            choice = 1
        else:
            choice = None

        m = re.search(r"(?<!\d)(\d{1,2})(?!\d)", text_lower)
        if choice is None and not m:
            return {
                'response': _format_hutang_selection(candidates),
                'completed': False
            }

        if choice is None:
            choice = int(m.group(1))
        if choice < 1 or choice > len(candidates):
            return {
                'response': f"Balas angka 1-{len(candidates)} atau /cancel.",
                'completed': False
            }

        selected = candidates[choice - 1]
        no_raw = str(selected.get('no', '') or '').strip()
        if not no_raw.isdigit():
            clear_pending_confirmation(user_id, chat_id)
            return {
                'response': '⚠️ Nomor hutang tidak valid. Ulangi perintah bayar hutang.',
                'completed': True
            }

        info = settle_hutang(int(no_raw), sender_name=sender_name, source='WhatsApp')
        if not info:
            clear_pending_confirmation(user_id, chat_id)
            return {
                'response': f"❌ Hutang #{no_raw} tidak ditemukan atau sudah lunas.",
                'completed': True
            }

        invalidate_dashboard_cache()
        clear_pending_confirmation(user_id, chat_id)
        response = _format_hutang_paid_response(info)
        return {'response': response, 'completed': True}

    # ==========================================
    # REVISION during confirmation
    # ==========================================
    
    revision_words = ['salah', 'eh salah', 'ralat', 'koreksi', 'bukan', 'ganti', 'wait']
    
    if any(word in text_lower for word in revision_words):
        # User wants to change answer
        pending_type = pending_data.get('type')
        
        if pending_type in ['category_scope', 'category_scope_confirm']:
            # Offer to re-select category
            response = """🔄 Oke, pilih lagi:

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
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': event_id
                }
            )
            
            return {
                'response': response,
                'completed': False
            }
        
        elif pending_type in ['dompet_selection_operational', 'dompet_selection_project']:
            # Offer to re-select dompet
            
            if 'operational' in pending_type:
                prompt_text = format_wallet_selection_prompt()
                response = f"🔄 Oke, pilih dompet lagi:\n\n{prompt_text}"
            else:
                transactions = pending_data.get('transactions', [])
                response = build_selection_prompt(transactions, "")
                response = "🔄 Oke, pilih ulang:\n" + response
            
            return {
                'response': response,
                'completed': False
            }
    
    # ===================================
    # HANDLE: Category Scope Selection
    # ===================================
    if pending_type == 'category_scope':
        
        category_scope = None
        raw_text = pending_data.get('raw_text', '')
        debt_source = _extract_debt_source(raw_text)
        # Parse user answer (accept tokens inside longer text)
        if any(k in text_lower for k in ['operational', 'operasional', 'kantor', 'ops']):
            category_scope = 'OPERATIONAL'
        elif any(k in text_lower for k in ['project', 'projek', 'client']):
            category_scope = 'PROJECT'
        else:
            # Try to detect numeric choice embedded in text (e.g., "... 2")
            m = re.search(r"(?<!\d)[12](?![\d.,])", text_lower)
            if m:
                category_scope = 'OPERATIONAL' if m.group(0) == '1' else 'PROJECT'
        if not category_scope:
            return {
                'response': 'Balas 1 untuk Operational atau 2 untuk Project. Ketik /cancel untuk batal.',
                'completed': False
            }
        
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
                    'original_message_id': original_msg_id,
                    'event_id': event_id,
                    'raw_text': pending_data.get('raw_text', '')
                }
            )
            
            prompt = format_wallet_selection_prompt() # From config/wallets.py
            
            response = f"Operational Kantor\n{prompt}"
            
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
                    'event_id': event_id,
                    'raw_text': raw_text, # Pass raw text for project extraction later
                    'debt_source_dompet': debt_source
                }
            )
            
            response = build_selection_prompt(transactions, "")
            
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
        raw_text = pending_data.get('raw_text', '')
        debt_source = _extract_debt_source(raw_text)
        
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
            return {
                'response': 'Balas 1 untuk setuju atau 2 untuk ganti pilihan. Ketik /cancel untuk batal.',
                'completed': False
            }
        
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
                    'original_message_id': original_msg_id,
                    'event_id': event_id,
                    'raw_text': pending_data.get('raw_text', '')
                }
            )
            prompt = format_wallet_selection_prompt()
            response = f"Operational Kantor\n{prompt}"
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
                    'event_id': event_id,
                    'raw_text': raw_text,
                    'debt_source_dompet': debt_source
                }
            )
            response = build_selection_prompt(transactions, "")
            return {'response': response, 'completed': False}
    
    # ===================================
    # HANDLE: Dompet Selection (Operational)
    # ===================================
    elif pending_type == 'dompet_selection_operational':
        
        # Switch to Project if user says so
        if text_lower == '4' or 'project' in text_lower or 'projek' in text_lower:
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_project',
                    'category_scope': 'PROJECT',
                    'transactions': pending_data.get('transactions', []),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id'),
                    'raw_text': pending_data.get('raw_text', ''),
                    'debt_source_dompet': pending_data.get('debt_source_dompet')
                }
            )
            response = build_selection_prompt(pending_data.get('transactions', []), "")
            return {'response': response, 'completed': False}
        
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
            return {
                'response': 'Pilih angka 1-4 untuk dompet operasional, atau ketik /cancel.',
                'completed': False
            }
        
        # Draft → Confirm → Commit
        transactions = pending_data.get('transactions', [])
        if pending_data.get('category'):
            kategori_final = pending_data.get('category')
        else:
            kategori_final = _detect_operational_category(transactions[0].get('keterangan', '') if transactions else '')
        
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'confirm_commit_operational',
                'transactions': transactions,
                'source_wallet': dompet_sheet,
                'category': kategori_final,
                'sender_name': sender_name,
                'source': pending_data.get('source', 'WhatsApp'),
                'original_message_id': pending_data.get('original_message_id'),
                'event_id': pending_data.get('event_id')
            }
        )
        
        response = format_draft_summary_operational(
            transactions, dompet_sheet, kategori_final, ""
        )
        
        return {
            'response': response,
            'completed': False
        }
    
    # ===================================
    # HANDLE: Dompet Selection (Project)
    # ===================================
    elif pending_type == 'dompet_selection_project':
        
        # Switch to Operational if user says so
        if text_lower == '5' or any(k in text_lower for k in ['operasional', 'kantor', 'operational', 'ops']):
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_operational',
                    'category_scope': 'OPERATIONAL',
                    'transactions': pending_data.get('transactions', []),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id'),
                    'raw_text': pending_data.get('raw_text', '')
                }
            )
            prompt = format_wallet_selection_prompt()
            return {'response': f"Operational Kantor\n{prompt}", 'completed': False}
        
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
            return {
                'response': 'Pilih angka 1-5 sesuai opsi, atau ketik /cancel.',
                'completed': False
            }
        
        transactions = pending_data.get('transactions', [])
        
        # Try to detect project name from original text
        # Check if project name is already in ALL transactions (from AI)
        all_have_project = all(t.get('nama_projek') for t in transactions)
        raw_text = pending_data.get('raw_text', '')
        debt_source = pending_data.get('debt_source_dompet')
        if not debt_source:
            debt_source = _extract_debt_source(raw_text)
        if debt_source == dompet_sheet:
            debt_source = None

        if all_have_project:
             # Already have project name from AI extraction
             pass
        else:
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
                        'raw_text': raw_text,
                        'debt_source_dompet': debt_source,
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
        
        _apply_project_prefix(transactions, dompet_sheet, company)
                        
        # Draft → Confirm → Commit
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'confirm_commit_project',
                'transactions': transactions,
                'dompet': dompet_sheet,
                'company': company,
                'debt_source_dompet': debt_source,
                'sender_name': sender_name,
                'source': pending_data.get('source', 'WhatsApp'),
                'original_message_id': pending_data.get('original_message_id'),
                'event_id': pending_data.get('event_id'),
                'raw_text': raw_text
            }
        )
        
        response = format_draft_summary_project(
            transactions, dompet_sheet, company, "", debt_source or ""
        )

        return {
            'response': response,
            'completed': False
        }

    # ===================================
    # HANDLE: Project Name Input
    # ===================================
    elif pending_type == 'project_name_input':
        
        project_name = text.strip()
        dompet_sheet = pending_data.get('dompet_sheet')
        company = pending_data.get('company')
        raw_text = pending_data.get('raw_text', '')
        debt_source = pending_data.get('debt_source_dompet')
        if not debt_source:
            debt_source = _extract_debt_source(raw_text)
            if debt_source == dompet_sheet:
                debt_source = None
        
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
             # If it's pure operational, it should be recorded in Operasional Ktr only.
             pass 
        
        prefix = extract_company_prefix(project_name)
        lookup_name = strip_company_prefix(project_name) if prefix else project_name
        res = resolve_project_name(lookup_name)
        
        # If ambiguous, ask confirmation
        if res.get('status') == 'AMBIGUOUS' and int(res.get('match_count', 2) or 2) != 1:
            suggested = res.get('final_name')
            if prefix:
                suggested = f"{prefix} - {suggested}".strip()
            else:
                suggested = apply_company_prefix(suggested, dompet_sheet, company)
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'project_name_confirm',
                    'suggested_project': suggested,
                    'transactions': pending_data.get('transactions', []),
                    'dompet_sheet': dompet_sheet,
                    'company': company,
                    'raw_text': raw_text,
                    'debt_source_dompet': debt_source,
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            return {
                'response': f"🤔 Maksudnya **{suggested}**?\n✅ Ya / ❌ Bukan".replace('*', ''),
                'completed': False
            }
        
        final_base = res.get('final_name') or lookup_name
        if prefix:
            final_name = f"{prefix} - {final_base}".strip()
        else:
            final_name = apply_company_prefix(final_base, dompet_sheet, company)
        is_new_project = (res.get('status') == 'NEW')
        transactions = pending_data.get('transactions', [])

        for tx in transactions:
            tx['nama_projek'] = final_name
        
        if is_new_project:
            display_name = res.get('original') or lookup_name
            is_first_expense = not any(t.get('tipe') == 'Pemasukan' for t in transactions)
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'project_new_confirm',
                    'project_name': final_name,
                    'project_display': display_name,
                    'new_project_first_expense': is_first_expense,
                    'transactions': transactions,
                    'dompet_sheet': dompet_sheet,
                    'company': company,
                    'raw_text': raw_text,
                    'debt_source_dompet': debt_source,
                    'sender_name': sender_name,
                    'source': pending_data.get('source', 'WhatsApp'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            if is_first_expense:
                prompt = (
                    "\U0001F4C1 *PROJECT BARU*\n"
                    "--------------------\n\n"
                    f"Project *{display_name}* belum terdaftar.\n"
                    "\U0001F4B8 *Transaksi: Pengeluaran*\n\n"
                    "\U0001F4A1 Biasanya project baru dimulai dari *DP (Pemasukan)*\n\n"
                    "--------------------\n"
                    "Pilih tindakan:\n\n"
                    "\u0031\ufe0f\u20e3 Lanjutkan sebagai project baru\n"
                    "\u0032\ufe0f\u20e3 Ubah jadi Operasional Kantor\n"
                    "\u0033\ufe0f\u20e3 Batal\n\n"
                    "Atau ketik *nama lain* untuk ganti"
                )
            else:
                prompt = (
                    "\U0001F4C1 *PROJECT BARU*\n"
                    "--------------------\n\n"
                    f"Project *{display_name}* belum terdaftar.\n\n"
                    "--------------------\n"
                    "Pilih tindakan:\n\n"
                    "Ya - *Buat project baru*\n"
                    "Ketik nama lain untuk ganti\n\n"
                    "Balas *Ya* atau ketik nama baru"
                )
            return {'response': prompt, 'completed': False}

        for tx in transactions:
            tx['nama_projek'] = apply_company_prefix(final_name, dompet_sheet, company)
        # Draft → Confirm → Commit
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'confirm_commit_project',
                'transactions': transactions,
                'dompet': dompet_sheet,
                'company': company,
                'debt_source_dompet': debt_source,
                'sender_name': sender_name,
                'source': pending_data.get('source', 'WhatsApp'),
                'original_message_id': pending_data.get('original_message_id'),
                'event_id': pending_data.get('event_id'),
                'is_new_project': is_new_project,
                'raw_text': raw_text
            }
        )
        
        response = format_draft_summary_project(
            transactions, dompet_sheet, company, "", debt_source or ""
        )

        return {
            'response': response,
            'completed': False
        }

    # ===================================
    # HANDLE: Project Name Confirm (Ambiguous)
    # ===================================
    elif pending_type == 'project_name_confirm':
        clean = text_lower.strip()
        if clean in ['ya', 'y', 'yes', 'oke', 'ok']:
            final_name = pending_data.get('suggested_project')
        else:
            # Ask retype
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'project_name_input',
                    'dompet_sheet': pending_data.get('dompet_sheet'),
                    'company': pending_data.get('company'),
                    'transactions': pending_data.get('transactions', []),
                    'raw_text': pending_data.get('raw_text', ''),
                    'debt_source_dompet': pending_data.get('debt_source_dompet'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            return {'response': '📝 Nama projek yang benar apa?', 'completed': False}
        
        transactions = pending_data.get('transactions', [])
        dompet_sheet = pending_data.get('dompet_sheet')
        company = pending_data.get('company')

        debt_source = pending_data.get('debt_source_dompet')
        if not debt_source:
            raw_text = pending_data.get('raw_text', '')
            debt_source = _extract_debt_source(raw_text)
            if debt_source == dompet_sheet:
                debt_source = None
        combined = bool(pending_data.get('new_project_first_expense'))
        
        for tx in transactions:
            tx['nama_projek'] = final_name
        
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'confirm_commit_project',
                'transactions': transactions,
                'dompet': dompet_sheet,
                'company': company,
                'debt_source_dompet': debt_source,
                'sender_name': sender_name,
                'source': pending_data.get('source', 'WhatsApp'),
                'original_message_id': pending_data.get('original_message_id'),
                'event_id': pending_data.get('event_id'),
                'raw_text': pending_data.get('raw_text', '')
            }
        )
        
        response = format_draft_summary_project(
            transactions, dompet_sheet, company, "", debt_source or ""
        )
        return {'response': response, 'completed': False}

    # ===================================
    # HANDLE: Project New Confirm
    # ===================================
    elif pending_type == 'project_new_confirm':
        clean = text_lower
        dompet_sheet = pending_data.get('dompet_sheet')
        company = pending_data.get('company')
        transactions = pending_data.get('transactions', [])
        project_name = pending_data.get('project_name')
        combined = bool(pending_data.get('new_project_first_expense'))
        debt_source = pending_data.get('debt_source_dompet')
        if not debt_source:
            raw_text = pending_data.get('raw_text', '')
            debt_source = _extract_debt_source(raw_text)
            if debt_source == dompet_sheet:
                debt_source = None

        if combined:
            if clean in ['1', 'ya', 'y', 'yes', 'oke', 'ok', 'buat', 'lanjut']:
                return _continue_project_after_name(
                    transactions, dompet_sheet, company,
                    user_id, sender_name, pending_data.get('source', 'WhatsApp'),
                    pending_data.get('original_message_id'), pending_data.get('event_id'),
                    True, is_group, chat_id, debt_source, skip_first_expense=True
                )
            if clean in ['2', 'operasional', 'kantor']:
                set_pending_confirmation(
                    user_id=user_id,
                    chat_id=chat_id,
                    data={
                        'type': 'confirm_commit_operational',
                        'transactions': transactions,
                        'source_wallet': dompet_sheet,
                        'category': 'Lain Lain',
                        'sender_name': sender_name,
                        'source': pending_data.get('source', 'WhatsApp'),
                        'original_message_id': pending_data.get('original_message_id'),
                        'event_id': pending_data.get('event_id'),
                        'pending_key': pending_data.get('pending_key')
                    }
                )
                response = format_draft_summary_operational(
                    transactions, dompet_sheet, 'Lain Lain', ""
                )
                return {'response': response, 'completed': False}
            if clean in ['3', 'batal', 'cancel', 'tidak', 'no']:
                clear_pending_confirmation(user_id, chat_id)
                if pending_data.get('pending_key'):
                    clear_pending_transaction(pending_data.get('pending_key'))
                return {'response': 'âŒ Dibatalkan.', 'completed': True}
            if clean.isdigit():
                return {'response': 'Balas 1/2/3 atau ketik nama project baru.', 'completed': False}

        if not combined and clean.isdigit() and len(clean) <= 2 and clean not in ['1']:
            return {'response': "Balas 'Ya' untuk membuat project baru, atau ketik nama project yang benar.", 'completed': False}

        if clean in ['1', 'ya', 'y', 'yes', 'oke', 'ok', 'buat', 'lanjut']:
            # Proceed as new project
            return _continue_project_after_name(
                transactions, dompet_sheet, company,
                user_id, sender_name, pending_data.get('source', 'WhatsApp'),
                pending_data.get('original_message_id'), pending_data.get('event_id'),
                True, is_group, chat_id, debt_source
            )

        if clean in ['tidak', 'no', 'ganti', 'bukan', 'salah']:
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'project_name_input',
                    'dompet_sheet': dompet_sheet,
                    'company': company,
                    'transactions': transactions,
                    'raw_text': pending_data.get('raw_text', ''),
                    'debt_source_dompet': debt_source,
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            return {'response': '📝 Nama projeknya apa?', 'completed': False}

        # Treat other input as new project name
        new_name = text.strip()
        if not new_name:
            return {'response': '📝 Nama projeknya apa?', 'completed': False}

        prefix = extract_company_prefix(new_name)
        lookup_name = strip_company_prefix(new_name) if prefix else new_name
        res = resolve_project_name(lookup_name)

        if res.get('status') == 'AMBIGUOUS' and int(res.get('match_count', 2) or 2) != 1:
            suggested = res.get('final_name')
            if prefix:
                suggested = f"{prefix} - {suggested}".strip()
            else:
                suggested = apply_company_prefix(suggested, dompet_sheet, company)
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'project_name_confirm',
                    'suggested_project': suggested,
                    'transactions': transactions,
                    'dompet_sheet': dompet_sheet,
                    'company': company,
                    'raw_text': pending_data.get('raw_text', ''),
                    'debt_source_dompet': debt_source,
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            return {
                'response': f"🤔 Maksudnya **{suggested}**?\n✅ Ya / ❌ Bukan".replace('*', ''),
                'completed': False
            }

        final_base = res.get('final_name') or lookup_name
        if prefix:
            final_name = f"{prefix} - {final_base}".strip()
        else:
            final_name = apply_company_prefix(final_base, dompet_sheet, company)

        for tx in transactions:
            tx['nama_projek'] = final_name

        return _continue_project_after_name(
            transactions, dompet_sheet, company,
            user_id, sender_name, pending_data.get('source', 'WhatsApp'),
            pending_data.get('original_message_id'), pending_data.get('event_id'),
            (res.get('status') == 'NEW'), is_group, chat_id, debt_source,
            skip_first_expense=combined
        )

    # ===================================
    # HANDLE: Operational Category Input (Draft Adjust)
    # ===================================
    elif pending_type == 'operational_category_input':
        new_cat = text.strip()
        if text_lower in ['/cancel', 'batal']:
            clear_pending_confirmation(user_id, chat_id)
            return {'response': '❌ Dibatalkan.', 'completed': True}
        
        # Normalize category
        norm = new_cat.lower()
        if 'gaji' in norm:
            category = 'Gaji'
        elif 'listrik' in norm or 'pln' in norm or 'air' in norm or 'pdam' in norm:
            category = 'ListrikAir'
        elif 'konsumsi' in norm or 'makan' in norm or 'minum' in norm:
            category = 'Konsumsi'
        elif 'peralatan' in norm or 'atk' in norm:
            category = 'Peralatan'
        else:
            category = 'Lain Lain'
        
        # Re-open draft confirmation
        transactions = pending_data.get('transactions', [])
        dompet_sheet = pending_data.get('source_wallet')
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'confirm_commit_operational',
                'transactions': transactions,
                'source_wallet': dompet_sheet,
                'category': category,
                'sender_name': sender_name,
                'source': pending_data.get('source', 'WhatsApp'),
                'original_message_id': pending_data.get('original_message_id'),
                'event_id': pending_data.get('event_id'),
                'pending_key': pending_data.get('pending_key')
            }
        )
        
        response = format_draft_summary_operational(
            transactions, dompet_sheet, category, ""
        )
        return {'response': response, 'completed': False}

    # ===================================
    # HANDLE: Confirm Commit (Operational)
    # ===================================
    elif pending_type == 'confirm_commit_operational':
        # Allow /revisi amount while in draft confirmation
        if text_lower.startswith('/revisi') or text_lower.startswith('revisi'):
            new_amt = parse_revision_amount(text)
            if not new_amt:
                return {'response': '❗ Nominal revisi tidak terbaca. Contoh: /revisi 150rb', 'completed': False}
            transactions = pending_data.get('transactions', [])
            if transactions:
                transactions[0]['jumlah'] = int(new_amt)

            response = format_draft_summary_operational(
                transactions,
                pending_data.get('source_wallet'),
                pending_data.get('category'),
                ""
            )
            return {'response': response, 'completed': False}

        # Allow plain nominal replies (e.g., "150rb") without forcing /revisi.
        plain_digits = re.sub(r"[^\d]", "", text_lower)
        looks_like_plain_amount = plain_digits.isdigit() and len(plain_digits) >= 3
        if text_lower not in {'1', '2', '3', '4'} and (has_amount_pattern(text) or looks_like_plain_amount):
            new_amt = parse_revision_amount(text)
            if new_amt:
                transactions = pending_data.get('transactions', [])
                target_tx = _first_invalid_amount_tx(transactions)
                if not target_tx and transactions:
                    target_tx = transactions[0]
                if target_tx:
                    target_tx['jumlah'] = int(new_amt)
                    target_tx.pop('needs_amount', None)
                response = format_draft_summary_operational(
                    transactions,
                    pending_data.get('source_wallet'),
                    pending_data.get('category'),
                    ""
                )
                return {'response': response, 'completed': False}

        if text_lower in ['1', 'ya', 'yes', 'simpan', 'ok', 'oke']:
            transactions = pending_data.get('transactions', [])
            dompet_sheet = pending_data.get('source_wallet')
            if pending_data.get('category'):
                category = pending_data.get('category')
            else:
                category = _detect_operational_category(transactions[0].get('keterangan', '') if transactions else '')
            event_id = pending_data.get('event_id') or pending_data.get('original_message_id')

            missing_tx = _first_invalid_amount_tx(transactions)
            if missing_tx:
                item = missing_tx.get('keterangan', 'Transaksi')
                return {
                    'response': f"❗ Nominal untuk \"{item}\" belum valid. Balas nominal dulu (contoh: 150rb).",
                    'completed': False
                }
            
            _assign_tx_ids(transactions, event_id)
            
            for tx in transactions:
                kategori = category or _detect_operational_category(tx.get('keterangan', ''))
                
                # 1) Save to Operasional sheet
                append_operational_transaction(
                    transaction={
                        'jumlah': tx['jumlah'],
                        'keterangan': tx['keterangan'],
                        'message_id': tx.get('message_id')
                    },
                    sender_name=sender_name,
                    source=pending_data.get('source', 'WhatsApp'),
                    source_wallet=dompet_sheet,
                    category=kategori
                )
            
            # If this is a revision move, delete old rows after re-save
            if pending_data.get('revision_delete'):
                for item in pending_data.get('revision_delete', []):
                    delete_transaction_row(item.get('dompet'), item.get('row'))
            
            invalidate_dashboard_cache()
            clear_pending_confirmation(user_id, chat_id)
            if pending_data.get('pending_key'):
                clear_pending_transaction(pending_data.get('pending_key'))
            
            response = format_success_reply_operational(
                transactions,
                dompet_sheet,
                category,
                "",
            ).replace('*', '')
            return {'response': response, 'completed': True, 'bot_ref_event_id': event_id}
        
        if text_lower in ['2', 'ganti dompet', 'dompet']:
            # Re-select dompet
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_operational',
                    'category_scope': 'OPERATIONAL',
                    'transactions': pending_data.get('transactions', []),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            prompt = format_wallet_selection_prompt()
            return {'response': f"🪙 Pilih dompet lagi:\n\n{prompt}", 'completed': False}
        
        if text_lower in ['3', 'ubah kategori', 'kategori']:
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'operational_category_input',
                    'transactions': pending_data.get('transactions', []),
                    'source_wallet': pending_data.get('source_wallet'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id'),
                    'pending_key': pending_data.get('pending_key')
                }
            )
            return {'response': '📂 Kategori baru apa? (Gaji/ListrikAir/Konsumsi/Peralatan/Lain Lain)', 'completed': False}
        
        # Cancel
        clear_pending_confirmation(user_id, chat_id)
        if pending_data.get('pending_key'):
            clear_pending_transaction(pending_data.get('pending_key'))
        return {'response': '❌ Dibatalkan.', 'completed': True}

    # ===================================
    # HANDLE: Confirm Commit (Project)
    # ===================================
    elif pending_type == 'confirm_commit_project':
        # Allow /revisi amount while in draft confirmation
        if text_lower.startswith('/revisi') or text_lower.startswith('revisi'):
            new_amt = parse_revision_amount(text)
            if not new_amt:
                return {'response': '❗ Nominal revisi tidak terbaca. Contoh: /revisi 150rb', 'completed': False}
            transactions = pending_data.get('transactions', [])

            def _is_fee_tx(tx: dict) -> bool:
                ket = (tx.get('keterangan', '') or '').lower()
                return 'biaya transfer' in ket or 'fee' in ket or 'biaya admin' in ket

            fee_tx = next((t for t in transactions if _is_fee_tx(t)), None)
            main_tx = next((t for t in transactions if t is not fee_tx), None)
            if main_tx:
                main_tx['jumlah'] = int(new_amt)

            response = format_draft_summary_project(
                transactions, pending_data.get('dompet'), pending_data.get('company'), "",
                pending_data.get('debt_source_dompet') or ""
            )
            return {'response': response, 'completed': False}

        # Update debt source if user mentions utang + dompet
        debt_from = _extract_debt_source(text_lower)
        if debt_from:
            if debt_from != pending_data.get('dompet'):
                pending_data['debt_source_dompet'] = debt_from
            else:
                pending_data['debt_source_dompet'] = None
            response = format_draft_summary_project(
                pending_data.get('transactions', []),
                pending_data.get('dompet'),
                pending_data.get('company'),
                "",
                pending_data.get('debt_source_dompet') or ""
            )
            return {'response': response, 'completed': False}

        if text_lower in ['1', 'ya', 'yes', 'simpan', 'ok', 'oke']:
            transactions = pending_data.get('transactions', [])
            
            def _has_finish_keyword(txs: list) -> bool:
                finish_keywords = ['pelunasan', 'lunas', 'final payment', 'penyelesaian', 'selesai', 'kelar', 'beres']
                for tx in txs:
                    if tx.get('tipe') != 'Pemasukan':
                        continue
                    desc = (tx.get('keterangan', '') or '').lower()
                    if any(k in desc for k in finish_keywords):
                        return True
                return False

            if _has_finish_keyword(transactions) and not pending_data.get('finish_decision'):
                set_pending_confirmation(
                    user_id=user_id,
                    chat_id=chat_id,
                    data={
                        'type': 'project_finish_confirm',
                        'transactions': transactions,
                        'dompet': pending_data.get('dompet'),
                        'company': pending_data.get('company'),
                        'sender_name': sender_name,
                        'source': pending_data.get('source', 'WhatsApp'),
                        'original_message_id': pending_data.get('original_message_id'),
                        'event_id': pending_data.get('event_id'),
                        'is_new_project': pending_data.get('is_new_project', False),
                        'pending_key': pending_data.get('pending_key'),
                        'revision_delete': pending_data.get('revision_delete')
                    }
                )
                return {
                    'response': 'Terdeteksi kata pelunasan/selesai. Tandai project sebagai (Finish)?\n\n1️⃣ Ya\n2️⃣ Tidak',
                    'completed': False
                }

            return _commit_project_transactions(pending_data, sender_name, user_id, chat_id, is_group)
        if text_lower in ['2', 'ganti dompet', 'dompet']:
            # Re-select company/dompet
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_project',
                    'category_scope': 'PROJECT',
                    'transactions': pending_data.get('transactions', []),
                    'raw_text': pending_data.get('raw_text', ''),
                    'debt_source_dompet': pending_data.get('debt_source_dompet'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            response = build_selection_prompt(pending_data.get('transactions', []), "")
            return {'response': response, 'completed': False}

        # Dompet hint inside text (e.g., "utang tx surabaya")
        dompet_hint = resolve_dompet_from_text(text_lower)
        if dompet_hint and not re.search(r"\b(utang|hutang|minjem|minjam|pinjam)\b", text_lower):
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'dompet_selection_project',
                    'category_scope': 'PROJECT',
                    'transactions': pending_data.get('transactions', []),
                    'raw_text': pending_data.get('raw_text', ''),
                    'debt_source_dompet': pending_data.get('debt_source_dompet'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            response = build_selection_prompt(pending_data.get('transactions', []), "")
            return {'response': response, 'completed': False}

        if text_lower in ['3', 'ubah projek', 'projek', 'project']:
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'project_name_input',
                    'dompet_sheet': pending_data.get('dompet'),
                    'company': pending_data.get('company'),
                    'transactions': pending_data.get('transactions', []),
                    'raw_text': pending_data.get('raw_text', ''),
                    'debt_source_dompet': pending_data.get('debt_source_dompet'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id')
                }
            )
            return {'response': '📝 Nama projeknya apa?', 'completed': False}
        
        # Unknown input -> keep pending and ask again
        return {
            'response': 'Balas: 1 Simpan, 2 Ganti dompet, 3 Ubah projek, atau 4 Batal.',
            'completed': False
        }

    # ===================================
    # HANDLE: Project Dompet Mismatch
    # ===================================
    elif pending_type == 'project_finish_confirm':
        if text_lower in ['1', 'ya', 'yes', 'ok', 'oke', 'simpan']:
            pending_data['finish_decision'] = 'APPLY'
            return _commit_project_transactions(pending_data, sender_name, user_id, chat_id, is_group)
        if text_lower in ['2', 'tidak', 'no', 'bukan']:
            pending_data['finish_decision'] = 'SKIP'
            return _commit_project_transactions(pending_data, sender_name, user_id, chat_id, is_group)
        return {'response': 'Balas 1 untuk tandai (Finish) atau 2 untuk tidak.', 'completed': False}

    elif pending_type == 'project_dompet_mismatch':
        choice = text_lower.strip()
        dompet_locked = pending_data.get('dompet_locked')
        company_locked = pending_data.get('company_locked')
        dompet_input = pending_data.get('dompet_input')
        company_input = pending_data.get('company_input')
        transactions = pending_data.get('transactions', [])
        is_new_project = pending_data.get('is_new_project', False)
        debt_source = pending_data.get('debt_source_dompet')
        if not debt_source:
            raw_text = pending_data.get('raw_text', '')
            debt_source = _extract_debt_source(raw_text)
        
        if choice in ['1', 'gunakan', 'ya', 'yes']:
            debt_use = None if debt_source == dompet_locked else debt_source
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'confirm_commit_project',
                    'transactions': transactions,
                    'dompet': dompet_locked,
                    'company': company_locked,
                    'debt_source_dompet': debt_use,
                    'sender_name': sender_name,
                    'source': pending_data.get('source', 'WhatsApp'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id'),
                    'is_new_project': is_new_project,
                    'pending_key': pending_data.get('pending_key'),
                    'raw_text': pending_data.get('raw_text', '')
                }
            )
            response = format_draft_summary_project(
                transactions, dompet_locked, company_locked, "", debt_use or ""
            )
            return {'response': response, 'completed': False}
        
        if choice in ['2', 'pindahkan', 'ganti', 'lanjut']:
            if transactions:
                pname = transactions[0].get('nama_projek')
                if pname:
                    set_project_lock(pname, dompet_input, actor=sender_name, reason="user_move", previous_dompet=dompet_locked)
            debt_use = None if debt_source == dompet_input else debt_source
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'confirm_commit_project',
                    'transactions': transactions,
                    'dompet': dompet_input,
                    'company': company_input,
                    'debt_source_dompet': debt_use,
                    'sender_name': sender_name,
                    'source': pending_data.get('source', 'WhatsApp'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id'),
                    'is_new_project': is_new_project,
                    'pending_key': pending_data.get('pending_key'),
                    'raw_text': pending_data.get('raw_text', '')
                }
            )
            response = format_draft_summary_project(
                transactions, dompet_input, company_input, "", debt_use or ""
            )
            return {'response': response, 'completed': False}
        
        clear_pending_confirmation(user_id, chat_id)
        if pending_data.get('pending_key'):
            clear_pending_transaction(pending_data.get('pending_key'))
        return {'response': '❌ Dibatalkan.', 'completed': True}

    # ===================================
    # HANDLE: New Project First Expense
    # ===================================
    elif pending_type == 'new_project_first_expense':
        choice = text_lower.strip()
        transactions = pending_data.get('transactions', [])
        dompet_sheet = pending_data.get('dompet')
        company = pending_data.get('company')
        debt_source = pending_data.get('debt_source_dompet')
        if not debt_source:
            raw_text = pending_data.get('raw_text', '')
            debt_source = _extract_debt_source(raw_text)
            if debt_source == dompet_sheet:
                debt_source = None
        
        if choice in ['1', 'lanjut', 'ya', 'yes']:
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'confirm_commit_project',
                    'transactions': transactions,
                    'dompet': dompet_sheet,
                    'company': company,
                    'debt_source_dompet': debt_source,
                    'sender_name': sender_name,
                    'source': pending_data.get('source', 'WhatsApp'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id'),
                    'is_new_project': True,
                    'pending_key': pending_data.get('pending_key'),
                    'raw_text': pending_data.get('raw_text', '')
                }
            )
            response = format_draft_summary_project(
                transactions, dompet_sheet, company, "", debt_source or ""
            )
            return {'response': response, 'completed': False}
        
        if choice in ['2', 'operasional', 'kantor']:
            set_pending_confirmation(
                user_id=user_id,
                chat_id=chat_id,
                data={
                    'type': 'confirm_commit_operational',
                    'transactions': transactions,
                    'source_wallet': dompet_sheet,
                    'category': 'Lain Lain',
                    'sender_name': sender_name,
                    'source': pending_data.get('source', 'WhatsApp'),
                    'original_message_id': pending_data.get('original_message_id'),
                    'event_id': pending_data.get('event_id'),
                    'pending_key': pending_data.get('pending_key')
                }
            )
            response = format_draft_summary_operational(
                transactions, dompet_sheet, 'Lain Lain', ""
            )
            return {'response': response, 'completed': False}
        
        clear_pending_confirmation(user_id, chat_id)
        if pending_data.get('pending_key'):
            clear_pending_transaction(pending_data.get('pending_key'))
        return {'response': '❌ Dibatalkan.', 'completed': True}

    # ===================================
    # HANDLE: Revision Move to Operational
    # ===================================
    elif pending_type == 'revision_move_to_operational':
        try:
            choice_idx = int(text_lower)
            selection = get_wallet_selection_by_idx(choice_idx)
            dompet_sheet = selection['dompet'] if selection else None
        except ValueError:
            dompet_sheet = None
        
        if not dompet_sheet:
            return {'response': '❌ Pilih angka 1-3.', 'completed': False}
        
        # Build new transactions from old items
        old_items = pending_data.get('transactions', [])
        transactions = []
        for item in old_items:
            transactions.append({
                'jumlah': item.get('amount', 0),
                'keterangan': item.get('keterangan', ''),
                'tipe': 'Pengeluaran'
            })
        
        # Draft confirmation before commit
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'confirm_commit_operational',
                'transactions': transactions,
                'source_wallet': dompet_sheet,
                'category': 'Lain Lain',
                'sender_name': sender_name,
                'source': pending_data.get('source', 'WhatsApp'),
                'original_message_id': pending_data.get('original_message_id'),
                'event_id': pending_data.get('event_id'),
                'revision_delete': old_items
            }
        )
        
        response = format_draft_summary_operational(
            transactions, dompet_sheet, 'Lain Lain', ""
        )
        return {'response': response, 'completed': False}

    # ===================================
    # HANDLE: Revision Move to Project
    # ===================================
    elif pending_type == 'revision_move_to_project':
        project_name = text.strip()
        if not project_name:
            return {'response': '📝 Nama projeknya apa?', 'completed': False}
        
        old_items = pending_data.get('transactions', [])
        dompet_sheet = pending_data.get('current_dompet')
        company = get_company_name_from_sheet(dompet_sheet) if dompet_sheet else None
        
        transactions = []
        for item in old_items:
            transactions.append({
                'jumlah': item.get('amount', 0),
                'keterangan': item.get('keterangan', ''),
                'tipe': item.get('tipe', 'Pengeluaran'),
                'nama_projek': apply_company_prefix(project_name, dompet_sheet, company)
            })
        
        set_pending_confirmation(
            user_id=user_id,
            chat_id=chat_id,
            data={
                'type': 'confirm_commit_project',
                'transactions': transactions,
                'dompet': dompet_sheet,
                'company': company,
                'sender_name': sender_name,
                'source': pending_data.get('source', 'WhatsApp'),
                'original_message_id': pending_data.get('original_message_id'),
                'event_id': pending_data.get('event_id'),
                'revision_delete': old_items
            }
        )
        
        response = format_draft_summary_project(
            transactions, dompet_sheet, company, ""
        )
        return {'response': response, 'completed': False}
    
    return {
        'response': 'Balasan belum sesuai format konfirmasi aktif. Ketik /cancel untuk batalkan sesi ini.',
        'completed': False
    }
