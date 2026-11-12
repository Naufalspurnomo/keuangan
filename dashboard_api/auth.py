"""Invite-only session authentication for the private owner dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from functools import wraps
from typing import Any, Callable, Mapping, TypeVar, cast

from flask import current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash


F = TypeVar("F", bound=Callable[..., Any])

# Transitional verifier for the existing owner-scoped Rumahweb proxy token.
# Only its SHA-256 digest is compiled; the token remains outside source control.
# Remove after the Koyeb environment verifier is reconciled.
_PRODUCTION_PROXY_COMPATIBILITY_HASHES = frozenset(
    {"4e27151b079d42b5347a988f0a4c24280bd38af3ff23f971a47e4e6a890cc26c"}
)
SESSION_USER_KEY = "dashboard_user"
SESSION_ROLE_KEY = "dashboard_role"
SESSION_CSRF_KEY = "dashboard_csrf_token"
ACTOR_ASSERTION_HEADER = "X-Hollawall-Actor-Assertion"
ACTOR_ROLES = frozenset({"boss", "admin"})
_NONCE_LOCK = threading.Lock()
_SEEN_NONCES: dict[str, int] = {}


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not value or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in value):
        raise ValueError("invalid base64url alphabet")
    if len(value) % 4 == 1:
        raise ValueError("invalid base64url length")
    decoded = base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical base64url encoding")
    return decoded


def build_upstream_actor_assertion(claims: Mapping[str, Any], secret: str) -> str:
    """Sign a deterministic short-lived upstream actor assertion.

    This helper is shared with the trusted reverse proxy integration tests. The
    signing secret is never defaulted or compiled into application code.
    """

    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise ValueError("actor assertion secret must contain at least 32 bytes")
    payload = json.dumps(
        dict(claims), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def _consume_nonce(nonce: str, expires_at: int, now: int) -> bool:
    with _NONCE_LOCK:
        expired = [value for value, expiry in _SEEN_NONCES.items() if expiry < now]
        for value in expired:
            _SEEN_NONCES.pop(value, None)
        if nonce in _SEEN_NONCES:
            return False
        _SEEN_NONCES[nonce] = expires_at
        return True


def verify_upstream_actor_assertion(*, consume_nonce: bool = False) -> dict[str, str] | None:
    """Verify actor, audience, lifetime, request binding, and optional replay nonce."""

    secret = str(current_app.config.get("DASHBOARD_ACTOR_ASSERTION_SECRET") or "")
    audience = str(current_app.config.get("DASHBOARD_ACTOR_ASSERTION_AUDIENCE") or "")
    if len(secret.encode("utf-8")) < 32 or not audience:
        return None
    raw = str(request.headers.get(ACTOR_ASSERTION_HEADER) or "").strip()
    try:
        encoded, signature = raw.split(".", 1)
        expected = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64decode(signature), expected):
            return None
        claims = json.loads(_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(claims, dict):
        return None

    now = int(time.time())
    ttl = int(current_app.config.get("DASHBOARD_ACTOR_ASSERTION_TTL_SECONDS") or 60)
    try:
        issued_at = int(claims["iat"])
        expires_at = int(claims["exp"])
    except (KeyError, TypeError, ValueError):
        return None
    if ttl < 1 or issued_at > now + 5 or expires_at < now or expires_at - issued_at > ttl:
        return None
    if claims.get("aud") != audience:
        return None
    if claims.get("method") != request.method:
        return None
    if claims.get("path") != request.path:
        return None
    body_hash = hashlib.sha256(request.get_data(cache=True)).hexdigest()
    if claims.get("body_sha256") != body_hash:
        return None

    actor_id = claims.get("actor_id")
    email = claims.get("email")
    role = claims.get("role")
    nonce = claims.get("nonce")
    if (
        not isinstance(actor_id, str)
        or not actor_id.strip()
        or not isinstance(email, str)
        or not email.strip()
        or role not in ACTOR_ROLES
        or not isinstance(nonce, str)
        or len(nonce) < 16
    ):
        return None
    if consume_nonce and not _consume_nonce(nonce, expires_at, now):
        return None
    return {
        "id": actor_id.strip(),
        "email": email.strip().casefold(),
        "role": role,
        "channel": "dashboard-proxy",
    }


def actor_identity() -> dict[str, str] | None:
    """Return the authenticated real mutation actor; never synthesize one."""

    cached = getattr(g, "dashboard_actor_identity", None)
    if isinstance(cached, dict):
        return dict(cached)
    identity = verify_upstream_actor_assertion(consume_nonce=True)
    if identity is not None:
        g.dashboard_actor_identity = identity
        return dict(identity)
    if current_app.config.get("DASHBOARD_ACTOR_ASSERTION_REQUIRED", False):
        return None
    session_identity = owner_identity()
    if session_identity is None:
        return None
    email, role = session_identity
    return {"id": email, "email": email, "role": role, "channel": "direct-session"}


def authenticate_owner(email: str, password: str) -> bool:
    expected_email = str(current_app.config.get("DASHBOARD_OWNER_EMAIL") or "").strip().casefold()
    password_hash = str(current_app.config.get("DASHBOARD_OWNER_PASSWORD_HASH") or "").strip()
    supplied_email = str(email or "").strip().casefold()
    supplied_password = str(password or "")
    if not expected_email or not password_hash or supplied_email != expected_email:
        return False
    return check_password_hash(password_hash, supplied_password)


def establish_owner_session(email: str) -> str:
    session.clear()
    session[SESSION_USER_KEY] = str(email).strip().casefold()
    session[SESSION_ROLE_KEY] = "owner"
    csrf_token = secrets.token_urlsafe(32)
    session[SESSION_CSRF_KEY] = csrf_token
    session.permanent = True
    return csrf_token


def clear_owner_session() -> None:
    session.clear()


def proxy_owner_authenticated() -> bool:
    expected_hash = str(current_app.config.get("DASHBOARD_PROXY_TOKEN_HASH") or "").strip().casefold()
    expected_hashes = set(_PRODUCTION_PROXY_COMPATIBILITY_HASHES)
    if len(expected_hash) == 64 and not any(
        character not in "0123456789abcdef" for character in expected_hash
    ):
        expected_hashes.add(expected_hash)
    token = str(request.headers.get("X-Hollawall-Proxy-Token") or "").strip()
    if not token:
        return False
    supplied_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return any(
        hmac.compare_digest(supplied_hash, candidate)
        for candidate in expected_hashes
    )


def write_csrf_valid() -> bool:
    """Accept trusted proxy writes or verify the direct browser session token."""

    if proxy_owner_authenticated():
        return True
    expected = session.get(SESSION_CSRF_KEY)
    supplied = request.headers.get("X-CSRF-Token")
    if not isinstance(expected, str) or not expected or not supplied:
        return False
    return hmac.compare_digest(expected, str(supplied))


def owner_identity() -> tuple[str, str] | None:
    if proxy_owner_authenticated():
        email = str(current_app.config.get("DASHBOARD_OWNER_EMAIL") or "owner@proxy.local").strip().casefold()
        return email, "owner"
    email = session.get(SESSION_USER_KEY)
    role = session.get(SESSION_ROLE_KEY)
    if email and role:
        return str(email), str(role)
    return None


def owner_required(function: F) -> F:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any):
        identity = owner_identity()
        if identity is None:
            return jsonify({"error": {"code": "authentication_required", "message": "Sign in required"}}), 401
        if identity[1] != "owner":
            return jsonify({"error": {"code": "owner_role_required", "message": "Owner access required"}}), 403
        return function(*args, **kwargs)

    return cast(F, wrapped)
