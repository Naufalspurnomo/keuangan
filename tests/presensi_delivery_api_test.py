import os
from unittest.mock import patch

from flask import Flask

from presensi_delivery_api import register_presensi_delivery_endpoint


SECRET = "s" * 32


def client(active_projects=None):
    app = Flask(__name__)
    register_presensi_delivery_endpoint(app, active_projects=active_projects)
    return app.test_client()


def test_project_catalog_rejects_missing_or_wrong_secret(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)
    source = lambda: []
    test_client = client(source)
    assert test_client.get("/internal/presensi/projects").status_code == 401
    assert test_client.get(
        "/internal/presensi/projects", headers={"X-Presensi-Secret": "x" * 32}
    ).status_code == 401


def test_project_catalog_returns_only_active_canonical_projects(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)
    source = lambda: [
        {"id": "11111111-1111-4111-8111-111111111111", "name": "Aktif A", "company": "Holla", "status": "active", "client_name": "Rahasia"},
        {"id": "22222222-2222-4222-8222-222222222222", "name": "Selesai B", "company": "Hojja", "status": "completed"},
        {"id": "33333333-3333-4333-8333-333333333333", "name": "Aktif C", "company": "Texturin Bali", "status": "active"},
    ]
    response = client(source).get(
        "/internal/presensi/projects", headers={"X-Presensi-Secret": SECRET}
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "version": "presensi.projects.v1",
        "projects": [
            {"id": "11111111-1111-4111-8111-111111111111", "name": "Aktif A", "company": "Holla"},
            {"id": "33333333-3333-4333-8333-333333333333", "name": "Aktif C", "company": "Texturin Bali"},
        ],
    }


def test_project_catalog_fails_closed_when_canonical_source_is_unavailable(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)

    def unavailable():
        raise RuntimeError("database unavailable")

    response = client(unavailable).get(
        "/internal/presensi/projects", headers={"X-Presensi-Secret": SECRET}
    )
    assert response.status_code == 503
    assert response.get_json() == {"error": {"code": "project_catalog_unavailable"}}


def test_trigger_rejects_missing_or_wrong_secret(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)
    test_client = client()
    assert test_client.post("/internal/presensi/deliver").status_code == 401
    assert test_client.post("/internal/presensi/deliver", headers={"X-Presensi-Secret": "x" * 32}).status_code == 401


def test_trigger_rejects_request_body(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)
    response = client().post(
        "/internal/presensi/deliver",
        headers={"X-Presensi-Secret": SECRET},
        data=b"not-allowed",
    )
    assert response.status_code == 413


def test_trigger_runs_exactly_one_item(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)
    summary = {"fatal_error": "", "claimed": 1, "sent": 1}
    with patch("presensi_delivery_api.WorkerConfig.from_env", return_value=object()), patch(
        "presensi_delivery_api.PresensiDeliveryWorker"
    ) as worker:
        worker.return_value.run.return_value = summary
        response = client().post(
            "/internal/presensi/deliver", headers={"X-Presensi-Secret": SECRET}
        )
    assert response.status_code == 200
    worker.return_value.run.assert_called_once_with(max_items=1)
    assert response.get_json()["summary"] == summary


def test_trigger_maps_configuration_and_fatal_failures(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)
    from presensi_delivery_worker import ConfigurationError

    with patch("presensi_delivery_api.WorkerConfig.from_env", side_effect=ConfigurationError("x")):
        assert client().post(
            "/internal/presensi/deliver", headers={"X-Presensi-Secret": SECRET}
        ).status_code == 503
    with patch("presensi_delivery_api.WorkerConfig.from_env", return_value=object()), patch(
        "presensi_delivery_api.PresensiDeliveryWorker"
    ) as worker:
        worker.return_value.run.return_value = {"fatal_error": "ack_transport_error"}
        assert client().post(
            "/internal/presensi/deliver", headers={"X-Presensi-Secret": SECRET}
        ).status_code == 502
