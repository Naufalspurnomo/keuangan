"""Authenticated canonical transaction HTTP boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from flask import Blueprint, Response, jsonify, request

from dashboard_api.auth import actor_identity, owner_required
from services.canonical_finance import (
    FinanceConflict,
    FinanceNotFound,
    FinanceValidationError,
)


def _error(code: str, message: str, status: int):
    response = jsonify({"error": {"code": code, "message": message}})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _body() -> dict[str, Any] | Response:
    if request.mimetype != "application/json":
        return _error("json_required", "Content-Type must be application/json", 422)
    try:
        value = json.loads(request.get_data(cache=True).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("invalid_json", "Request body must be valid JSON", 422)
    if not isinstance(value, dict):
        return _error("json_object_required", "Request body must be a JSON object", 422)
    return value


def _mutation_context(body: dict[str, Any], *, roles: frozenset[str]):
    identity = actor_identity()
    if identity is None:
        return None, _error(
            "actor_assertion_required", "A valid signed actor assertion is required", 401
        )
    if identity["role"] not in roles:
        return None, _error("actor_role_forbidden", "Actor role cannot perform this action", 403)
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, _error("idempotency_key_required", "Idempotency-Key is required", 422)
    if body.get("idempotency_key") != key:
        return None, _error(
            "idempotency_key_mismatch",
            "Idempotency-Key header must match the request body",
            422,
        )
    return identity, None


def _run(operation: Callable[[], Any], *, created: bool = True):
    try:
        result = operation()
    except FinanceValidationError:
        return _error("invalid_finance_command", "Finance command is invalid", 422)
    except FinanceConflict:
        return _error("finance_conflict", "Finance command conflicts with current state", 409)
    except FinanceNotFound:
        return _error("finance_not_found", "Financial transaction was not found", 404)
    except Exception:
        return _error("finance_unavailable", "Finance service temporarily unavailable", 503)
    response = jsonify({"api_version": "finance.v1", "data": result})
    response.status_code = 201 if created and not result.get("duplicate", False) else 200
    response.headers["Cache-Control"] = "no-store"
    return response


def create_canonical_finance_blueprint(service: Any) -> Blueprint:
    blueprint = Blueprint(
        "canonical_finance_api", __name__, url_prefix="/api/dashboard/v1/canonical-transactions"
    )

    @blueprint.post("")
    def create_transaction():
        body = _body()
        if isinstance(body, Response):
            return body
        identity, error = _mutation_context(body, roles=frozenset({"boss", "admin"}))
        if error is not None:
            return error
        return _run(lambda: service.create_transaction(body, actor=identity))

    @blueprint.post("/<transaction_id>/corrections")
    def correct_transaction(transaction_id: str):
        body = _body()
        if isinstance(body, Response):
            return body
        identity, error = _mutation_context(body, roles=frozenset({"boss", "admin"}))
        if error is not None:
            return error
        return _run(lambda: service.correct_transaction(transaction_id, body, actor=identity))

    @blueprint.post("/<transaction_id>/reversals")
    def reverse_transaction(transaction_id: str):
        body = _body()
        if isinstance(body, Response):
            return body
        identity, error = _mutation_context(body, roles=frozenset({"boss"}))
        if error is not None:
            return error
        return _run(lambda: service.reverse_transaction(transaction_id, body, actor=identity))

    @blueprint.get("")
    @owner_required
    def list_transactions():
        return _run(lambda: {"items": service.list_effective_transactions()}, created=False)

    @blueprint.get("/<transaction_id>")
    @owner_required
    def get_transaction(transaction_id: str):
        return _run(lambda: service.get_transaction(transaction_id), created=False)

    return blueprint
