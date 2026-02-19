import os
import requests
import mimetypes
from typing import Dict, Optional, Tuple, Any
from security import secure_log, sanitize_input

# Environment Variables
WUZAPI_DOMAIN = os.getenv('WUZAPI_DOMAIN')  # e.g. https://wuzapi-x.sumopod.my.id
WUZAPI_TOKEN = os.getenv('WUZAPI_TOKEN')    # e.g. keuanganpakevan
WUZAPI_INSTANCE = os.getenv('WUZAPI_INSTANCE', 'Keuangan') 
WUZAPI_INSTANCE_ID = os.getenv('WUZAPI_INSTANCE_ID', '').strip()

# Global session
_wuzapi_session = None

def get_wuzapi_session():
    """Get secure request session for WuzAPI."""
    global _wuzapi_session
    if _wuzapi_session is None:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        _wuzapi_session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503])
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=5, max_retries=retry)
        _wuzapi_session.mount("https://", adapter)
        _wuzapi_session.headers.update({
            'token': WUZAPI_TOKEN,
            'Content-Type': 'application/json'
        })
    return _wuzapi_session

def _normalize_base(domain: str) -> str:
    """Normalize WuzAPI domain - remove trailing /api if present."""
    if not domain:
        return ""
    base = domain.strip().rstrip("/")
    # Many users accidentally set domain to .../api (which is swagger docs)
    if base.lower().endswith("/api"):
        base = base[:-4]
    return base


def _is_group_jid(to: str) -> bool:
    """Check if recipient is a WhatsApp group."""
    return isinstance(to, str) and ("@g.us" in to)


def _build_wuzapi_endpoints(base: str, path_suffix: str) -> list[str]:
    """Build endpoint candidates for hosted/self-hosted WuzAPI variants."""
    if not base:
        return []

    clean_suffix = path_suffix.lstrip("/")
    candidates = [
        f"{base}/{clean_suffix}",
        f"{base}/api/{clean_suffix}",
    ]

    # De-duplicate while preserving order.
    return list(dict.fromkeys(candidates))


