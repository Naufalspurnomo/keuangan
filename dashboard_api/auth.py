"""Invite-only session authentication for the private owner dashboard."""

from __future__ import annotations

import hashlib
import hmac
from functools import wraps
from typing import Any, Callable, TypeVar, cast

from flask import current_app, jsonify, request, session
from werkzeug.security import check_password_hash


F = TypeVar("F", bound=Callable[..., Any])
SESSION_USER_KEY = "dashboard_user"
SESSION_ROLE_KEY = "dashboard_role"


def authenticate_owner(email: str, password: str) -> bool:
    expected_email = str(current_app.config.get("DASHBOARD_OWNER_EMAIL") or "").strip().casefold()
    password_hash = str(current_app.config.get("DASHBOARD_OWNER_PASSWORD_HASH") or "").strip()
    supplied_email = str(email or "").strip().casefold()
    supplied_password = str(password or "")
    if not expected_email or not password_hash or supplied_email != expected_email:
        return False
    return check_password_hash(password_hash, supplied_password)


def establish_owner_session(email: str) -> None:
    session.clear()
    session[SESSION_USER_KEY] = str(email).strip().casefold()
    session[SESSION_ROLE_KEY] = "owner"
    session.permanent = True


def clear_owner_session() -> None:
    session.clear()


def _proxy_owner_authenticated() -> bool:
    expected_hash = str(current_app.config.get("DASHBOARD_PROXY_TOKEN_HASH") or "").strip().casefold()
    if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
        return False
    token = str(request.headers.get("X-Hollawall-Proxy-Token") or "").strip()
    if not token:
        return False
    supplied_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(supplied_hash, expected_hash)


def owner_identity() -> tuple[str, str] | None:
    if _proxy_owner_authenticated():
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
