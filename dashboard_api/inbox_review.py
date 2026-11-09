"""Owner-only review controls for unresolved durable inbox events.

Review is deliberately conservative: the release supports only terminal decisions
backed by a complete authoritative-ledger scan. Automatic retry is excluded because
split media/text events can map to one ledger source and cannot be retried safely
without group-level atomicity.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, request

from dashboard_api.auth import owner_identity, owner_required, write_csrf_valid
from services import durable_inbox
from services.durable_inbox import (
    InboxUnavailable,
    ReviewConflict,
    ReviewNotFound,
    ReviewValidationError,
)


LedgerLookup = Callable[[str], dict[str, Any]]
WritesEnabled = Callable[[], bool]
_ALLOWED_ACTIONS = frozenset({"ignore", "confirm_processed"})
_METADATA_FIELDS = (
    "event_key", "provider", "message_id", "event_type", "is_group",
    "finance_signal", "payload_score", "status", "result_status", "attempts",
    "received_at", "updated_at",
)
_DETAIL_FIELDS = _METADATA_FIELDS + ("body_text", "quoted_message_id")
_EVENT_KEY = re.compile(r"^[0-9a-f]{64}$")
_COMMAND_KEY = re.compile(r"^[^\s\x00-\x1f\x7f]{16,128}$")
_REVIEW_STATUS = re.compile(r"^needs_review(?:_[a-z0-9_]+)?$")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _writes_enabled() -> bool:
    return _truthy(os.getenv("INBOX_REVIEW_WRITES_ENABLED"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _default_ledger_lookup(message_id: str) -> dict[str, Any]:
    from sheets_helper import find_all_transactions_by_message_id_strict

    return find_all_transactions_by_message_id_strict(message_id)


def _review_detail(event: dict[str, Any]) -> dict[str, Any]:
    detail = {field: event.get(field) for field in _DETAIL_FIELDS}
    detail["media_available"] = bool(event.get("media_data") or event.get("media_path"))
    return detail


def create_inbox_review_blueprint(
    *,
    service: Any = durable_inbox,
    ledger_lookup: LedgerLookup = _default_ledger_lookup,
    writes_enabled: WritesEnabled = _writes_enabled,
) -> Blueprint:
    blueprint = Blueprint(
        "inbox_review_api",
        __name__,
        url_prefix="/api/dashboard/v1/inbox/reviews",
    )

    @blueprint.after_request
    def disable_caching(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        return response

    def error(code: str, message: str, status: int):
        response = jsonify({"error": {"code": code, "message": message}})
        response.status_code = status
        return response

    def valid_event_key(event_key: str):
        if not _EVENT_KEY.fullmatch(event_key):
            return error("invalid_event_key", "Review event identifier is invalid", 422)
        return None

    @blueprint.get("")
    @owner_required
    def list_reviews():
        try:
            items = service.list_review_events(limit=50)
        except Exception:
            return error("review_service_unavailable", "Review service temporarily unavailable", 503)
        metadata = [{field: item.get(field) for field in _METADATA_FIELDS} for item in items]
        return jsonify({
            "api_version": "dashboard.v1",
            "data": {
                "items": _json_safe(metadata),
                "writes_enabled": bool(writes_enabled()),
                "allowed_actions": sorted(_ALLOWED_ACTIONS) if writes_enabled() else [],
            },
        })

    @blueprint.get("/<event_key>")
    @owner_required
    def review_detail(event_key: str):
        invalid = valid_event_key(event_key)
        if invalid is not None:
            return invalid
        try:
            event = service.get_review_event(event_key)
        except Exception:
            return error("review_service_unavailable", "Review service temporarily unavailable", 503)
        if event is None:
            return error("review_not_found", "Review event not found", 404)
        return jsonify({"api_version": "dashboard.v1", "data": _json_safe(_review_detail(event))})

    @blueprint.post("/<event_key>/actions")
    @owner_required
    def resolve_review(event_key: str):
        invalid = valid_event_key(event_key)
        if invalid is not None:
            return invalid
        if not writes_enabled():
            return error("review_writes_disabled", "Review actions are disabled", 503)
        if not write_csrf_valid():
            return error("csrf_validation_failed", "CSRF validation failed", 403)
        if request.mimetype != "application/json":
            return error("json_required", "Content-Type must be application/json", 422)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return error("json_object_required", "Request body must be a JSON object", 422)
        allowed_fields = {"action", "reason", "expected_status"}
        if set(body) - allowed_fields:
            return error("unsupported_fields", "Request body contains unsupported fields", 422)

        action = body.get("action")
        reason = body.get("reason")
        expected_status = body.get("expected_status")
        command_key = request.headers.get("Idempotency-Key", "").strip()
        if not isinstance(action, str) or action not in _ALLOWED_ACTIONS:
            return error("invalid_review_action", "Unsupported review action", 422)
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
            return error("invalid_review_reason", "Review reason must be 1 to 1000 characters", 422)
        reason = reason.strip()
        if not isinstance(expected_status, str) or not _REVIEW_STATUS.fullmatch(expected_status):
            return error("invalid_expected_status", "Expected review status is invalid", 422)
        if not _COMMAND_KEY.fullmatch(command_key):
            return error("idempotency_key_required", "A valid Idempotency-Key is required", 422)

        identity = owner_identity()
        if identity is None:
            return error("authentication_required", "Sign in required", 401)
        try:
            replay = service.get_review_command_result(
                command_key,
                event_key=event_key,
                action=action,
                actor=identity[0],
                reason=reason,
                expected_status=expected_status,
            )
        except ReviewConflict:
            return error("review_conflict", "Review command conflicts with an earlier request", 409)
        except ReviewValidationError:
            return error("invalid_review_action", "Review action failed validation", 422)
        except InboxUnavailable:
            return error("review_service_unavailable", "Review service temporarily unavailable", 503)
        except Exception:
            return error("review_service_unavailable", "Review service temporarily unavailable", 503)
        if replay is not None:
            return jsonify({"api_version": "dashboard.v1", "data": _json_safe(replay)})

        try:
            event = service.get_review_event(event_key)
        except Exception:
            return error("review_service_unavailable", "Review service temporarily unavailable", 503)
        if event is None:
            return error("review_not_found", "Review event not found", 404)

        message_id = str(event.get("message_id") or "").strip()
        if not message_id:
            return error("ledger_proof_unavailable", "Review event has no message identifier", 409)
        try:
            proof = ledger_lookup(message_id)
        except Exception:
            return error("ledger_unavailable", "Authoritative ledger temporarily unavailable", 503)
        if not isinstance(proof, dict) or proof.get("status") != "complete":
            return error("ledger_proof_incomplete", "Authoritative ledger scan is incomplete", 503)
        matches = proof.get("matches")
        if not isinstance(matches, list):
            return error("ledger_proof_incomplete", "Authoritative ledger scan is incomplete", 503)
        if action == "ignore" and matches:
            return error("ledger_transaction_exists", "Ignore blocked because ledger rows exist", 409)
        if action == "confirm_processed" and not matches:
            return error("ledger_transaction_not_found", "Processed confirmation requires ledger proof", 409)

        try:
            result = service.resolve_review_event(
                event_key,
                action,
                actor=identity[0],
                reason=reason,
                expected_status=expected_status,
                command_key=command_key,
                ledger_proof=proof,
            )
        except ReviewNotFound:
            return error("review_not_found", "Review event not found", 404)
        except ReviewConflict:
            return error("review_conflict", "Review event changed concurrently", 409)
        except ReviewValidationError:
            return error("invalid_review_action", "Review action failed validation", 422)
        except InboxUnavailable:
            return error("review_service_unavailable", "Review service temporarily unavailable", 503)
        except Exception:
            return error("review_service_unavailable", "Review service temporarily unavailable", 503)
        return jsonify({"api_version": "dashboard.v1", "data": _json_safe(result)})

    return blueprint


__all__ = ["create_inbox_review_blueprint"]