def _build_instance_variants(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Build payload variants for WuzAPI deployments with different instance fields."""
    variants: list[Dict[str, Any]] = [dict(payload)]

    # Some deployments require/accept an explicit instance name or id in payload.
    if WUZAPI_INSTANCE:
        variants.extend([
            {**payload, "Instance": WUZAPI_INSTANCE},
            {**payload, "instance": WUZAPI_INSTANCE},
            {**payload, "Account": WUZAPI_INSTANCE},
        ])

    if WUZAPI_INSTANCE_ID:
        variants.extend([
            {**payload, "InstanceID": WUZAPI_INSTANCE_ID},
            {**payload, "instanceId": WUZAPI_INSTANCE_ID},
            {**payload, "AccountID": WUZAPI_INSTANCE_ID},
        ])

    def _freeze_for_hash(value: Any) -> Any:
        """Convert nested dict/list/set into hashable structure for dedup markers."""
        if isinstance(value, dict):
            return tuple(sorted((k, _freeze_for_hash(v)) for k, v in value.items()))
        if isinstance(value, (list, tuple)):
            return tuple(_freeze_for_hash(v) for v in value)
        if isinstance(value, set):
            return tuple(sorted(_freeze_for_hash(v) for v in value))
        try:
            hash(value)
            return value
        except TypeError:
            return repr(value)

    # De-duplicate while preserving order to avoid repeated requests.
    deduped: list[Dict[str, Any]] = []
    seen = set()
    for item in variants:
        marker = _freeze_for_hash(item)
        if marker not in seen:
            deduped.append(item)
            seen.add(marker)

    return deduped


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
        is_group = _is_group_jid(to)

        # Normalize recipient
        phone = to
        if isinstance(to, str) and ("@" in to) and not is_group:
            phone = to.split("@")[0].split(":")[0]

        session = get_wuzapi_session()

        # Build payload variants (different WuzAPI builds use different field names)
        payload_variants = []
        
        if is_group:
            base_payload = {"JID": to, "Body": body}
            if mention_jid:
                base_payload["MentionedJID"] = [mention_jid]

            payload_variants.extend(_build_instance_variants(base_payload))
            payload_variants.extend(_build_instance_variants({**base_payload, "Message": body}))
            # Variant: use JID as 'Phone' (some versions)
            payload_variants.extend(_build_instance_variants({**base_payload, "Phone": to}))
        else:
            # Handle LID and Phone
            phone_clean = phone.split(":")[0] if ":" in phone else phone

            payload_variants.extend(_build_instance_variants({"Phone": phone_clean, "Body": body}))
            payload_variants.extend(_build_instance_variants({"Phone": phone_clean, "Message": body}))
            # Variant: use JID format
            payload_variants.extend(_build_instance_variants({
                "JID": to if "@" in to else f"{phone_clean}@s.whatsapp.net",
                "Body": body,
            }))

        # Endpoints to try (Simplified to most likely ones based on Swagger)
        endpoints = []
        for suffix in ("chat/send/text", "send/text", "message/send/text"):
            endpoints.extend(_build_wuzapi_endpoints(base, suffix))

        last_err = ""
        for url in endpoints:
            for payload in payload_variants:
                try:
                    resp = session.post(url, json=payload, timeout=15)
                    if resp.status_code in (200, 201):
                        secure_log("INFO", f"WuzAPI Send OK via {url.split('/')[-1]}")
                        return resp.json()
                    
                    # Capture error details
                    current_err = f"{resp.status_code} on {url}: {resp.text[:200]}"
                    
                    # Stop if auth error
                    if resp.status_code in (401, 403):
                        secure_log("ERROR", f"WuzAPI Auth Error: {current_err}")
                        return None
                    
                    # 500 error is critical - usually DB lock
                    if resp.status_code == 500:
                        secure_log("ERROR", f"WuzAPI Server Error (500): {resp.text[:500]}")
                        # Don't return None immediately, try other payloads just in case
                        last_err = current_err
                        continue
                        
                    if resp.status_code == 404:
                        last_err = current_err
                        continue
                    
                    last_err = current_err
                    
                except Exception as e:
                    last_err = f"{type(e).__name__}: {str(e)[:200]}"
                    continue

        secure_log("ERROR", f"WuzAPI: All send endpoints failed: {last_err}")
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

        import base64
        # Check file size (max 10MB approx for safety)
        if os.path.getsize(file_path) > 10 * 1024 * 1024:
             secure_log("WARNING", "File too large for WuzAPI base64 send")
        
        with open(file_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode('utf-8')

        base = _normalize_base(WUZAPI_DOMAIN)
        is_group = _is_group_jid(to)
        session = get_wuzapi_session()
        filename = os.path.basename(file_path)

        # Payload construction
        payload_base = {
            "Caption": caption or filename,
            "Media": b64_data,
            "FileName": filename
        }
        
        if is_group:
            payload_base["JID"] = to
        else:
            # Handle both Phone and JID formats for private
            if "@" in to:
                payload_base["JID"] = to
                payload_base["Phone"] = to.split("@")[0]
            else:
                payload_base["Phone"] = to

        payload_variants = _build_instance_variants(payload_base)

        # Endpoints to try
        endpoints = []
        for suffix in ("chat/send/media", "send/media", "message/send/media"):
            endpoints.extend(_build_wuzapi_endpoints(base, suffix))

        last_err = ""
        for url in endpoints:
            try:
                # Need to increase timeout for media upload
                for payload in payload_variants:
                    resp = session.post(url, json=payload, timeout=60)
                    if resp.status_code in (200, 201):
                        secure_log("INFO", f"WuzAPI Media Sent via {url.split('/')[-1]}")
                        return resp.json()

                    last_err = f"{resp.status_code} on {url}: {resp.text[:200]}"
                    if resp.status_code == 413: # Payload too large
                        secure_log("ERROR", "File too large for server config")
                        break

            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                continue
        
        secure_log("ERROR", f"WuzAPI Media Send Failed: {last_err}")
        return None

    except Exception as e:
        secure_log("ERROR", f"send_wuzapi_document exception: {e}")
        return None
