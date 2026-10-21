"""Invite-only session authentication for the private owner dashboard."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from flask import current_app, jsonify, session
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


def owner_required(function: F) -> F:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any):
        if not session.get(SESSION_USER_KEY):
            return jsonify({"error": {"code": "authentication_required", "message": "Sign in required"}}), 401
        if session.get(SESSION_ROLE_KEY) != "owner":
            return jsonify({"error": {"code": "owner_role_required", "message": "Owner access required"}}), 403
        return function(*args, **kwargs)

    return cast(F, wrapped)
