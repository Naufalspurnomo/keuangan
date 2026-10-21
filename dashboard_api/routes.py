"""Versioned, GET-only finance dashboard routes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, make_response, request, session

from dashboard_api.auth import (
    SESSION_ROLE_KEY,
    SESSION_USER_KEY,
    authenticate_owner,
    clear_owner_session,
    establish_owner_session,
    owner_required,
)
from dashboard_api.contracts import DashboardContractError, parse_filters
from dashboard_api.service import build_overview


API_VERSION = "dashboard.v1"
LAUNCH_VIEWS = {
    "overview",
    "cashflow",
    "wallets",
    "transactions",
    "projects",
    "internal-debts",
    "reports",
    "options",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _freshness_state(last_updated_at: str | None, now: datetime) -> str:
    if not last_updated_at:
        return "unknown"
    try:
        value = datetime.fromisoformat(last_updated_at)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - value.astimezone(timezone.utc)).total_seconds())
    except ValueError:
        return "unknown"
    if age <= 300:
        return "fresh"
    if age <= 1800:
        return "delayed"
    return "stale"


def _without_volatile_timestamps(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile_timestamps(item)
            for key, item in value.items()
            if key != "as_of"
        }
    if isinstance(value, list):
        return [_without_volatile_timestamps(item) for item in value]
    return value


def _make_etag(payload: dict[str, Any]) -> str:
    stable = _without_volatile_timestamps(payload)
    encoded = json.dumps(_json_safe(stable), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _respond(payload: dict[str, Any], status: int = 200) -> Response:
    etag = _make_etag(payload)
    if request.if_none_match.contains(etag):
        response = make_response("", 304)
        response.set_etag(etag)
        return response
    response = jsonify(_json_safe(payload))
    response.status_code = status
    response.set_etag(etag)
    response.headers["Cache-Control"] = "private, no-cache, must-revalidate"
    return response


def _parse_request_filters(repository: Any):
    options = repository.fetch_filter_options()
    return parse_filters(
        request.args,
        allowed_projects=options.get("projects", ()),
    )


def _envelope(data: Any, filters: Any, repository: Any, *, completeness: int | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    source = repository.fetch_freshness()
    if completeness is None:
        total = int(source.get("row_count") or 0)
        invalid = int(source.get("invalid_count") or 0)
        completeness = round(((total - invalid) / total) * 100) if total else 0
    return {
        "api_version": API_VERSION,
        "data": _json_safe(data),
        "meta": {
            "as_of": now.isoformat(),
            "freshness": _freshness_state(source.get("last_updated_at"), now),
            "data_completeness": completeness,
            "filters": filters.to_query() if filters is not None else {},
            "source": {
                "last_updated_at": source.get("last_updated_at"),
                "row_count": int(source.get("row_count") or 0),
                "invalid_count": int(source.get("invalid_count") or 0),
            },
        },
    }


def create_dashboard_blueprint(repository: Any) -> Blueprint:
    blueprint = Blueprint("dashboard_api", __name__, url_prefix="/api/dashboard/v1")

    @blueprint.post("/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email") or "")
        password = str(body.get("password") or "")
        if not authenticate_owner(email, password):
            return jsonify({"error": {"code": "invalid_credentials", "message": "Invalid email or password"}}), 401
        establish_owner_session(email)
        return jsonify({"api_version": API_VERSION, "data": {"email": email.casefold(), "role": "owner"}})

    @blueprint.post("/auth/logout")
    def logout():
        clear_owner_session()
        return jsonify({"api_version": API_VERSION, "data": {"signed_out": True}})

    @blueprint.get("/auth/me")
    @owner_required
    def me():
        return jsonify(
            {
                "api_version": API_VERSION,
                "data": {"email": session[SESSION_USER_KEY], "role": session[SESSION_ROLE_KEY]},
            }
        )

    @blueprint.get("/<view>")
    @owner_required
    def read_view(view: str):
        if view not in LAUNCH_VIEWS:
            return jsonify({"error": {"code": "not_found", "message": "Dashboard resource not found"}}), 404
        try:
            filters = _parse_request_filters(repository)
        except DashboardContractError as exc:
            return jsonify({"error": {"code": "invalid_filter", "message": str(exc)}}), 400

        if view == "options":
            return _respond(_envelope(repository.fetch_filter_options(), filters, repository))

        rows = repository.fetch_metric_rows(filters)
        overview = build_overview(rows, filters, datetime.now(timezone.utc))
        completeness = int(overview["metrics"]["data_completeness"])

        if view == "overview":
            data: Any = overview
        elif view == "transactions":
            page = repository.fetch_transactions(
                filters,
                limit=request.args.get("limit", 50, type=int),
                cursor=request.args.get("cursor"),
            )
            data = {"items": page.items, "next_cursor": page.next_cursor}
        elif view == "cashflow":
            data = {"metrics": overview["metrics"], "transactions": rows}
        elif view == "wallets":
            data = {"items": rows, "metrics": overview["metrics"]}
        elif view == "projects":
            data = {"items": rows, "metric_label": "Kontribusi tercatat"}
        elif view == "internal-debts":
            data = {
                "items": [
                    row for row in rows
                    if str(row.get("source_block") or "").casefold() in {"hutang", "debt"}
                ],
                "open_balance": overview["metrics"]["open_internal_debt"],
            }
        else:
            data = {
                "available": [
                    "cash-position",
                    "cash-movement",
                    "wallet-balances",
                    "project-contribution",
                    "internal-debt",
                ]
            }
        return _respond(_envelope(data, filters, repository, completeness=completeness))

    @blueprint.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify({"error": {"code": "method_not_allowed", "message": "Read-only dashboard"}}), 405

    return blueprint
