import base64
import io
import json
from unittest.mock import Mock, patch

import pytest
from PIL import Image

import presensi_delivery_worker as delivery
import wuzapi_helper


EVENT_ID = "evt-0123456789abcdef01234567"
LEASE_TOKEN = "a" * 64
GROUP_JID = "120363123456789012@g.us"
SECRET = "s" * 32


def jpeg_bytes(size=(8, 8)):
    output = io.BytesIO()
    Image.new("RGB", size, (24, 96, 160)).save(output, format="JPEG")
    return output.getvalue()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, *, raw=None, content_type="application/json"):
        self.status_code = status_code
        self._raw = raw if raw is not None else json.dumps(payload).encode("utf-8")
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(self._raw)),
        }
        self.closed = False

    @property
    def text(self):
        return self._raw.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self._raw)

    def iter_content(self, chunk_size=8192):
        for offset in range(0, len(self._raw), chunk_size):
            yield self._raw[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def claim_payload(photo=None, **overrides):
    event = {
        "event_id": EVENT_ID,
        "lease_token": LEASE_TOKEN,
        "lease_expires_at": "2026-11-05T08:02:00+00:00",
        "attempt": 1,
        "employee_name": "Naufal",
        "action": "check_in",
        "project_name": "Project Atlas",
        "occurred_at": "2026-11-05T08:00:00+07:00",
        "accuracy_m": 4.2,
        "photo_mime": "image/jpeg",
        "photo_base64": base64.b64encode(photo or jpeg_bytes()).decode("ascii"),
    }
    event.update(overrides)
    return {"version": "presensi.outbox.claim.v1", "event": event}


def ack_payload(outcome):
    return {
        "version": "presensi.outbox.ack.v1",
        "event_id": EVENT_ID,
        "status": outcome,
        "attempts": 1,
    }


def worker_config(**overrides):
    values = {
        "base_url": "https://presensi.test/api",
        "shared_secret": SECRET,
        "group_jid": GROUP_JID,
        "connect_timeout_seconds": 2.0,
        "read_timeout_seconds": 8.0,
        "max_claim_response_bytes": 5_000_000,
        "max_ack_response_bytes": 65_536,
        "max_jpeg_bytes": 3_145_728,
    }
    values.update(overrides)
    return delivery.WorkerConfig(**values)


def test_send_image_payload_uses_exact_group_jpeg_data_uri_caption_and_event_id(monkeypatch):
    image = jpeg_bytes()
    response = FakeResponse(200, {"Details": "Sent", "Timestamp": 1, "Id": "wamid-1"})
    session = FakeSession([response])
    monkeypatch.setenv("PRESENSI_WHATSAPP_GROUP_JID", GROUP_JID)

    with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test/api"), \
         patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
         patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
        result = wuzapi_helper.send_image_to_whatsapp_group(
            image,
            "Presensi masuk — Naufal",
            event_id=EVENT_ID,
        )

    assert result == {
        "outcome": "sent",
        "provider_message_id": "wamid-1",
        "error_code": "",
    }
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://wuzapi.test/chat/send/image"
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["json"] == {
        "Phone": GROUP_JID,
        "Image": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
        "Caption": "Presensi masuk — Naufal",
        "Id": EVENT_ID,
    }
    assert response.closed is True


@pytest.mark.parametrize(
    ("provider_payload", "expected"),
    [
        ({"success": False, "error": "not connected"}, "failed"),
        ({"status": "failed", "message": "rejected"}, "failed"),
        ({}, "unknown"),
        ({"message": "ok maybe"}, "unknown"),
        ({"Id": "message-id-without-success"}, "unknown"),
    ],
)
def test_send_image_strict_ack_classification_without_retry(monkeypatch, provider_payload, expected):
    session = FakeSession([FakeResponse(200, provider_payload)])
    monkeypatch.setenv("PRESENSI_WHATSAPP_GROUP_JID", GROUP_JID)

    with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test"), \
         patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
         patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
        result = wuzapi_helper.send_image_to_whatsapp_group(
            jpeg_bytes(), "Caption", event_id=EVENT_ID
        )

    assert result["outcome"] == expected
    assert len(session.calls) == 1


def test_send_image_transport_error_is_unknown_without_retry(monkeypatch):
    session = FakeSession([TimeoutError("contains-secret-value")])
    monkeypatch.setenv("PRESENSI_WHATSAPP_GROUP_JID", GROUP_JID)

    with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test"), \
         patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
         patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
        result = wuzapi_helper.send_image_to_whatsapp_group(
            jpeg_bytes(), "Caption", event_id=EVENT_ID
        )

    assert result["outcome"] == "unknown"
    assert "secret" not in result["error_code"]
    assert len(session.calls) == 1


@pytest.mark.parametrize(("status_code", "outcome"), [(400, "failed"), (503, "unknown")])
def test_send_image_http_outcome_avoids_retry_on_ambiguous_server_error(
    monkeypatch, status_code, outcome
):
    session = FakeSession([FakeResponse(status_code, {"error": "upstream"})])
    monkeypatch.setenv("PRESENSI_WHATSAPP_GROUP_JID", GROUP_JID)

    with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test"), \
         patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
         patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
        result = wuzapi_helper.send_image_to_whatsapp_group(
            jpeg_bytes(), "Caption", event_id=EVENT_ID
        )

    assert result["outcome"] == outcome
    assert len(session.calls) == 1


def test_send_image_rejects_invalid_jpeg_or_group_before_http(monkeypatch):
    session = FakeSession([])
    monkeypatch.setenv("PRESENSI_WHATSAPP_GROUP_JID", "not-a-group")

    with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "https://wuzapi.test"), \
         patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
         patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
        result = wuzapi_helper.send_image_to_whatsapp_group(
            b"not-jpeg", "Caption", event_id=EVENT_ID
        )

    assert result["outcome"] == "failed"
    assert session.calls == []


