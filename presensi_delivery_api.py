"""Authenticated Presensi project catalog and bounded WhatsApp delivery trigger."""
from __future__ import annotations

import hmac
import os
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from uuid import UUID

from flask import jsonify, request

from presensi_delivery_worker import ConfigurationError, PresensiDeliveryWorker, WorkerConfig


def _authenticated() -> bool:
    expected = os.getenv("PRESENSI_OUTBOX_SHARED_SECRET", "").strip()
    provided = request.headers.get("X-Presensi-Secret", "").strip()
    return len(expected) >= 32 and bool(provided) and hmac.compare_digest(expected, provided)


def _active_project_catalog(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    projects: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if str(row.get("status") or "") != "active":
            continue
        project_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        company = str(row.get("company") or "").strip()
        try:
            UUID(project_id)
        except (TypeError, ValueError, AttributeError):
            continue
        if not name or not company or project_id in seen:
            continue
        seen.add(project_id)
        projects.append({"id": project_id, "name": name, "company": company})
    return projects


def register_presensi_delivery_endpoint(
    app,
    *,
    active_projects: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
) -> None:
    @app.get("/internal/presensi/projects")
    def presensi_projects():
        if not _authenticated():
            return jsonify({"error": {"code": "authentication_required"}}), 401
        if active_projects is None:
            return jsonify({"error": {"code": "project_catalog_unavailable"}}), 503
        try:
            projects = _active_project_catalog(active_projects())
        except Exception:
            return jsonify({"error": {"code": "project_catalog_unavailable"}}), 503
        response = jsonify({"version": "presensi.projects.v1", "projects": projects})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/internal/presensi/deliver")
    def trigger_presensi_delivery():
        if not _authenticated():
            return jsonify({"error": {"code": "authentication_required"}}), 401
        if request.content_length not in (None, 0):
            return jsonify({"error": {"code": "payload_not_allowed"}}), 413
        try:
            summary = PresensiDeliveryWorker(WorkerConfig.from_env()).run(max_items=1)
        except ConfigurationError:
            return jsonify({"error": {"code": "delivery_unavailable"}}), 503
        status = 502 if summary["fatal_error"] else 200
        return jsonify({"version": "presensi.delivery.trigger.v1", "summary": summary}), status
