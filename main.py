"""
main.py

Features:
- COST ACCOUNTING: Splits Operational (Fixed) vs Project (Variable) costs.
- SMART ROUTING: Auto-detects context (Salary/Utilities vs Project Expenses).
- PROJECT LIFECYCLE: Auto-tags confirmed new projects with (Start) and completed projects with (Selesai).
- MULTI-CHANNEL: WhatsApp + Telegram support.
- SECURE: Rate limiting, prompt injection protection...
"""

import base64
import os
import re
import threading
import tempfile
import time
import uuid
from datetime import datetime
from typing import Optional

from flask import Flask, g, request, jsonify
from dotenv import load_dotenv
from werkzeug.exceptions import RequestEntityTooLarge

# Load environment variables
load_dotenv()

# ===================== GLOBAL IMPORTS =====================
# AI & Data Processing
from ai_helper import extract_financial_data, RateLimitException, extract_source_wallet_from_ocr, split_ocr_user_text

# Google Sheets Integration
from sheets_helper import (
    append_transactions, append_transaction,
    format_dashboard_message, get_dashboard_summary,
    get_wallet_balances,
    invalidate_dashboard_cache,
    DOMPET_SHEETS, DOMPET_COMPANIES, SELECTION_OPTIONS,
    get_selection_by_idx, get_dompet_for_company,
    check_duplicate_transaction,
    # New Split Layout Functions
    append_project_transaction,
    move_finish_marker_to_latest,
    append_operational_transaction,
    append_hutang_entry,
    update_hutang_status_by_no,
    settle_hutang,
    cancel_hutang_by_event_id,
    find_open_hutang,
    get_all_data,
    get_raw_rows_for_audit,
    get_hutang_summary,
    find_company_for_project_exact,
)

# Services
from handlers.telegram_webhook import handle_telegram_webhook
from handlers.wuzapi_webhook import handle_wuzapi_webhook
from services.retry_service import process_retry_queue
from services.durable_inbox import (
    claim_recovery_bundle,
    complete_bundle,
    inbox_health,
    inbox_required,
    prune_inbox,
)
from services.project_service import (
    resolve_project_name,
    resolve_project_name_for_context,
    infer_project_from_text_context,
    add_new_project_to_cache,
    normalize_project_input,
)
from services.finance_decision import decide_project_resolution
from services.group_reply_hints import should_send_group_reply_hint
from services.hutang_flow import (
    build_saldo_message as _build_saldo_message,
    extract_repayment_amount_from_transactions as _extract_repayment_amount_from_transactions,
    format_hutang_paid_response as _format_hutang_paid_response,
    handle_auto_hutang_payment as _handle_auto_hutang_payment,
    is_debt_payment_text as _is_debt_payment_text,
    pick_dompet_by_prep as _pick_dompet_by_prep,
)
from services.transaction_queue import (
    first_missing_amount_tx as _first_missing_amount_tx,
    merge_transaction_queue as _merge_transaction_queue,
)
from services.transaction_context import detect_transaction_context
from agent_core.conversation_memory import record_message
from agent_core.intent_router import record_intent_shadow
from services.state_manager import (
    pending_key, pending_is_expired,
    clear_message_duplicate, store_bot_message_ref,
    store_pending_message_ref,
    get_pending_key_from_message,
    store_visual_buffer, get_visual_buffer,
    clear_visual_buffer, has_visual_buffer,
    get_visual_buffer_by_message, remove_visual_buffer_by_message,
    mark_visual_message_consumed, clear_visual_message_consumed,
    is_visual_message_consumed,
    store_last_bot_report,
    store_last_tx_event,
    # New Pending Confirmations
    get_pending_confirmation, set_pending_confirmation,
    has_pending_confirmation,
    store_user_message, get_user_last_message, clear_user_last_message,
    wait_for_visual_buffer,
    get_project_lock, set_project_lock, remember_project_knowledge
)

# Layer Integration - Superseded by SmartHandler
# from layer_integration_v2 import process_with_layers, USE_ENHANCED_LAYERS as USE_LAYERS
USE_LAYERS = True # Enable SmartHandler logic by default

# Utilities
from wuzapi_helper import (
    send_wuzapi_reply, format_mention_body,
    get_clean_jid, send_wuzapi_document
)
from security import (
    sanitize_input, detect_prompt_injection,
    rate_limit_check, secure_log,
    log_timing,
    SecurityError, RateLimitError,
    ALLOWED_CATEGORIES, now_wib,
)
try:
    from pdf_report import generate_pdf_from_input, PDFNoDataError
except ImportError:
    from pdf_report import generate_pdf_from_input

    class PDFNoDataError(Exception):
        def __init__(self, period: str = "periode tersebut"):
            self.period = period
            super().__init__(f"No data for period: {period}")
from utils.parsers import (
    parse_selection, parse_revision_amount,
    should_respond_in_group, is_command_match,
    is_prefix_match, is_explicit_catat_command,
    strip_explicit_catat_command, GROUP_TRIGGERS, PENDING_TTL_SECONDS,
    extract_project_name_from_text,
)
from utils.groq_analyzer import is_saldo_update
from utils.formatters import (
    format_success_reply, format_success_reply_new, format_success_reply_operational,
    format_draft_summary_operational, format_draft_summary_project,
    build_selection_prompt,
    format_reply_message, append_active_transaction_notice,
    START_MESSAGE, HELP_MESSAGE,
    CATEGORIES_DISPLAY, SELECTION_DISPLAY,
)
from utils.lifecycle import apply_lifecycle_markers, has_finish_marker, select_start_marker_indexes
from utils.wallet_updates import (
    is_absolute_balance_update,
    pick_wallet_target_amount,
    compute_balance_adjustment,
)

# Configuration
from config.constants import Commands, Timeouts, GROUP_TRIGGERS, SPREADSHEET_ID, OPERATIONAL_KEYWORDS, FAST_MODE
from config.errors import UserErrors
from config.wallets import (
    format_wallet_selection_prompt,
    get_wallet_selection_by_idx,
    WALLET_SELECTION_OPTIONS,
    get_dompet_short_name,
    apply_company_prefix,
    extract_company_prefix,
    strip_company_prefix,
    DOMPET_COMPANIES,
    get_company_name_from_sheet,
    resolve_dompet_from_text,
    normalize_company_name,
    resolve_company_from_text,
)

# Initialize Flask app
app = Flask(__name__)

# Configuration Flags
DEBUG = os.getenv('FLASK_DEBUG', '0') == '1'
IMAGE_GRACE_SECONDS = int(os.getenv('IMAGE_GRACE_SECONDS', '5'))
OWNER_FAST_FOLLOW_SECONDS = int(os.getenv('OWNER_FAST_FOLLOW_SECONDS', '3'))
SPLIT_EVENT_JOIN_SECONDS = float(os.getenv('SPLIT_EVENT_JOIN_SECONDS', '2.5'))
SPLIT_EVENT_PAIR_WINDOW_SECONDS = int(os.getenv('SPLIT_EVENT_PAIR_WINDOW_SECONDS', '30'))
MAX_WEBHOOK_BYTES = int(os.getenv('MAX_WEBHOOK_BYTES', str(25 * 1024 * 1024)))
app.config['MAX_CONTENT_LENGTH'] = MAX_WEBHOOK_BYTES
app.config['MAX_FORM_MEMORY_SIZE'] = MAX_WEBHOOK_BYTES


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(_err):
    secure_log("WARNING", f"Webhook payload too large (>{MAX_WEBHOOK_BYTES} bytes)")
    # Return 200 to prevent provider retry storm for oversized payloads.
    return jsonify({'status': 'payload_too_large'}), 200

# Import legacy pending dict (now managed via state_manager proxy)
from services import state_manager as _state
_pending_transactions = _state._pending_transactions


# ===================== LOGIC CORE: SMART ROUTER =====================
# Enhanced with amount pattern detection and AI category_scope integration
from handlers.smart_handler import SmartHandler
import services.state_manager as state_manager_module

# Initialize SmartHandler
smart_handler = SmartHandler(state_manager_module)

from utils.amounts import has_amount_pattern


def _deterministic_transaction_scope(text: str) -> Optional[str]:
    """Return a safe scope for obvious transactions without invoking Groq."""
    lower = (text or '').strip().lower()
    if not lower or not has_amount_pattern(lower):
        return None
    if '?' in lower or re.search(r"\b(berapa|gimana|bagaimana|cek|lihat|tanya|besok|nanti|akan|rencana|mau|perlu)\b", lower):
        return None

    has_action = bool(re.search(
        r"\b(dp|bayar|beli|biaya|fee|gaji|upah|honor|transfer|kirim|isi|tambah|topup|deposit|tarik|ambil|masuk|keluar|catat|simpan)\b",
        lower,
    ))
    has_project = bool(re.search(r"\b(projek|project|proyek|prj)\b", lower))
    has_operational = bool(re.search(r"\b(kantor|operasional|operational|office|ops)\b", lower)) or any(
        re.search(r"\b" + re.escape(keyword) + r"\b", lower)
        for keyword in OPERATIONAL_KEYWORDS
    )
    has_wallet = bool(resolve_dompet_from_text(lower)) or bool(
        re.search(r"\b(dompet|wallet|saldo|rekening|rek)\b", lower)
    )
    if not has_action and not (has_project or has_operational or has_wallet):
        return None
    if is_saldo_update(lower) or (has_wallet and not has_project and not has_operational):
        return "TRANSFER"
    if has_project:
        return "PROJECT"
    if has_operational:
        return "OPERATIONAL"
    return None


def _build_extraction_failure_message(raw_text: str, input_type: str) -> str:
    """Explain why an accepted transaction attempt produced no valid record."""
    text = str(raw_text or '').strip()
    lower = text.lower()
    zero_amount = re.search(r"\b(?:0|nol)\s*(?:rupiah|rp|idr|ribu|rb|k)?\b", lower)

    if zero_amount:
        return (
            "⚠️ *Belum dicatat.*\n"
            "Alasan: nominal yang terbaca adalah *Rp0*. Nominal nol ditolak agar tidak menjadi transaksi palsu.\n\n"
            "Yang sudah terbaca: transaksi masuk untuk operasional kantor.\n"
            "Yang kurang: nominal pemasukan harus lebih dari Rp0.\n\n"
            "Contoh: *Masuk 250rb, untuk operasional kantor CV HB*"
        )

    if input_type == 'image':
        return (
            "⚠️ *Belum dicatat.*\n"
            "Gambar sudah dipindai, tetapi tidak ada transaksi valid yang bisa disimpan.\n"
            "Kemungkinan penyebab: nominal tidak terbaca, gambar terlalu kecil/buram, atau format struk tidak dikenali.\n\n"
            "Kirim gambar resolusi penuh atau tambahkan caption dengan nominal, contoh:\n"
            "*Bayar 250rb, operasional kantor CV HB*"
        )

    if not has_amount_pattern(text):
        return (
            "⚠️ *Belum dicatat.*\n"
            "Konteks transaksi sudah terbaca, tetapi nominal belum ditemukan.\n\n"
            "Tambahkan nominal lebih dari Rp0, contoh:\n"
            "*Masuk 250rb, untuk operasional kantor CV HB*"
        )

    return (
        "⚠️ *Belum dicatat.*\n"
        "Bot belum menemukan transaksi yang lolos validasi. Pastikan ada jenis transaksi, nominal, dan keterangan yang jelas.\n\n"
        "Contoh: *Keluar 150rb, beli ATK operasional kantor CV HB*"
    )

# ===================== NARROW RESOLVER SHADOW (Fase 2a) =====================
# Run the typed narrow_resolver in PARALLEL with the legacy pipeline and only
# LOG divergences. The legacy pipeline still makes every decision; this changes
# no behavior. Enable by setting NARROW_RESOLVER_SHADOW=1 to collect comparison
# data from real chats before any promotion (Fase 2b).
NARROW_RESOLVER_SHADOW = os.getenv('NARROW_RESOLVER_SHADOW', '0').strip().lower() in ('1', 'true', 'yes', 'on')

# Fase 3: context-aware confirmation prompts. Default ON for the small trusted
# group; set SMART_CONFIRMATION=0 to revert to the plain prompt instantly.
SMART_CONFIRMATION = os.getenv('SMART_CONFIRMATION', '1').strip().lower() in ('1', 'true', 'yes', 'on')



def _shadow_compare_narrow_resolver(original_text, pipeline_dompet,
                                    pipeline_debt_source, pipeline_projects):
    """Compare narrow_resolver output against the pipeline decision (log-only).

    Never raises: any failure here must not affect the live transaction flow.
    """
    if not NARROW_RESOLVER_SHADOW:
        return
    try:
        from services.narrow_resolver import resolve_finance_message
        decision = resolve_finance_message(original_text or "")

        diffs = []
        # main_wallet vs pipeline dompet
        if (decision.main_wallet or None) != (pipeline_dompet or None):
            diffs.append(f"main_wallet: resolver={decision.main_wallet!r} pipeline={pipeline_dompet!r}")
        # debt_source
        if (decision.debt_source or None) != (pipeline_debt_source or None):
            diffs.append(f"debt_source: resolver={decision.debt_source!r} pipeline={pipeline_debt_source!r}")
        # project (compare resolver hint against normalized pipeline project names)
        def _project_shadow_key(value):
            base = strip_company_prefix(str(value or "").strip()) or str(value or "").strip()
            return base.lower()

        pipeline_proj_set = {
            key for p in (pipeline_projects or [])
            if (key := _project_shadow_key(p))
        }
        resolver_proj = _project_shadow_key(decision.project)
        if resolver_proj or pipeline_proj_set:
            if not resolver_proj or resolver_proj not in pipeline_proj_set:
                diffs.append(f"project: resolver={decision.project!r} pipeline={sorted(pipeline_proj_set)}")

        if diffs:
            secure_log(
                "INFO",
                "NARROW_SHADOW divergence | "
                + f"conf={decision.confidence} needs_conf={decision.needs_confirmation} | "
                + " | ".join(diffs)
            )
        else:
            secure_log("INFO", f"NARROW_SHADOW match | conf={decision.confidence}")
    except Exception as e:
        secure_log("WARNING", f"NARROW_SHADOW failed (ignored): {type(e).__name__}: {e}")



# ===================== HEALTH CHECK ENDPOINT =====================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check including the transaction durability gate."""
    try:
        inbox = inbox_health()
        durable = bool(inbox.get('durable'))
        serving = durable or not inbox_required()
        return jsonify({
            'status': 'healthy' if durable else 'degraded',
            'timestamp': datetime.now().isoformat(),
            'transaction_inbox': inbox,
        }), 200 if serving else 503
    except Exception as exc:
        secure_log("ERROR", f"Health durable inbox check failed: {type(exc).__name__}: {exc}")
        return jsonify({
            'status': 'unhealthy' if inbox_required() else 'degraded',
            'timestamp': datetime.now().isoformat(),
            'transaction_inbox': {'durable': False, 'error': type(exc).__name__},
        }), 503 if inbox_required() else 200


# ===================== WUZAPI HANDLER =====================

@app.route('/webhook_wuzapi', methods=['POST'])
def webhook_wuzapi():
    return handle_wuzapi_webhook(request, process_wuzapi_message, MAX_WEBHOOK_BYTES)


# ===================== TELEGRAM HANDLER =====================

@app.route('/telegram', methods=['POST'])
def webhook_telegram():
    return handle_telegram_webhook(request, process_incoming_message)


def process_wuzapi_message(sender_number: str, sender_name: str, text: str,
                           input_type: str = 'text', media_url: str = None,
                           local_media_path: str = None,
                           quoted_msg_id: str = None, message_id: str = None,
                           is_group: bool = False, chat_jid: str = None,
                           sender_jid: str = None, quoted_message_text: str = None,
                           deferred: bool = False):
    try:
        reply_to = chat_jid if (is_group and chat_jid) else sender_number

        # --- Helper: Send Reply ---
        def send_reply(body: str, mention: bool = True):
            body_norm = format_reply_message(body)
            if is_group and mention and sender_jid:
                clean_jid = get_clean_jid(sender_jid)
                body_fmt = format_mention_body(body_norm, sender_name, sender_jid)
                return send_wuzapi_reply(reply_to, body_fmt, clean_jid)
            return send_wuzapi_reply(reply_to, body_norm)

        return process_incoming_message(
            sender_number=sender_number,
            sender_name=sender_name,
            text=text,
            input_type=input_type,
            media_url=media_url,
            local_media_path=local_media_path,
            quoted_msg_id=quoted_msg_id,
            message_id=message_id,
            is_group=is_group,
            chat_jid=chat_jid,
            sender_jid=sender_jid,
            quoted_message_text=quoted_message_text,
            send_reply=send_reply,
            send_document=send_wuzapi_document,
            source_label='WhatsApp',
            reply_to=reply_to,
            deferred=deferred,
        )
    except Exception as e:
        secure_log("ERROR", f"WuzAPI processing failed: {type(e).__name__}: {e}")
        return jsonify({'status': 'error'}), 500


