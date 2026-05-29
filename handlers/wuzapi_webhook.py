"""WuzAPI webhook request parsing and dispatch."""

import json
import traceback
from typing import Callable

from flask import jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from config.allowlist import is_sender_allowed
from security import secure_log
from services.state_manager import is_message_duplicate
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
    sender_alt = info.get('SenderAlt', '')
    sender_jid = info.get('Sender', '')
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


def handle_wuzapi_webhook(
    flask_request,
    process_message: Callable,
    max_webhook_bytes: int,
):
    try:
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
            send_wuzapi_reply(reply_target, "Ã¢ÂÅ’ Akses Ditolak. Hubungi Admin.")
            return jsonify({'status': 'forbidden'}), 200

        message_obj = event.get('Message', {})
        text = ''
        input_type = 'text'
        media_url = None
        local_media_path = None
        quoted_msg_id = ''

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
        elif msg_type in ['media', 'image']:
            text = message_obj.get('imageMessage', {}).get('caption', '')
            input_type = 'image'
            if event_data.get('base64'):
                media_url = f"data:image/jpeg;base64,{event_data['base64']}"
            elif info.get('ID'):
                try:
                    local_media_path = download_wuzapi_image(info.get('ID'), chat_jid)
                except Exception:
                    local_media_path = None

            if not media_url and not local_media_path:
                if (text or '').strip():
                    secure_log("WARNING", "Webhook image payload missing media; fallback to caption-only text extraction")
                    input_type = 'text'
                else:
                    secure_log("WARNING", "Webhook image payload missing media and caption; skipping message")
                    return jsonify({'status': 'image_missing_media'}), 200

            secure_log(
                "INFO",
                f"Webhook: Image message received (caption_len={len(text or '')}, "
                f"base64={'yes' if event_data.get('base64') else 'no'}, "
                f"download={'yes' if local_media_path else 'no'})"
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

        message_id = info.get('ID', '')
        dedup_score = 0
        if text and text.strip():
            dedup_score += min(len(text.strip()), 200)
        if input_type == 'image' and (local_media_path or media_url or event_data.get('base64')):
            dedup_score += 1000
        if is_message_duplicate(message_id, score=dedup_score, allow_upgrade=True):
            secure_log("INFO", f"Webhook: Duplicate message {message_id} ignored")
            return jsonify({'status': 'duplicate'}), 200

        return process_message(
            sender_number, info.get('PushName', 'User'), text,
            input_type, media_url, local_media_path, quoted_msg_id, message_id,
            is_group, chat_jid, info.get('SenderAlt', '')
        )

    except Exception:
        secure_log("ERROR", f"Webhook Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500
