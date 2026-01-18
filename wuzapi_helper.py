import os
import requests
import mimetypes
from typing import Dict, Optional, Tuple, Any
from security import secure_log, sanitize_input

# Environment Variables
WUZAPI_DOMAIN = os.getenv('WUZAPI_DOMAIN')  # e.g. https://wuzapi-x.sumopod.my.id
WUZAPI_TOKEN = os.getenv('WUZAPI_TOKEN')    # e.g. keuanganpakevan

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

def send_wuzapi_reply(to: str, body: str) -> Optional[Dict]:
    """Send WhatsApp message via WuzAPI.
    
    WuzAPI uses /chat/send/text endpoint with token in header.
    Phone format: country code + number (no + prefix)
    """
    try:
        if not WUZAPI_DOMAIN or not WUZAPI_TOKEN:
            secure_log("ERROR", "WuzAPI params missing")
            return None

        # WuzAPI uses phone number without @ suffix for sending
        # Format: country code + number (e.g. 6281212042709)
        phone = to.split('@')[0].split(':')[0] if '@' in to else to
        
        # Try multiple endpoint formats since WuzAPI versions differ
        endpoints = [
            f"{WUZAPI_DOMAIN}/chat/send/text",  # Standard WuzAPI format
            f"{WUZAPI_DOMAIN}/send/text",        # Alternative format
            f"{WUZAPI_DOMAIN}/message/text",     # Another variant
        ]
        
        # Standard WuzAPI payload
        payload = {
            "Phone": phone,
            "Body": body
        }
        
        session = get_wuzapi_session()
        
        for url in endpoints:
            try:
                response = session.post(url, json=payload, timeout=10)
                
                if response.status_code in [200, 201]:
                    secure_log("INFO", f"WuzAPI Send OK via {url.split('/')[-1]}")
                    return response.json()
                elif response.status_code == 404:
                    continue  # Try next endpoint
                else:
                    secure_log("ERROR", f"WuzAPI Send {response.status_code}: {response.text[:100]}")
            except Exception as e:
                secure_log("ERROR", f"WuzAPI endpoint {url} failed: {str(e)}")
                continue
        
        secure_log("ERROR", "WuzAPI: All send endpoints failed")
        return None
        
    except Exception as e:
        secure_log("ERROR", f"WuzAPI Send Except: {type(e).__name__}: {str(e)}")
        return None

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