def test_worker_claims_sends_and_acks_sent_with_auth_headers_only():
    session = FakeSession([
        FakeResponse(200, claim_payload()),
        FakeResponse(200, ack_payload("sent")),
        FakeResponse(200, {"version": "presensi.outbox.claim.v1", "event": None}),
    ])
    sender = Mock(return_value={
        "outcome": "sent",
        "provider_message_id": "wamid-1",
        "error_code": "",
    })
    worker = delivery.PresensiDeliveryWorker(worker_config(), session=session, sender=sender)

    summary = worker.run(max_items=2)

    assert summary["sent"] == 1
    assert summary["acked"] == 1
    assert summary["claimed"] == 1
    sender.assert_called_once()
    image_arg, caption_arg = sender.call_args.args
    assert image_arg[:3] == b"\xff\xd8\xff"
    assert "Presensi masuk" in caption_arg
    assert "Naufal" in caption_arg
    assert sender.call_args.kwargs == {"event_id": EVENT_ID, "group_jid": GROUP_JID}

    claim_url, claim_kwargs = session.calls[0]
    assert claim_url == "https://presensi.test/api/outbox-claim.php"
    assert SECRET not in claim_url
    assert claim_kwargs["headers"]["X-Presensi-Secret"] == SECRET
    assert "json" not in claim_kwargs
    assert claim_kwargs["allow_redirects"] is False
    assert claim_kwargs["stream"] is True
    assert claim_kwargs["timeout"] == (2.0, 8.0)

    ack_url, ack_kwargs = session.calls[1]
    assert ack_url == "https://presensi.test/api/outbox-ack.php"
    assert SECRET not in ack_url
    assert ack_kwargs["headers"]["X-Presensi-Secret"] == SECRET
    assert SECRET not in json.dumps(ack_kwargs["json"])
    assert ack_kwargs["json"] == {
        "event_id": EVENT_ID,
        "lease_token": LEASE_TOKEN,
        "outcome": "sent",
        "provider_message_id": "wamid-1",
        "error_code": "",
    }


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_worker_acks_provider_failed_and_unknown(outcome):
    session = FakeSession([
        FakeResponse(200, claim_payload()),
        FakeResponse(200, ack_payload(outcome)),
    ])
    sender = Mock(return_value={
        "outcome": outcome,
        "provider_message_id": "",
        "error_code": "wuzapi_rejected" if outcome == "failed" else "wuzapi_ack_unknown",
    })
    worker = delivery.PresensiDeliveryWorker(worker_config(), session=session, sender=sender)

    summary = worker.run(max_items=1)

    assert summary[outcome] == 1
    assert session.calls[1][1]["json"]["outcome"] == outcome
    assert session.calls[1][1]["json"]["error_code"].startswith("wuzapi_")


def test_worker_does_not_send_duplicate_event_in_same_bounded_run():
    session = FakeSession([
        FakeResponse(200, claim_payload()),
        FakeResponse(200, ack_payload("sent")),
        FakeResponse(200, claim_payload(lease_token="b" * 64)),
        FakeResponse(200, ack_payload("sent")),
    ])
    sender = Mock(return_value={
        "outcome": "sent",
        "provider_message_id": "wamid-1",
        "error_code": "",
    })
    worker = delivery.PresensiDeliveryWorker(worker_config(), session=session, sender=sender)

    summary = worker.run(max_items=2)

    sender.assert_called_once()
    assert summary["duplicates"] == 1
    assert summary["acked"] == 2
    assert session.calls[3][1]["json"]["lease_token"] == "b" * 64


