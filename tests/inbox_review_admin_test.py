from __future__ import annotations

from copy import deepcopy

import pytest
from flask import Flask

from dashboard_api.inbox_review import create_inbox_review_blueprint
from services.durable_inbox import ReviewConflict


EVENT_KEY = "a" * 64
MESSAGE_ID = "provider-message-123"
CSRF_TOKEN = "owner-csrf-token"
OWNER_EMAIL = "naufalspurnomo@gmail.com"


class FakeInboxReviewService:
    def __init__(self) -> None:
        self.event = {
            "event_key": EVENT_KEY,
            "provider": "wuzapi",
            "message_id": MESSAGE_ID,
            "chat_id": "private-chat-id",
            "sender_id": "private-sender-id",
            "sender_name": "Private Sender",
            "sender_jid": "private@jid",
            "event_type": "image",
            "body_text": "private transaction body",
            "media_data": "data:image/jpeg;base64,PRIVATE",
            "media_path": "/private/media/path.jpg",
            "quoted_message_id": "quoted-private-id",
            "is_group": False,
            "finance_signal": True,
            "payload_score": 9,
            "status": "needs_review_notified",
            "result_status": "ignored_finance_signal",
            "attempts": 4,
            "last_error": "private processing detail",
            "received_at": "2026-11-09T10:00:00+00:00",
            "updated_at": "2026-11-09T10:05:00+00:00",
        }
        self.resolve_calls: list[dict] = []
        self.replay_calls: list[dict] = []
        self.command_results: dict[str, tuple[dict, dict]] = {}
        self.conflict = False

    def list_review_events(self, *, limit: int):
        assert limit == 50
        return [deepcopy(self.event)]

    def get_review_event(self, event_key: str):
        if event_key != EVENT_KEY or not str(self.event["status"]).startswith("needs_review"):
            return None
        return deepcopy(self.event)

    def get_review_command_result(
        self,
        command_key: str,
        *,
        event_key: str,
        action: str,
        actor: str,
        reason: str,
        expected_status: str,
    ):
        self.replay_calls.append({
            "command_key": command_key,
            "event_key": event_key,
            "action": action,
            "actor": actor,
            "reason": reason,
            "expected_status": expected_status,
        })
        stored = self.command_results.get(command_key)
        if stored is None:
            return None
        request_data, result = stored
        if request_data != {
            "event_key": event_key,
            "action": action,
            "actor": actor,
            "reason": reason,
            "expected_status": expected_status,
        }:
            raise ReviewConflict("idempotency key was reused with another request")
        replayed = deepcopy(result)
        replayed["replayed"] = True
        return replayed

    def resolve_review_event(
        self,
        event_key: str,
        action: str,
        *,
        actor: str,
        reason: str,
        expected_status: str,
        command_key: str,
        ledger_proof: dict,
    ):
        call = {
            "event_key": event_key,
            "action": action,
            "actor": actor,
            "reason": reason,
            "expected_status": expected_status,
            "command_key": command_key,
            "ledger_proof": ledger_proof,
        }
        self.resolve_calls.append(call)
        if self.conflict:
            raise ReviewConflict("event already resolved")
        result = {
            "event_key": event_key,
            "message_id": MESSAGE_ID,
            "action": action,
            "status": {
                "ignore": "ignored",
                "confirm_processed": "processed",
            }[action],
            "replayed": False,
        }
        self.command_results[command_key] = ({
            "event_key": event_key,
            "action": action,
            "actor": actor,
            "reason": reason,
            "expected_status": expected_status,
        }, result)
        self.event["status"] = result["status"]
        return result


@pytest.fixture
def review_app():
    service = FakeInboxReviewService()
    ledger_state = {"found": False, "error": None, "calls": []}

    def ledger_lookup(message_id: str) -> dict:
        ledger_state["calls"].append(message_id)
        if ledger_state["error"] is not None:
            raise ledger_state["error"]
        found = ledger_state["found"]
        if isinstance(found, dict):
            return found
        return {
            "status": "complete",
            "message_id": message_id,
            "matches": [{"source_key": message_id}] if found else [],
        }

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    app.register_blueprint(
        create_inbox_review_blueprint(
            service=service,
            ledger_lookup=ledger_lookup,
            writes_enabled=lambda: True,
        )
    )
    return app, service, ledger_state


