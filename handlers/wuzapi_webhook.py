"""WuzAPI webhook request parsing and dispatch."""

import base64
import json
import os
import re
import time
import traceback
from typing import Callable

from flask import g, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from config.allowlist import is_sender_allowed
from security import log_timing, secure_log, verify_webhook_secret
from services.state_manager import clear_message_duplicate, is_message_duplicate, store_visual_buffer
from services.durable_inbox import InboxUnavailable, capture_event, mark_event, mark_source_event
from wuzapi_helper import download_wuzapi_image, send_wuzapi_reply


IGNORED_EVENT_TYPES = {
    'Connected',
    'ReadReceipt',
    'Receipt',
    'Typing',
    'TypingStarted',
    'TypingStopped',
    'Presence',
    'PresenceUpdate',
    'ChatState',
    'Composing',
    'Paused',
}


def _extract_sender_number(info: dict) -> str:
    sender_alt = str(info.get('SenderAlt') or '')
    sender_jid = str(info.get('Sender') or '')
    sender_number = (
        sender_alt.split('@')[0].split(':')[0]
        if '@' in sender_alt
        else (sender_jid.split('@')[0].split(':')[0] if '@' in sender_jid else '')
    )

    if not sender_number:
        info_id = str(info.get('ID', '') or '')
        if '@' in info_id:
            sender_number = info_id.split('@')[0].split(':')[0]

    return sender_number


def _extract_context_info(event_data: dict, event: dict, info: dict, message_obj: dict):
    if message_obj.get('extendedTextMessage', {}).get('contextInfo'):
        return message_obj['extendedTextMessage']['contextInfo']
    if message_obj.get('messageContextInfo'):
        return message_obj['messageContextInfo']
    if message_obj.get('imageMessage', {}).get('contextInfo'):
        return message_obj['imageMessage']['contextInfo']
    if message_obj.get('contextInfo'):
        return message_obj['contextInfo']
    if info.get('ContextInfo'):
        return info['ContextInfo']
    if event_data.get('event', {}).get('ContextInfo'):
        return event['ContextInfo']
    return None


def _quoted_message_id(ctx_info: dict) -> str:
    if not ctx_info:
        return ''
    return (
        ctx_info.get('stanzaId')
        or ctx_info.get('StanzaId')
        or ctx_info.get('stanzaID')
        or ctx_info.get('quotedMessageID')
        or ctx_info.get('quotedMessageId')
        or ''
    )


def _finance_signal(text: str, input_type: str) -> bool:
    if input_type == 'image':
        return True
    lower = str(text or '').lower()
    has_amount = bool(re.search(r"(?:rp\s*)?\d[\d.,]*(?:\s*(?:rb|ribu|jt|juta|k))?\b", lower))
    keywords = r"\b(fee|gaji|upah|bayar|beli|biaya|transfer|dp|invoice|nota|struk|projek|project|proyek|kantor|operasional|dompet)\b"
    return has_amount or bool(re.search(keywords, lower))


def _result_status(result) -> str:
    response = result[0] if isinstance(result, tuple) and result else result
    try:
        payload = response.get_json(silent=True)
    except Exception:
        payload = None
    return str((payload or {}).get('status') or '')


def _lifecycle_for_result(status: str, finance_signal: bool) -> str:
    if status in {'buffered_image_waiting_text', 'buffered_image_pending_confirmation', 'queued_image'}:
        return 'waiting_pair'
    if status.startswith('ignored'):
        return 'needs_review' if finance_signal else 'ignored'
    if status in {'error', 'rate_limit', 'image_missing_media'} or status.startswith('error_'):
        return 'retryable'
    return 'processed'