def process_incoming_message(sender_number: str, sender_name: str, text: str,
                             input_type: str = 'text', media_url: str = None,
                             local_media_path: str = None,
                             quoted_msg_id: str = None, message_id: str = None,
                             is_group: bool = False, chat_jid: str = None,
                             sender_jid: str = None, quoted_message_text: str = None,
                             send_reply=None, send_document=None,
                             source_label: str = 'WhatsApp', reply_to=None,
                             deferred: bool = False):
    try:
        record_message(chat_jid, sender_number, 'user', text)
        try:
            shadow_pending = _pending_transactions.get(pending_key(sender_number, chat_jid))
            shadow_has_pending = bool(shadow_pending and not pending_is_expired(shadow_pending))
        except Exception:
            shadow_has_pending = False
        record_intent_shadow(
            text,
            chat_id=chat_jid,
            user_id=sender_number,
            source=source_label,
            is_group=is_group,
            has_media=bool(input_type in {'image', 'voice'} or media_url or local_media_path),
            has_pending=shadow_has_pending,
            is_reply=bool(quoted_msg_id),
        )
        send_reply_fn = send_reply

        def send_reply_tracked(body: str, mention: bool = True):
            if send_reply_fn is None:
                return None
            sent = send_reply_fn(body, mention=mention)
            if sent is None:
                secure_log(
                    "ERROR",
                    f"WhatsApp reply not acknowledged source={source_label} "
                    f"chat={chat_jid or '-'} body_len={len(body or '')}",
                )
            else:
                record_message(chat_jid, sender_number, 'bot', body)
            return sent

        send_reply = send_reply_tracked

        # --- Helper: State Management ---
        def extract_bot_msg_id(sent):
            if not sent or not isinstance(sent, dict): return None
            return (sent.get('data', {}).get('Id') or sent.get('id') or sent.get('ID'))

        def cache_prompt(pkey, pending, sent):
            bid = extract_bot_msg_id(sent)
            if bid:
                store_pending_message_ref(bid, pkey)
                pending.setdefault('prompt_message_ids', []).append(str(bid))

        def send_pending_reply(body: str, mention: bool = True):
            """Send reply with active-transaction timeout hint."""
            return send_reply(append_active_transaction_notice(body), mention=mention)

        def build_extraction_inputs(current_text: str, current_input_type: str,
                                    current_media_url: str, current_media_path: str):
            """Prepare input_data/media list/caption for extract_financial_data."""
            if current_input_type == 'image' and current_media_path:
                # Local file path, pass as input_data and no media URLs
                return current_media_path, None, current_text
            media_list = [current_media_url] if current_media_url else None
            caption = current_text if current_input_type == 'image' else None
            return current_text, media_list, caption

        def safe_extract(input_data: str, in_type: str, sender: str, media_list=None, caption=None):
            """Extract financial data with graceful AI rate-limit handling."""
            def announce_ocr_model(model_name: str) -> None:
                send_reply(f"🔎 Memindai gambar dengan AI Vision: *{model_name}*")

            started_at = time.perf_counter()
            try:
                return extract_financial_data(
                    input_data, in_type, sender, media_list, caption,
                    chat_id=chat_jid, user_id=sender_number,
                    ocr_progress=announce_ocr_model if in_type == 'image' else None,
                )
            except RateLimitException as e:
                wait = getattr(e, "wait_time", "beberapa saat")
                send_reply(f"⚠️ AI sedang sibuk (limit). Coba lagi dalam {wait}.")
                return None
            finally:
                log_timing(
                    "ocr" if in_type == 'image' else "extract_financial_data",
                    started_at,
                    input_type=in_type,
                )

        def is_explicit_bot_call(msg: str) -> bool:
            if not msg:
                return False
            t = msg.strip().lower()
            if is_explicit_catat_command(t) or t.startswith('+bot'):
                return True
            if re.match(r'^catat\b', t):
                return True
            if t.startswith('bot') or '@bot' in t:
                return True
            return False

        def schedule_group_image_grace() -> None:
            if IMAGE_GRACE_SECONDS <= 0:
                return

            def _worker():
                time.sleep(IMAGE_GRACE_SECONDS)
                buf = get_visual_buffer(sender_number, chat_jid)
                if not buf:
                    return
                item = next((b for b in buf if b.get('message_id') == message_id), None)
                if not item:
                    return
                item_message_id = item.get('message_id') or message_id
                if item_message_id and is_visual_message_consumed(chat_jid, item_message_id):
                    return

                pkey = pending_key(sender_number, chat_jid)
                pending = _pending_transactions.get(pkey)
                if pending and not pending_is_expired(pending):
                    return
                if has_pending_confirmation(sender_number, chat_jid):
                    secure_log(
                        "INFO",
                        f"Skip deferred image {message_id}: pending confirmation is active"
                    )
                    return

                deferred_text = item.get('caption') or ''
                if not deferred_text:
                    item_ctx = item.get('context') if isinstance(item.get('context'), dict) else {}
                    deferred_text = (item_ctx.get('original_text') or '').strip()
                if not deferred_text:
                    latest_text = (
                        get_user_last_message(
                            sender_number,
                            chat_jid,
                            max_age_seconds=max(1, SPLIT_EVENT_PAIR_WINDOW_SECONDS),
                        )
                        or ''
                    ).strip()
                    if latest_text and _should_bind_visual_text(latest_text):
                        deferred_text = latest_text
                        secure_log(
                            "INFO",
                            f"Deferred image {item_message_id} joined with follow-up text",
                        )

                # Deferred worker runs outside request context; provide app context
                # because process_incoming_message uses Flask helpers (jsonify).
                with app.app_context():
                    process_incoming_message(
                        sender_number=sender_number,
                        sender_name=sender_name,
                        text=deferred_text,
                        input_type='image',
                        media_url=item.get('media_url'),
                        local_media_path=item.get('media_path'),
                        quoted_msg_id=quoted_msg_id,
                        message_id=item_message_id,
                        is_group=is_group,
                        chat_jid=chat_jid,
                        sender_jid=sender_jid,
                        quoted_message_text=quoted_message_text,
                        send_reply=send_reply,
                        send_document=send_document,
                        source_label=source_label,
                        reply_to=reply_to,
                        deferred=True
                    )

            threading.Thread(target=_worker, daemon=True).start()

        # Event envelope
        event_id = str(message_id) if message_id else f"evt_{uuid.uuid4().hex[:12]}"
        claimed_visual_source_id = None
        bound_visual_message_id = None

        def _resolve_visual_source_message_id() -> Optional[str]:
            if bound_visual_message_id:
                return str(bound_visual_message_id)
            if input_type != 'image':
                return None
            if message_id:
                return str(message_id)
            if quoted_msg_id:
                quoted_item = get_visual_buffer_by_message(chat_jid, quoted_msg_id)
                if quoted_item and quoted_item.get('message_id'):
                    return str(quoted_item.get('message_id'))
            return None

        def _claim_visual_source_once() -> bool:
            nonlocal claimed_visual_source_id
            visual_source_id = _resolve_visual_source_message_id()
            if not visual_source_id:
                return True
            if claimed_visual_source_id == visual_source_id:
                return True
            if not mark_visual_message_consumed(chat_jid, visual_source_id):
                send_reply("ℹ️ Struk ini sudah diproses. Gunakan /revisi atau /undo jika perlu koreksi.")
                return False
            claimed_visual_source_id = visual_source_id
            return True

        def _release_visual_source_claim() -> None:
            nonlocal claimed_visual_source_id
            if not claimed_visual_source_id:
                return
            clear_visual_message_consumed(chat_jid, claimed_visual_source_id)
            claimed_visual_source_id = None

        def _has_wallet_context_hint(raw_text: str) -> bool:
            lower = (raw_text or "").lower().strip()
            if not lower:
                return False
            if not resolve_dompet_from_text(lower):
                return False
            if re.search(r"\b(dompet|wallet|saldo|utang|hutang|minjem|minjam|pinjam|dari|dr|pakai)\b", lower):
                return True
            return bool(re.search(r"\b(tx\s*sby|tx\s*bali|cv\s*hb|101|216|087)\b", lower))

        def _should_bind_visual_text(raw_text: str) -> bool:
            clean = (raw_text or "").strip()
            if not clean:
                return False
            lower = clean.lower()
            if re.search(r"\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b", lower):
                return True
            if is_explicit_bot_call(clean):
                return True
            if has_amount_pattern(clean):
                return True
            if _has_wallet_context_hint(clean):
                return True
            should, _ = should_respond_in_group(
                clean,
                is_group,
                has_media=False,
                has_pending=False,
                is_mentioned=is_explicit_bot_call(clean)
            )
            return should

        def _looks_like_structured_finance_text(raw_text: str) -> bool:
            lower = (raw_text or "").lower()
            labels = [
                r"\btanggal\s*:",
                r"\btipe\s*:",
                r"\bnominal\s*:",
                r"\bketerangan\s*:",
                r"\bcatatan\s*:",
            ]
            return sum(1 for pattern in labels if re.search(pattern, lower)) >= 2

        def _should_preserve_extraction_text(original: str, candidate: str) -> bool:
            original = original or ""
            candidate = candidate or ""
            if not candidate:
                return True
            if _looks_like_structured_finance_text(original):
                return True
            if has_amount_pattern(original) and not has_amount_pattern(candidate):
                return True
            if len(candidate) < max(40, int(len(original) * 0.6)) and has_amount_pattern(original):
                return True
            return False

        def _get_pending_confirmation_by_key(conf_key: str) -> Optional[dict]:
            """Resolve pending confirmation by exact key format: '<chat_id>:<user_id>'."""
            if not conf_key or ":" not in conf_key:
                return None
            chat_part, user_part = conf_key.split(":", 1)
            if not chat_part or not user_part:
                return None
            return get_pending_confirmation(user_part, chat_part)

        def _get_pending_owner_user_from_key(conf_key: str, expected_chat_id: str, fallback_user: str) -> str:
            """
            Resolve pending owner user-id from confirmation key '<chat_id>:<user_id>'.
            Falls back to current sender when key is invalid/mismatched.
            """
            if not conf_key or ":" not in conf_key:
                return fallback_user
            chat_part, user_part = conf_key.split(":", 1)
            if not user_part:
                return fallback_user
            if expected_chat_id and chat_part and chat_part != expected_chat_id:
                return fallback_user
            return user_part

        def _extract_pending_owner_from_key(target_pkey: str) -> str:
            """Extract owner user-id from pending key format '<chat_id>:<user_id>'."""
            pkey_text = str(target_pkey or "").strip()
            if not pkey_text:
                return ""
            if chat_jid and pkey_text.startswith(f"{chat_jid}:"):
                return pkey_text.split(":", 1)[1]
            if "@g.us:" in pkey_text:
                return pkey_text.split(":", 1)[1]
            return pkey_text

        def _can_access_group_session(owner_user: str, via_reply: bool) -> bool:
            """
            Group rule:
            - owner can always continue
            - any allowed group participant can continue ONLY by replying to a
              bot prompt that is already bound to that pending session.

            This keeps free-form/bare answers safe in busy groups while allowing
            real delegation (user B answers a prompt created by user A).
            SESSION_DELEGATE_IDS remains useful for future privileged actions,
            but transaction prompt replies are intentionally collaborative.
            """
            owner = str(owner_user or "").strip()
            if not owner or owner == sender_number:
                return True
            if is_group and via_reply:
                return True
            return False

        def _can_access_pending_key(target_pkey: str, via_reply: bool) -> bool:
            return _can_access_group_session(
                _extract_pending_owner_from_key(target_pkey),
                via_reply=via_reply
            )

        def _session_access_denied_message() -> str:
            return UserErrors.SESSION_ACCESS_DENIED

        def _count_active_group_sessions(target_chat_id: str) -> int:
            """Count active pending transaction + confirmation sessions in a group chat."""
            if not target_chat_id:
                return 0

            total = 0
            now = datetime.now()

            # Pending transaction sessions (group keys are prefixed with '<chat_id>:')
            for pkey, pdata in list(_pending_transactions.items()):
                if not isinstance(pkey, str) or not pkey.startswith(f"{target_chat_id}:"):
                    continue
                if pdata and not pending_is_expired(pdata):
                    total += 1

            # Pending confirmation sessions
            for ckey, cdata in list(state_manager_module.PENDING_CONFIRMATIONS.items()):
                if not isinstance(ckey, str) or not ckey.startswith(f"{target_chat_id}:"):
                    continue
                expires = cdata.get('expires_at') if isinstance(cdata, dict) else None
                if isinstance(expires, datetime) and now > expires:
                    continue
                total += 1

            return total

        def _looks_like_ambiguous_reply(raw_text: str) -> bool:
            """
            Detect short/ambiguous reply-like messages in group chat
            that should be tied to a specific prompt via reply.
            """
            clean = (raw_text or "").strip().lower()
            if not clean:
                return False

            if bool(re.fullmatch(r"\d{1,2}", clean)):
                return True

            if clean in {
                'ya', 'y', 'iya', 'ok', 'oke', 'yes',
                'no', 'tidak', 'bukan',
                'simpan', 'batal', 'cancel', '/cancel',
                'operasional', 'operational', 'ops', 'kantor',
                'project', 'projek'
            }:
                return True

            # Bare amount replies like "150rb" / "rp 41.852" are ambiguous in busy groups.
            if bool(re.fullmatch(r"(rp\s*)?\d[\d\.,\s]*(rb|ribu|k|jt|juta)?", clean)):
                return True

            return False

        # --- CORE WORKFLOW: FINALIZE TRANSACTION ---
        def finalize_transaction_workflow(pending: dict, pkey: str):
            raw_txs = pending.get('transactions', [])
            txs, _ = _merge_transaction_queue(raw_txs, [])
            pending['transactions'] = txs
            if not txs:
                return jsonify({'status': 'error_no_tx'}), 200

            missing_tx = _first_missing_amount_tx(txs)
            if missing_tx:
                pending['pending_type'] = 'needs_amount'
                item = missing_tx.get('keterangan', 'Transaksi')
                sent = send_pending_reply(f"Nominal untuk \"{item}\" berapa? (contoh: 150rb)")
                cache_prompt(pkey, pending, sent)
                return jsonify({'status': 'asking_amount'}), 200

            def _assign_tx_ids(transactions: list, event_id: str) -> None:
                base = event_id or f"evt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                for idx, tx in enumerate(transactions, start=1):
                    tx_id = f"{base}|{idx}"
                    tx['message_id'] = tx_id
                    tx['tx_id'] = tx_id

            def _detect_operational_category(keterangan: str) -> str:
                keterangan_lower = (keterangan or "").lower()
                if 'gaji' in keterangan_lower:
                    return 'Gaji'
                if any(x in keterangan_lower for x in ['listrik', 'pln', 'token', 'air', 'pdam']):
                    return 'ListrikAir'
                if any(x in keterangan_lower for x in ['konsumsi', 'snack', 'makan', 'minum']):
                    return 'Konsumsi'
                if any(x in keterangan_lower for x in ['atk', 'printer', 'kertas', 'tinta', 'peralatan']):
                    return 'Peralatan'
                if 'internet' in keterangan_lower or 'wifi' in keterangan_lower:
                    return 'ListrikAir'
                return 'Lain Lain'

            def _extract_debt_source(text: str) -> Optional[str]:
                if not text:
                    return None
                lower = text.lower()
                normalized = re.sub(r"[^a-z0-9]+", " ", lower).strip()
                debt_pattern = r"\b(utang|hutang|minjem|minjam|pinjam)\b"
                if not re.search(debt_pattern, normalized):
                    return None

                # If project context exists, this is a project expense funded by debt
                # (e.g., "bayar fee sugeng, project vadim, utang CV HB")
                # → NOT a debt repayment, so skip the payment-text guard.
                has_project_context = bool(
                    re.search(r"\b(projek|project|proyek|prj)\b", normalized)
                )

                # If this looks like paying a debt (and NOT a project expense), skip
                if not has_project_context and _is_debt_payment_text(lower):
                    # Only treat as debt payment if the payment keyword is near the debt keyword
                    # "bayar hutang ke TX SBY" = debt payment
                    # "bayar fee sugeng ... utang CV HB" = project expense + borrowing
                    debt_payment_near = bool(re.search(
                        r"\b(bayar|lunas|lunasi|pelunasan|cicil)\s+(?:\w+\s+){0,2}(utang|hutang)\b",
                        normalized
                    ))
                    borrower_hint = (
                        _pick_dompet_by_prep(lower, ["dari", "dr", "pakai", "pake", "via"])
                        or _pick_dompet_by_prep(normalized, ["dari", "dr", "pakai", "pake", "via"])
                    )
                    if debt_payment_near and not borrower_hint:
                        return None

                # Prefer explicit lender markers to avoid clashing with project/company words
                by_prep = (
                    _pick_dompet_by_prep(lower, ["dari", "dr", "ke", "kepada", "kpd", "pakai", "pake", "via"])
                    or _pick_dompet_by_prep(normalized, ["dari", "dr", "ke", "kepada", "kpd", "pakai", "pake", "via"])
                )
                if by_prep:
                    return by_prep

                # Fallback: only parse the text tail that starts from debt keyword
                for source_text in (lower, normalized):
                    m = re.search(debt_pattern, source_text)
                    if m:
                        tail = source_text[m.start():]
                        from_tail = resolve_dompet_from_text(tail)
                        if from_tail:
                            return from_tail

                # Last resort: full text parse
                return resolve_dompet_from_text(normalized) or resolve_dompet_from_text(lower)

            def _without_debt_source_context(text: str) -> str:
                if not text:
                    return ""
                return re.sub(
                    r"\b(?:utang|hutang|minjem|minjam|pinjam)\b.*$",
                    "",
                    str(text),
                    flags=re.IGNORECASE,
                ).strip()

            def _send_and_track(response: str, event_id: str) -> None:
                sent = send_reply(response)
                bid = extract_bot_msg_id(sent)
                if bid:
                    store_bot_message_ref(bid, event_id)
                    store_last_bot_report(chat_jid, bid)
                # Fallback: track last event per user/chat even if bot msg ID missing
                store_last_tx_event(sender_number, chat_jid, event_id)

            # ROUTING CHECK
            original_text = pending.get('original_text', '')
            category_scope = pending.get('category_scope', 'UNKNOWN')  # From AI layer
            debt_source_hint = _extract_debt_source(original_text)
            has_debt_context = bool(
                re.search(r"\b(utang|hutang|minjem|minjam|pinjam)\b", (original_text or "").lower())
            )

            # If already routed/flagged, respect it
            if pending.get('is_operational'):
                context = {'mode': 'OPERATIONAL', 'needs_wallet': True,
                           'category': pending.get('operational_category', 'Lain Lain')}
            else:
                # Pass category_scope from AI layer for smarter routing
                context = detect_transaction_context(original_text, txs, category_scope)

            # If still ambiguous, ask user to choose scope
            if context.get('mode') == 'AMBIGUOUS':
                set_pending_confirmation(
                    user_id=pending.get('sender_number', sender_number),
                    chat_id=pending.get('chat_jid', chat_jid),
                    data={
                        'type': 'category_scope',
                        'transactions': txs,
                        'raw_text': original_text,
                        'original_message_id': pending.get('message_id')
                    }
                )
                response = """🤔 Ini untuk Operational Kantor atau Project?

1️⃣ Operational Kantor
   (Gaji staff, listrik, wifi, ATK, dll)

2️⃣ Project
   (Material, upah tukang, transport ke site)

Balas 1 atau 2"""
                sent = send_reply(response)
                bid = extract_bot_msg_id(sent)
                if bid:
                    store_pending_message_ref(bid, f"{pending.get('chat_jid', chat_jid)}:{pending.get('sender_number', sender_number)}")
                return jsonify({'status': 'asking_scope'}), 200

            # Guardrail: Operational flow must not carry OCR-extracted project names.
            if context.get('mode') == 'OPERATIONAL':
                pending['project_confirmed'] = False
                pending['project_validated'] = False
                for tx in txs:
                    tx.pop('nama_projek', None)
                    tx.pop('needs_project', None)

            # === JALUR 1: OPERATIONAL ===
            if context['mode'] == 'OPERATIONAL':
                source_wallet = pending.get('selected_source_wallet')
                if not source_wallet:
                    # Auto-pick wallet when user already mentions it in text/AI extraction.
                    source_wallet = next(
                        (t.get('detected_dompet') for t in txs if t.get('detected_dompet')),
                        None,
                    )
                    # OCR-aware wallet detection: parse account numbers from receipt
                    if not source_wallet:
                        user_part, ocr_part = split_ocr_user_text(original_text)
                        if ocr_part:
                            source_wallet = extract_source_wallet_from_ocr(ocr_part)
                        # Fallback: resolve from user caption only (not OCR body)
                        if not source_wallet:
                            source_wallet = resolve_dompet_from_text(user_part)
                    if source_wallet:
                        pending['selected_source_wallet'] = source_wallet

                # Step 1: Ask Wallet if missing
                if not source_wallet:
                    pending['pending_type'] = 'select_source_wallet'
                    pending['is_operational'] = True
                    pending['operational_category'] = context['category']

                    prompt = format_wallet_selection_prompt()
                    total = sum(t.get('jumlah', 0) for t in txs)
                    item = txs[0].get('keterangan', 'Biaya')

                    if SMART_CONFIRMATION:
                        # Context-aware prompt: mention the detected item + amount
                        # so the question feels specific, not a blank menu.
                        try:
                            from services.smart_confirmation import build_wallet_question
                            body = build_wallet_question(
                                transactions=txs,
                                base_prompt=prompt,
                            )
                            msg = ("🏢 *Deteksi: Operasional Kantor*\n" + body)
                        except Exception:
                            msg = (f"🏢 *Deteksi: Operasional Kantor*\n"
                                   f"📝 {item} (Rp {total:,})\n\n"
                                   f"{prompt}").replace(',', '.')
                    else:
                        msg = (f"🏢 *Deteksi: Operasional Kantor*\n"
                               f"📝 {item} (Rp {total:,})\n\n"
                               f"{prompt}").replace(',', '.')

                    sent = send_reply(msg)
                    cache_prompt(pkey, pending, sent)
                    return jsonify({'status': 'asking_wallet'}), 200


                # Step 2: Save to Operational Sheet (fast mode auto-commit)
                if FAST_MODE:
                    event_id = pending.get('event_id') or pending.get('message_id')
                    _assign_tx_ids(txs, event_id)
                    category = context.get('category') or _detect_operational_category(
                        txs[0].get('keterangan', '') if txs else ''
                    )
                    for tx in txs:
                        kategori = category or _detect_operational_category(tx.get('keterangan', ''))
                        append_operational_transaction(
                            transaction={
                                'jumlah': tx['jumlah'],
                                'keterangan': tx['keterangan'],
                                'message_id': tx.get('message_id')
                            },
                            sender_name=pending.get('sender_name', sender_name),
                            source=pending.get('source', 'WhatsApp'),
                            source_wallet=source_wallet,
                            category=kategori
                        )

                    # Operational expenses can also be funded by another wallet.
                    # The expense belongs to the selected wallet; mirror the
                    # lender outflow and create the OPEN inter-wallet debt.
                    if debt_source_hint and source_wallet and debt_source_hint != source_wallet:
                        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in txs)
                        if total_amount > 0:
                            append_project_transaction(
                                transaction={
                                    'jumlah': total_amount,
                                    'keterangan': f'Hutang ke dompet {source_wallet}',
                                    'tipe': 'Pengeluaran',
                                    'message_id': f'{event_id}|UTANG',
                                },
                                sender_name=pending.get('sender_name', sender_name),
                                source=pending.get('source', 'WhatsApp'),
                                dompet_sheet=debt_source_hint,
                                project_name='Saldo Umum',
                            )
                            append_hutang_entry(
                                amount=total_amount,
                                keterangan=txs[0].get('keterangan', '') if txs else '',
                                yang_hutang=source_wallet,
                                yang_dihutangi=debt_source_hint,
                                message_id=f'{event_id}|HUTANG',
                            )

                    invalidate_dashboard_cache()
                    _pending_transactions.pop(pkey, None)

                    response = format_success_reply_operational(
                        txs,
                        source_wallet,
                        category,
                        "",
                    )
                    if debt_source_hint and source_wallet and debt_source_hint != source_wallet:
                        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in txs)
                        response += (
                            f'\n💳 Hutang dicatat: {source_wallet} pinjam dari '
                            f'{debt_source_hint} (Rp {total_amount:,})'
                        ).replace(',', '.')
                    _send_and_track(response, event_id)
                    return jsonify({'status': 'saved_operational'}), 200

                # Strict mode: Draft → Confirm → Commit
                set_pending_confirmation(
                    user_id=sender_number,
                    chat_id=chat_jid,
                    data={
                        'type': 'confirm_commit_operational',
                        'transactions': txs,
                        'source_wallet': source_wallet,
                        'category': context['category'],
                        'sender_name': pending.get('sender_name'),
                        'source': pending.get('source'),
                        'original_message_id': pending.get('message_id'),
                        'event_id': pending.get('event_id'),
                        'pending_key': pkey
                    }
                )
                draft_msg = format_draft_summary_operational(
                    txs, source_wallet, context.get('category'), mention
                )
                send_reply(draft_msg)
                return jsonify({'status': 'draft_operational'}), 200

            # === JALUR 2: PROJECT (Standard) ===
            lock_note = None
            new_project_expense_note = None
            wallet_set_note = None
            wallet_set_target_amount = None

            # --- VALIDATION: CHECK PROJECT EXISTENCE ---
            # Checks if project exists in Spreadsheet/Cache before proceeding
            if not pending.get('project_validated'):
                validation_user_part, _validation_ocr_part = split_ocr_user_text(original_text)
                validation_text_scope = validation_user_part or original_text
                validation_main_scope = (
                    _without_debt_source_context(validation_text_scope)
                    if has_debt_context
                    else validation_text_scope
                )
                validation_dompet_scope = resolve_dompet_from_text(validation_main_scope)
                validation_company_scope = resolve_company_from_text(
                    validation_main_scope,
                    validation_dompet_scope,
                )
                if not validation_dompet_scope and validation_company_scope and validation_company_scope != "UMUM":
                    validation_dompet_scope = get_dompet_for_company(validation_company_scope)

                for t in txs:
                    p_name_raw = t.get('nama_projek')
                    # Skip validation for "Saldo Umum", empty, or "Umum"
                    if not p_name_raw or p_name_raw.lower() in ['saldo umum', 'umum', 'unknown']:
                        inferred_project = infer_project_from_text_context(
                            validation_text_scope or original_text,
                            dompet_sheet=validation_dompet_scope,
                            company=validation_company_scope,
                            debt_source_dompet=debt_source_hint,
                        )
                        if inferred_project and inferred_project.get('status') in ['EXACT', 'AUTO_FIX']:
                            t['nama_projek'] = inferred_project['final_name']
                            pending['project_confirmed'] = True
                        continue

                    # Prefer the complete explicit project phrase over a short
                    # model token such as "Laundry" when the user said more.
                    explicit_project = extract_project_name_from_text(validation_text_scope or original_text)
                    raw_project_norm = re.sub(r"\s+", " ", str(p_name_raw or "").strip().lower())
                    explicit_project_norm = re.sub(r"\s+", " ", str(explicit_project or "").strip().lower())
                    if (
                        explicit_project_norm
                        and raw_project_norm
                        and len(explicit_project_norm) >= len(raw_project_norm) + 6
                        and re.search(rf"(?<!\w){re.escape(raw_project_norm)}(?!\w)", explicit_project_norm)
                    ):
                        p_name_raw = explicit_project
                        t['nama_projek'] = explicit_project
                    # Resolve Name
                    lookup_name = strip_company_prefix(p_name_raw)
                    res = resolve_project_name_for_context(
                        lookup_name,
                        dompet_sheet=validation_dompet_scope,
                        company=validation_company_scope,
                        debt_source_dompet=debt_source_hint,
                    )
                    if res['status'] == 'INVALID':
                        inferred_project = infer_project_from_text_context(
                            validation_text_scope or original_text,
                            dompet_sheet=validation_dompet_scope,
                            company=validation_company_scope,
                            debt_source_dompet=debt_source_hint,
                        )
                        explicit_project = extract_project_name_from_text(validation_text_scope or original_text)
                        if inferred_project and inferred_project.get('status') in ['EXACT', 'AUTO_FIX']:
                            t['nama_projek'] = inferred_project['final_name']
                            pending['project_confirmed'] = True
                            continue
                        if explicit_project and explicit_project.lower() != str(p_name_raw).strip().lower():
                            t['nama_projek'] = explicit_project
                            p_name_raw = explicit_project
                            lookup_name = strip_company_prefix(p_name_raw)
                            res = resolve_project_name_for_context(
                                lookup_name,
                                dompet_sheet=validation_dompet_scope,
                                company=validation_company_scope,
                                debt_source_dompet=debt_source_hint,
                            )
                        else:
                            t.pop('nama_projek', None)
                            t['needs_project'] = True
                            pending['project_confirmed'] = False
                            continue
                    if res['status'] == 'NEW':
                        inferred_project = infer_project_from_text_context(
                            validation_text_scope or original_text,
                            dompet_sheet=validation_dompet_scope,
                            company=validation_company_scope,
                            debt_source_dompet=debt_source_hint,
                        )
                        if inferred_project and inferred_project.get('status') in ['EXACT', 'AUTO_FIX']:
                            t['nama_projek'] = inferred_project['final_name']
                            pending['project_confirmed'] = True
                            continue
                    if res['status'] == 'AMBIGUOUS':
                        # Safety: never auto-pick ambiguous project names unless the user
                        # explicitly gave a trusted prefix (HOLLA/HOJJA) that resolves exactly.
                        raw_prefix = extract_company_prefix(p_name_raw or "")
                        if FAST_MODE and raw_prefix:
                            prefixed_candidate = f"{raw_prefix} - {lookup_name}"
                            prefixed_res = resolve_project_name(
                                prefixed_candidate,
                                dompet_sheet=validation_dompet_scope,
                                company=raw_prefix,
                            )
                            if prefixed_res.get('status') in ['EXACT', 'AUTO_FIX']:
                                t['nama_projek'] = prefixed_res.get('final_name') or prefixed_candidate
                                pending['project_confirmed'] = True
                                continue

                        pending['pending_type'] = 'confirmation_project'
                        pending['suggested_project'] = res.get('final_name') or res.get('original') or lookup_name
                        msg = (
                             f"🤔 *KONFIRMASI PROJECT*\n"
                             f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                             f"Maksudnya *{pending['suggested_project']}*?\n\n"
                             f"━━━━━━━━━━━━━━━━━━━━━\n"
                             f"✅ *Ya* — Lanjutkan\n"
                             f"❌ *Bukan* — Langsung ketik nama yang benar"
                         )
                        send_pending_reply(msg)
                        return jsonify({'status': 'asking_project_confirm'}), 200

                    elif res['status'] == 'NEW':
                        has_income = any(t.get('tipe') == 'Pemasukan' for t in txs)
                        pending['pending_type'] = 'confirmation_new_project'
                        pending['new_project_name'] = res['original']
                        if not has_income:
                            pending['new_project_first_expense'] = True
                            msg = (
                                f"\U0001F4C1 *PROJECT BARU*\n"
                                f"--------------------\n\n"
                                f"Project *{res['original']}* belum terdaftar.\n"
                                f"\U0001F4B8 *Transaksi: Pengeluaran*\n\n"
                                f"\U0001F4A1 Biasanya project baru dimulai dari *DP (Pemasukan)*\n\n"
                                f"--------------------\n"
                                f"Pilih tindakan:\n\n"
                                f"\u0031\ufe0f\u20e3 Lanjutkan sebagai project baru\n"
                                f"\u0032\ufe0f\u20e3 Ubah jadi Operasional Kantor\n"
                                f"\u0033\ufe0f\u20e3 Batal\n\n"
                                f"Atau ketik *nama lain* untuk ganti"
                            )
                            send_pending_reply(msg)
                            return jsonify({'status': 'asking_new_project'}), 200
                        msg = (
                            f"\U0001F4C1 *PROJECT BARU*\n"
                            f"--------------------\n\n"
                            f"Project *{res['original']}* belum terdaftar.\n\n"
                            f"--------------------\n"
                            f"Pilih tindakan:\n\n"
                            f"Ya - *Buat project baru*\n"
                            f"Ketik nama lain untuk ganti\n\n"
                            f"Balas *Ya* atau ketik nama baru"
                        )
                        send_pending_reply(msg)
                        return jsonify({'status': 'asking_new_project'}), 200
                    elif res['status'] in ['EXACT', 'AUTO_FIX']:

                        # Auto update to canonical name
                        t['nama_projek'] = res['final_name']
                        pending['project_confirmed'] = True

                # Mark as validated once all checks pass (no NEW/AMBIGUOUS trigger)
                pending['project_validated'] = True

            # 1. Resolve Company/Dompet
            detected_company = None
            for t in txs:
                raw_company = t.get('company')
                if raw_company:
                    detected_company = normalize_company_name(raw_company) or str(raw_company).strip()
                    break

            # Prefer explicit company mention in user text (e.g., "hojja").
            user_part, ocr_part = split_ocr_user_text(original_text)
            user_main_scope = (
                _without_debt_source_context(user_part or original_text)
                if has_debt_context
                else (user_part or original_text)
            )
            explicit_company = resolve_company_from_text(user_main_scope)
            selected_option = pending.get('selected_option') or {}
            selected_company = selected_option.get('company')
            if explicit_company:
                detected_company = explicit_company
            elif detected_company and detected_company != "UMUM" and not selected_company:
                # AI/model output may guess a company for project transactions.
                # If the user did not explicitly mention it and it was not selected
                # through the 1-5 prompt, keep it unresolved so we ask instead
                # of silently defaulting (e.g. bare project text -> TX SBY).
                secure_log(
                    "WARNING",
                    f"Company '{detected_company}' was not explicitly mentioned; asking user to choose",
                )
                detected_company = None

            dompet = None
            detected_dompet = next((t.get('detected_dompet') for t in txs if t.get('detected_dompet')), None)
            if detected_dompet:
                if has_debt_context and debt_source_hint and detected_dompet == debt_source_hint and not detected_company:
                    secure_log(
                        "INFO",
                        f"Ignoring detected dompet {detected_dompet} as main dompet (treated as debt source context)"
                    )
                else:
                    dompet = detected_dompet
                    # Only override company if not already detected by AI
                    if not detected_company:
                        scoped_company = resolve_company_from_text(user_part or original_text, dompet)
                        if scoped_company:
                            detected_company = scoped_company
                        elif dompet != "CV HB(101)":
                            detected_company = get_company_name_from_sheet(dompet)

            if detected_company:
                if detected_company == "UMUM":
                    dompet = pending.get('override_dompet')
                else:
                    dompet = get_dompet_for_company(detected_company)

            # OCR-aware: resolve dompet from user caption (not OCR body)
            explicit_dompet = resolve_dompet_from_text(user_part)
            # If user caption didn't mention a wallet, try OCR account numbers
            if not explicit_dompet and ocr_part:
                explicit_dompet = extract_source_wallet_from_ocr(ocr_part)
            if explicit_dompet:
                if has_debt_context and debt_source_hint and explicit_dompet == debt_source_hint:
                    secure_log(
                        "INFO",
                        f"Ignoring explicit dompet {explicit_dompet} as main dompet (treated as debt source context)"
                    )
                    explicit_dompet = None
                else:
                    dompet = explicit_dompet
                    # Only override company if not already detected by AI,
                    # OR if AI company doesn't belong to the resolved dompet.
                    if detected_company:
                        valid_companies = DOMPET_COMPANIES.get(dompet, [])
                        if detected_company not in valid_companies:
                            scoped_company = resolve_company_from_text(user_part or original_text, dompet)
                            if scoped_company:
                                detected_company = scoped_company
                            elif dompet != "CV HB(101)":
                                detected_company = get_company_name_from_sheet(dompet)
                            else:
                                detected_company = None
                    else:
                        scoped_company = resolve_company_from_text(user_part or original_text, dompet)
                        if scoped_company:
                            detected_company = scoped_company
                        elif dompet != "CV HB(101)":
                            detected_company = get_company_name_from_sheet(dompet)

            if dompet and not detected_company and pending.get('project_confirmed'):
                valid_companies = set(DOMPET_COMPANIES.get(dompet, []))
                for t in txs:
                    project_company = extract_company_prefix(t.get('nama_projek') or "")
                    if project_company and project_company in valid_companies:
                        detected_company = project_company
                        secure_log(
                            "INFO",
                            f"Resolved company from canonical project prefix '{project_company}' for {dompet}"
                        )
                        break

            # --- AUTO-RESOLVE COMPANY FROM PROJECT HISTORY (NEW) ---
            # If we know the project, but not the company, try to find where it was last used
            if not dompet and pending.get('project_confirmed'):
                # Check first transaction's project
                p_name_check = txs[0].get('nama_projek')
                if p_name_check:
                    found_dompet, found_comp = find_company_for_project_exact(p_name_check)
                    if found_dompet:
                        dompet = found_dompet
                        detected_company = found_comp
                        if found_comp:
                            secure_log("INFO", f"Auto-resolved project exact-match '{p_name_check}' to {found_comp}")
                        else:
                            secure_log(
                                "INFO",
                                f"Auto-resolved dompet for project '{p_name_check}' to {found_dompet}; company remains ambiguous"
                            )

            needs_company_selection = (
                context.get('mode') == 'PROJECT'
                and pending.get('is_new_project')
                and not pending.get('selected_option')
                and not explicit_company
                and not explicit_dompet
            )
            if needs_company_selection:
                pending['pending_type'] = 'selection'
                reply = (
                    "📁 *PROJECT BARU*\n"
                    "Project baru belum punya company/dompet yang jelas.\n\n"
                    "Pilih company untuk project ini supaya tidak otomatis masuk ke TX SBY.\n\n"
                    f"{build_selection_prompt(txs)}"
                )
                if is_group:
                    reply += "\n\n↩️ Reply angka 1-5"
                sent = send_pending_reply(reply)
                cache_prompt(pkey, pending, sent)
                return jsonify({'status': 'asking_company_for_new_project'}), 200

            # 2. Save if Resolved
            if detected_company and dompet:
                debt_source = debt_source_hint

                is_transfer_flow = pending.get('category_scope') == 'TRANSFER'
                is_wallet_set_mode = is_transfer_flow and is_absolute_balance_update(original_text)
                skip_duplicate_check = False

                if is_wallet_set_mode:
                    target_amount = pick_wallet_target_amount(txs)
                    if target_amount <= 0:
                        send_reply("❗ Nominal target saldo belum terbaca. Contoh: update saldo dompet TX SBY 10jt")
                        return jsonify({'status': 'wallet_set_missing_amount'}), 200

                    balances = get_wallet_balances()
                    dompet_info = balances.get(dompet, {})
                    current_balance = int(dompet_info.get('saldo', 0) or 0)
                    adjustment = compute_balance_adjustment(current_balance, target_amount)

                    if int(adjustment.get('amount', 0) or 0) <= 0:
                        _pending_transactions.pop(pkey, None)
                        response = (
                            f"ℹ️ Saldo {dompet} sudah sesuai target (Rp {target_amount:,}). "
                            "Tidak ada transaksi penyesuaian."
                        ).replace(',', '.')
                        _send_and_track(response, pending.get('event_id') or pending.get('message_id'))
                        return jsonify({'status': 'wallet_set_no_change'}), 200

                    adj_amount = int(adjustment.get('amount', 0) or 0)
                    adj_tipe = str(adjustment.get('tipe') or 'Pemasukan')
                    adj_delta = int(adjustment.get('delta', 0) or 0)

                    tx_template = dict(txs[0]) if txs else {}
                    tx_template['jumlah'] = adj_amount
                    tx_template['tipe'] = adj_tipe
                    tx_template['nama_projek'] = 'Saldo Umum'
                    tx_template['company'] = 'UMUM'
                    tx_template['needs_project'] = False
                    tx_template['keterangan'] = (
                        f"Set saldo ke Rp {target_amount:,} (saldo sebelumnya Rp {current_balance:,})"
                    ).replace(',', '.')
                    txs[:] = [tx_template]
                    pending['transactions'] = txs
                    # Isolate wallet-set flow from debt/project side effects.
                    debt_source = None
                    wallet_set_target_amount = target_amount

                    sign = "+" if adj_delta > 0 else "-"
                    wallet_set_note = (
                        f"Mode set saldo: target Rp {target_amount:,}, "
                        f"saldo sebelumnya Rp {current_balance:,}, "
                        f"penyesuaian {sign}Rp {abs(adj_delta):,}. "
                        f"Rumus: {current_balance:,} {sign} {abs(adj_delta):,} = {target_amount:,}."
                    ).replace(',', '.')
                    skip_duplicate_check = True

                # Check Duplicates
                t0 = txs[0]
                if not skip_duplicate_check:
                    is_dupe, warn = check_duplicate_transaction(
                        t0.get('jumlah', 0), t0.get('keterangan', ''),
                        t0.get('nama_projek', ''), detected_company
                    )

                    if is_dupe:
                        pending['pending_type'] = 'confirmation_dupe'
                        pending['selected_option'] = {'dompet': dompet, 'company': detected_company}
                        send_reply(warn)
                        return jsonify({'status': 'dupe_warning'}), 200

                # Project lock check (consistency across dompet)
                # IMPORTANT:
                # If user explicitly mentions company/dompet in current message,
                # don't silently override in FAST_MODE. Prefer current explicit intent
                # and force confirmation flow on mismatch.
                p_name_check = t0.get('nama_projek', '')
                if p_name_check and p_name_check.lower() not in ['saldo umum', 'operasional kantor', 'umum', 'unknown']:
                    locked_dompet = get_project_lock(p_name_check)
                    if locked_dompet and locked_dompet != dompet:
                        locked_company = get_company_name_from_sheet(locked_dompet)
                        user_explicit_wallet_intent = bool(explicit_dompet or explicit_company)
                        if FAST_MODE and not user_explicit_wallet_intent:
                            dompet = locked_dompet
                            detected_company = locked_company
                            lock_note = f"Dompet disesuaikan ke {locked_dompet} (sesuai riwayat project)."
                        else:
                            # Ask user to confirm locked dompet or move project
                            debt_source_is_input = bool(debt_source and debt_source == dompet)
                            set_pending_confirmation(
                                user_id=sender_number,
                                chat_id=chat_jid,
                                data={
                                    'type': 'project_dompet_mismatch',
                                    'transactions': txs,
                                    'dompet_input': dompet,
                                    'company_input': detected_company,
                                    'dompet_locked': locked_dompet,
                                    'company_locked': locked_company,
                                    'debt_source_dompet': debt_source,
                                    'raw_text': original_text,
                                    'sender_name': pending.get('sender_name'),
                                    'source': pending.get('source'),
                                    'original_message_id': pending.get('message_id'),
                                    'event_id': pending.get('event_id'),
                                    'is_new_project': pending.get('is_new_project', False),
                                    'pending_key': pkey
                                }
                            )
                            if debt_source_is_input:
                                msg = (
                                    f"\u26a0\ufe0f *KONFIRMASI SUMBER DANA*\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"\U0001F4C1 Project: *{p_name_check}*\n"
                                    f"\U0001F4CC Project terdaftar di: *{locked_dompet}*\n"
                                    f"\U0001F4B3 Sumber dana terdeteksi: *{dompet}*\n\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"*Pilih tindakan:*\n\n"
                                    f"\u0031\ufe0f\u20e3  Catat project di {locked_dompet}, pinjam dari {dompet}\n"
                                    f"\u0032\ufe0f\u20e3  Pindahkan project ke {dompet}\n"
                                    f"\u0033\ufe0f\u20e3  Batal\n\n"
                                    f"↩️ _Balas 1, 2, 3, atau ketik: pinjam <dompet>_"
                                )
                            else:
                                msg = (
                                    f"\u26a0\ufe0f *KONFIRMASI DOMPET*\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"\U0001F4C1 Project: *{p_name_check}*\n"
                                    f"\U0001F4CC Terdaftar di: *{locked_dompet}*\n"
                                    f"\U0001F504 Input baru: *{dompet}*\n\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"*Pilih tindakan:*\n\n"
                                    f"\u0031\ufe0f\u20e3  Gunakan dompet terdaftar ({locked_dompet})\n"
                                    f"\u0032\ufe0f\u20e3  Pindahkan project ke ({dompet})\n"
                                    f"\u0033\ufe0f\u20e3  Batal\n\n"
                                    f"↩️ _Balas 1, 2, 3, atau ketik: pinjam <dompet>_"
                                )
                            send_reply(msg)
                            return jsonify({'status': 'project_lock_mismatch'}), 200

                # Normalize debt_source only after final dompet is resolved
                if debt_source == dompet:
                    debt_source = None


                for t in txs:
                    pname = t.get('nama_projek')
                    if pname:
                        t['nama_projek'] = apply_company_prefix(pname, dompet, detected_company)

                # Fast mode: commit directly
                if FAST_MODE:
                    event_id = pending.get('event_id') or pending.get('message_id')
                    _assign_tx_ids(txs, event_id)
                    is_new_project_batch = bool(pending.get('is_new_project', False))
                    start_marker_indexes = (
                        select_start_marker_indexes(txs) if is_new_project_batch else set()
                    )
                    failed_saves = []
                    for idx, tx in enumerate(txs):
                        pname = tx.get('nama_projek') or 'Umum'
                        pname = apply_company_prefix(pname, dompet, detected_company)
                        pname = apply_lifecycle_markers(
                            pname,
                            tx,
                            is_new_project=is_new_project_batch,
                            allow_finish=True,
                            allow_start=(not is_new_project_batch) or (idx in start_marker_indexes),
                        )
                        save_result = append_project_transaction(
                            transaction={
                                'jumlah': tx['jumlah'],
                                'keterangan': tx['keterangan'],
                                'tipe': tx.get('tipe', 'Pengeluaran'),
                                'message_id': tx.get('message_id')
                            },
                            sender_name=pending.get('sender_name', sender_name),
                            source=pending.get('source', 'WhatsApp'),
                            dompet_sheet=dompet,
                            project_name=pname
                        )
                        if not save_result.get('success'):
                            failed_saves.append({
                                'tx': tx,
                                'error': save_result.get('error', 'Unknown error'),
                                'pname': pname
                            })
                        if save_result.get('success') and has_finish_marker(pname):
                            move_finish_marker_to_latest(
                                dompet_sheet=dompet,
                                project_name=pname,
                                keep_row=save_result.get('row'),
                                keep_tipe=tx.get('tipe', ''),
                            )
                        if pname and pname.lower() not in ['saldo umum', 'operasional kantor', 'umum', 'unknown']:
                            set_project_lock(pname, dompet, actor=pending.get('sender_name', sender_name), reason='commit')
                            remember_project_knowledge(
                                project_name=pname,
                                dompet_sheet=dompet,
                                company=detected_company,
                                actor=pending.get('sender_name', sender_name),
                                source=pending.get('source', 'WhatsApp'),
                                status='finished' if has_finish_marker(pname) else 'active',
                            )

                    # If any saves failed, notify user and abort success flow
                    if failed_saves:
                        _pending_transactions.pop(pkey, None)
                        fail_count = len(failed_saves)
                        total_count = len(txs)
                        error_msg = failed_saves[0].get('error', '')
                        response = (
                            f"❌ Gagal menyimpan {fail_count}/{total_count} transaksi ke spreadsheet!\n"
                            f"📋 Dompet: {dompet}\n"
                            f"⚠️ Penyebab: {error_msg[:150]}\n\n"
                            f"Coba kirim ulang transaksi."
                        )
                        _send_and_track(response, event_id)
                        return jsonify({'status': 'sheet_write_failed', 'failed': fail_count}), 200

                    # If funded by another dompet (utang), record lender outflow only
                    if debt_source and debt_source != dompet:
                        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in txs)
                        if total_amount > 0:
                            debt_desc = f"Hutang ke dompet {dompet}"
                            append_project_transaction(
                                transaction={
                                    'jumlah': total_amount,
                                    'keterangan': debt_desc,
                                    'tipe': 'Pengeluaran',
                                    'message_id': f"{event_id}|UTANG"
                                },
                                sender_name=pending.get('sender_name', sender_name),
                                source=pending.get('source', 'WhatsApp'),
                                dompet_sheet=debt_source,
                                project_name="Saldo Umum"
                            )
                            # Log hutang entry (borrower = dompet, lender = debt_source)
                            append_hutang_entry(
                                amount=total_amount,
                                keterangan=txs[0].get('keterangan', '') if txs else '',
                                yang_hutang=dompet,
                                yang_dihutangi=debt_source,
                                message_id=f"{event_id}|HUTANG"
                            )

                    if pending.get('is_new_project'):
                        raw_proj = txs[0].get('nama_projek') if txs else ''
                        if raw_proj:
                            add_new_project_to_cache(raw_proj)

                    # Fase 2a: shadow-compare narrow_resolver (log-only, no behavior change).
                    _shadow_compare_narrow_resolver(
                        original_text,
                        dompet,
                        debt_source if debt_source and debt_source != dompet else None,
                        [t.get('nama_projek') for t in txs],
                    )

                    invalidate_dashboard_cache()
                    _pending_transactions.pop(pkey, None)
                    response = format_success_reply_new(txs, dompet, detected_company, "")

                    if lock_note:
                        response += f"\n {lock_note}"
                    if new_project_expense_note:
                        response += f"\n {new_project_expense_note}"
                    if wallet_set_note:
                        response += f"\n {wallet_set_note}"
                    if is_wallet_set_mode and wallet_set_target_amount is not None:
                        verified_balance = None
                        verified_ok = False
                        for _ in range(4):
                            try:
                                verified = get_wallet_balances()
                                verified_balance = int((verified.get(dompet) or {}).get('saldo', 0) or 0)
                                if verified_balance == wallet_set_target_amount:
                                    verified_ok = True
                                    break
                            except Exception as e:
                                secure_log("WARNING", f"Wallet set verification failed for {dompet}: {type(e).__name__}: {e}")
                            time.sleep(0.35)

                        if verified_ok:
                            response += (
                                f"\n✅ Verifikasi: saldo {dompet} sekarang Rp {wallet_set_target_amount:,}."
                            ).replace(',', '.')
                        else:
                            shown = verified_balance if verified_balance is not None else 0
                            response += (
                                f"\n⚠️ Verifikasi belum cocok. Target Rp {wallet_set_target_amount:,}, "
                                f"terbaca Rp {shown:,}. Cek lagi /saldo 10-20 detik."
                            ).replace(',', '.')
                    if debt_source and debt_source != dompet:
                        total_amount = sum(int(t.get('jumlah', 0) or 0) for t in txs)
                        response += f"\n💳 Utang dicatat: {debt_source} → {dompet} (Rp {total_amount:,})".replace(',', '.')
                    _send_and_track(response, event_id)
                    return jsonify({'status': 'saved_project'}), 200

                # Strict mode: Draft ? Confirm ? Commit
                set_pending_confirmation(
                    user_id=sender_number,
                    chat_id=chat_jid,
                    data={
                        'type': 'confirm_commit_project',
                        'transactions': txs,
                        'dompet': dompet,
                        'company': detected_company,
                        'debt_source_dompet': debt_source,
                        'sender_name': pending.get('sender_name'),
                        'source': pending.get('source'),
                        'original_message_id': pending.get('message_id'),
                        'event_id': pending.get('event_id'),
                        'is_new_project': pending.get('is_new_project', False),
                        'pending_key': pkey,
                        'raw_text': original_text
                    }
                )
                draft_msg = format_draft_summary_project(
                    txs, dompet, detected_company, mention, debt_source or ""
                )
                if wallet_set_note:
                    draft_msg += f"\n{wallet_set_note}"
                send_reply(draft_msg)
                return jsonify({'status': 'draft_project'}), 200

            # 3. Ask Company if Unresolved
            pending['pending_type'] = 'selection'
            reply = build_selection_prompt(txs)
            if is_group: reply += "\n\n↩️ Reply angka 1-5"
            sent = send_pending_reply(reply)
            cache_prompt(pkey, pending, sent)
            return jsonify({'status': 'asking_company'}), 200

        # --- FLOW CONTROL ---

        # 1. Rate Limit
        allowed, wait = rate_limit_check(sender_number)
        if not allowed: return jsonify({'status': 'rate_limit'}), 200

        recent_text_for_image = ""
        recent_scope_hint = None

        # 2. Visual Buffer (store all images for "catat diatas" binding)
        if input_type == 'image' and not deferred:
            recent_text_for_image = (
                get_user_last_message(
                    sender_number,
                    chat_jid,
                    max_age_seconds=max(1, OWNER_FAST_FOLLOW_SECONDS)
                ) or ""
            ).strip()
            if recent_text_for_image:
                recent_lower = recent_text_for_image.lower()
                if re.search(r"\b(operasional|kantor|operational|office|ops)\b", recent_lower):
                    recent_scope_hint = "OPERATIONAL"
                elif re.search(r"\b(projek|project|proyek|prj)\b", recent_lower):
                    recent_scope_hint = "PROJECT"

            visual_context = {}
            if recent_scope_hint:
                visual_context["category_scope"] = recent_scope_hint
            if recent_text_for_image:
                visual_context["original_text"] = recent_text_for_image

            store_visual_buffer(
                sender_number, chat_jid, media_url, message_id,
                caption=text, media_path=local_media_path, context=visual_context
            )

        has_visual = has_visual_buffer(sender_number, chat_jid)

        # If user says "catat diatas" but no buffered image, ask to reply/attach
        if input_type == 'text':
            ref_phrase = re.search(r'\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b', (text or '').lower())
            if ref_phrase and not has_visual and not quoted_msg_id:
                send_reply("❗ Belum ada gambar/struk sebelumnya. Tolong reply struknya atau kirim ulang.")
                return jsonify({'status': 'missing_reference'}), 200

        # Strict group mode: answer-like texts must reply to a mapped bot prompt.
        # This avoids cross-session mistakes when multiple users interact concurrently.
        if is_group and input_type == 'text' and _looks_like_ambiguous_reply(text):
            active_sessions = _count_active_group_sessions(chat_jid)
            if active_sessions > 0:
                quoted_pending_ref = get_pending_key_from_message(quoted_msg_id) if quoted_msg_id else ''
                if not quoted_pending_ref and quoted_msg_id:
                    # Fallback: user replied, but prompt->pending mapping might be missing.
                    # If user still has own pending confirmation, let flow continue.
                    user_pending_conf = get_pending_confirmation(sender_number, chat_jid)
                    if user_pending_conf:
                        quoted_pending_ref = f"{chat_jid}:{sender_number}"
                    else:
                        user_pending_key = pending_key(sender_number, chat_jid)
                        user_pending_data = _pending_transactions.get(user_pending_key)
                        if user_pending_data and not pending_is_expired(user_pending_data):
                            quoted_pending_ref = user_pending_key
                if quoted_pending_ref and not _can_access_pending_key(
                    quoted_pending_ref, via_reply=bool(quoted_msg_id)
                ):
                    quoted_pending_ref = ''
                if not quoted_pending_ref:
                    if quoted_msg_id:
                        send_reply(UserErrors.GROUP_REPLY_PROMPT_NOT_ACTIVE)
                        return jsonify({'status': 'prompt_not_active_for_answer'}), 200
                    if should_send_group_reply_hint(chat_jid, sender_number, "reply_required_for_answers"):
                        send_reply(UserErrors.GROUP_REPLY_REQUIRED)
                    return jsonify({'status': 'reply_required_for_answers'}), 200

        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        # ========================================
        # STEP 0: CHECK PENDING CONFIRMATION (New Logic)
        # ========================================
        from handlers.pending_handler import handle_pending_response
        quoted_pending_key = ''
        pending_conf_key = ''
        if is_group and quoted_msg_id:
            quoted_pending_key = get_pending_key_from_message(quoted_msg_id) or ''
            if quoted_pending_key:
                if not _can_access_pending_key(quoted_pending_key, via_reply=True):
                    send_reply(_session_access_denied_message())
                    return jsonify({'status': 'session_access_denied'}), 200
                secure_log("DEBUG", f"Found pending ref: {quoted_msg_id[:20]}... -> {quoted_pending_key}")
            else:
                secure_log("DEBUG", f"No pending ref for quoted_msg_id: {quoted_msg_id[:20]}...")

        pending_conf = None
        if is_group and quoted_pending_key:
            # Reply to bot prompt takes precedence and can target any user's session.
            pending_conf = _get_pending_confirmation_by_key(quoted_pending_key)
            if pending_conf:
                pending_conf_key = quoted_pending_key

        if not pending_conf:
            pending_conf = get_pending_confirmation(sender_number, chat_jid)
            if pending_conf:
                pending_conf_key = f"{chat_jid}:{sender_number}"

        # Strict group mode: quick confirmations without reply are never auto-routed.
        # This avoids accidental takeover when multiple users are active.
        if pending_conf:
            pending_conf_user = _get_pending_owner_user_from_key(
                pending_conf_key,
                chat_jid,
                sender_number
            )
            if is_group and not _can_access_group_session(
                pending_conf_user,
                via_reply=bool(quoted_msg_id and pending_conf_key == quoted_pending_key),
            ):
                send_reply(_session_access_denied_message())
                return jsonify({'status': 'session_access_denied'}), 200
            if input_type == 'image' and not (text or '').strip():
                secure_log(
                    "INFO",
                    f"Buffered image {message_id} while pending confirmation is active; waiting user reply"
                )
                return jsonify({'status': 'buffered_image_pending_confirmation'}), 200
            # Check if handled by pending handler
            send_reply("⏳ Memproses jawaban...")
            pending_started_at = time.perf_counter()
            try:
                result = handle_pending_response(
                    user_id=pending_conf_user,
                    chat_id=chat_jid,
                    text=text,
                    pending_data=pending_conf,
                    sender_name=sender_name
                )
            finally:
                log_timing("pending_response", pending_started_at)

            if result:
                if result.get('response'):
                    sent = send_reply(result['response'])
                    bid = extract_bot_msg_id(sent)
                    if bid and pending_conf_key:
                        # Allow next answer to be routed by replying bot prompt message.
                        store_pending_message_ref(bid, pending_conf_key)
                    # Store bot message ref for revision tracking if provided
                    if result.get('bot_ref_event_id'):
                        bid = bid or extract_bot_msg_id(sent)
                        if bid:
                            store_bot_message_ref(bid, result.get('bot_ref_event_id'))
                            store_last_bot_report(chat_jid, bid)
                        store_last_tx_event(pending_conf_user, chat_jid, result.get('bot_ref_event_id'))

                if result.get('completed'):
                    # Flow finished (saved or cancelled)
                    return jsonify({'status': 'handled_confirmation'}), 200
                else:
                    # Flow continues (asked next question)
                    return jsonify({'status': 'pending_interaction'}), 200

        # 3. Check Pending (Standard/Legacy)
        sender_pkey = pending_key(sender_number, chat_jid)
        pending_pkey = sender_pkey
        pending_routed_by_prompt = False
        if is_group and quoted_msg_id:
            mapped = quoted_pending_key or get_pending_key_from_message(quoted_msg_id)
            if mapped:
                if not _can_access_pending_key(mapped, via_reply=True):
                    send_reply(_session_access_denied_message())
                    return jsonify({'status': 'session_access_denied'}), 200
                pending_pkey = mapped
                pending_routed_by_prompt = True

        pending_data = _pending_transactions.get(pending_pkey)
        if pending_data and pending_is_expired(pending_data):
            _pending_transactions.pop(pending_pkey, None)
            pending_data = None

        has_pending = pending_data is not None
        if has_pending and is_group:
            pending_owner = str(
                pending_data.get('sender_number')
                or _extract_pending_owner_from_key(pending_pkey)
                or ""
            ).strip()
            if pending_owner and pending_owner != sender_number:
                if not _can_access_group_session(pending_owner, via_reply=pending_routed_by_prompt):
                    send_reply(_session_access_denied_message())
                    return jsonify({'status': 'session_access_denied'}), 200

        # If /cancel is sent without any pending flow, clear visual buffer and stop.
        if is_command_match(text, Commands.CANCEL, is_group) and not has_pending and not pending_conf:
            clear_visual_buffer(sender_number, chat_jid)
            send_reply(UserErrors.CANCELLED)
            return jsonify({'status': 'cancelled_no_pending'}), 200

        # If user sends a bare selection number without pending context:
        # - in group: require reply to avoid cross-session mistakes
        # - in private: keep legacy fallback message
        if not has_pending:
            clean_sel = (text or "").strip()
            if clean_sel.isdigit() and len(clean_sel) <= 2:
                if is_group and chat_jid:
                    if quoted_msg_id:
                        send_reply(UserErrors.GROUP_REPLY_PROMPT_NOT_ACTIVE)
                        return jsonify({'status': 'prompt_not_active_for_selection'}), 200
                    send_reply(UserErrors.NO_ACTIVE_QUESTION)
                    return jsonify({'status': 'no_active_selection'}), 200
                else:
                    send_reply(UserErrors.NO_ACTIVE_QUESTION)
                    return jsonify({'status': 'no_pending_selection'}), 200

        # Bind split image/text events before any group or AI gate. A webhook log
        # appearing first does not guarantee its request reaches the buffer first.
        raw_text = text or ""
        explicit_catat = is_explicit_catat_command(raw_text)
        quoted_visual_item = None
        if input_type == 'text' and quoted_msg_id:
            quoted_visual_item = get_visual_buffer_by_message(chat_jid, quoted_msg_id)

        visual_item = quoted_visual_item
        should_bind_visual = input_type == 'text' and _should_bind_visual_text(text)
        if input_type == 'text' and not visual_item:
            user_buf = get_visual_buffer(sender_number, chat_jid)
            if not user_buf and should_bind_visual and SPLIT_EVENT_JOIN_SECONDS > 0:
                user_buf = wait_for_visual_buffer(
                    sender_number,
                    chat_jid,
                    timeout_seconds=SPLIT_EVENT_JOIN_SECONDS,
                )

            now = datetime.now()
            for item in reversed(user_buf):
                candidate_id = item.get('message_id')
                if candidate_id and is_visual_message_consumed(chat_jid, candidate_id):
                    continue
                created = item.get('created_at')
                if isinstance(created, datetime):
                    age_seconds = (now - created).total_seconds()
                    if age_seconds > SPLIT_EVENT_PAIR_WINDOW_SECONDS:
                        continue
                visual_item = item
                break

        if input_type == 'text' and quoted_msg_id and not visual_item and should_bind_visual:
            if is_visual_message_consumed(chat_jid, quoted_msg_id):
                send_reply("ℹ️ Struk ini sudah diproses. Gunakan /revisi atau /undo jika perlu koreksi.")
                return jsonify({'status': 'duplicate_visual_reference'}), 200

        if visual_item and should_bind_visual:
            candidate_id = str(visual_item.get('message_id') or "")
            media_url = visual_item.get('media_url')
            local_media_path = visual_item.get('media_path')
            buf_caption = visual_item.get('caption') or ''
            ref_phrase = re.search(
                r'\b(catat\s+(di\s+)?(atas|tadi|sebelumnya)|catat\s+itu)\b',
                (text or '').lower(),
            )
            if ref_phrase and buf_caption.strip():
                text = buf_caption.strip()
            input_type = 'image'
            if candidate_id:
                bound_visual_message_id = candidate_id
                # Use the visual source as the stable ledger id in both the live
                # path and crash-recovery path, preventing split-flow duplicates.
                event_id = candidate_id
                g.transaction_visual_message_id = candidate_id
            secure_log(
                "INFO",
                f"Joined split transaction text={message_id} visual={candidate_id}",
            )

        quoted_visual_actionable = bool(visual_item and should_bind_visual)
        has_visual = (
            has_visual_buffer(sender_number, chat_jid) or quoted_visual_actionable
        ) if is_group else False
        # Group noise gate (pre-AI): avoid processing random media/chatter.
        if is_group and not has_pending:
            is_mentioned = False
            try:
                is_mentioned = is_explicit_bot_call(text)
            except Exception:
                is_mentioned = False
            should, cleaned = should_respond_in_group(
                text or "",
                is_group,
                has_media=(input_type == 'image' or media_url is not None or has_visual),
                has_pending=has_pending,
                is_mentioned=is_mentioned
            )
            if not should:
                return jsonify({'status': 'ignored_group'}), 200
            if cleaned:
                text = cleaned

        # 4. Filter AI Trigger
        if explicit_catat:
            text = strip_explicit_catat_command(raw_text)
        text = sanitize_input(text or '')
        extraction_text = text
        force_record = explicit_catat

        # ========== PRIORITY: COMMANDS FIRST (before layer processing) ==========
        if text.strip().startswith('/'):
            # /catat -> force transaction, strip command
            if text.lower().startswith('/catat'):
                force_record = True
                text = text[len('/catat'):].strip()

            if is_command_match(text, Commands.START, is_group):
                send_reply(START_MESSAGE)
                return jsonify({'status': 'command_start'}), 200

            if is_command_match(text, Commands.HELP, is_group):
                send_reply(HELP_MESSAGE)
                return jsonify({'status': 'command_help'}), 200

            if is_command_match(text, Commands.SALDO, is_group):
                try:
                    balances = get_wallet_balances()
                    msg = _build_saldo_message(balances)
                    send_reply(msg)
                    return jsonify({'status': 'command_saldo'}), 200
                except Exception as e:
                    secure_log("ERROR", f"Saldo command failed: {e}")
                    send_reply(UserErrors.SHEET_READ_FAILED)
                    return jsonify({'status': 'error'}), 200

            if is_prefix_match(text, Commands.LUNAS_PREFIXES, is_group):
                try:
                    match = re.search(r"\b(\d+)\b", text)
                    if not match:
                        send_reply(UserErrors.HUTANG_FORMAT)
                        return jsonify({'status': 'command_lunas_invalid'}), 200
                    no = int(match.group(1))
                    info = settle_hutang(no, sender_name=sender_name, source='WhatsApp')
                    if not info:
                        send_reply(UserErrors.HUTANG_NOT_FOUND.format(no=no))
                        return jsonify({'status': 'command_lunas_not_found'}), 200
                    if info.get('error'):
                        send_reply(UserErrors.HUTANG_SETTLE_FAILED.format(no=no, reason=info['error']))
                        return jsonify({'status': 'command_lunas_failed'}), 200
                    invalidate_dashboard_cache()
                    send_reply(_format_hutang_paid_response(info))
                    return jsonify({'status': 'command_lunas'}), 200
                except Exception as e:
                    secure_log("ERROR", f"Lunas command failed: {e}")
                    send_reply(UserErrors.HUTANG_SETTLE_FAILED.format(no="?", reason="sistem tidak bisa membaca/update data. Coba lagi 1 menit."))
                    return jsonify({'status': 'error'}), 200


            if is_command_match(text, Commands.STATUS, is_group):
                try:
                    dashboard = get_dashboard_summary()
                    msg = format_dashboard_message(dashboard)
                    send_reply(msg)
                    return jsonify({'status': 'command_status'}), 200
                except Exception as e:
                    secure_log("ERROR", f"Status command failed: {e}")
                    send_reply(UserErrors.SHEET_READ_FAILED)
                    return jsonify({'status': 'error'}), 200

    # ========================================
    # NEW: /tanya Command - AI Query dengan Real Data
    # ========================================
            if text.startswith('/tanya '):
                query = text.replace('/tanya ', '').strip()

                if not query:
                    send_reply("💡 Contoh: /tanya cek keuangan hari ini")
                    return jsonify({'status': 'command_tanya_empty'}), 200

                try:
                    from handlers.query_handler import handle_query_command

                    # Send "analyzing" message first
                    send_reply("🤔 Menganalisis data...")

                    # Get answer with real data
                    answer = handle_query_command(query, sender_number, chat_jid)

                    # Send answer
                    response = answer
                    send_reply(response)

                    return jsonify({'status': 'command_tanya_success'}), 200

                except Exception as e:
                    # secure_assert logger is not defined in this scope locally, using secure_log if available or just print
                    secure_log("ERROR", f"/tanya command failed: {e}")
                    send_reply(UserErrors.QUERY_FAILED)
                    return jsonify({'status': 'command_tanya_error'}), 200

        # Initialize category scope and intent variables (prevent UnboundLocalError)
        layer_category_scope = 'UNKNOWN'
        intent = 'UNKNOWN'
        action = 'IGNORE'
        is_reply_to_bot = False
        transfer_dompet = None
        smart_result = {}
        processing_ack_sent = False

        def run_smart_handler():
            started_at = time.perf_counter()
            try:
                return smart_handler.process(
                    text=text,
                    chat_jid=chat_jid,
                    sender_number=sender_number,
                    reply_message_id=quoted_msg_id,
                    has_media=(input_type == 'image' or media_url is not None),
                    sender_name=sender_name,
                    quoted_message_text=quoted_message_text,
                    has_visual=has_visual,
                )
            finally:
                log_timing("smart_handler", started_at)

        # Acknowledge clear finance inputs before the classifier or extractor.
        # Group chatter still stays quiet unless it carries an actionable signal.
        clear_finance_signal = (
            input_type == 'image'
            or force_record
            or is_explicit_bot_call(text)
            or (
                has_amount_pattern(text)
                and bool(re.search(
                    r"\b(dp|fee|gaji|upah|bayar|beli|biaya|transfer|saldo|hutang|utang|projek|project|proyek|operasional|dompet|wifi|nota|struk)\b",
                    (text or '').lower(),
                ))
            )
            or (
                not is_group
                and bool(re.search(
                    r"\b(saldo|hutang|utang|dompet|transfer|bayar|beli|biaya|fee|gaji|upah|nota|struk|projek|project|proyek|operasional|wifi)\b",
                    (text or '').lower(),
                ))
            )
        )
        if not has_pending and clear_finance_signal:
            send_reply("⏳ Memproses...")
            processing_ack_sent = True

        deterministic_scope = (
            _deterministic_transaction_scope(text)
            if input_type == 'text' and not has_pending
            else None
        )

        if has_pending:
            # Bypass AI if pending active to reach state machine below
            pass
        else:
            # ==== Context Enhancement: Combine with last message if applicable ====
            last_message = get_user_last_message(sender_number, chat_jid, max_age_seconds=60)

            if last_message:
                def _is_amount_only(msg: str) -> bool:
                    clean = msg.strip().lower()
                    if not clean or clean.startswith("/"):
                        return False
                    if not has_amount_pattern(clean):
                        return False
                    return bool(re.fullmatch(r"(rp|rb|ribu|k|jt|juta|m|milyar|b|bn|[0-9]|[.,\s])+", clean))

                def _should_combine_amount(prev_msg: str, cur_msg: str) -> bool:
                    if not _is_amount_only(cur_msg):
                        return False
                    prev = (prev_msg or "").strip()
                    if prev.startswith("/") and " " in prev:
                        return False
                    return True

                # Check if current message is just an amount and safe to combine
                if _should_combine_amount(last_message, text):
                    # Likely continuing previous message
                    combined_text = f"{last_message} {text}"
                    secure_log("INFO", f"Combined with last message: {combined_text}")
                    text = combined_text
                    extraction_text = text
                    # Clear buffer after use
                    clear_user_last_message(sender_number, chat_jid)

            # Store current message for next time
            store_user_message(sender_number, chat_jid, text)

            # Smart Handler (AI Layer)
            if USE_LAYERS:
                if force_record or deterministic_scope:
                    action = "PROCESS"
                    intent = "RECORD_TRANSACTION"
                    # Explicit/obvious transactions do not need a classifier round trip.
                    smart_result = {}
                    smart_scope = deterministic_scope

                    # Fallback lightweight scope detection for explicit "catat"
                    if not smart_scope:
                        text_lower = (text or "").lower()
                        has_project_word = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
                        has_kantor_word = bool(re.search(r"\b(kantor|office|operasional|ops)\b", text_lower))
                        has_operational_kw = any(
                            re.search(r'\b' + re.escape(kw) + r'\b', text_lower)
                            for kw in OPERATIONAL_KEYWORDS
                        )
                        if has_project_word:
                            smart_scope = "PROJECT"
                        elif has_kantor_word or has_operational_kw:
                            smart_scope = "OPERATIONAL"
                        else:
                            smart_scope = "UNKNOWN"

                    layer_category_scope = smart_scope or "UNKNOWN"
                else:
                    # Use the initialized smart_handler instance
                    # It returns a dict with action, intent, normalized_text, etc.
                    smart_result = run_smart_handler()

                    action = smart_result.get('action', 'IGNORE')
                    resp = smart_result.get('response') # For REPLY
                    intent = smart_result.get('intent', 'UNKNOWN')

                    # Store extra data
                    layer_category_scope = smart_result.get('category_scope', 'UNKNOWN')
                    if intent == "RECORD_TRANSACTION":
                         # In case smart_handler cleaned the text (e.g. from extracted data)
                         normalized_text = smart_result.get('normalized_text')
                         if normalized_text and not _should_preserve_extraction_text(text, normalized_text):
                             text = normalized_text
                             extraction_text = text

                if action == "IGNORE": return jsonify({'status': 'ignored'}), 200
                if action == "REPLY":
                    send_reply(resp)
                    return jsonify({'status': 'replied'}), 200
                if action == "PROCESS":
                    if intent == "RECORD_TRANSACTION":
                        # For image input, defer debt-payment matching until OCR amount is available.
                        if input_type != 'image':
                            auto_hutang = _handle_auto_hutang_payment(text, sender_number, chat_jid)
                            if auto_hutang:
                                send_reply(auto_hutang)
                                return jsonify({'status': 'auto_hutang_paid'}), 200
                        # Send quick ack only when explicitly addressed or private chat
                        if (force_record or (not is_group) or is_explicit_bot_call(text)) and not processing_ack_sent:
                            send_reply("⏳ Memproses...")
                            processing_ack_sent = True

                    if intent == "QUERY_STATUS":
                        send_reply("🤔 Menganalisis...")
                        try:
                            from handlers.query_handler import handle_query_command
                            query_text = smart_result.get('layer_response', text)
                            ans = handle_query_command(query_text, sender_number, chat_jid, raw_query=text)
                            send_reply(ans)
                            return jsonify({'status': 'queried'}), 200
                        except Exception as e:
                            secure_log("ERROR", f"Query handler failed: {e}")

                    # ========================================
                    # STEP 2: HANDLE SPECIAL INTENTS
                    # ========================================

                    if intent == "TRANSFER_FUNDS":
                        # Force logic for Transfer/Saldo logic
                        if smart_result.get('layer_response'):
                             text = smart_result.get('layer_response')
                             extraction_text = text

                        text_lower = (text or "").lower()
                        has_project_context = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
                        has_spending_context = bool(
                            re.search(
                                r"\b(beli|pembelian|bayar|biaya|material|upah|jasa|ongkir|transport|belanja|buat|untuk)\b",
                                text_lower
                            )
                        )

                        # Safety: don't force TRANSFER for project expense text that only mentions a dompet.
                        if has_project_context and has_spending_context and not is_saldo_update(text):
                            intent = "RECORD_TRANSACTION"
                            layer_category_scope = "PROJECT"
                            transfer_dompet = resolve_dompet_from_text(text)
                            secure_log(
                                "INFO",
                                "Transfer intent downgraded to RECORD_TRANSACTION due project expense context"
                            )
                        else:
                            layer_category_scope = "TRANSFER"
                            # Try to resolve dompet directly from text to avoid extra prompts
                            transfer_dompet = resolve_dompet_from_text(text)

                    if intent == "RECORD_TRANSACTION":
                        # Logic continues to Step 8 (Extraction) with refined text/scope
                        if (
                            input_type == 'image'
                            and layer_category_scope in ['UNKNOWN', 'AMBIGUOUS']
                            and recent_scope_hint in {'OPERATIONAL', 'PROJECT'}
                        ):
                            layer_category_scope = recent_scope_hint
                            if not (text or '').strip() and recent_text_for_image:
                                text = recent_text_for_image
                            secure_log(
                                "INFO",
                                f"Applied recent text scope hint for image: {layer_category_scope}"
                            )

                        # Deterministic override: explicit scope words should beat AI ambiguity.
                        if layer_category_scope in ['UNKNOWN', 'AMBIGUOUS']:
                            text_scope_lower = (text or "").lower()
                            explicit_project_scope = bool(
                                re.search(r"\b(projek|project|proyek|prj)\b", text_scope_lower)
                            )
                            explicit_operational_scope = bool(
                                re.search(r"\b(kantor|office|operasional|operational|ops)\b", text_scope_lower)
                            )
                            if explicit_project_scope and not explicit_operational_scope:
                                layer_category_scope = "PROJECT"
                                secure_log("INFO", "Scope override: explicit project keyword")
                            elif explicit_operational_scope and not explicit_project_scope:
                                layer_category_scope = "OPERATIONAL"
                                secure_log("INFO", "Scope override: explicit operational keyword")

                        # PRE-EMPTIVE CONFIRMATION FOR AMBIGUOUS SCOPE
                        # If AI is still unsure (AMBIGUOUS/UNKNOWN), ask user before extraction/saving
                        if layer_category_scope in ['UNKNOWN', 'AMBIGUOUS']:
                            if input_type == 'image':
                                caption_text = (text or "").strip()
                                has_scope_hint = bool(
                                    re.search(
                                        r"\b(projek|project|proyek|prj|operasional|operational|kantor|ops)\b",
                                        caption_text.lower(),
                                    )
                                )
                                has_context_hint = (
                                    has_scope_hint
                                    or _has_wallet_context_hint(caption_text)
                                    or has_amount_pattern(caption_text)
                                )
                                # Image-first flow: avoid noisy scope prompt when user has not
                                # provided actionable caption yet. Keep image buffered and wait
                                # for follow-up text (e.g. "2 project X dompet tx sby").
                                if not has_context_hint:
                                    if not deferred:
                                        schedule_group_image_grace()
                                    secure_log(
                                        "INFO",
                                        "Buffered image with weak caption; waiting follow-up text before scope prompt",
                                    )
                                    return jsonify({'status': 'buffered_image_waiting_text'}), 200
                            if input_type == 'image' and not _claim_visual_source_once():
                                return jsonify({'status': 'duplicate_visual_reference'}), 200
                            # Extract temporarily to show context
                            inp, media_list, caption = build_extraction_inputs(
                                text, input_type, media_url, local_media_path
                            )
                            temp_txs = safe_extract(
                                inp, input_type, sender_name, media_list, caption
                            )

                            if temp_txs is None:
                                if input_type == 'image':
                                    _release_visual_source_claim()
                                return jsonify({'status': 'rate_limit'}), 200
                            if temp_txs:
                                # REMOVED local import of format_mention to fix UnboundLocalError
                                set_pending_confirmation(
                                    user_id=sender_number,
                                    chat_id=chat_jid,
                                    data={
                                        'type': 'category_scope',
                                        'transactions': temp_txs,
                                        'raw_text': text,
                                        'original_message_id': event_id,
                                        'event_id': event_id
                                    }
                                )
                                response = """🤔 Ini untuk Operational Kantor atau Project?

 1️⃣ Operational Kantor
    (Gaji staff, listrik, wifi, ATK, dll)

 2️⃣ Project
    (Material, upah tukang, transport ke site)

 Balas 1 atau 2"""
                                sent = send_reply(response)
                                bid = extract_bot_msg_id(sent)
                                if bid:
                                    store_pending_message_ref(bid, f"{chat_jid}:{sender_number}")
                                return jsonify({'status': 'asking_scope'}), 200

        # 5. REVISION HANDLER (New)
        clean_text = (text or "").strip().lower()
        digit_count = sum(ch.isdigit() for ch in clean_text)
        is_quick_control_reply = (
            bool(re.fullmatch(r"\d{1,2}", clean_text)) or
            clean_text in {
                'ya', 'y', 'iya', 'yes', 'ok', 'oke',
                'tidak', 'no', 'bukan', 'batal', 'cancel', '/cancel', 'simpan'
            }
        )
        has_revision_keyword = any(
            kw in clean_text for kw in {
                'revisi', 'ubah', 'ganti', 'koreksi', 'salah',
                'operasional', 'operational', 'project', 'projek'
            }
        )
        is_likely_amount_revision = (digit_count >= 2 and not is_quick_control_reply)
        # Guardrail: explicit "catat" intent must stay on record flow,
        # even when user replies and message contains revision-like keywords.
        should_try_quoted_revision = (
            bool(quoted_msg_id) and
            (not has_pending) and
            (not force_record) and
            (has_revision_keyword or is_likely_amount_revision)
        )

        if should_try_quoted_revision or is_command_match(text, Commands.UNDO, is_group) or is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
            from handlers.revision_handler import handle_revision_command, handle_undo_command

            revision_result = None

            # Check for standard commands
            if is_command_match(text, Commands.UNDO, is_group):
                 revision_result = handle_undo_command(sender_number, chat_jid, quoted_msg_id)

            # Check for /revisi command or reply revision
            elif should_try_quoted_revision or is_prefix_match(text, Commands.REVISION_PREFIXES, is_group):
                 revision_result = handle_revision_command(sender_number, chat_jid, text, quoted_msg_id)

            if revision_result:
                if revision_result.get('action') == 'REPLY':
                    send_reply(revision_result.get('response'))
                    return jsonify({'status': 'handled_revision'}), 200

        # 6. PENDING STATE MACHINE
        if has_pending:
            pending = pending_data
            ptype = pending.get('pending_type')

            # NEW: Merge concurrent transactions (e.g. multiple images)
            # If user sends another image/transaction while one is pending, ADD to it.
            # Keep text-merge strict so short replies like "3" are not treated as new transactions.
            clean_pending_reply = (text or "").strip().lower()
            is_short_numeric_reply = bool(re.fullmatch(r"\d{1,2}", clean_pending_reply))
            is_quick_control_reply = (
                is_short_numeric_reply or
                clean_pending_reply in {
                    'ya', 'y', 'iya', 'yes', 'ok', 'oke',
                    'tidak', 'no', 'bukan', 'batal', 'cancel', '/cancel', 'simpan'
                }
            )
            is_potential_text_tx = (
                intent in {'UNKNOWN', 'RECORD_TRANSACTION'}
                and bool(text)
                and bool(has_amount_pattern(text))
                and not is_short_numeric_reply
            )
            expects_selection_reply = ptype in {
                'selection',
                'select_source_wallet',
                'confirmation_project',
                'confirmation_new_project',
                'confirmation_dupe',
                'needs_project',
            }

            # Guard stale pending entries (e.g., confirmation state missing after restart/replica drift).
            if ptype is None and is_quick_control_reply:
                _pending_transactions.pop(pending_pkey, None)
                send_reply(UserErrors.STALE_PENDING_STATE)
                return jsonify({'status': 'stale_pending'}), 200

            if (
                input_type == 'image'
                or (
                    not expects_selection_reply
                    and (
                        # Keep text-merge strict during pending to avoid group chatter being queued.
                        is_potential_text_tx
                        or (
                            explicit_catat
                            and bool(text)
                            and not is_short_numeric_reply
                        )
                    )
                )
            ):
                if input_type == 'image' and not _claim_visual_source_once():
                    return jsonify({'status': 'duplicate_visual_reference'}), 200
                inp, media_list, caption = build_extraction_inputs(
                    text, input_type, media_url, local_media_path
                )
                new_txs = safe_extract(
                    inp, input_type, sender_name, media_list, caption
                )

                if new_txs is None:
                    if input_type == 'image':
                        _release_visual_source_claim()
                    return jsonify({'status': 'rate_limit'}), 200
                if new_txs:
                    merged_txs, merge_meta = _merge_transaction_queue(
                        pending.get('transactions', []),
                        new_txs
                    )
                    pending['transactions'] = merged_txs

                    if merge_meta.get('added', 0) > 0 or merge_meta.get('upgraded', 0) > 0:
                        send_reply("Menambahkan ke antrian transaksi...")
                    else:
                        send_reply("Item terdeteksi duplikat. Antrian tidak berubah.")

                    if merge_meta.get('duplicates', 0) > 0 or merge_meta.get('upgraded', 0) > 0:
                        secure_log(
                            "INFO",
                            (
                                f"Pending merge {pending_pkey}: "
                                f"added={merge_meta.get('added', 0)}, "
                                f"upgraded={merge_meta.get('upgraded', 0)}, "
                                f"duplicates={merge_meta.get('duplicates', 0)}"
                            )
                        )

                    state_manager_module.set_pending_transaction(pending_pkey, pending)
                    if claimed_visual_source_id:
                        remove_visual_buffer_by_message(chat_jid, claimed_visual_source_id)

                    missing_tx = _first_missing_amount_tx(merged_txs)
                    if missing_tx:
                        pending['pending_type'] = 'needs_amount'
                        state_manager_module.set_pending_transaction(pending_pkey, pending)
                        has_any_positive_amount = False
                        for t in merged_txs:
                            try:
                                if int(t.get('jumlah', 0) or 0) > 0:
                                    has_any_positive_amount = True
                                    break
                            except Exception:
                                continue
                        if has_any_positive_amount:
                            item = missing_tx.get('keterangan', 'Transaksi')
                            sent = send_pending_reply(f"Nominal untuk \"{item}\" berapa? (contoh: 150rb)")
                            cache_prompt(pending_pkey, pending, sent)
                        else:
                            send_pending_reply(
                                "📷 OCR belum berhasil membaca nominal dari struk. "
                                "Ketik nominal manual (contoh: 1080000/1.080.000) "
                                "atau kirim ulang gambar yang lebih jelas (crop struk saja)."
                            )
                        return jsonify({'status': 'asking_amount'}), 200

                    # Re-send updated prompt
                    reply = build_selection_prompt(merged_txs)
                    if is_group: reply += "\n\n↩️ Reply angka 1-5"
                    send_pending_reply(reply)
                    return jsonify({'status': 'merged'}), 200

                # If image provided no transaction data during pending state, IGNORE it.
                # Don't let it fall through to 'selection' validation which would error.
                if input_type == 'image':
                    _release_visual_source_claim()
                    return jsonify({'status': 'ignored_image'}), 200

            # Cancel
            if is_command_match(text, Commands.CANCEL, is_group):
                _pending_transactions.pop(pending_pkey, None)
                clear_visual_buffer(sender_number, chat_jid)
                send_reply(UserErrors.CANCELLED)
                return jsonify({'status': 'cancelled'}), 200

            # Z. Needs Amount
            if ptype == 'needs_amount':
                try:
                    amt = parse_revision_amount(text)
                except Exception:
                    amt = 0
                if not amt:
                    # In busy groups, ignore normal chatter while waiting nominal.
                    # Reply only when user is clearly interacting with this pending flow.
                    if is_group:
                        explicit_call = False
                        try:
                            explicit_call = is_explicit_bot_call(text)
                        except Exception:
                            explicit_call = False

                        is_pending_interaction = bool(
                            is_reply_to_bot
                            or explicit_call
                            or has_amount_pattern(text)
                            or is_command_match(text, Commands.CANCEL, is_group)
                        )
                        if not is_pending_interaction:
                            return jsonify({'status': 'ignored_pending_chatter'}), 200

                    sent = send_pending_reply("❗ Nominalnya berapa? (contoh: 150rb)")
                    cache_prompt(pending_pkey, pending, sent)
                    return jsonify({'status': 'asking_amount'}), 200

                for t in pending.get('transactions', []):
                    if t.get('needs_amount') or int(t.get('jumlah', 0) or 0) <= 0:
                        t['jumlah'] = int(amt)
                        t.pop('needs_amount', None)

                pending.pop('pending_type', None)
                return finalize_transaction_workflow(pending, pending_pkey)

            # A. Select Source Wallet (Operational)
            if ptype == 'select_source_wallet':
                clean = text.strip().lower()
                if clean == '4' or 'project' in clean or 'projek' in clean:
                    pending['pending_type'] = None
                    pending['is_operational'] = False
                    pending.pop('operational_category', None)
                    pending['project_confirmed'] = False
                    pending['category_scope'] = 'PROJECT'
                    needs_project = any(not t.get('nama_projek') or t.get('needs_project') for t in pending.get('transactions', []))
                    if needs_project:
                        pending['pending_type'] = 'needs_project'
                        send_pending_reply("Nama projeknya apa?")
                        return jsonify({'status': 'switch_to_project'}), 200
                    return finalize_transaction_workflow(pending, pending_pkey)
                try:
                    # Numeric quick reply (1-3)
                    sel = int(clean)
                    opt = get_wallet_selection_by_idx(sel)
                    if not opt:
                        raise ValueError()
                except (TypeError, ValueError):
                    opt = None

                # Text alias reply (e.g., "tx bali", "tx sby", "cv hb", "087")
                if not opt:
                    opt_dompet = resolve_dompet_from_text(clean)
                    if not opt_dompet and clean in {"101", "216", "087", "87"}:
                        opt_dompet = {
                            "101": "CV HB(101)",
                            "216": "TX SBY(216)",
                            "087": "TX BALI(087)",
                            "87": "TX BALI(087)",
                        }.get(clean)
                    if opt_dompet:
                        opt = {"dompet": opt_dompet}

                if opt:
                    pending['selected_source_wallet'] = opt['dompet']
                    return finalize_transaction_workflow(pending, pending_pkey)

                send_pending_reply("❌ Pilih angka 1-4 atau ketik dompet (contoh: TX BALI).")
                return jsonify({'status': 'invalid'}), 200

            # B. Project Confirmation (Existing - Ambiguous Name)
            if ptype == 'confirmation_project':
                clean = text.lower().strip()
                final_proj = ""

                if clean in ['ya', 'y', 'ok', 'siap']:
                    final_proj = pending.get('suggested_project')
                    send_reply(f"✅ Oke, masuk ke **{final_proj}**.")
                elif clean in ['tidak', 'no', 'bukan']:
                    send_pending_reply("Nama projeknya apa?")
                    pending['pending_type'] = 'needs_project'
                    return jsonify({'status': 'asking'}), 200
                else:
                    # Direct correction
                    final_proj = normalize_project_input(sanitize_input(text.strip()))
                    if len(final_proj) < 3:
                        send_reply("⚠️ Nama terlalu pendek.")
                        return jsonify({'status': 'invalid'}), 200
                    add_new_project_to_cache(final_proj)
                    send_reply(f"👌 Project baru: **{final_proj}**")

                # Update transactions
                for t in pending['transactions']:
                    t['nama_projek'] = final_proj
                    t.pop('needs_project', None)

                # Set confirmed to true so we don't ask again
                pending['project_confirmed'] = True
                pending['project_validated'] = True
                return finalize_transaction_workflow(pending, pending_pkey)

            # G. New Project Confirmation (NEW -> Create or Rename)
            if ptype == 'confirmation_new_project':
                clean = text.lower().strip()
                if pending.get('new_project_first_expense'):
                    if clean in ['1', 'ya', 'y', 'ok', 'siap', 'lanjut']:
                        pending['project_confirmed'] = True
                        pending['is_new_project'] = True
                        pending['project_validated'] = True
                        pending['new_project_first_expense_confirmed'] = True
                        pending.pop('new_project_first_expense', None)
                        return finalize_transaction_workflow(pending, pending_pkey)
                    if clean in ['2', 'operasional', 'kantor']:
                        pending['pending_type'] = 'select_source_wallet'
                        pending['is_operational'] = True
                        pending['operational_category'] = pending.get('operational_category', 'Lain Lain')
                        pending['project_confirmed'] = False
                        pending.pop('new_project_first_expense', None)
                        prompt = format_wallet_selection_prompt()
                        send_reply(f"🏢 Diganti ke Operasional Kantor\n\n{prompt}")
                        return jsonify({'status': 'switch_to_operational'}), 200
                    if clean in ['3', 'batal', 'cancel', 'tidak', 'no']:
                        _pending_transactions.pop(pending_pkey, None)
                        send_reply("❌ Dibatalkan.")
                        return jsonify({'status': 'cancelled'}), 200
                    # Treat input as new project name
                    final_proj = normalize_project_input(sanitize_input(text.strip()))
                    if len(final_proj) < 3:
                        send_reply("⚠️ Nama terlalu pendek.")
                        return jsonify({'status': 'invalid'}), 200
                    selected_scope = pending.get('selected_option') or {}
                    res_check = resolve_project_name_for_context(
                        strip_company_prefix(final_proj),
                        dompet_sheet=selected_scope.get('dompet') or pending.get('override_dompet'),
                        company=selected_scope.get('company'),
                        debt_source_dompet=pending.get('debt_source_dompet'),
                    )
                    if res_check.get('status') == 'INVALID':
                        send_pending_reply("Nama projeknya belum valid. Ketik nama projek yang benar.")
                        return jsonify({'status': 'asking_project_name'}), 200
                    if res_check.get('final_name'):
                        final_proj = res_check['final_name']
                    if res_check.get('status') == 'NEW':
                        pending['is_new_project'] = True
                    pending['new_project_first_expense_confirmed'] = True
                    for t in pending['transactions']:
                        t['nama_projek'] = final_proj
                    pending['project_confirmed'] = True
                    pending['project_validated'] = True
                    pending.pop('new_project_first_expense', None)
                    return finalize_transaction_workflow(pending, pending_pkey)
                if clean.isdigit() and len(clean) <= 2 and clean not in ['1']:
                    send_pending_reply("Balas 'Ya' untuk membuat project baru, atau ketik nama project yang benar.")
                    return jsonify({'status': 'invalid'}), 200

                if clean in ['1', 'ya', 'y', 'ok', 'siap', 'buat', 'lanjut']:
                    # User confirmed it is new
                    pending['project_confirmed'] = True
                    pending['is_new_project'] = True  # Flag for lifecycle marker
                    pending['project_validated'] = True
                    # Delayed cache update until save success
                    return finalize_transaction_workflow(pending, pending_pkey)

                elif clean in ['tidak', 'no', 'ganti', 'bukan', 'salah']:
                    send_pending_reply("Nama projeknya apa?")
                    pending['pending_type'] = 'needs_project'
                    return jsonify({'status': 'asking'}), 200
                else:
                    # Treat input as the CORRECT name (and implicitly NEW if not resolved previously)
                    final_proj = normalize_project_input(sanitize_input(text.strip()))
                    # Check if actually exists now
                    selected_scope = pending.get('selected_option') or {}
                    res_check = resolve_project_name_for_context(
                        strip_company_prefix(final_proj),
                        dompet_sheet=selected_scope.get('dompet') or pending.get('override_dompet'),
                        company=selected_scope.get('company'),
                        debt_source_dompet=pending.get('debt_source_dompet'),
                    )
                    final_proj = res_check.get('final_name') or final_proj
                    if res_check.get('status') == 'INVALID':
                        send_pending_reply("Nama projeknya belum valid. Ketik nama projek yang benar.")
                        return jsonify({'status': 'asking_project_name'}), 200
                    if res_check['status'] == 'NEW':
                         pending['is_new_project'] = True

                    send_reply(f"👌 Update ke: **{final_proj}**")
                    for t in pending['transactions']: t['nama_projek'] = final_proj
                    pending['project_confirmed'] = True
                    pending['project_validated'] = True
                    return finalize_transaction_workflow(pending, pending_pkey)

            # C. Needs Project
            if ptype == 'needs_project':
                proj = sanitize_input(text.strip())
                selected_scope = pending.get('selected_option') or {}
                res = resolve_project_name_for_context(
                    strip_company_prefix(proj),
                    dompet_sheet=selected_scope.get('dompet') or pending.get('override_dompet'),
                    company=selected_scope.get('company'),
                    debt_source_dompet=pending.get('debt_source_dompet'),
                )

                project_decision = decide_project_resolution(res)

                if project_decision.should_accept:
                    final = project_decision.final_name
                    for t in pending['transactions']:
                        t['nama_projek'] = final
                    pending['project_confirmed'] = True
                    pending['project_validated'] = True
                    return finalize_transaction_workflow(pending, pending_pkey)

                if project_decision.action == 'missing':
                    send_pending_reply("Nama projeknya belum valid. Ketik nama projek yang benar.")
                    return jsonify({'status': 'asking_project_name'}), 200

                if project_decision.should_confirm:
                    pending['pending_type'] = 'confirmation_project'
                    pending['suggested_project'] = project_decision.suggested_name
                    send_pending_reply(f"🤔 Maksudnya **{project_decision.suggested_name}**?\n✅ Ya / ❌ Bukan")
                    return jsonify({'status': 'confirm'}), 200

                if project_decision.action == 'new':
                    for t in pending['transactions']:
                        t['nama_projek'] = project_decision.final_name
                    pending['pending_type'] = 'confirmation_new_project'
                    pending['new_project_name'] = project_decision.final_name
                    send_pending_reply(
                        f"📁 Project **{project_decision.final_name}** belum terdaftar.\n\n"
                        "Buat project baru?\n"
                        "✅ Ya / ketik nama lain untuk ganti"
                    )
                    return jsonify({'status': 'asking_new_project'}), 200

                final = project_decision.final_name or res['final_name']
                for t in pending['transactions']: t['nama_projek'] = final
                # Set confirmed to true
                pending['project_confirmed'] = True
                pending['project_validated'] = True
                return finalize_transaction_workflow(pending, pending_pkey)

            # D. Company Selection
            if ptype == 'selection':
                clean = text.strip().lower()
                if clean == '5' or any(k in clean for k in ['operasional', 'kantor']):
                    pending['pending_type'] = 'select_source_wallet'
                    pending['is_operational'] = True
                    pending['operational_category'] = pending.get('operational_category', 'Lain Lain')
                    pending['project_confirmed'] = False
                    prompt = format_wallet_selection_prompt()
                    send_reply(f"🏢 Diganti ke Operasional Kantor\n\n{prompt}")
                    return jsonify({'status': 'switch_to_operational'}), 200
                valid, sel, err = parse_selection(text)
                if not valid:
                    send_reply(f"❌ {err}")
                    return jsonify({'status': 'invalid'}), 200

                opt = get_selection_by_idx(sel)
                if not opt:
                    send_reply(UserErrors.SELECTION_UNAVAILABLE)
                    return jsonify({'status': 'error_opt'}), 200

                pending['selected_option'] = opt
                for t in pending['transactions']: t['company'] = opt['company']

                return finalize_transaction_workflow(pending, pending_pkey)

            # E. Duplicate Confirm
            if ptype == 'confirmation_dupe':
                if text.lower().strip() == 'y':
                    opt = pending.get('selected_option')
                    if not opt:
                         _pending_transactions.pop(pending_pkey, None)
                         send_reply(UserErrors.STALE_PENDING_STATE)
                         return jsonify({'status': 'error_state'}), 200

                    # Manual save
                    res = append_transactions(pending['transactions'], pending['sender_name'],
                                            pending['source'], opt['dompet'], opt['company'])
                    if res['success']:
                        _pending_transactions.pop(pending_pkey, None)
                        send_reply("✅ Disimpan (Duplikat).")
                    return jsonify({'status': 'saved_dupe'}), 200
                    _pending_transactions.pop(pending_pkey, None)
                    send_reply("❌ Dibatalkan.")
                    return jsonify({'status': 'cancelled'}), 200

            # F. OCR Amount Confirmation (image safety)
            if ptype == 'confirm_amount':
                clean = text.lower().strip()
                if clean in ['ok', 'oke', 'ya', 'y', 'benar', 'betul']:
                    pending.pop('pending_type', None)
                    pending.pop('pending_amount', None)
                    return finalize_transaction_workflow(pending, pending_pkey)
                else:
                    try:
                        amt = parse_revision_amount(clean)
                    except Exception:
                        amt = 0
                    if not amt or int(amt) <= 0:
                        send_reply("⚠️ Nominal tidak valid. Balas *OK* atau ketik nominal yang benar (contoh: 202500).")
                        return jsonify({'status': 'invalid_amount'}), 200
                    for t in pending.get('transactions', []):
                        t['jumlah'] = int(amt)
                        t.pop('needs_amount', None)
                    pending.pop('pending_type', None)
                    pending.pop('pending_amount', None)
                    return finalize_transaction_workflow(pending, pending_pkey)

            # F. Undo Confirmation
            if ptype == 'undo_confirmation':
                if text.lower().strip() in ['1', 'ya', 'yes', 'hapus']:
                    from handlers.revision_handler import process_undo_deletion

                    result = process_undo_deletion(
                        pending.get('transactions', []),
                        pending.get('original_message_id')
                    )

                    _pending_transactions.pop(pending_pkey, None)
                    send_reply(result.get('response'))
                    return jsonify({'status': 'undo_completed'}), 200
                else:
                    _pending_transactions.pop(pending_pkey, None)
                    send_reply("❌ Batal hapus.")
                    return jsonify({'status': 'undo_cancelled'}), 200

        # 7. COMMANDS (PRIORITY - Execute BEFORE layer processing)
        # This ensures /start, /help, etc. work properly instead of triggering layers
        if is_command_match(text, Commands.START, is_group):
            send_reply(START_MESSAGE)
            return jsonify({'status': 'command_start'}), 200

        if is_command_match(text, Commands.HELP, is_group):
            send_reply(HELP_MESSAGE)
            return jsonify({'status': 'command_help'}), 200

        if is_command_match(text, Commands.SALDO, is_group):
            try:
                balances = get_wallet_balances()
                msg = _build_saldo_message(balances)
                send_reply(msg)
                return jsonify({'status': 'command_saldo'}), 200
            except Exception as e:
                secure_log("ERROR", f"Saldo command failed: {e}")
                send_reply(UserErrors.SHEET_READ_FAILED)
                return jsonify({'status': 'error'}), 200

        if is_prefix_match(text, Commands.LUNAS_PREFIXES, is_group):
            try:
                match = re.search(r"\b(\d+)\b", text)
                if not match:
                    send_reply(UserErrors.HUTANG_FORMAT)
                    return jsonify({'status': 'command_lunas_invalid'}), 200
                no = int(match.group(1))
                info = settle_hutang(no, sender_name=sender_name, source='WhatsApp')
                if not info:
                    send_reply(UserErrors.HUTANG_NOT_FOUND.format(no=no))
                    return jsonify({'status': 'command_lunas_not_found'}), 200
                if info.get('error'):
                    send_reply(UserErrors.HUTANG_SETTLE_FAILED.format(no=no, reason=info['error']))
                    return jsonify({'status': 'command_lunas_failed'}), 200
                invalidate_dashboard_cache()
                send_reply(_format_hutang_paid_response(info))
                return jsonify({'status': 'command_lunas'}), 200
            except Exception as e:
                secure_log("ERROR", f"Lunas command failed: {e}")
                send_reply(UserErrors.HUTANG_SETTLE_FAILED.format(no="?", reason="sistem tidak bisa membaca/update data. Coba lagi 1 menit."))
                return jsonify({'status': 'error'}), 200


        if is_command_match(text, Commands.STATUS, is_group):
            try:
                dashboard = get_dashboard_summary()
                msg = format_dashboard_message(dashboard)
                send_reply(msg)
                return jsonify({'status': 'command_status'}), 200
            except Exception as e:
                secure_log("ERROR", f"Status command failed: {e}")
                send_reply(UserErrors.SHEET_READ_FAILED)
                return jsonify({'status': 'error'}), 200

        if is_command_match(text, Commands.LIST, is_group):
            try:
                data = get_all_data(days=7)
                if not data:
                    send_reply("📭 Belum ada transaksi 7 hari terakhir.")
                else:
                    data.sort(key=lambda x: x.get('tanggal', ''), reverse=True)
                    msg = "📜 *Riwayat Transaksi (7 Hari)*\n\n"
                    # Limit to 15
                    for tx in data[:15]:
                        try:
                            t_amt = tx.get('jumlah', 0) or 0
                            amt = int(t_amt)
                        except: amt = 0

                        icon = "🔴" if str(tx.get('tipe', 'Pengeluaran')) == 'Pengeluaran' else "🟢"
                        src = tx.get('nama_projek') or tx.get('company_sheet') or "?"
                        msg += f"{icon} {tx['tanggal']} - Rp {amt:,}\n"
                        msg += f"   _{tx['keterangan']}_ [{src}]\n"

                    msg = msg.replace(',', '.')
                    send_reply(msg)
                return jsonify({'status': 'command_list'}), 200
            except Exception as e:
                secure_log("ERROR", f"List command failed: {e}")
                send_reply(UserErrors.SHEET_READ_FAILED)
                return jsonify({'status': 'error'}), 200
        if is_command_match(text, Commands.LAPORAN, is_group) or is_command_match(text, Commands.LAPORAN_30, is_group):
            try:
                is_30 = '30' in text
                days = 30 if is_30 else 7
                data = get_all_data(days=days)
                hutang = get_hutang_summary(days=days)

                income = sum(int(t.get('jumlah', 0) or 0) for t in data if str(t.get('tipe')) == 'Pemasukan')
                expense = sum(int(t.get('jumlah', 0) or 0) for t in data if str(t.get('tipe')) == 'Pengeluaran')
                profit = income - expense
                open_count = int(hutang.get('open_count', 0) or 0)
                open_total = int(hutang.get('open_total', 0) or 0)
                created_count = int(hutang.get('created_period_count', 0) or 0)
                created_total = int(hutang.get('created_period_total', 0) or 0)
                paid_period_count = int(hutang.get('paid_period_count', 0) or 0)
                paid_period_total = int(hutang.get('paid_period_total', 0) or 0)
                paid_count = int(hutang.get('paid_count', 0) or 0)
                paid_total = int(hutang.get('paid_total', 0) or 0)
                has_hutang_data = any([open_count, open_total, created_count, created_total, paid_period_count, paid_period_total, paid_count, paid_total])

                title = f"LAPORAN {'BULANAN (30 HARI)' if days == 30 else 'MINGGUAN (7 HARI)'}"
                msg = f"{title}\n{'=' * len(title)}\n\n"
                msg += f"💰 Pemasukan: Rp {income:,}\n"
                msg += f"💸 Pengeluaran: Rp {expense:,}\n"
                msg += f"📈 Profit: Rp {profit:,}\n"
                msg += f"📝 Total Tx: {len(data)}\n"

                msg += "\nStatus Hutang Antar Dompet:\n"
                if has_hutang_data:
                    msg += f"🟡 OPEN saat ini: {open_count} item (Rp {open_total:,})\n"
                    msg += f"🆕 Dibuat {days} hari: {created_count} item (Rp {created_total:,})\n"
                    msg += f"✅ Lunas {days} hari: {paid_period_count} item (Rp {paid_period_total:,})\n"
                    msg += f"📚 Total PAID: {paid_count} item (Rp {paid_total:,})\n"
                else:
                    msg += "ℹ️ Belum ada data hutang antar dompet.\n"

                balances = get_wallet_balances()
                msg += "\nSaldo Dompet Real (snapshot):\n"
                for dompet, info in balances.items():
                    msg += f"- {dompet}: Rp {int(info.get('saldo', 0) or 0):,}\n"

                msg += "\nCatatan: hutang antar dompet dipisah dari metrik profit.\n"
                msg = msg.replace(',', '.')
                send_reply(msg)
                return jsonify({'status': 'command_laporan'}), 200
            except Exception as e:
                secure_log("ERROR", f"Laporan command failed: {e}")
                send_reply(UserErrors.SHEET_READ_FAILED)
                return jsonify({'status': 'error'}), 200

        if is_command_match(text, Commands.LINK, is_group):
            url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
            send_reply(f"🔗 *Google Sheets Link:*\n{url}")
            return jsonify({'status': 'command_link'}), 200

        if is_command_match(text, Commands.AUDIT, is_group):
            # Read-only data integrity check. Flags rows likely broken by
            # manual Sheet edits (empty/non-numeric amount, unknown tipe,
            # unknown dompet/company). Does not modify any data.
            try:
                from services.row_validator import validate_rows, format_issue_report
                rows = get_raw_rows_for_audit()
                issues = validate_rows(rows)
                send_reply(format_issue_report(issues))
                return jsonify({'status': 'command_audit', 'issues': len(issues)}), 200
            except Exception as e:
                secure_log("ERROR", f"Audit command failed: {type(e).__name__}: {e}")
                send_reply(UserErrors.SHEET_READ_FAILED)
                return jsonify({'status': 'error'}), 200


        if is_prefix_match(text, Commands.EXPORT_PDF_PREFIXES, is_group) or is_command_match(text, Commands.EXPORT_PDF_PREFIXES, is_group):
             try:
                 parts = text.strip().split(' ', 1)
                 arg = parts[1] if len(parts) > 1 else now_wib().strftime("%Y-%m")

                 send_reply(f"⏳ Proses Membuat PDF {arg}...")
                 from pdf_report import generate_pdf_from_input
                 fpath = generate_pdf_from_input(arg)

                 if fpath and os.path.exists(fpath):
                     if send_document:
                         send_document(reply_to, fpath, caption=f"Laporan {arg}")
                     else:
                         fname = os.path.basename(fpath)
                         send_reply(f"✅ PDF berhasil dibuat: {fname}\nDi channel ini belum bisa kirim PDF. Silakan ambil dari server.")
                 else:
                     send_reply(
                         "❌ PDF tidak dibuat karena data periode kosong atau format periode tidak cocok.\n"
                         "Contoh: exportpdf 2026-01"
                     )
                 return jsonify({'status': 'command_pdf'}), 200
             except PDFNoDataError as nde:
                 period = getattr(nde, "period", arg or "periode tersebut")
                 send_reply(UserErrors.PDF_NO_DATA.format(period=period))
                 return jsonify({'status': 'error_pdf_no_data'}), 200
             except ValueError as ve:
                 msg = str(ve).lower()
                 if "tidak ada data" in msg:
                     send_reply(UserErrors.PDF_NO_DATA.format(period=arg or "periode tersebut"))
                     return jsonify({'status': 'error_pdf_no_data'}), 200
                 send_reply(UserErrors.PDF_FORMAT_ERROR)
                 return jsonify({'status': 'error_pdf'}), 200
             except Exception as e:
                 msg = str(e).lower()
                 secure_log("ERROR", f"PDF Error: {e}")
                 if "tidak ada data" in msg:
                     send_reply(UserErrors.PDF_NO_DATA.format(period=arg or "periode tersebut"))
                     return jsonify({'status': 'error_pdf_no_data'}), 200
                 if "tahun tidak valid" in msg or "bulan tidak valid" in msg or "format tidak" in msg:
                     send_reply(UserErrors.PDF_FORMAT_ERROR)
                     return jsonify({'status': 'error_pdf'}), 200
                 send_reply("❌ Gagal export PDF karena sistem pembuat PDF bermasalah. Coba lagi 1 menit.")
                 return jsonify({'status': 'error'}), 200

        # Group image grace period: give users time to type after sending image
        if (
            input_type == 'image'
            and is_group
            and not has_pending
            and not deferred
        ):
            caption_text = (text or "").strip()
            caption_should_process = False
            if caption_text:
                caption_should_process, _ = should_respond_in_group(
                    caption_text,
                    is_group,
                    has_media=False,
                    has_pending=False,
                    is_mentioned=is_explicit_bot_call(caption_text)
                )
            if not caption_should_process:
                schedule_group_image_grace()
                return jsonify({'status': 'queued_image'}), 200

        # 8. PROCESS NEW INPUT (AI)
        transactions = []
        try:
            if input_type == 'image' and not (media_url or local_media_path):
                if (text or '').strip():
                    secure_log("WARNING", "Image input without media payload; fallback to text-only extraction")
                    input_type = 'text'
                else:
                    send_reply("❗ Gambar tidak bisa diunduh. Tolong kirim ulang struk atau tambahkan caption transaksi.")
                    return jsonify({'status': 'image_missing_media'}), 200

            if input_type == 'image' and not _claim_visual_source_once():
                return jsonify({'status': 'duplicate_visual_reference'}), 200
            if not processing_ack_sent:
                send_reply("🔍 Scan...")

            inp, media_list, caption = build_extraction_inputs(
                extraction_text, input_type, media_url, local_media_path
            )
            transactions = safe_extract(inp, input_type, sender_name, media_list, caption)
            if transactions is None:
                if input_type == 'image':
                    _release_visual_source_claim()
                return jsonify({'status': 'rate_limit'}), 200

            transactions, extracted_meta = _merge_transaction_queue([], transactions or [])
            if extracted_meta.get('duplicates', 0) > 0 or extracted_meta.get('upgraded', 0) > 0:
                secure_log(
                    "INFO",
                    (
                        f"Extract normalization: "
                        f"added={extracted_meta.get('added', 0)}, "
                        f"upgraded={extracted_meta.get('upgraded', 0)}, "
                        f"duplicates={extracted_meta.get('duplicates', 0)}"
                    )
                )

            if not transactions:
                if input_type == 'image':
                    _release_visual_source_claim()
                if message_id:
                    clear_message_duplicate(message_id)
                send_reply(_build_extraction_failure_message(extraction_text, input_type))
                return jsonify({'status': 'no_tx'}), 200

            # Clear visual buffer on successful extraction to avoid double-binding
            if input_type == 'image':
                if claimed_visual_source_id:
                    remove_visual_buffer_by_message(chat_jid, claimed_visual_source_id)
                else:
                    clear_visual_buffer(sender_number, chat_jid)

            # Debt-payment from image caption: validate using OCR-derived amount first.
            if input_type == 'image':
                auto_hutang = _handle_auto_hutang_payment(
                    text,
                    sender_number,
                    chat_jid,
                    amount_hint=_extract_repayment_amount_from_transactions(transactions),
                )
                if auto_hutang:
                    send_reply(auto_hutang)
                    return jsonify({'status': 'auto_hutang_paid_image'}), 200

            # Setup New Pending State
            _pending_transactions[sender_pkey] = {
                'transactions': transactions,
                'sender_name': sender_name,
                'sender_number': sender_number,
                'source': source_label,
                'created_at': datetime.now(),
                'message_id': event_id,
                'event_id': event_id,
                'chat_jid': chat_jid,
                'quoted_message_id': quoted_msg_id,
                'requires_reply': is_group,
                'original_text': extraction_text, # Important for Smart Router
                'normalized_text': text,
                'input_type': input_type,
                'caption': text if input_type == 'image' else None,
                'attachments': {
                    'media_url': media_url,
                    'media_path': local_media_path
                },
                'prompt_message_ids': [],
                'category_scope': layer_category_scope,  # From AI layer (initialized earlier)
                'override_dompet': transfer_dompet if layer_category_scope == 'TRANSFER' else None,
            }

            # OCR safety: ask confirmation for single-transaction images (strict mode only)
            if (not FAST_MODE) and input_type == 'image' and len(transactions) == 1:
                t0 = transactions[0]
                try:
                    amt0 = int(t0.get('jumlah', 0) or 0)
                except Exception:
                    amt0 = 0
                if amt0 > 0:
                    _pending_transactions[sender_pkey]['pending_type'] = 'confirm_amount'
                    item = t0.get('keterangan', 'Transaksi')
                    amt_text = f"{amt0:,}".replace(',', '.')
                    send_reply(f"📷 OCR terdeteksi: {item} (Rp {amt_text}).\nBalas *OK* jika benar, atau ketik nominal yang benar.")
                    return jsonify({'status': 'confirm_amount'}), 200

            # If amount missing/zero, ask user before proceeding
            missing_tx = _first_missing_amount_tx(transactions)
            if missing_tx:
                for t in transactions:
                    try:
                        if int(t.get('jumlah', 0) or 0) <= 0:
                            t['needs_amount'] = True
                    except Exception:
                        t['needs_amount'] = True
                _pending_transactions[sender_pkey]['pending_type'] = 'needs_amount'
                item = missing_tx.get('keterangan', 'Transaksi')
                sent = send_pending_reply(f"❗ Nominal untuk \"{item}\" berapa? (contoh: 150rb)")
                cache_prompt(sender_pkey, _pending_transactions[sender_pkey], sent)
                return jsonify({'status': 'asking_amount'}), 200

            if (
                layer_category_scope != 'OPERATIONAL'
                and all(t.get('nama_projek') and not t.get('needs_project') for t in transactions)
            ):
                _pending_transactions[sender_pkey]['project_confirmed'] = True

            # Check for Needs Project (Manual override from AI)
            if layer_category_scope == 'TRANSFER':
                text_lower = (text or "").lower()
                has_project_context = bool(re.search(r"\b(projek|project|proyek|prj)\b", text_lower))
                has_non_saldo_project = any(
                    (t.get('nama_projek') or '').strip()
                    and (t.get('nama_projek') or '').strip().lower() not in {'saldo umum', 'umum', 'operasional kantor'}
                    for t in transactions
                )
                if has_project_context or has_non_saldo_project:
                    layer_category_scope = 'PROJECT'
                elif not is_saldo_update(text):
                    layer_category_scope = 'UNKNOWN'

            if layer_category_scope == 'TRANSFER':
                # Force "Saldo Umum" for explicit wallet updates
                for t in transactions:
                    t['nama_projek'] = 'Saldo Umum'
                    t['company'] = 'UMUM'
                    t['needs_project'] = False

            elif any(t.get('needs_project') for t in transactions):
                # Only if NOT operational
                ctx = detect_transaction_context(text, transactions, layer_category_scope)
                if ctx['mode'] == 'PROJECT':
                    _pending_transactions[sender_pkey]['pending_type'] = 'needs_project'
                    send_pending_reply("❓ Nama projeknya apa?")
                    return jsonify({'status': 'asking_project'}), 200

            # Intercept Smart Project Check
            # ... (Existing logic for ambiguous project check) ...

            return finalize_transaction_workflow(_pending_transactions[sender_pkey], sender_pkey)

        except ValueError as e:
            msg = str(e)
            secure_log("WARNING", f"AI Proc ValueError: {msg}")
            if input_type == 'image':
                _release_visual_source_claim()
            if message_id:
                clear_message_duplicate(message_id)
            if input_type == 'image':
                if "Tidak ada teks ditemukan" in msg:
                    send_reply(UserErrors.IMAGE_NOT_READABLE)
                elif "tidak terdeteksi sebagai struk" in msg:
                    send_reply(UserErrors.IMAGE_NOT_RECEIPT)
                else:
                    send_reply(UserErrors.SYSTEM_PROCESSING_FAILED)
            else:
                send_reply(UserErrors.SYSTEM_PROCESSING_FAILED)
            return jsonify({'status': 'error'}), 200
        except Exception as e:
            secure_log("ERROR", f"AI Proc Error: {e}")
            if input_type == 'image':
                _release_visual_source_claim()
            if message_id:
                clear_message_duplicate(message_id)
            send_reply(UserErrors.SYSTEM_PROCESSING_FAILED)
            return jsonify({'status': 'error'}), 200

    except Exception as e:
        secure_log("ERROR", f"Flow Error: {e}")
        return jsonify({'status': 'error'}), 500