def login_owner(client) -> None:
    with client.session_transaction() as session:
        session["dashboard_user"] = OWNER_EMAIL
        session["dashboard_role"] = "owner"
        session["dashboard_csrf_token"] = CSRF_TOKEN


def action_request(
    client,
    action: str,
    reason: str = "owner reviewed evidence",
    *,
    expected_status: str = "needs_review_notified",
    command_key: str = "review-command-0001",
):
    return client.post(
        f"/api/dashboard/v1/inbox/reviews/{EVENT_KEY}/actions",
        json={"action": action, "reason": reason, "expected_status": expected_status},
        headers={"X-CSRF-Token": CSRF_TOKEN, "Idempotency-Key": command_key},
    )


def test_all_review_endpoints_require_owner_authentication_and_disable_caching(review_app):
    app, service, _ledger = review_app
    client = app.test_client()

    responses = (
        client.get("/api/dashboard/v1/inbox/reviews"),
        client.get(f"/api/dashboard/v1/inbox/reviews/{EVENT_KEY}"),
        client.post(
            f"/api/dashboard/v1/inbox/reviews/{EVENT_KEY}/actions",
            json={"action": "ignore", "reason": "not a transaction"},
        ),
    )

    for response in responses:
        assert response.status_code == 401
        assert response.get_json()["error"]["code"] == "authentication_required"
        assert response.headers["Cache-Control"] == "no-store"
    assert service.resolve_calls == []


