import os
import base64
import requests
import mimetypes
from typing import Dict, Optional, Any
from security import secure_log

# Environment Variables
WUZAPI_DOMAIN = (os.getenv('WUZAPI_DOMAIN') or '').strip()  # e.g. https://wuzapi-x.sumopod.my.id
WUZAPI_TOKEN = (os.getenv('WUZAPI_TOKEN') or '').strip()    # e.g. keuanganpakevan

# Global session
_wuzapi_session = None


def get_wuzapi_session():
    """Get secure request session for WuzAPI."""
    global _wuzapi_session
    if _wuzapi_session is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        _wuzapi_session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.4, status_forcelist=[429, 500, 502, 503])
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=5, max_retries=retry)
        _wuzapi_session.mount("https://", adapter)
        _wuzapi_session.headers.update({
            "Token": WUZAPI_TOKEN,
            "Authorization": WUZAPI_TOKEN,
            "x-api-key": WUZAPI_TOKEN,
            "Content-Type": "application/json",
        })
    return _wuzapi_session


def _normalize_base(domain: str) -> str:
    """Normalize WuzAPI domain - remove trailing /api if present."""
    if not domain:
        return ""
    base = domain.strip().rstrip("/")
    if base.lower().endswith("/api"):
        base = base[:-4]
    return base


def _build_wuzapi_endpoints(base: str, path_suffix: str) -> list[str]:
    """Build minimal endpoint candidates for hosted/self-hosted WuzAPI variants."""
    if not base:
        return []
    clean_suffix = path_suffix.lstrip("/")
    return list(dict.fromkeys([
        f"{base}/{clean_suffix}",
        f"{base}/api/{clean_suffix}",
    ]))


def _normalize_recipient_phone(to: str) -> str:
    """Normalize recipient into WuzAPI Phone field format."""
    if not isinstance(to, str):
        return ""
    if "@g.us" in to:
        return to
    if "@" in to:
        return to.split("@")[0].split(":")[0]
    return to.split(":")[0]


def _is_wuzapi_not_started(resp: requests.Response) -> bool:
    """Detect provider-level not-started responses."""
    try:
        body = (resp.text or "")[:500].lower()
    except Exception:
        body = ""
    location = (resp.headers.get("Location") or "").lower()
    return ("errors/not-started" in body) or ("errors/not-started" in location)


def _safe_response_excerpt(resp: requests.Response, max_chars: int = 200) -> str:
    """Return compact response text for logs."""
    try:
        body = (resp.text or "").replace("\n", " ").replace("\r", " ").strip()
    except Exception:
        body = ""
    if len(body) > max_chars:
        body = body[:max_chars]
    return body


def send_wuzapi_reply(to: str, body: str, mention_jid: str = None) -> Optional[Dict]:
    """Send WhatsApp message via WuzAPI.
    
    Standard endpoint: POST /chat/send/text with Token header.
    Payload: {"Phone":"62812xxxx","Body":"..."} for private
             {"JID":"xxx@g.us","Body":"..."} for groups
             
    Args:
        to: Recipient phone/JID
        body: Message body
        mention_jid: Optional JID to mention (for groups). Format: "628xxx@s.whatsapp.net"
    """
    try:
        if not WUZAPI_DOMAIN or not WUZAPI_TOKEN:
            secure_log("ERROR", "WuzAPI params missing")
            return None

        base = _normalize_base(WUZAPI_DOMAIN)
        session = get_wuzapi_session()
        phone = _normalize_recipient_phone(to)
        if not phone:
            secure_log("ERROR", "WuzAPI send failed: empty recipient")
            return None

        payload: Dict[str, Any] = {
            "Phone": phone,
            "Body": body,
        }
        if mention_jid:
            payload["ContextInfo"] = {"MentionedJID": [mention_jid]}

        endpoints = _build_wuzapi_endpoints(base, "chat/send/text")
        last_err = ""
        for url in endpoints:
            try:
                resp = session.post(url, json=payload, timeout=8, allow_redirects=False)
                if resp.status_code in (200, 201, 202):
                    secure_log("INFO", f"WuzAPI Send OK via {url.split('/')[-1]}")
                    try:
                        return resp.json()
                    except Exception:
                        return {"status": "ok", "status_code": resp.status_code}

                loc = resp.headers.get("Location", "")
                last_err = f"{resp.status_code} on {url} loc={loc}: {_safe_response_excerpt(resp)}"
                if resp.status_code in (401, 403):
                    secure_log("ERROR", f"WuzAPI Auth Error: {last_err}")
                    return None
                if _is_wuzapi_not_started(resp):
                    secure_log(
                        "ERROR",
                        "WuzAPI reports session not started for this token/instance. "
                        "Please reconnect/start session from provider dashboard."
                    )
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:200]}"

        secure_log("ERROR", f"WuzAPI: send text failed: {last_err}")
        return None
    except Exception as e:
        secure_log("ERROR", f"WuzAPI Send Except: {type(e).__name__}: {str(e)}")
        return None


def format_mention_body(body: str, sender_name: str, sender_jid: str) -> str:
    """Format message body with @mention at the beginning.
    
    Args:
        body: Original message body
        sender_name: Display name of the user to mention (e.g., "Naufalspurnomo")
        sender_jid: JID of the user (e.g., "628xxx:72@s.whatsapp.net")
    
    Returns:
        Message body with @mention prepended using sender's display name
    """
    if not sender_jid:
        return body
    
    # Use sender's display name for the visible @mention
    # WhatsApp will still tag the correct user via MentionedJID
    display_name = sender_name if sender_name else "User"
    
    # Format: @DisplayName at the beginning, followed by message
    return f"@{display_name}\n{body}"