_background_worker_lock = threading.Lock()
_background_workers_started = False


def run_retry_service():
    """Background loop to process retry queue."""
    import time
    from sheets_helper import append_transaction

    def retry_handler(transaction, metadata):
        try:
            write_kind = metadata.get('write_kind', 'general')
            if write_kind == 'project':
                result = append_project_transaction(
                    transaction=transaction,
                    sender_name=metadata.get('sender_name', 'System'),
                    source=metadata.get('source', 'Retry'),
                    dompet_sheet=metadata.get('dompet_sheet'),
                    project_name=metadata.get('project_name'),
                    allow_queue=False,
                )
                return bool(result.get('success'))
            if write_kind == 'operational':
                result = append_operational_transaction(
                    transaction=transaction,
                    sender_name=metadata.get('sender_name', 'System'),
                    source=metadata.get('source', 'Retry'),
                    source_wallet=metadata.get('source_wallet'),
                    category=metadata.get('category', 'Lain Lain'),
                    allow_queue=False,
                )
                return bool(result.get('success'))
            if write_kind == 'hutang':
                result = append_hutang_entry(
                    amount=transaction.get('amount'),
                    keterangan=transaction.get('keterangan', ''),
                    yang_hutang=transaction.get('yang_hutang', ''),
                    yang_dihutangi=transaction.get('yang_dihutangi', ''),
                    message_id=transaction.get('message_id', ''),
                    status=transaction.get('status', 'OPEN'),
                    allow_queue=False,
                )
                return bool(result.get('success'))
            result = append_transaction(
                transaction=transaction,
                sender_name=metadata.get('sender_name', 'System'),
                source=metadata.get('source', 'Retry'),
                dompet_sheet=metadata.get('dompet_sheet'),
                company=metadata.get('company'),
                nama_projek=metadata.get('nama_projek'),
                allow_queue=False,
            )
            return result > 0
        except Exception as e:
            secure_log("ERROR", f"Retry handler failed: {e}")
            return False

    while True:
        try:
            processed = process_retry_queue(retry_handler)
            time.sleep(10 if processed > 0 else 60)
        except Exception as e:
            secure_log("ERROR", f"Retry service crashed: {e}")
            time.sleep(60)


