"""Owner-only project and commercial-document API routes.

The routes expose PostgreSQL project/document state without changing the Google
Sheets cash authority. Every mutation is feature-gated, CSRF protected,
idempotent, and optimistic-lock guarded. Reads remain available while writes
are disabled.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from flask import Blueprint, Response, current_app, jsonify, make_response, request

from dashboard_api.auth import owner_identity, owner_required, write_csrf_valid
from services.project_document_models import DocumentCalculationError
from services.project_document_repository import (
    ProjectDocumentConflict,
    ProjectDocumentNotFound,
    ProjectDocumentUnavailable,
)
from services.project_documents import ProjectDocumentService


API_VERSION = "dashboard.v1"
MAX_JSON_BODY_BYTES = 256 * 1024
MAX_JSON_DEPTH = 32
_IDEMPOTENCY_KEY = re.compile(r"^[^\s\x00-\x1f\x7f]{16,128}$")
_CONTENT_TYPE = re.compile(r"^application/json(?:\s*;\s*charset=utf-8)?$", re.IGNORECASE)
_QUOTED_VERSION = re.compile(r'^"(0|[1-9][0-9]*)"$')
PROJECT_STATUSES = frozenset({"planned", "active", "completed", "cancelled"})


class RequestContractError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code = code
        self.public_message = message
        self.status = status
        super().__init__(message)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _capabilities() -> dict[str, bool]:
    return {
        "reads_enabled": True,
        "project_document_writes_enabled": bool(
            current_app.config.get("PROJECT_DOCUMENT_WRITES_ENABLED", False)
        ),
        # The shared service does not safely mutate authoritative Sheets cash.
        "transaction_correction_reversal": False,
        "hard_delete": False,
    }


def _envelope(data: Any) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "data": _json_safe(data),
        "meta": {"capabilities": _capabilities()},
    }


def _response(data: Any, status: int = 200) -> Response:
    response = jsonify(_envelope(data))
    response.status_code = status
    response.headers["Cache-Control"] = "no-store, private"
    return response


def _error(code: str, message: str, status: int) -> Response:
    response = jsonify({"error": {"code": code, "message": message}})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store, private"
    return response


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestContractError("duplicate_json_key", "Request body contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise RequestContractError("invalid_json", "Request body must contain strict JSON")


def _check_depth(value: Any, depth: int = 1) -> None:
    if depth > MAX_JSON_DEPTH:
        raise RequestContractError("json_too_deep", "Request body is too deeply nested")
    if isinstance(value, dict):
        for item in value.values():
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)


def _strict_json(*, allowed_fields: frozenset[str]) -> dict[str, Any]:
    content_type = str(request.headers.get("Content-Type") or "").strip()
    if not _CONTENT_TYPE.fullmatch(content_type):
        raise RequestContractError(
            "json_required", "Content-Type must be application/json with optional UTF-8 charset", 415
        )
    content_length = request.content_length
    if content_length is not None and content_length > MAX_JSON_BODY_BYTES:
        raise RequestContractError("request_too_large", "Request body is too large", 413)
    raw = request.get_data(cache=False, as_text=False)
    if not raw:
        raise RequestContractError("json_object_required", "Request body must be a JSON object")
    if len(raw) > MAX_JSON_BODY_BYTES:
        raise RequestContractError("request_too_large", "Request body is too large", 413)
    try:
        text = raw.decode("utf-8", errors="strict")
        body = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except RequestContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestContractError("invalid_json", "Request body must contain valid UTF-8 JSON") from exc
    if not isinstance(body, dict):
        raise RequestContractError("json_object_required", "Request body must be a JSON object")
    _check_depth(body)
    unknown = set(body) - allowed_fields
    if unknown:
        raise RequestContractError("unsupported_fields", "Request body contains unsupported fields")
    return body


def _idempotency_key(body: Mapping[str, Any]) -> str:
    header = str(request.headers.get("Idempotency-Key") or "")
    if not header:
        raise RequestContractError(
            "idempotency_key_required", "Idempotency-Key header is required"
        )
    if not _IDEMPOTENCY_KEY.fullmatch(header):
        raise RequestContractError("invalid_idempotency_key", "Idempotency-Key header is invalid")
    value = body.get("idempotency_key")
    if not isinstance(value, str) or value != header:
        raise RequestContractError(
            "idempotency_key_mismatch", "Idempotency-Key header must match the request body"
        )
    return header


def _expected_version(body: Mapping[str, Any], *, create: bool = False) -> int | None:
    supplied = str(request.headers.get("If-Match") or "").strip()
    if not supplied:
        raise RequestContractError("if_match_required", "If-Match header is required", 428)
    if create:
        if supplied != "*":
            raise RequestContractError(
                "if_match_failed", "If-Match must be * when creating a resource", 412
            )
        return None
    match = _QUOTED_VERSION.fullmatch(supplied)
    if match is None:
        raise RequestContractError(
            "invalid_if_match", "If-Match must be a quoted lock version", 422
        )
    expected = body.get("expected_version")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise RequestContractError(
            "expected_version_required", "A non-negative integer expected_version is required"
        )
    header_version = int(match.group(1))
    if header_version != expected:
        raise RequestContractError(
            "if_match_failed", "If-Match must match expected_version", 412
        )
    return expected


def _actor() -> dict[str, str]:
    identity = owner_identity()
    if identity is None or identity[1] != "owner":
        raise RequestContractError("owner_required", "Owner access required", 403)
    return {"email": identity[0], "role": identity[1]}


def _write_request(
    *, allowed_fields: frozenset[str], create: bool = False
) -> tuple[dict[str, Any], str, int | None, dict[str, str]]:
    if not current_app.config.get("PROJECT_DOCUMENT_WRITES_ENABLED", False):
        raise RequestContractError(
            "project_document_writes_disabled", "Project and document writes are disabled", 503
        )
    if not write_csrf_valid():
        raise RequestContractError("csrf_validation_failed", "CSRF validation failed", 403)
    body = _strict_json(allowed_fields=allowed_fields)
    key = _idempotency_key(body)
    version = _expected_version(body, create=create)
    return body, key, version, _actor()


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RequestContractError("invalid_project_document_request", f"{field} must be an object")
    return value


def _service(repository: Any) -> ProjectDocumentService:
    return ProjectDocumentService(repository)


def create_project_document_blueprint(repository: Any) -> Blueprint:
    blueprint = Blueprint(
        "project_document_api", __name__, url_prefix="/api/dashboard/v1"
    )

    @blueprint.after_request
    def no_store(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @blueprint.get("/project-documents/capabilities")
    @owner_required
    def capabilities():
        return _response(_capabilities())

    @blueprint.get("/projects")
    @owner_required
    def list_projects():
        return _response({"items": repository.list_projects()})

    @blueprint.get("/projects/<uuid:project_id>")
    @owner_required
    def get_project(project_id: UUID):
        return _response(repository.get_project(str(project_id)))

    @blueprint.post("/projects")
    @owner_required
    def create_project():
        body, key, _version, actor = _write_request(
            allowed_fields=frozenset({"idempotency_key", "values"}), create=True
        )
        values = _mapping(body.get("values"), field="values")
        result = _service(repository).create_project(
            values, idempotency_key=key, actor=actor
        )
        return _response(result, 201)

    @blueprint.patch("/projects/<uuid:project_id>")
    @owner_required
    def update_project(project_id: UUID):
        body, key, version, actor = _write_request(
            allowed_fields=frozenset(
                {"idempotency_key", "expected_version", "changes"}
            )
        )
        changes = _mapping(body.get("changes"), field="changes")
        result = repository.update_project(
            str(project_id),
            changes,
            expected_version=version,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result)

    @blueprint.post("/projects/<uuid:project_id>/status")
    @owner_required
    def update_project_status(project_id: UUID):
        body, key, version, actor = _write_request(
            allowed_fields=frozenset(
                {"idempotency_key", "expected_version", "status"}
            )
        )
        status = str(body.get("status") or "")
        if status not in PROJECT_STATUSES:
            raise RequestContractError(
                "invalid_project_document_request", "Unsupported project status"
            )
        result = repository.update_project(
            str(project_id),
            {"status": status},
            expected_version=version,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result)

    @blueprint.post("/projects/<uuid:project_id>/archive")
    @owner_required
    def archive_project(project_id: UUID):
        body, key, version, actor = _write_request(
            allowed_fields=frozenset({"idempotency_key", "expected_version"})
        )
        # The persisted soft-terminal state is `cancelled`; hard deletion is forbidden.
        result = repository.update_project(
            str(project_id),
            {"status": "cancelled"},
            expected_version=version,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result)

    @blueprint.get("/projects/<uuid:project_id>/audit")
    @owner_required
    def project_audit(project_id: UUID):
        events = _service(repository).replay_audit(project_id=str(project_id))
        return _response({"items": events})

    @blueprint.get("/projects/<uuid:project_id>/documents")
    @owner_required
    def list_documents(project_id: UUID):
        return _response({"items": repository.list_documents(str(project_id))})

    @blueprint.get("/documents/<uuid:document_id>")
    @owner_required
    def get_document(document_id: UUID):
        return _response(repository.get_document(str(document_id)))

    @blueprint.post("/projects/<uuid:project_id>/documents/invoices")
    @owner_required
    def create_invoice(project_id: UUID):
        body, key, _version, actor = _write_request(
            allowed_fields=frozenset(
                {"idempotency_key", "kind", "values"}
            ),
            create=True,
        )
        values = _mapping(body.get("values"), field="values")
        result = _service(repository).create_invoice(
            str(project_id),
            kind=str(body.get("kind") or ""),
            values=values,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result, 201)

    @blueprint.post("/projects/<uuid:project_id>/documents/receipts")
    @owner_required
    def create_receipt(project_id: UUID):
        body, key, _version, actor = _write_request(
            allowed_fields=frozenset(
                {"idempotency_key", "allocations", "values"}
            ),
            create=True,
        )
        allocations = body.get("allocations")
        if not isinstance(allocations, list):
            raise RequestContractError(
                "invalid_project_document_request", "allocations must be an array"
            )
        values = _mapping(body.get("values"), field="values")
        result = _service(repository).create_receipt(
            str(project_id),
            allocations=allocations,
            values=values,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result, 201)

    @blueprint.patch("/documents/<uuid:document_id>")
    @owner_required
    def update_document(document_id: UUID):
        body, key, version, actor = _write_request(
            allowed_fields=frozenset(
                {"idempotency_key", "expected_version", "changes"}
            )
        )
        changes = _mapping(body.get("changes"), field="changes")
        result = _service(repository).update_draft(
            str(document_id),
            changes,
            expected_version=version,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result)

    @blueprint.post("/documents/<uuid:document_id>/issue")
    @owner_required
    def issue_document(document_id: UUID):
        body, key, version, actor = _write_request(
            allowed_fields=frozenset({"idempotency_key", "expected_version"})
        )
        result = _service(repository).issue_document(
            str(document_id),
            expected_version=version,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result)

    @blueprint.post("/documents/<uuid:document_id>/void")
    @owner_required
    def void_document(document_id: UUID):
        body, key, version, actor = _write_request(
            allowed_fields=frozenset(
                {"idempotency_key", "expected_version", "reason"}
            )
        )
        result = _service(repository).void_document(
            str(document_id),
            reason=str(body.get("reason") or ""),
            expected_version=version,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result)

    @blueprint.post("/documents/<uuid:document_id>/revise")
    @owner_required
    def revise_document(document_id: UUID):
        body, key, version, actor = _write_request(
            allowed_fields=frozenset({"idempotency_key", "expected_version"})
        )
        result = _service(repository).revise_document(
            str(document_id),
            expected_version=version,
            idempotency_key=key,
            actor=actor,
        )
        return _response(result, 201)

    @blueprint.get("/documents/<uuid:document_id>/audit")
    @owner_required
    def document_audit(document_id: UUID):
        events = _service(repository).replay_audit(document_id=str(document_id))
        return _response({"items": events})

    @blueprint.get("/documents/<uuid:document_id>/download")
    @owner_required
    def download_document(document_id: UUID):
        artifact = repository.get_artifact(str(document_id))
        pdf = artifact.get("bytes")
        expected_size = artifact.get("byte_size")
        expected_hash = str(artifact.get("sha256") or "")
        if (
            not isinstance(pdf, bytes)
            or not pdf.startswith(b"%PDF-")
            or isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or len(pdf) != expected_size
            or len(expected_hash) != 64
            or hashlib.sha256(pdf).hexdigest() != expected_hash.casefold()
        ):
            raise ProjectDocumentUnavailable("persisted PDF integrity validation failed")
        response = make_response(pdf)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Length"] = str(len(pdf))
        response.headers["Content-Disposition"] = (
            f'attachment; filename="hollawall-document-{document_id}.pdf"'
        )
        response.headers["X-Content-SHA256"] = expected_hash.casefold()
        return response

    @blueprint.errorhandler(RequestContractError)
    def request_contract_error(error: RequestContractError):
        return _error(error.code, error.public_message, error.status)

    @blueprint.errorhandler(ProjectDocumentNotFound)
    def project_document_not_found(_exception: ProjectDocumentNotFound):
        return _error(
            "project_document_not_found", "Project or document was not found", 404
        )

    @blueprint.errorhandler(ProjectDocumentConflict)
    def project_document_conflict(exception: ProjectDocumentConflict):
        code = (
            "optimistic_lock_conflict"
            if "optimistic lock version conflict" in str(exception)
            else "project_document_conflict"
        )
        return _error(
            code, "Project or document state conflicts with the request", 409
        )

    @blueprint.errorhandler(ProjectDocumentUnavailable)
    def project_document_unavailable(_exception: ProjectDocumentUnavailable):
        return _error(
            "project_document_unavailable", "Project document service temporarily unavailable", 503
        )

    @blueprint.errorhandler(DocumentCalculationError)
    @blueprint.errorhandler(TypeError)
    @blueprint.errorhandler(ValueError)
    def invalid_project_document_request(_exception: Exception):
        return _error(
            "invalid_project_document_request", "Project or document request is invalid", 422
        )

    return blueprint


__all__ = ["create_project_document_blueprint"]