def test_worker_rejects_invalid_jpeg_and_acks_failed_without_sending():
    bad_claim = claim_payload()
    bad_claim["event"]["photo_base64"] = base64.b64encode(b"not a jpeg").decode("ascii")
    session = FakeSession([
        FakeResponse(200, bad_claim),
        FakeResponse(200, ack_payload("failed")),
    ])
    sender = Mock()
    worker = delivery.PresensiDeliveryWorker(worker_config(), session=session, sender=sender)

    summary = worker.run(max_items=1)

    sender.assert_not_called()
    assert summary["failed"] == 1
    assert summary["acked"] == 1
    assert session.calls[1][1]["json"]["outcome"] == "failed"
    assert session.calls[1][1]["json"]["error_code"] == "claim_invalid_jpeg"


def test_worker_sender_exception_is_unknown_and_acked_without_retry():
    session = FakeSession([
        FakeResponse(200, claim_payload()),
        FakeResponse(200, ack_payload("unknown")),
    ])
    sender = Mock(side_effect=RuntimeError("secret provider details"))
    worker = delivery.PresensiDeliveryWorker(worker_config(), session=session, sender=sender)

    summary = worker.run(max_items=1)

    sender.assert_called_once()
    assert summary["unknown"] == 1
    assert summary["acked"] == 1
    assert session.calls[1][1]["json"]["error_code"] == "sender_exception_unknown"


def test_worker_rejects_declared_oversized_claim_before_reading_body():
    response = FakeResponse(200, claim_payload())
    response.headers["Content-Length"] = "99999999"
    session = FakeSession([response])
    worker = delivery.PresensiDeliveryWorker(
        worker_config(max_claim_response_bytes=16_384, max_jpeg_bytes=1_024),
        session=session,
    )

    summary = worker.run(max_items=1)

    assert summary["fatal_error"] == "claim_response_too_large"
    assert summary["claimed"] == 0
    assert response.closed is True


def test_worker_config_requires_https_same_origin_endpoints_and_long_secret(monkeypatch):
    monkeypatch.setenv("PRESENSI_OUTBOX_BASE_URL", "http://presensi.test/api")
    monkeypatch.setenv("PRESENSI_OUTBOX_SHARED_SECRET", SECRET)
    monkeypatch.setenv("PRESENSI_WHATSAPP_GROUP_JID", GROUP_JID)
    with pytest.raises(delivery.ConfigurationError):
        delivery.WorkerConfig.from_env()

    monkeypatch.setenv("PRESENSI_OUTBOX_BASE_URL", "https://presensi.test/api?secret=bad")
    with pytest.raises(delivery.ConfigurationError):
        delivery.WorkerConfig.from_env()

    monkeypatch.setenv("PRESENSI_OUTBOX_BASE_URL", "https://presensi.test/api")
    monkeypatch.setenv("WUZAPI_DOMAIN", "http://wuzapi.test")
    monkeypatch.setenv("WUZAPI_TOKEN", "token")
    with pytest.raises(delivery.ConfigurationError):
        delivery.WorkerConfig.from_env()


def test_caption_converts_server_utc_to_wib(monkeypatch):
    monkeypatch.delenv("PRESENSI_BUSINESS_TIMEZONE", raising=False)
    event = delivery.ClaimedEvent(
        event_id=EVENT_ID,
        lease_token=LEASE_TOKEN,
        employee_name="Naufal",
        action="check_in",
        project_name="Project Atlas",
        occurred_at="2026-11-05T08:00:00+00:00",
        accuracy_m=4.2,
        jpeg=jpeg_bytes(),
    )
    caption = delivery._caption(event)
    assert "2026-11-05 15:00 WIB" in caption


def test_send_image_rejects_plaintext_wuzapi_before_http(monkeypatch):
    session = FakeSession([])
    monkeypatch.setenv("PRESENSI_WHATSAPP_GROUP_JID", GROUP_JID)
    with patch.object(wuzapi_helper, "WUZAPI_DOMAIN", "http://wuzapi.test"), \
         patch.object(wuzapi_helper, "WUZAPI_TOKEN", "token"), \
         patch.object(wuzapi_helper, "get_wuzapi_session", return_value=session):
        result = wuzapi_helper.send_image_to_whatsapp_group(
            jpeg_bytes(), "Caption", event_id=EVENT_ID
        )
    assert result["outcome"] == "failed"
    assert result["error_code"] == "wuzapi_not_configured"
    assert session.calls == []


def test_worker_max_items_is_strictly_bounded():
    worker = delivery.PresensiDeliveryWorker(worker_config(), session=FakeSession([]))
    with pytest.raises(ValueError):
        worker.run(max_items=0)
    with pytest.raises(ValueError):
        worker.run(max_items=delivery.MAX_ITEMS_PER_RUN + 1)