def _background_result_status(result) -> str:
    response = result[0] if isinstance(result, tuple) and result else result
    try:
        payload = response.get_json(silent=True)
    except Exception:
        payload = None
    return str((payload or {}).get('status') or '')


def _notify_inbox_review(event: dict, text: str, reason: str) -> None:
    target = str(event.get('chat_id') or event.get('sender_id') or '')
    if not target:
        return
    preview = " ".join((text or '').split())[:140] or "gambar tanpa keterangan"
    message_id = str(event.get('message_id') or '')[-16:]
    body = (
        "⚠️ *TRANSAKSI TERTAHAN*\n"
        f"📝 {preview}\n"
        f"🔖 Ref: {message_id or '-'}\n"
        f"Alasan: {reason}\n\n"
        "Data sudah diamankan di inbox audit. Admin cukup tindak lanjuti alert ini; "
        "tidak perlu mencari chat awal."
    )
    media_data = str(event.get('media_data') or '')
    if media_data.startswith('data:') and ',' in media_data:
        temp_path = ''
        try:
            encoded = media_data.split(',', 1)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                temp_file.write(base64.b64decode(encoded))
                temp_path = temp_file.name
            if send_wuzapi_document(target, temp_path, caption=body):
                return
        except Exception as exc:
            secure_log("WARNING", f"Could not attach review evidence: {type(exc).__name__}")
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    send_wuzapi_reply(target, body)


