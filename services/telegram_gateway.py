"""
Telegram network helpers.

Kept separate from main.py so webhook orchestration does not own HTTP session
setup and Telegram API details.
"""

import os
from typing import Dict, Optional

import requests

from security import secure_log


_TELEGRAM_API_URL = None
_telegram_session = None


def get_telegram_session():
    """Get or create requests Session with connection pooling."""
    global _telegram_session
    if _telegram_session is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        _telegram_session = requests.Session()
        retry_strategy = Retry(
            total=3, backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retry_strategy)
        _telegram_session.mount("https://", adapter)
        _telegram_session.mount("http://", adapter)

    return _telegram_session


def get_telegram_api_url():
    """Get Telegram API URL."""
    global _TELEGRAM_API_URL
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if _TELEGRAM_API_URL is None and token:
        _TELEGRAM_API_URL = f"https://api.telegram.org/bot{token}"
    return _TELEGRAM_API_URL


def send_telegram_reply(chat_id: int, message: str, parse_mode: str = 'Markdown'):
    """Send Telegram reply securely."""
    try:
        api_url = get_telegram_api_url()
        if not api_url:
            return None

        session = get_telegram_session()
        response = session.post(
            f"{api_url}/sendMessage",
            json={'chat_id': chat_id, 'text': message, 'parse_mode': parse_mode},
            timeout=10
        )
        return response.json()
    except Exception as e:
        secure_log("ERROR", f"Telegram send failed: {type(e).__name__}")
        return None


def get_telegram_file_url(file_id: str) -> Optional[str]:
    """Resolve a Telegram file_id to a downloadable URL."""
    try:
        api_url = get_telegram_api_url()
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not api_url or not token or not file_id:
            return None

        session = get_telegram_session()
        response = session.get(
            f"{api_url}/getFile",
            params={'file_id': file_id},
            timeout=10
        )
        if response.status_code != 200:
            secure_log("ERROR", f"Telegram getFile failed: {response.status_code}")
            return None

        payload = response.json()
        file_path = payload.get('result', {}).get('file_path')
        if not file_path:
            return None

        return f"https://api.telegram.org/file/bot{token}/{file_path}"
    except Exception as e:
        secure_log("ERROR", f"Telegram getFile exception: {type(e).__name__}: {e}")
        return None


def send_telegram_document(chat_id: int, file_path: str, caption: str = None) -> Optional[Dict]:
    """Send a document to Telegram."""
    try:
        api_url = get_telegram_api_url()
        if not api_url or not file_path:
            return None

        session = get_telegram_session()
        with open(file_path, "rb") as f:
            response = session.post(
                f"{api_url}/sendDocument",
                data={'chat_id': chat_id, 'caption': caption or ''},
                files={'document': f},
                timeout=30
            )
        return response.json()
    except Exception as e:
        secure_log("ERROR", f"Telegram sendDocument failed: {type(e).__name__}: {e}")
        return None
