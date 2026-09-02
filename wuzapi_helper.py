import os
import base64
import time
import requests
import mimetypes
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit
from typing import Dict, Optional, Any
from security import log_timing, secure_log

# Environment Variables
WUZAPI_DOMAIN = (os.getenv('WUZAPI_DOMAIN') or '').strip()  # e.g. https://wuzapi-x.sumopod.my.id
WUZAPI_TOKEN = (os.getenv('WUZAPI_TOKEN') or '').strip()    # e.g. keuanganpakevan

# Global session
_wuzapi_session = None
_status_lock = threading.Lock()
_reconnect_lock = threading.Lock()
_monitor_lock = threading.Lock()
_status_cache = None
_status_cache_monotonic = 0.0
_last_reconnect_monotonic = 0.0
_monitor_started = False


def _bounded_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _env_enabled(name: str, default: bool = True) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _empty_wuzapi_status(error: str = "") -> dict:
    configured = bool(WUZAPI_DOMAIN and WUZAPI_TOKEN)
    return {
        "configured": configured,
        "reachable": False,
        "connected": False,
        "logged_in": False,
        "state": "unconfigured" if not configured else "unknown",
        "error": error or ("not_configured" if not configured else ""),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _response_value(objects: list[dict], names: tuple[str, ...]) -> Any:
    for obj in reversed(objects):
        for name in names:
            if name in obj:
                return obj[name]
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "connected", "online", "logged_in"}


def _safe_provider_state(value: Any, connected: bool) -> str:
    state = str(value or ("connected" if connected else "disconnected")).strip().lower()
    state = re.sub(r"[^a-z0-9_. -]", "", state)[:64]
    allowed = {
        "connected", "connected_not_logged_in", "disconnected", "connecting",
        "reconnecting", "logged_in", "logged_out", "online", "offline",
        "ready", "unknown",
    }
    return state if state in allowed else ("connected" if connected else "disconnected")