def run_inbox_recovery_service():
    """Recover webhook events left unfinished by races, crashes, or restarts."""
    last_prune_at = 0.0
    while True:
        try:
            if time.time() - last_prune_at >= 3600:
                removed = prune_inbox()
                if removed:
                    secure_log("INFO", f"Pruned {removed} terminal inbox events")
                last_prune_at = time.time()
            bundle = claim_recovery_bundle(SPLIT_EVENT_PAIR_WINDOW_SECONDS)
            if not bundle:
                time.sleep(10)
                continue

            events = [event for event in (bundle.get('primary'), bundle.get('counterpart')) if event]
            image_event = next((event for event in events if event.get('event_type') == 'image'), None)
            text_event = next((event for event in events if event.get('event_type') == 'text'), None)
            base_event = image_event or text_event or bundle['primary']
            body_text = str((text_event or base_event).get('body_text') or '')
            input_type = 'image' if image_event else str(base_event.get('event_type') or 'text')
            media_data = image_event.get('media_data') if image_event else None
            quoted_id = str((text_event or base_event).get('quoted_message_id') or '')
            source_message_id = str((image_event or base_event).get('message_id') or '')

            with app.app_context():
                result = process_wuzapi_message(
                    sender_number=str(base_event.get('sender_id') or ''),
                    sender_name=str(base_event.get('sender_name') or 'User'),
                    text=body_text,
                    input_type=input_type,
                    media_url=media_data,
                    local_media_path=None,
                    quoted_msg_id=quoted_id,
                    message_id=source_message_id,
                    is_group=bool(base_event.get('is_group')),
                    chat_jid=str(base_event.get('chat_id') or ''),
                    sender_jid=str(base_event.get('sender_jid') or ''),
                    deferred=True,
                )
                result_status = _background_result_status(result)

            finance_signal = any(bool(event.get('finance_signal')) for event in events)
            if result_status in {'error', 'rate_limit'} or result_status.startswith('error_'):
                attempts = max(int(event.get('attempts') or 0) for event in events)
                if attempts >= 4:
                    _notify_inbox_review(base_event, body_text, f"gagal diproses setelah retry ({result_status})")
                    complete_bundle(bundle, 'needs_review_notified', result_status)
                else:
                    complete_bundle(bundle, 'retryable', result_status, result_status)
            elif (
                result_status.startswith('ignored')
                or result_status in {
                    'buffered_image_waiting_text',
                    'buffered_image_pending_confirmation',
                    'queued_image',
                }
            ):
                if finance_signal:
                    reason = (
                        "gambar dan keterangan belum dapat dipastikan"
                        if image_event and not text_event
                        else f"pipeline belum menghasilkan transaksi ({result_status})"
                    )
                    _notify_inbox_review(base_event, body_text, reason)
                    complete_bundle(bundle, 'needs_review_notified', result_status)
                else:
                    complete_bundle(bundle, 'ignored', result_status)
            else:
                complete_bundle(bundle, 'processed', result_status)
        except Exception as exc:
            secure_log("ERROR", f"Inbox recovery worker failed: {type(exc).__name__}: {exc}")
            time.sleep(30)


def start_background_workers():
    """Start durable background workers once per Gunicorn worker process."""
    global _background_workers_started
    with _background_worker_lock:
        if _background_workers_started:
            return
        from services.ledger_bootstrap import start_ledger_bootstrap_if_requested

        start_ledger_bootstrap_if_requested()
        retry_thread = threading.Thread(
            target=run_retry_service,
            daemon=True,
            name="transaction-retry-worker",
        )
        retry_thread.start()
        inbox_thread = threading.Thread(
            target=run_inbox_recovery_service,
            daemon=True,
            name="transaction-inbox-recovery-worker",
        )
        inbox_thread.start()
        _background_workers_started = True
        secure_log("INFO", "Background transaction retry and inbox recovery workers started")

if __name__ == '__main__':
    start_background_workers()
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)
