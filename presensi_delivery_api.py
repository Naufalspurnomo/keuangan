"""Authenticated, bounded trigger for one presensi WhatsApp outbox delivery."""
from __future__ import annotations

import hmac
import os

from flask import jsonify, request

from presensi_delivery_worker import ConfigurationError, PresensiDeliveryWorker, WorkerConfig


def register_presensi_delivery_endpoint(app) -> None:
    @app.post("/internal/presensi/deliver")
    def trigger_presensi_delivery():
        expected = os.getenv("PRESENSI_OUTBOX_SHARED_SECRET", "").strip()
        provided = request.headers.get("X-Presensi-Secret", "").strip()
        if len(expected) < 32 or not provided or not hmac.compare_digest(expected, provided):
            return jsonify({"error": {"code": "authentication_required"}}), 401
        if request.content_length not in (None, 0):
            return jsonify({"error": {"code": "payload_not_allowed"}}), 413
        try:
            summary = PresensiDeliveryWorker(WorkerConfig.from_env()).run(max_items=1)
        except ConfigurationError:
            return jsonify({"error": {"code": "delivery_unavailable"}}), 503
        status = 502 if summary["fatal_error"] else 200
        return jsonify({"version": "presensi.delivery.trigger.v1", "summary": summary}), status
