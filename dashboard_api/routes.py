"""Versioned private finance dashboard routes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, make_response, request

from dashboard_api.auth import (
    authenticate_owner,
    clear_owner_session,
    establish_owner_session,
    owner_identity,
    owner_required,
    write_csrf_valid,
)
from dashboard_api import live_source
from dashboard_api.contracts import DashboardContractError, parse_filters
from dashboard_api.service import build_overview
from dashboard_api.write_contracts import TransactionValidationError
from services.dashboard_transaction_service import (
    DashboardTransactionConflict,
    DashboardTransactionService,
    DashboardTransactionUnavailable,
)
from services.dashboard_write_requests import (
    DashboardWriteRequestConflict,
    DashboardWriteRequestUnavailable,
)


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


def create_dashboard_blueprint(
    repository: Any,
    *,
    transaction_service: Any | None = None,
) -> Blueprint:
    blueprint = Blueprint("dashboard_api", __name__, url_prefix="/api/dashboard/v1")

    def write_error(code: str, message: str, status: int):
        response = jsonify({"error": {"code": code, "message": message}})
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    def selected_transaction_service():
        if transaction_service is not None:
            return transaction_service
        projects = frozenset(
            str(project)
            for project in repository.fetch_filter_options().get("projects", ())
        )
        return DashboardTransactionService(project_exists=projects.__contains__)

    @blueprint.after_request
    def prevent_transaction_write_caching(response: Response):
        if request.method == "POST" and request.path == "/api/dashboard/v1/transactions":
            response.headers["Cache-Control"] = "no-store"
        return response

    @blueprint.post("/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email") or "")
        password = str(body.get("password") or "")
        if not authenticate_owner(email, password):
            return jsonify({"error": {"code": "invalid_credentials", "message": "Invalid email or password"}}), 401
        csrf_token = establish_owner_session(email)
        return jsonify(
            {
                "api_version": API_VERSION,
                "data": {
                    "email": email.casefold(),
                    "role": "owner",
                    "csrf_token": csrf_token,
                },
            }
        )

    @blueprint.post("/auth/logout")
    def logout():
        clear_owner_session()
        return jsonify({"api_version": API_VERSION, "data": {"signed_out": True}})

    @blueprint.get("/auth/me")
    @owner_required
    def me():
        email, role = owner_identity() or ("", "")
        return jsonify(
            {
                "api_version": API_VERSION,
                "data": {"email": email, "role": role},
            }
        )

    @blueprint.post("/transactions")
    @owner_required
    def create_transaction():
        if not current_app.config.get("DASHBOARD_TRANSACTION_WRITES_ENABLED", False):
            return write_error(
                "transaction_writes_disabled",
                "Transaction writes are disabled",
                503,
            )
        if not write_csrf_valid():
            return write_error(
                "csrf_validation_failed",
                "CSRF validation failed",
                403,
            )
        if request.mimetype != "application/json":
            return write_error("json_required", "Content-Type must be application/json", 422)
        try:
            raw_body = request.get_data(cache=True).decode("utf-8")
            body = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return write_error("invalid_json", "Request body must be valid JSON", 422)
        if not isinstance(body, dict):
            return write_error("json_object_required", "Request body must be a JSON object", 422)

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return write_error(
                "idempotency_key_required",
                "Idempotency-Key header is required",
                422,
            )
        if body.get("idempotency_key") != idempotency_key:
            return write_error(
                "idempotency_key_mismatch",
                "Idempotency-Key header must match the request body",
                422,
            )

        identity = owner_identity()
        if identity is None:
            return write_error("authentication_required", "Sign in required", 401)
        message_id = "dashboard-api:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        try:
            result = selected_transaction_service().record(
                body,
                actor={"email": identity[0], "role": identity[1]},
                message_id=message_id,
            )
        except TransactionValidationError:
            return write_error(
                "invalid_transaction",
                "Transaction request is invalid",
                422,
            )
        except (DashboardWriteRequestConflict, DashboardTransactionConflict):
            return write_error(
                "transaction_conflict",
                "Transaction conflicts with an existing request",
                409,
            )
        except (DashboardWriteRequestUnavailable, DashboardTransactionUnavailable, Exception):
            return write_error(
                "transaction_unavailable",
                "Transaction service temporarily unavailable",
                503,
            )

        response = jsonify({"api_version": API_VERSION, "data": _json_safe(result)})
        response.status_code = 201
        response.headers["Cache-Control"] = "no-store"
        return response

    @blueprint.get("/snapshot")
    @owner_required
    def snapshot():
        try:
            payload = live_source.load_live_snapshot()
        except Exception:
            return jsonify(
                {"error": {"code": "source_unavailable", "message": "Dashboard source temporarily unavailable"}}
            ), 503
        return _respond(payload)

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