def test_post_requires_csrf_before_review_action(review_app):
    app, service, _ledger = review_app
    client = app.test_client()
    login_owner(client)

    response = client.post(
        f"/api/dashboard/v1/inbox/reviews/{EVENT_KEY}/actions",
        json={"action": "ignore", "reason": "not a transaction"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_validation_failed"
    assert response.headers["Cache-Control"] == "no-store"
    assert service.resolve_calls == []


def test_metadata_and_detail_never_expose_identity_paths_or_raw_media(review_app):
    app, _service, _ledger = review_app
    client = app.test_client()
    login_owner(client)

    list_response = client.get("/api/dashboard/v1/inbox/reviews")
    detail_response = client.get(f"/api/dashboard/v1/inbox/reviews/{EVENT_KEY}")

    assert list_response.status_code == 200
    item = list_response.get_json()["data"]["items"][0]
    assert item["event_key"] == EVENT_KEY
    assert item["message_id"] == MESSAGE_ID
    assert {"body_text", "media_data", "media_path"}.isdisjoint(item)
    assert "private transaction body" not in list_response.get_data(as_text=True)
    assert "PRIVATE" not in list_response.get_data(as_text=True)
    assert list_response.headers["Cache-Control"] == "no-store"

    assert detail_response.status_code == 200
    detail = detail_response.get_json()["data"]
    assert detail["body_text"] == "private transaction body"
    assert detail["media_available"] is True
    assert {
        "chat_id", "sender_id", "sender_name", "sender_jid", "media_data",
        "media_path", "last_error",
    }.isdisjoint(detail)
    assert detail_response.headers["Cache-Control"] == "no-store"


def test_invalid_action_is_rejected_without_ledger_or_state_change(review_app):
    app, service, ledger = review_app
    client = app.test_client()
    login_owner(client)

    response = action_request(client, "mark_event")

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "invalid_review_action"
    assert response.headers["Cache-Control"] == "no-store"
    assert ledger["calls"] == []
    assert service.resolve_calls == []


def test_compare_and_set_conflict_returns_409(review_app):
    app, service, ledger = review_app
    service.conflict = True
    client = app.test_client()
    login_owner(client)

    response = action_request(client, "ignore", "already handled elsewhere")

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "review_conflict"
    assert response.headers["Cache-Control"] == "no-store"
    assert ledger["calls"] == [MESSAGE_ID]
    assert len(service.resolve_calls) == 1


def test_retry_is_not_a_supported_owner_action(review_app):
    app, service, ledger = review_app

    client = app.test_client()
    login_owner(client)

    response = action_request(client, "retry", "retry requested after inspection")

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "invalid_review_action"
    assert ledger["calls"] == []
    assert service.resolve_calls == []


def test_confirm_processed_requires_positive_authoritative_ledger_proof(review_app):
    app, service, ledger = review_app
    ledger["found"] = False
    client = app.test_client()
    login_owner(client)

    response = action_request(client, "confirm_processed", "transaction appears processed")

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ledger_transaction_not_found"
    assert ledger["calls"] == [MESSAGE_ID]
    assert service.resolve_calls == []


@pytest.mark.parametrize(
    ("action", "ledger_found", "expected_status"),
    (
        ("ignore", False, "ignored"),
        ("confirm_processed", True, "processed"),
    ),
)
def test_successful_review_actions_are_exact_auditable_and_proof_gated(
    review_app,
    action,
    ledger_found,
    expected_status,
):
    app, service, ledger = review_app
    ledger["found"] = ledger_found
    client = app.test_client()
    login_owner(client)
    reason = f"owner reason for {action}"

    response = action_request(client, action, reason)

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == expected_status
    assert response.headers["Cache-Control"] == "no-store"
    assert ledger["calls"] == [MESSAGE_ID]
    assert service.resolve_calls == [
        {
            "event_key": EVENT_KEY,
            "action": action,
            "actor": OWNER_EMAIL,
            "reason": reason,
            "expected_status": "needs_review_notified",
            "command_key": "review-command-0001",
            "ledger_proof": {
                "status": "complete",
                "message_id": MESSAGE_ID,
                "matches": [{"source_key": MESSAGE_ID}] if ledger_found else [],
            },
        }
    ]


def test_response_loss_replay_succeeds_after_event_leaves_review_queue(review_app):
    app, service, ledger = review_app
    client = app.test_client()
    login_owner(client)

    first = action_request(client, "ignore", "duplicate delivery safe", command_key="review-command-replay")
    second = action_request(client, "ignore", "duplicate delivery safe", command_key="review-command-replay")

    assert first.status_code == 200
    assert first.get_json()["data"]["replayed"] is False
    assert service.get_review_event(EVENT_KEY) is None
    assert second.status_code == 200
    assert second.get_json()["data"] == {
        "event_key": EVENT_KEY,
        "message_id": MESSAGE_ID,
        "action": "ignore",
        "status": "ignored",
        "replayed": True,
    }
    assert ledger["calls"] == [MESSAGE_ID]
    assert len(service.resolve_calls) == 1
    assert len(service.replay_calls) == 2


def test_partial_ledger_scan_blocks_every_owner_action(review_app):
    app, service, ledger = review_app
    ledger["found"] = {"status": "partial", "message_id": MESSAGE_ID, "matches": []}
    client = app.test_client()
    login_owner(client)

    response = action_request(client, "ignore", "ledger scan incomplete")

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "ledger_proof_incomplete"
    assert service.resolve_calls == []


def test_stale_expected_status_is_forwarded_for_atomic_conflict_check(review_app):
    app, service, ledger = review_app
    ledger["found"] = False
    client = app.test_client()
    login_owner(client)

    response = action_request(client, "ignore", expected_status="needs_review")

    assert response.status_code == 200
    assert service.resolve_calls[0]["expected_status"] == "needs_review"


def test_action_rejects_unknown_fields_and_missing_idempotency_key(review_app):
    app, service, _ledger = review_app
    client = app.test_client()
    login_owner(client)

    unknown = client.post(
        f"/api/dashboard/v1/inbox/reviews/{EVENT_KEY}/actions",
        json={"action": "ignore", "reason": "x", "expected_status": "needs_review", "extra": True},
        headers={"X-CSRF-Token": CSRF_TOKEN, "Idempotency-Key": "review-command-0002"},
    )
    missing_key = client.post(
        f"/api/dashboard/v1/inbox/reviews/{EVENT_KEY}/actions",
        json={"action": "ignore", "reason": "x", "expected_status": "needs_review"},
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )

    assert unknown.status_code == 422
    assert unknown.get_json()["error"]["code"] == "unsupported_fields"
    assert missing_key.status_code == 422
    assert missing_key.get_json()["error"]["code"] == "idempotency_key_required"
    assert service.resolve_calls == []
