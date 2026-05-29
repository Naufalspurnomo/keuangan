"""Telegram webhook request parsing and dispatch."""

import traceback
from typing import Callable

from flask import jsonify

from config.allowlist import is_sender_allowed
from security import secure_log
from services.state_manager import is_message_duplicate
from services.telegram_gateway import (
    get_telegram_file_url,
    send_telegram_document,
    send_telegram_reply,
)
from utils.formatters import format_reply_message


def handle_telegram_webhook(flask_request, process_message: Callable):
    try:
        update = flask_request.get_json(silent=True) or {}
        message = update.get('message') or update.get('edited_message')
        if not message:
            return jsonify({'status': 'no_message'}), 200

        sender = message.get('from', {})
        if sender.get('is_bot'):
            return jsonify({'status': 'own_message'}), 200

        chat = message.get('chat', {})
        chat_id = chat.get('id')
        if chat_id is None:
            return jsonify({'status': 'no_chat'}), 200

        chat_type = chat.get('type', 'private')
        is_group = chat_type in ('group', 'supergroup')

        sender_id = sender.get('id')
        sender_name = " ".join(filter(None, [sender.get('first_name'), sender.get('last_name')])).strip()
        if not sender_name:
            sender_name = sender.get('username', 'User')
        sender_number = str(sender_id) if sender_id is not None else sender.get('username', '')
        sender_username = sender.get('username')

        if not is_sender_allowed([sender_number, sender_username, sender_name]):
            secure_log("WARNING", f"Telegram: Access denied for {sender_number}")
            send_telegram_reply(chat_id, "Ã¢ÂÅ’ Akses Ditolak. Hubungi Admin.")
            return jsonify({'status': 'forbidden'}), 200

        text = message.get('text') or ''
        input_type = 'text'
        media_url = None

        if message.get('photo'):
            photo = message['photo'][-1]
            file_id = photo.get('file_id')
            media_url = get_telegram_file_url(file_id)
            input_type = 'image'
            if not text:
                text = message.get('caption', '') or ''

        quoted_msg_id = None
        quoted_message_text = None
        reply_msg = message.get('reply_to_message')
        if reply_msg:
            reply_message_id = reply_msg.get('message_id')
            if reply_message_id is not None:
                quoted_msg_id = f"tg:{chat_id}:{reply_message_id}"
            quoted_message_text = reply_msg.get('text') or reply_msg.get('caption')

        message_id = message.get('message_id')
        if message_id is not None:
            message_key = f"tg:{chat_id}:{message_id}"
        else:
            message_key = f"tg:{chat_id}:{update.get('update_id', '')}"

        if is_message_duplicate(message_key):
            secure_log("INFO", f"Telegram: Duplicate message {message_key} ignored")
            return jsonify({'status': 'duplicate'}), 200

        def send_reply(body: str, mention: bool = True):
            body_fmt = format_reply_message(body)
            return send_telegram_reply(chat_id, body_fmt)

        return process_message(
            sender_number=sender_number,
            sender_name=sender_name,
            text=text,
            input_type=input_type,
            media_url=media_url,
            quoted_msg_id=quoted_msg_id,
            message_id=message_key,
            is_group=is_group,
            chat_jid=str(chat_id),
            sender_jid=None,
            quoted_message_text=quoted_message_text,
            send_reply=send_reply,
            send_document=send_telegram_document,
            source_label='Telegram',
            reply_to=chat_id,
        )
    except Exception:
        secure_log("ERROR", f"Telegram Webhook Error: {traceback.format_exc()}")
        return jsonify({'status': 'error'}), 500