def _status_from_payload(payload: Any) -> dict:
    objects = _wuzapi_response_objects(payload)
    connected = _as_bool(_response_value(objects, ("connected", "Connected", "isConnected", "IsConnected")))
    logged_in_value = _response_value(objects, ("logged_in", "loggedIn", "LoggedIn", "isLoggedIn", "IsLoggedIn"))
    logged_in = connected if logged_in_value is None else _as_bool(logged_in_value)
    state_value = _response_value(objects, ("state", "State", "status", "Status"))
    if state_value is None and connected and not logged_in:
        state_value = "connected_not_logged_in"
    return {
        "configured": True,
        "reachable": True,
        "connected": connected,
        "logged_in": logged_in,
        "state": _safe_provider_state(state_value, connected),
        "error": "",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _cache_status(status: dict) -> dict:
    global _status_cache, _status_cache_monotonic
    _status_cache = dict(status)
    _status_cache_monotonic = time.monotonic()
    return dict(status)


def get_wuzapi_status(force: bool = False) -> dict:
    """Return a cached, sanitized WuzAPI session status."""
    global _status_cache
    cache_seconds = _bounded_env_float("WUZAPI_STATUS_CACHE_SECONDS", 10, 1, 60)
    with _status_lock:
        if not force and _status_cache is not None:
            if time.monotonic() - _status_cache_monotonic < cache_seconds:
                return dict(_status_cache)
        if not WUZAPI_DOMAIN or not WUZAPI_TOKEN:
            return _cache_status(_empty_wuzapi_status())

        try:
            session = get_wuzapi_session()
        except Exception as exc:
            status = _empty_wuzapi_status(f"unreachable:{type(exc).__name__}")
            status["state"] = "unreachable"
            return _cache_status(status)
        timeout = _bounded_env_float("WUZAPI_STATUS_TIMEOUT_SECONDS", 3, 1, 5)
        last_status = None
        last_error = "unreachable"
        for url in _build_wuzapi_endpoints(_normalize_base(WUZAPI_DOMAIN), "session/status"):
            try:
                response = session.get(url, timeout=timeout, allow_redirects=False)
                last_status = response.status_code
                if 200 <= response.status_code < 300:
                    try:
                        return _cache_status(_status_from_payload(response.json()))
                    except Exception:
                        last_error = "invalid_json"
                        break
                last_error = f"http_{response.status_code}"
            except Exception as exc:
                last_error = f"unreachable:{type(exc).__name__}"
                # Both candidates share one origin. Retrying the alternate path
                # after a transport failure only doubles health-check latency.
                break

        status = _empty_wuzapi_status(last_error)
        status["reachable"] = last_status is not None
        status["state"] = "unknown" if last_status is not None else "unreachable"
        return _cache_status(status)


def _invalidate_status_cache() -> None:
    global _status_cache, _status_cache_monotonic
    with _status_lock:
        _status_cache = None
        _status_cache_monotonic = 0.0


def ensure_wuzapi_connected(force: bool = False) -> dict:
    """Reconnect one reachable, disconnected WuzAPI session with cooldown protection."""
    global _last_reconnect_monotonic
    observed_reconnect = _last_reconnect_monotonic
    status = get_wuzapi_status(force=force)
    if (
        not status["configured"]
        or not status["reachable"]
        or (status["connected"] and status["logged_in"])
    ):
        return status

    with _reconnect_lock:
        if _last_reconnect_monotonic != observed_reconnect:
            status = get_wuzapi_status(force=True)
            if (
                not status["reachable"]
                or (status["connected"] and status["logged_in"])
            ):
                return status
        cooldown = _bounded_env_float("WUZAPI_RECONNECT_COOLDOWN_SECONDS", 60, 5, 600)
        if _last_reconnect_monotonic and time.monotonic() - _last_reconnect_monotonic < cooldown:
            return status

        _last_reconnect_monotonic = time.monotonic()
        session = get_wuzapi_session()
        base = _normalize_base(WUZAPI_DOMAIN)
        if status["connected"] and not status["logged_in"]:
            disconnect_timeout = _bounded_env_float(
                "WUZAPI_DISCONNECT_TIMEOUT_SECONDS", 5, 1, 8
            )
            disconnected = False
            for url in _build_wuzapi_endpoints(base, "session/disconnect"):
                try:
                    response = session.post(
                        url,
                        timeout=disconnect_timeout,
                        allow_redirects=False,
                    )
                    if 200 <= response.status_code < 300:
                        disconnected = True
                        break
                except Exception:
                    continue
            if not disconnected:
                status["error"] = "stale_disconnect_failed"
                return _cache_status(status)
            _invalidate_status_cache()

        # WuzAPI waits about ten seconds when Immediate is false, so the client
        # timeout must exceed the server-side connection verification window.
        timeout = _bounded_env_float("WUZAPI_CONNECT_TIMEOUT_SECONDS", 15, 11, 20)
        accepted = False
        connect_error = "connect_failed"
        payload = {"Subscribe": [], "Immediate": False}
        for url in _build_wuzapi_endpoints(_normalize_base(WUZAPI_DOMAIN), "session/connect"):
            try:
                response = session.post(
                    url,
                    json=payload,
                    timeout=timeout,
                    allow_redirects=False,
                )
                if 200 <= response.status_code < 300:
                    accepted = True
                    break
                connect_error = f"connect_http_{response.status_code}"
            except Exception as exc:
                connect_error = f"connect_error:{type(exc).__name__}"

        if not accepted:
            status["error"] = connect_error
            return _cache_status(status)

        poll_count = int(_bounded_env_float("WUZAPI_CONNECT_POLL_COUNT", 3, 1, 5))
        poll_interval = _bounded_env_float("WUZAPI_CONNECT_POLL_INTERVAL_SECONDS", 1, 0.1, 2)
        for poll_index in range(poll_count):
            if poll_index:
                time.sleep(poll_interval)
            status = get_wuzapi_status(force=True)
            if status["connected"] and status["logged_in"]:
                secure_log("INFO", "WuzAPI session reconnected and logged in")
                return status
        status["error"] = "reconnect_pending"
        return _cache_status(status)


def run_wuzapi_monitor(stop_event: Optional[threading.Event] = None) -> None:
    """Periodically verify and heal the WuzAPI session."""
    if not _env_enabled("WUZAPI_MONITOR_ENABLED", True):
        return
    stopper = stop_event or threading.Event()
    interval = _bounded_env_float("WUZAPI_MONITOR_INTERVAL_SECONDS", 60, 15, 3600)
    while not stopper.is_set():
        try:
            ensure_wuzapi_connected()
        except Exception as exc:
            secure_log("WARNING", f"WuzAPI monitor check failed: {type(exc).__name__}")
        stopper.wait(interval)


def start_wuzapi_monitor() -> bool:
    """Start the WuzAPI monitor at most once per process."""
    global _monitor_started
    with _monitor_lock:
        if _monitor_started or not _env_enabled("WUZAPI_MONITOR_ENABLED", True):
            return False
        thread = threading.Thread(
            target=run_wuzapi_monitor,
            daemon=True,
            name="wuzapi-connection-monitor",
        )
        thread.start()
        _monitor_started = True
        return True


def _reset_wuzapi_runtime_state_for_tests() -> None:
    global _status_cache, _status_cache_monotonic, _last_reconnect_monotonic, _monitor_started
    _status_cache = None
    _status_cache_monotonic = 0.0
    _last_reconnect_monotonic = 0.0
    _monitor_started = False


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
    """Detect explicit provider-level not-started/disconnected responses."""
    try:
        body = (resp.text or "")[:500].lower()
    except Exception:
        body = ""
    location = (resp.headers.get("Location") or "").lower()
    markers = (
        "errors/not-started",
        "session not started",
        "session is not started",
        "session disconnected",
        "session is disconnected",
        "not connected",
    )
    return any(marker in body or marker in location for marker in markers)


def _payload_reports_disconnected(payload: Any) -> bool:
    """Recognize only explicit provider disconnected/not-started errors."""
    for obj in _wuzapi_response_objects(payload):
        values = [obj.get(key) for key in (
            "error", "Error", "errors", "Errors", "message", "Message", "status", "Status"
        )]
        text = " ".join(str(value).lower() for value in values if value not in (None, ""))
        if any(marker in text for marker in (
            "errors/not-started", "session not started", "session is not started",
            "session disconnected", "session is disconnected", "not connected",
        )):
            return True
    return False


def _safe_response_excerpt(resp: requests.Response, max_chars: int = 200) -> str:
    """Return compact response text for logs."""
    try:
        body = (resp.text or "").replace("\n", " ").replace("\r", " ").strip()
    except Exception:
        body = ""
    if len(body) > max_chars:
        body = body[:max_chars]
    return body


def _wuzapi_response_objects(payload: Any) -> list[dict]:
    """Return the top-level and common nested WuzAPI response objects."""
    if not isinstance(payload, dict):
        return []

    objects = [payload]
    for key in ("data", "Data", "result", "Result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            objects.append(nested)
    return objects


def _wuzapi_send_ack(payload: Any) -> tuple[str, str, str]:
    """Classify a WuzAPI send response without trusting HTTP status alone.

    WuzAPI's normal send response contains delivery metadata such as Details,
    Timestamp, and Id. Some deployments wrap that response in ``data`` or
    expose an explicit ``success`` flag. A positive HTTP status with neither
    success marker nor send metadata is deliberately treated as unknown.
    """
    objects = _wuzapi_response_objects(payload)
    if not objects:
        return "unknown", "", "response bukan object JSON"

    error_values = []
    for obj in objects:
        for key in ("success", "Success", "ok", "Ok"):
            if key in obj and obj[key] is False:
                reason = obj.get("error") or obj.get("Error") or obj.get("message") or obj.get("Message")
                return "rejected", "", str(reason or "provider menyatakan gagal")[:200]
        for key in ("error", "Error", "errors", "Errors", "failure", "Failure"):
            value = obj.get(key)
            if value not in (None, "", False, [], {}):
                error_values.append(str(value)[:200])

    if error_values:
        return "rejected", "", error_values[0]

    for obj in objects:
        status = str(obj.get("status") or obj.get("Status") or "").strip().casefold()
        if status in {"error", "failed", "failure", "rejected", "not sent"}:
            return "rejected", "", status

    message_id = ""
    timestamp = ""
    details = ""
    explicit_success = False
    for obj in objects:
        if not message_id:
            message_id = str(obj.get("Id") or obj.get("id") or obj.get("ID") or "")
        if not timestamp:
            timestamp = str(obj.get("Timestamp") or obj.get("timestamp") or "")
        if not details:
            details = str(obj.get("Details") or obj.get("details") or "").strip()
        for key in ("success", "Success", "ok", "Ok"):
            if obj.get(key) is True:
                explicit_success = True

    detail_status = details.casefold()
    if explicit_success or detail_status in {"sent", "success", "successful", "ok", "accepted"}:
        return "sent", message_id, details or "success"
    if message_id or timestamp:
        return "sent", message_id, details or "metadata"

    return "unknown", "", "provider tidak mengembalikan acknowledgement pengiriman"


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

        phone = _normalize_recipient_phone(to)
        if not phone:
            secure_log("ERROR", "WuzAPI send failed: empty recipient")
            return None

        # Heal a known disconnected session before the first delivery attempt.
        ensure_wuzapi_connected()
        base = _normalize_base(WUZAPI_DOMAIN)
        session = get_wuzapi_session()
        payload: Dict[str, Any] = {
            "Phone": phone,
            "Body": body,
        }
        if mention_jid:
            payload["ContextInfo"] = {"MentionedJID": [mention_jid]}

        def post_once(url: str):
            endpoint_started = time.perf_counter()
            response = None
            error = ""
            try:
                response = session.post(url, json=payload, timeout=8, allow_redirects=False)
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
            finally:
                log_timing(
                    "wuzapi.send_text",
                    endpoint_started,
                    endpoint="chat/send/text",
                    status=getattr(response, "status_code", "error"),
                )
            return response, error

        endpoints = _build_wuzapi_endpoints(base, "chat/send/text")
        last_err = ""
        for url in endpoints:
            resp, request_error = post_once(url)
            if resp is None:
                last_err = request_error
                continue

            retried_after_reconnect = False
            while True:
                if 200 <= resp.status_code < 300:
                    try:
                        provider_payload = resp.json()
                    except Exception:
                        provider_payload = None

                    ack_state, message_id, ack_reason = _wuzapi_send_ack(provider_payload)
                    if ack_state == "sent":
                        secure_log(
                            "INFO",
                            "WuzAPI Send acknowledged "
                            f"endpoint={url.split('/')[-1]} status={resp.status_code} "
                            f"message_id={message_id[:80] or '-'} body_len={len(body or '')} "
                            f"ack={ack_reason}",
                        )
                        return provider_payload

                    last_err = (
                        f"{resp.status_code} on {url} provider_ack={ack_state}: {ack_reason}"
                    )
                    secure_log("WARNING", f"WuzAPI Send not acknowledged: {last_err}")
                    # Unknown 2xx responses may represent a delivered message.
                    # Never retry them, including after a successful reconnect.
                    if ack_state == "unknown":
                        secure_log("ERROR", f"WuzAPI: send outcome unknown; not retrying: {last_err}")
                        return None
                    if _payload_reports_disconnected(provider_payload) and not retried_after_reconnect:
                        secure_log("WARNING", "WuzAPI rejected send because the session is disconnected; attempting reconnect")
                        connected = ensure_wuzapi_connected(force=True)
                        if not connected.get("connected"):
                            return None
                        retried_after_reconnect = True
                        resp, request_error = post_once(url)
                        if resp is None:
                            secure_log("ERROR", f"WuzAPI reconnect retry outcome unknown: {request_error}")
                            return None
                        continue
                    if retried_after_reconnect:
                        secure_log("ERROR", f"WuzAPI: reconnect retry was rejected: {last_err}")
                        return None
                    break

                loc = resp.headers.get("Location", "")
                last_err = f"{resp.status_code} on {url} loc={loc}: {_safe_response_excerpt(resp)}"
                if _is_wuzapi_not_started(resp) and not retried_after_reconnect:
                    secure_log("WARNING", "WuzAPI session not started; attempting reconnect")
                    connected = ensure_wuzapi_connected(force=True)
                    if not connected.get("connected"):
                        secure_log("ERROR", f"WuzAPI reconnect failed before send retry: {last_err}")
                        return None
                    retried_after_reconnect = True
                    resp, request_error = post_once(url)
                    if resp is None:
                        secure_log(
                            "ERROR",
                            f"WuzAPI reconnect retry outcome unknown; not retrying: {request_error}",
                        )
                        return None
                    continue
                if resp.status_code in (401, 403):
                    secure_log("ERROR", f"WuzAPI Auth Error: {last_err}")
                    return None
                if retried_after_reconnect:
                    secure_log("ERROR", f"WuzAPI reconnect retry failed: {last_err}")
                    return None
                break

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
    if not media_url:
        return None
    parsed = urlsplit(str(media_url))
    provider = urlsplit(WUZAPI_DOMAIN)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname.lower().rstrip(".") != (provider.hostname or "").lower().rstrip(".")
    ):
        secure_log("WARNING", "WuzAPI media URL rejected: unexpected host or scheme")
        return None

    max_size = 10 * 1024 * 1024
    response = None
    temp_path = None
    completed = False
    try:
        session = get_wuzapi_session()
        response = session.get(media_url, stream=True, timeout=30, allow_redirects=False)
        
        if response.status_code == 200:
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_size:
                secure_log("WARNING", "WuzAPI media download rejected: file too large")
                return None
            content_type = response.headers.get('content-type', '')
            ext = mimetypes.guess_extension(content_type) or '.bin'
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                temp_path = tmp.name
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    downloaded += len(chunk)
                    if downloaded > max_size:
                        secure_log("WARNING", "WuzAPI media download rejected: file too large")
                        return None
                    tmp.write(chunk)
                completed = True
                return temp_path
        else:
            secure_log("ERROR", f"WuzAPI Media Download Failed: {response.status_code}")
            return None
    except Exception as e:
        secure_log("ERROR", f"WuzAPI Media Except: {str(e)}")
        return None
    finally:
        if response is not None:
            response.close()
        if temp_path and not completed:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


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
    
    response = None
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
                        img_bytes = base64.b64decode(image_data, validate=True)
                        if len(img_bytes) > 10 * 1024 * 1024:
                            secure_log("WARNING", "WuzAPI image rejected: file too large")
                            return None
                        
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
    finally:
        if response is not None:
            response.close()

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
            return None
        
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