def handle_wuzapi_webhook(
    flask_request,
    process_message: Callable,
    max_webhook_bytes: int,
):
    message_id = ''
    inbox_event_key = ''
    try:
        if not verify_webhook_secret(
            flask_request,
            "WUZAPI_WEBHOOK_SECRET",
            ("X-WuzAPI-Webhook-Secret", "X-Webhook-Secret"),
        ):
            secure_log("WARNING", "WuzAPI webhook secret rejected")
            return jsonify({'status': 'unauthorized'}), 401
        try:
            json_data_raw = flask_request.form.get('jsonData')
        except RequestEntityTooLarge:
            secure_log("WARNING", f"Webhook payload too large while reading form (>{max_webhook_bytes} bytes)")
            return jsonify({'status': 'payload_too_large'}), 200
        if not json_data_raw:
            return jsonify({'status': 'no_data'}), 200

        try:
            event_data = json.loads(json_data_raw)
        except json.JSONDecodeError:
            return jsonify({'status': 'parse_error'}), 200

        event = event_data.get('event', {})
        if not isinstance(event, dict):
            secure_log("INFO", f"Webhook: Ignored malformed event type={type(event).__name__}")
            return jsonify({'status': 'ignored_malformed_event'}), 200

        info = event.get('Info', event)
        if not isinstance(info, dict):
            secure_log("INFO", f"Webhook: Ignored malformed info type={type(info).__name__}")
            return jsonify({'status': 'ignored_malformed_info'}), 200
        event_type = event_data.get('type', '')

        if not event_type or event_type in IGNORED_EVENT_TYPES:
            return jsonify({'status': 'ignored_event'}), 200

        if info.get('IsFromMe', False):
            return jsonify({'status': 'own_message'}), 200

        sender_number = _extract_sender_number(info)
        if not sender_number:
            secure_log("WARNING", f"Webhook: No sender number found in {info}")
            return jsonify({'status': 'no_sender'}), 200

        chat_jid = info.get('Chat', '')
        is_group = '@g.us' in chat_jid
        if not is_sender_allowed([sender_number]):
            secure_log("WARNING", f"Webhook: Access denied for {sender_number}")
            reply_target = chat_jid if (is_group and chat_jid) else sender_number
            send_wuzapi_reply(
                reply_target,
                "❌ Akses ditolak.\nNomor ini belum masuk allowlist bot. Hubungi admin."
            )
            return jsonify({'status': 'forbidden'}), 200

        message_obj = event.get('Message', {})
        message_id = info.get('ID', '')
        text = ''
        input_type = 'text'
        media_url = None
        local_media_path = None
        quoted_msg_id = ''
        image_missing_media = False

        msg_type = info.get('Type', '')
        if not msg_type:
            secure_log("INFO", f"Webhook: Missing message type (info.Type empty). Info keys: {list(info.keys())}")
        if msg_type not in ['text', 'media', 'image']:
            secure_log("INFO", f"Webhook: Ignored message type '{msg_type}'")
            return jsonify({'status': f'ignored_type_{msg_type}'}), 200

        if msg_type == 'text':
            msg_keys = list(message_obj.keys()) if isinstance(message_obj, dict) else []
            secure_log("DEBUG", f"Webhook: text msg_keys={msg_keys}")
            if message_obj.get('extendedTextMessage'):
                ext_keys = list(message_obj['extendedTextMessage'].keys())
                secure_log("DEBUG", f"Webhook: extendedTextMessage keys={ext_keys}")

        if msg_type == 'text':
            text = (
                message_obj.get('conversation')
                or message_obj.get('extendedTextMessage', {}).get('text', '')
            )
            dedup_score = min(len((text or '').strip()), 200)
            if is_message_duplicate(message_id, score=dedup_score, allow_upgrade=True):
                secure_log("INFO", f"Webhook: Duplicate message {message_id} ignored")
                return jsonify({'status': 'duplicate'}), 200
        elif msg_type in ['media', 'image']:
            text = message_obj.get('imageMessage', {}).get('caption', '')
            input_type = 'image'
            raw_media_score = 1000 if event_data.get('base64') else 0
            dedup_score = raw_media_score + min(len((text or '').strip()), 200)
            if is_message_duplicate(message_id, score=dedup_score, allow_upgrade=True):
                secure_log("INFO", f"Webhook: Duplicate message {message_id} ignored before media download")
                return jsonify({'status': 'duplicate'}), 200
            if event_data.get('base64'):
                media_url = f"data:image/jpeg;base64,{event_data['base64']}"
            elif info.get('ID'):
                try:
                    local_media_path = download_wuzapi_image(info.get('ID'), chat_jid)
                except Exception:
                    local_media_path = None

            # Upgrade the dedup record after a successful provider download.
            if local_media_path and not raw_media_score:
                is_message_duplicate(message_id, score=1000 + dedup_score, allow_upgrade=True)

            if not media_url and not local_media_path:
                if (text or '').strip():
                    secure_log("WARNING", "Webhook image payload missing media; fallback to caption-only text extraction")
                    input_type = 'text'
                else:
                    secure_log("WARNING", "Webhook image payload missing media and caption; skipping message")
                    image_missing_media = True

            secure_log(
                "INFO",
                f"Webhook: Image message received (caption_len={len(text or '')}, "
                f"base64={'yes' if event_data.get('base64') else 'no'}, "
                f"download={'yes' if local_media_path else 'no'})"
            )

            # Publish the visual before the heavier transaction pipeline starts.
            # Concurrent follow-up text can now bind even if this request is descheduled.
            if not image_missing_media:
                store_visual_buffer(
                    sender_number,
                    chat_jid,
                    media_url,
                    message_id,
                    caption=text,
                    media_path=local_media_path,
                )

        if msg_type == 'text' and not (text or '').strip():
            secure_log("INFO", f"Webhook: Empty text ignored from {sender_number}")
            return jsonify({'status': 'empty_text'}), 200

        secure_log("INFO", f"Webhook: Msg from {sender_number} (Group: {is_group}): {text[:50]}...")

        ctx_info = _extract_context_info(event_data, event, info, message_obj)
        if ctx_info:
            quoted_msg_id = _quoted_message_id(ctx_info)
            if quoted_msg_id:
                secure_log("INFO", f"Webhook: Quoted message detected: {quoted_msg_id[:20]}...")
            else:
                secure_log("DEBUG", f"Webhook: contextInfo found but no stanzaId. Keys: {list(ctx_info.keys())}")

        durable_media = media_url
        if not durable_media and local_media_path and os.path.isfile(local_media_path):
            try:
                with open(local_media_path, 'rb') as media_file:
                    encoded = base64.b64encode(media_file.read()).decode('ascii')
                durable_media = f"data:image/jpeg;base64,{encoded}"
            except OSError as exc:
                secure_log("WARNING", f"Could not persist downloaded media: {type(exc).__name__}")

        finance_signal = _finance_signal(text, input_type)
        capture_started = time.perf_counter()
        try:
            inbox_event_key = capture_event({
                'provider': 'wuzapi',
                'message_id': message_id,
                'chat_id': chat_jid,
                'sender_id': sender_number,
                'sender_name': info.get('PushName', 'User'),
                'sender_jid': info.get('SenderAlt', ''),
                'event_type': input_type,
                'body_text': text,
                'media_data': durable_media,
                'media_path': None,
                'quoted_message_id': quoted_msg_id,
                'is_group': is_group,
                'finance_signal': finance_signal,
                'payload_score': (1000 if durable_media else 0) + min(len((text or '').strip()), 200),
            })
        except InboxUnavailable as exc:
            clear_message_duplicate(message_id)
            secure_log("CRITICAL", f"Webhook not acknowledged because durable inbox is unavailable: {exc}")
            return jsonify({'status': 'durable_inbox_unavailable'}), 503
        finally:
            log_timing("webhook.capture_event", capture_started)

        if image_missing_media:
            mark_event(
                inbox_event_key,
                'needs_review',
                result_status='image_missing_media',
                error='provider image event contained no retrievable media',
            )
            return jsonify({'status': 'image_missing_media'}), 200

        mark_event(inbox_event_key, 'processing')
        process_started = time.perf_counter()
        try:
            result = process_message(
                sender_number, info.get('PushName', 'User'), text,
                input_type, media_url, local_media_path, quoted_msg_id, message_id,
                is_group, chat_jid, info.get('SenderAlt', '')
            )
        finally:
            log_timing("webhook.process_message", process_started, input_type=input_type)
        result_status = _result_status(result)
        lifecycle_status = _lifecycle_for_result(result_status, finance_signal)
        mark_event(
            inbox_event_key,
            lifecycle_status,
            result_status=result_status,
        )
        bound_visual_id = str(getattr(g, 'transaction_visual_message_id', '') or '')
        if bound_visual_id:
            mark_source_event(
                'wuzapi',
                chat_jid,
                bound_visual_id,
                lifecycle_status,
                result_status=result_status,
            )
        return result

    except Exception:
        if message_id and not inbox_event_key:
            clear_message_duplicate(message_id)
        secure_log("ERROR", f"Webhook Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500
