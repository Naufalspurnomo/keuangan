"""Durable idempotency claims for validated dashboard write requests.

This module owns coordination evidence only. It never writes the financial
ledger and never falls back to process memory when Postgres is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from dashboard_api.write_contracts import TransactionRequest


class DashboardWriteRequestUnavailable(RuntimeError):
    """The durable coordinator cannot safely accept a write request."""


class DashboardWriteRequestConflict(RuntimeError):
    """An idempotency key was already claimed for different request bytes."""


@dataclass(frozen=True, slots=True)
class DashboardWriteClaim:
    """Stored state for one durable dashboard write request."""

    request_id: int
    idempotency_key_hash: str
    request_hash: str
    canonical_request: dict[str, Any]
    actor: dict[str, Any]
    message_id: str
    status: str
    completion_response: dict[str, Any] | None
    claimed: bool


ConnectionFactory = Callable[..., Any]
_ALLOWED_COMPLETION_STATUSES = frozenset({"completed", "failed"})
_SELECT_COLUMNS = """
    id, idempotency_key_hash, request_hash, canonical_request,
    actor, message_id, status, completion_response
"""


def _database_url() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _default_connection_factory(dsn: str):
    import psycopg

    return psycopg.connect(dsn)


def _canonical_json(value: Any, *, label: str) -> tuple[str, Any]:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{label} must contain only JSON values") from exc
    return serialized, json.loads(serialized)


def _canonical_request(request: TransactionRequest) -> tuple[str, dict[str, Any]]:
    if not isinstance(request, TransactionRequest):
        raise TypeError("request must be a validated TransactionRequest")
    values = asdict(request)
    request_date = values.get("date")
    if not isinstance(request_date, date):
        raise TypeError("request date must be datetime.date")
    values["date"] = request_date.isoformat()
    serialized, canonical = _canonical_json(values, label="request")
    return serialized, canonical


def _decode_json_object(value: Any, *, column: str) -> dict[str, Any] | None:
    if value is None:
        return None
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise DashboardWriteRequestUnavailable(f"stored {column} is not a JSON object")
    return dict(decoded)


def _claim_from_row(row: Any, *, claimed: bool) -> DashboardWriteClaim:
    if not row or len(row) != 8:
        raise DashboardWriteRequestUnavailable("database returned an invalid write request row")
    return DashboardWriteClaim(
        request_id=int(row[0]),
        idempotency_key_hash=str(row[1]),
        request_hash=str(row[2]),
        canonical_request=_decode_json_object(row[3], column="canonical_request") or {},
        actor=_decode_json_object(row[4], column="actor") or {},
        message_id=str(row[5]),
        status=str(row[6]),
        completion_response=_decode_json_object(row[7], column="completion_response"),
        claimed=claimed,
    )


class DashboardWriteRequestStore:
    """Postgres-backed claim and replay store for dashboard ledger requests."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._dsn = str(dsn or "").strip()
        self._connection_factory = connection_factory or _default_connection_factory

    def _connect(self):
        dsn = self._dsn or _database_url()
        if not dsn:
            raise DashboardWriteRequestUnavailable(
                "Dashboard write request store requires STATE_DATABASE_URL or DATABASE_URL"
            )
        try:
            return self._connection_factory(dsn)
        except DashboardWriteRequestUnavailable:
            raise
        except Exception as exc:
            raise DashboardWriteRequestUnavailable(
                f"Dashboard write request database unavailable: {type(exc).__name__}"
            ) from exc

    def claim(
        self,
        request: TransactionRequest,
        *,
        actor: Mapping[str, Any],
        message_id: str,
    ) -> DashboardWriteClaim:
        """Atomically claim a validated request or replay its stored state."""

        request_json, canonical_request = _canonical_request(request)
        if not isinstance(actor, Mapping):
            raise TypeError("actor must be a mapping")
        actor_json, _ = _canonical_json(dict(actor), label="actor")
        canonical_message_id = str(message_id or "").strip()
        if not canonical_message_id:
            raise ValueError("message_id is required")

        key_hash = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()
        request_hash = hashlib.sha256(request_json.encode("utf-8")).hexdigest()

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO dashboard_write_requests (
                            idempotency_key_hash, request_hash, canonical_request,
                            actor, message_id, status
                        ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, 'claimed')
                        ON CONFLICT (idempotency_key_hash) DO NOTHING
                        RETURNING {_SELECT_COLUMNS}
                        """,
                        (key_hash, request_hash, request_json, actor_json, canonical_message_id),
                    )
                    row = cursor.fetchone()
                    if row:
                        claim = _claim_from_row(row, claimed=True)
                    else:
                        cursor.execute(
                            f"""
                            SELECT {_SELECT_COLUMNS}
                            FROM dashboard_write_requests
                            WHERE idempotency_key_hash = %s
                            """,
                            (key_hash,),
                        )
                        existing = cursor.fetchone()
                        if not existing:
                            raise DashboardWriteRequestUnavailable(
                                "idempotency claim disappeared before replay"
                            )
                        claim = _claim_from_row(existing, claimed=False)
        except (DashboardWriteRequestConflict, DashboardWriteRequestUnavailable):
            raise
        except Exception as exc:
            raise DashboardWriteRequestUnavailable(
                f"Dashboard write request database unavailable: {type(exc).__name__}"
            ) from exc

        if claim.request_hash != request_hash or claim.canonical_request != canonical_request:
            raise DashboardWriteRequestConflict(
                "idempotency key already belongs to a different canonical request"
            )
        return claim

    def complete(
        self,
        claim: DashboardWriteClaim,
        response: Mapping[str, Any],
        *,
        status: str = "completed",
    ) -> DashboardWriteClaim:
        """Persist the terminal response returned for subsequent safe replays."""

        if not isinstance(claim, DashboardWriteClaim):
            raise TypeError("claim must be a DashboardWriteClaim")
        if status not in _ALLOWED_COMPLETION_STATUSES:
            raise ValueError("status must be completed or failed")
        if not isinstance(response, Mapping):
            raise TypeError("response must be a mapping")
        response_json, _ = _canonical_json(dict(response), label="response")

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE dashboard_write_requests
                        SET completion_response = %s::jsonb,
                            status = %s,
                            completed_at = NOW(),
                            updated_at = NOW()
                        WHERE idempotency_key_hash = %s
                          AND request_hash = %s
                        RETURNING {_SELECT_COLUMNS}
                        """,
                        (
                            response_json,
                            status,
                            claim.idempotency_key_hash,
                            claim.request_hash,
                        ),
                    )
                    row = cursor.fetchone()
        except DashboardWriteRequestUnavailable:
            raise
        except Exception as exc:
            raise DashboardWriteRequestUnavailable(
                f"Dashboard write request database unavailable: {type(exc).__name__}"
            ) from exc

        if not row:
            raise DashboardWriteRequestConflict(
                "stored write request no longer matches the claimed request"
            )
        return _claim_from_row(row, claimed=False)
