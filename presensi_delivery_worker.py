"""Bounded presensi outbox delivery worker.

Required environment variables:
- PRESENSI_OUTBOX_BASE_URL: HTTPS URL ending at the Rumahweb presensi API dir.
- PRESENSI_OUTBOX_SHARED_SECRET: shared secret (minimum 32 characters).
- PRESENSI_WHATSAPP_GROUP_JID: exact WhatsApp group JID (``...@g.us``).
- WUZAPI_DOMAIN / WUZAPI_TOKEN: used by ``wuzapi_helper`` for image delivery.

Optional bounded settings:
- PRESENSI_OUTBOX_CONNECT_TIMEOUT_SECONDS (default 3, range 1..10)
- PRESENSI_OUTBOX_READ_TIMEOUT_SECONDS (default 15, range 2..30)
- PRESENSI_OUTBOX_MAX_CLAIM_RESPONSE_BYTES (default 5,000,000)
- PRESENSI_OUTBOX_MAX_ACK_RESPONSE_BYTES (default 65,536)
- PRESENSI_OUTBOX_MAX_JPEG_BYTES (default 3,145,728)

Run explicitly from a scheduler, never as a Gunicorn/background thread:
``python presensi_delivery_worker.py --max-items 5``.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit

import requests

from wuzapi_helper import _validated_jpeg_bytes, send_image_to_whatsapp_group


MAX_ITEMS_PER_RUN = 20
_EVENT_ID_RE = re.compile(r"evt-[a-f0-9]{24}\Z")
_LEASE_TOKEN_RE = re.compile(r"[a-f0-9]{64}\Z")
_GROUP_JID_RE = re.compile(r"[1-9][0-9]{5,24}@g\.us\Z")
_SAFE_ERROR_RE = re.compile(r"[^a-z0-9_.:-]")


class ConfigurationError(ValueError):
    """Raised when required worker configuration is absent or unsafe."""


class ProtocolError(RuntimeError):
    """Raised for bounded HTTP or response-contract failures."""

    def __init__(self, code: str):
        self.code = _sanitize_error_code(code)
        super().__init__(self.code)


class ClaimValidationError(ValueError):
    """Raised when a claimed event violates the presensi outbox contract."""

    def __init__(self, code: str):
        self.code = _sanitize_error_code(code)
        super().__init__(self.code)


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _sanitize_error_code(value: Any) -> str:
    clean = _SAFE_ERROR_RE.sub("", str(value or "").strip().lower())[:80]
    return clean or "internal_error"


def _validate_https_base_url(value: str) -> str:
    base = str(value or "").strip().rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("PRESENSI_OUTBOX_BASE_URL must be a plain HTTPS URL")
    return base


@dataclass(frozen=True)
class WorkerConfig:
    base_url: str
    shared_secret: str
    group_jid: str
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 15.0
    max_claim_response_bytes: int = 5_000_000
    max_ack_response_bytes: int = 65_536
    max_jpeg_bytes: int = 3_145_728

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _validate_https_base_url(self.base_url))
        if len(self.shared_secret) < 32 or len(self.shared_secret) > 512:
            raise ConfigurationError("PRESENSI_OUTBOX_SHARED_SECRET length is invalid")
        if not _GROUP_JID_RE.fullmatch(self.group_jid):
            raise ConfigurationError("PRESENSI_WHATSAPP_GROUP_JID is invalid")
        if not 1 <= self.connect_timeout_seconds <= 10:
            raise ConfigurationError("connect timeout is outside allowed range")
        if not 2 <= self.read_timeout_seconds <= 30:
            raise ConfigurationError("read timeout is outside allowed range")
        if not 2_048 <= self.max_ack_response_bytes <= 1_048_576:
            raise ConfigurationError("ACK response bound is outside allowed range")
        if not 16_384 <= self.max_claim_response_bytes <= 15_000_000:
            raise ConfigurationError("claim response bound is outside allowed range")
        if not 1_024 <= self.max_jpeg_bytes <= 10 * 1024 * 1024:
            raise ConfigurationError("JPEG bound is outside allowed range")
        minimum_claim_bound = 4 * math.ceil(self.max_jpeg_bytes / 3) + 4_096
        if self.max_claim_response_bytes < minimum_claim_bound:
            raise ConfigurationError("claim response bound cannot hold configured JPEG bound")

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        wuzapi_domain = os.getenv("WUZAPI_DOMAIN", "").strip()
        if not wuzapi_domain or not os.getenv("WUZAPI_TOKEN", "").strip():
            raise ConfigurationError("WUZAPI_DOMAIN and WUZAPI_TOKEN are required")
        _validate_https_base_url(wuzapi_domain)
        return cls(
            base_url=os.getenv("PRESENSI_OUTBOX_BASE_URL", ""),
            shared_secret=os.getenv("PRESENSI_OUTBOX_SHARED_SECRET", ""),
            group_jid=os.getenv("PRESENSI_WHATSAPP_GROUP_JID", ""),
            connect_timeout_seconds=_bounded_float(
                "PRESENSI_OUTBOX_CONNECT_TIMEOUT_SECONDS", 3, 1, 10
            ),
            read_timeout_seconds=_bounded_float(
                "PRESENSI_OUTBOX_READ_TIMEOUT_SECONDS", 15, 2, 30
            ),
            max_claim_response_bytes=_bounded_int(
                "PRESENSI_OUTBOX_MAX_CLAIM_RESPONSE_BYTES", 5_000_000, 16_384, 15_000_000
            ),
            max_ack_response_bytes=_bounded_int(
                "PRESENSI_OUTBOX_MAX_ACK_RESPONSE_BYTES", 65_536, 2_048, 1_048_576
            ),
            max_jpeg_bytes=_bounded_int(
                "PRESENSI_OUTBOX_MAX_JPEG_BYTES", 3_145_728, 1_024, 10 * 1024 * 1024
            ),
        )


@dataclass(frozen=True)
class ClaimedEvent:
    event_id: str
    lease_token: str
    employee_name: str
    action: str
    project_name: str
    occurred_at: str
    accuracy_m: float
    jpeg: bytes


def _bounded_json_response(response: requests.Response, max_bytes: int, prefix: str) -> Any:
    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ProtocolError(f"{prefix}_content_type_invalid")
    try:
        declared = response.headers.get("Content-Length", "")
        if declared and int(declared) > max_bytes:
            raise ProtocolError(f"{prefix}_response_too_large")
    except (TypeError, ValueError):
        raise ProtocolError(f"{prefix}_content_length_invalid")

    chunks = []
    received = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        received += len(chunk)
        if received > max_bytes:
            raise ProtocolError(f"{prefix}_response_too_large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProtocolError(f"{prefix}_json_invalid")


def _bounded_text(value: Any, field: str, maximum: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum or re.search(r"[\x00-\x1f\x7f]", text):
        raise ClaimValidationError(f"claim_invalid_{field}")
    return text


def _claim_identity(raw_event: Any) -> tuple[str, str]:
    if not isinstance(raw_event, dict):
        raise ClaimValidationError("claim_event_invalid")
    event_id = str(raw_event.get("event_id") or "").strip()
    lease_token = str(raw_event.get("lease_token") or "").strip()
    if not _EVENT_ID_RE.fullmatch(event_id):
        raise ClaimValidationError("claim_invalid_event_id")
    if not _LEASE_TOKEN_RE.fullmatch(lease_token):
        raise ClaimValidationError("claim_invalid_lease_token")
    return event_id, lease_token


def _decode_claim(raw_event: Any, max_jpeg_bytes: int) -> ClaimedEvent:
    event_id, lease_token = _claim_identity(raw_event)
    employee_name = _bounded_text(raw_event.get("employee_name"), "employee_name", 100)
    project_name = _bounded_text(raw_event.get("project_name"), "project_name", 160)
    action = str(raw_event.get("action") or "").strip()
    if action not in {"check_in", "check_out"}:
        raise ClaimValidationError("claim_invalid_action")
    occurred_at = _bounded_text(raw_event.get("occurred_at"), "occurred_at", 40)
    try:
        datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        raise ClaimValidationError("claim_invalid_occurred_at")
    try:
        accuracy_m = float(raw_event.get("accuracy_m"))
    except (TypeError, ValueError):
        raise ClaimValidationError("claim_invalid_accuracy")
    if not math.isfinite(accuracy_m) or accuracy_m < 0 or accuracy_m > 100_000:
        raise ClaimValidationError("claim_invalid_accuracy")
    if raw_event.get("photo_mime") != "image/jpeg":
        raise ClaimValidationError("claim_invalid_photo_mime")
    encoded = raw_event.get("photo_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ClaimValidationError("claim_invalid_photo_base64")
    if len(encoded) > 4 * math.ceil(max_jpeg_bytes / 3) + 4:
        raise ClaimValidationError("claim_jpeg_too_large")
    try:
        jpeg = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ClaimValidationError("claim_invalid_photo_base64")
    if len(jpeg) > max_jpeg_bytes:
        raise ClaimValidationError("claim_jpeg_too_large")
    if _validated_jpeg_bytes(jpeg, max_jpeg_bytes) is None:
        raise ClaimValidationError("claim_invalid_jpeg")
    return ClaimedEvent(
        event_id=event_id,
        lease_token=lease_token,
        employee_name=employee_name,
        action=action,
        project_name=project_name,
        occurred_at=occurred_at,
        accuracy_m=accuracy_m,
        jpeg=jpeg,
    )


def _caption(event: ClaimedEvent) -> str:
    action = "masuk" if event.action == "check_in" else "pulang"
    occurred = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00"))
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    timezone_name = os.getenv("PRESENSI_BUSINESS_TIMEZONE", "Asia/Jakarta").strip() or "Asia/Jakarta"
    try:
        occurred = occurred.astimezone(ZoneInfo(timezone_name))
    except (KeyError, ValueError):
        occurred = occurred.astimezone(ZoneInfo("Asia/Jakarta"))
        timezone_name = "Asia/Jakarta"
    timezone_label = "WIB" if timezone_name == "Asia/Jakarta" else timezone_name
    return (
        f"Presensi {action} — {event.employee_name}\n"
        f"{event.project_name} · {occurred:%Y-%m-%d %H:%M} {timezone_label} · ±{event.accuracy_m:.0f} m"
    )


def _normalize_send_result(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict) or value.get("outcome") not in {"sent", "failed", "unknown"}:
        return {
            "outcome": "unknown",
            "provider_message_id": "",
            "error_code": "sender_result_invalid",
        }
    outcome = str(value["outcome"])
    provider_message_id = str(value.get("provider_message_id") or "")[:160]
    error_code = "" if outcome == "sent" else _sanitize_error_code(value.get("error_code") or outcome)
    return {
        "outcome": outcome,
        "provider_message_id": provider_message_id if outcome == "sent" else "",
        "error_code": error_code,
    }


class PresensiDeliveryWorker:
    """Claim, send, and acknowledge no more than the caller's finite budget."""

    def __init__(
        self,
        config: WorkerConfig,
        *,
        session: Optional[Any] = None,
        sender: Callable[..., Dict[str, str]] = send_image_to_whatsapp_group,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.sender = sender
        self._outcomes_by_event: Dict[str, Dict[str, str]] = {}

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Presensi-Secret": self.config.shared_secret,
        }

    @property
    def _timeout(self) -> tuple[float, float]:
        return (self.config.connect_timeout_seconds, self.config.read_timeout_seconds)

    def _post_json(self, endpoint: str, payload: Optional[dict], max_bytes: int, prefix: str) -> Any:
        response = None
        kwargs: Dict[str, Any] = {
            "headers": self._headers,
            "timeout": self._timeout,
            "allow_redirects": False,
            "stream": True,
        }
        if payload is not None:
            kwargs["json"] = payload
        try:
            response = self.session.post(f"{self.config.base_url}/{endpoint}", **kwargs)
            if not 200 <= response.status_code < 300:
                raise ProtocolError(f"{prefix}_http_{response.status_code}")
            return _bounded_json_response(response, max_bytes, prefix)
        except requests.RequestException:
            raise ProtocolError(f"{prefix}_transport_error")
        except ProtocolError:
            raise
        except Exception:
            raise ProtocolError(f"{prefix}_transport_error")
        finally:
            if response is not None:
                response.close()

    def _claim(self) -> Optional[dict]:
        payload = self._post_json(
            "outbox-claim.php", None, self.config.max_claim_response_bytes, "claim"
        )
        if not isinstance(payload, dict) or payload.get("version") != "presensi.outbox.claim.v1":
            raise ProtocolError("claim_contract_invalid")
        event = payload.get("event")
        if event is None:
            return None
        if not isinstance(event, dict):
            raise ProtocolError("claim_contract_invalid")
        return event

    def _ack(self, event_id: str, lease_token: str, result: Dict[str, str]) -> None:
        payload = {
            "event_id": event_id,
            "lease_token": lease_token,
            "outcome": result["outcome"],
            "provider_message_id": result["provider_message_id"],
            "error_code": result["error_code"],
        }
        body = self._post_json(
            "outbox-ack.php", payload, self.config.max_ack_response_bytes, "ack"
        )
        if (
            not isinstance(body, dict)
            or body.get("version") != "presensi.outbox.ack.v1"
            or body.get("event_id") != event_id
            or body.get("status") not in {"sent", "failed", "unknown"}
        ):
            raise ProtocolError("ack_contract_invalid")

    def run(self, *, max_items: int) -> Dict[str, Any]:
        if isinstance(max_items, bool) or not isinstance(max_items, int):
            raise ValueError("max_items must be an integer")
        if not 1 <= max_items <= MAX_ITEMS_PER_RUN:
            raise ValueError(f"max_items must be between 1 and {MAX_ITEMS_PER_RUN}")

        summary: Dict[str, Any] = {
            "requested": max_items,
            "claimed": 0,
            "sent": 0,
            "failed": 0,
            "unknown": 0,
            "duplicates": 0,
            "acked": 0,
            "empty": False,
            "fatal_error": "",
        }
        for _ in range(max_items):
            try:
                raw_event = self._claim()
            except ProtocolError as exc:
                summary["fatal_error"] = exc.code
                break
            if raw_event is None:
                summary["empty"] = True
                break
            summary["claimed"] += 1

            try:
                event_id, lease_token = _claim_identity(raw_event)
            except ClaimValidationError as exc:
                summary["fatal_error"] = exc.code
                break

            if event_id in self._outcomes_by_event:
                result = self._outcomes_by_event[event_id]
                summary["duplicates"] += 1
            else:
                try:
                    event = _decode_claim(raw_event, self.config.max_jpeg_bytes)
                except ClaimValidationError as exc:
                    result = {
                        "outcome": "failed",
                        "provider_message_id": "",
                        "error_code": exc.code,
                    }
                else:
                    try:
                        send_value = self.sender(
                            event.jpeg,
                            _caption(event),
                            event_id=event.event_id,
                            group_jid=self.config.group_jid,
                        )
                    except Exception:
                        send_value = {
                            "outcome": "unknown",
                            "provider_message_id": "",
                            "error_code": "sender_exception_unknown",
                        }
                    result = _normalize_send_result(send_value)
                self._outcomes_by_event[event_id] = result
                summary[result["outcome"]] += 1

            try:
                self._ack(event_id, lease_token, result)
            except ProtocolError as exc:
                summary["fatal_error"] = exc.code
                break
            summary["acked"] += 1
        return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claim and deliver a bounded presensi WhatsApp outbox batch.",
        epilog=(
            "Required env: PRESENSI_OUTBOX_BASE_URL, PRESENSI_OUTBOX_SHARED_SECRET, "
            "PRESENSI_WHATSAPP_GROUP_JID, WUZAPI_DOMAIN, WUZAPI_TOKEN."
        ),
    )
    parser.add_argument(
        "--max-items",
        type=int,
        required=True,
        help=f"maximum events to claim (1..{MAX_ITEMS_PER_RUN})",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = WorkerConfig.from_env()
        summary = PresensiDeliveryWorker(config).run(max_items=args.max_items)
    except (ConfigurationError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": _sanitize_error_code(type(exc).__name__)}))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 1 if summary["fatal_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