def get_clean_jid(sender_jid: str) -> str:
    """Clean the sender JID by removing device suffix for MentionedJID.
    
    WhatsApp multi-device adds :XX suffix (e.g., 628xxx:72@s.whatsapp.net)
    which should be stripped for mentions to work correctly.
    
    Args:
        sender_jid: Raw JID (e.g., "628xxx:72@s.whatsapp.net")
    
    Returns:
        Clean JID (e.g., "628xxx@s.whatsapp.net")
    """
    if not sender_jid:
        return ""
    
    # Split by @ first
    if "@" in sender_jid:
        phone_part, domain = sender_jid.split("@", 1)
        # Remove :XX device suffix from phone part
        if ":" in phone_part:
            phone_part = phone_part.split(":")[0]
        return f"{phone_part}@{domain}"
    
    return sender_jid

def download_wuzapi_media(media_url: str) -> Optional[str]:
    """Download media from WuzAPI or direct URL."""
    import tempfile
    try:
        session = get_wuzapi_session()
        response = session.get(media_url, stream=True, timeout=30)
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            ext = mimetypes.guess_extension(content_type) or '.bin'
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp.write(chunk)
                return tmp.name
        else:
            secure_log("ERROR", f"WuzAPI Media Download Failed: {response.status_code}")
            return None
    except Exception as e:
        secure_log("ERROR", f"WuzAPI Media Except: {str(e)}")
        return None


def download_wuzapi_image(message_id: str, chat_jid: str) -> Optional[str]:
    """Download image from WuzAPI using message ID and chat JID.
    
    WuzAPI provides /chat/downloadimage endpoint to download media.
    Returns the local file path of the downloaded image, or None if failed.
    """
    import tempfile
    import base64
    
    if not WUZAPI_DOMAIN or not WUZAPI_TOKEN:
        secure_log("ERROR", "WuzAPI params missing for image download")
        return None
    
    try:
        session = get_wuzapi_session()
        
        # WuzAPI download image endpoint
        url = f"{WUZAPI_DOMAIN}/chat/downloadimage"
        payload = {
            "MessageID": message_id,
            "JID": chat_jid
        }
        
        response = session.post(url, json=payload, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            
            # WuzAPI returns base64 encoded image data
            if result.get('success') and result.get('data'):
                image_data = result['data']
                
                # Check if it's base64 encoded
                if isinstance(image_data, str):
                    try:
                        # Decode base64
                        img_bytes = base64.b64decode(image_data)
                        
                        # Save to temp file
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                            tmp.write(img_bytes)
                            secure_log("INFO", f"WuzAPI image downloaded: {tmp.name}")
                            return tmp.name
                    except Exception as e:
                        secure_log("ERROR", f"WuzAPI base64 decode failed: {str(e)}")
                        return None
                        
            # Alternative: check if direct bytes or URL
            elif result.get('url'):
                return download_wuzapi_media(result['url'])
            
            secure_log("DEBUG", f"WuzAPI image response: {str(result)[:200]}")
            return None
        else:
            secure_log("ERROR", f"WuzAPI Download Image failed: {response.status_code} - {response.text[:100]}")
            return None
            
    except Exception as e:
        secure_log("ERROR", f"WuzAPI Download Image Except: {type(e).__name__}: {str(e)}")
        return None

def send_wuzapi_document(to: str, file_path: str, caption: str = None) -> Optional[Dict]:
    """Send document/media via WuzAPI (Base64 method)."""
    try:
        if not WUZAPI_DOMAIN or not WUZAPI_TOKEN:
            secure_log("ERROR", "WuzAPI params missing")
            return None
            
        if not os.path.exists(file_path):
            secure_log("ERROR", f"File not found: {file_path}")
            return None

        # Check file size (max 10MB approx for safety)
        if os.path.getsize(file_path) > 10 * 1024 * 1024:
             secure_log("WARNING", "File too large for WuzAPI base64 send")
        
        with open(file_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode('utf-8')

        base = _normalize_base(WUZAPI_DOMAIN)
        session = get_wuzapi_session()
        filename = os.path.basename(file_path)
        phone = _normalize_recipient_phone(to)
        if not phone:
            secure_log("ERROR", "WuzAPI media send failed: empty recipient")
            return None
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        doc_data = f"data:{mime};base64,{b64_data}"

        payload = {
            "Phone": phone,
            "FileName": filename,
            "Document": doc_data,
        }

        if caption:
            payload["Caption"] = caption

        endpoints = _build_wuzapi_endpoints(base, "chat/send/document")
        last_err = ""
        for url in endpoints:
            try:
                resp = session.post(url, json=payload, timeout=20, allow_redirects=False)
                if resp.status_code in (200, 201, 202):
                    secure_log("INFO", f"WuzAPI Media Sent via {url.split('/')[-1]}")
                    try:
                        return resp.json()
                    except Exception:
                        return {"status": "ok", "status_code": resp.status_code}

                loc = resp.headers.get("Location", "")
                last_err = f"{resp.status_code} on {url} loc={loc}: {_safe_response_excerpt(resp)}"
                if resp.status_code in (401, 403):
                    secure_log("ERROR", f"WuzAPI Media Auth Error: {last_err}")
                    return None
                if _is_wuzapi_not_started(resp):
                    secure_log(
                        "ERROR",
                        "WuzAPI reports session not started for media send. "
                        "Please reconnect/start session from provider dashboard."
                    )
                if resp.status_code == 413:
                    secure_log("ERROR", "File too large for server config")
                    return None
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:200]}"

        secure_log("ERROR", f"WuzAPI Media Send Failed: {last_err}")
        return None

    except Exception as e:
        secure_log("ERROR", f"send_wuzapi_document exception: {e}")
        return None
