"""Durable WhatsApp event inbox and recovery claims.

The webhook records normalized evidence here before acknowledging processing.
Postgres is shared across Koyeb replicas; the in-memory backend is development
only and intentionally exposes its degraded status through ``inbox_health``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from security import secure_log


class InboxUnavailable(RuntimeError):
    pass


class ReviewNotFound(LookupError):
    """The exact inbox event key does not exist."""


class ReviewConflict(RuntimeError):
    """The event is no longer in a reviewable lifecycle state."""


class ReviewValidationError(ValueError):
    """A review action attempted to bypass its proof or status constraints."""


REVIEW_ACTION_STATUSES = {
    "ignore": "ignored",
    "confirm_processed": "processed",
}
REVIEW_RESULT_STATUSES = {
    "ignore": "review_ignored",
    "confirm_processed": "review_confirmed_processed",
}
_REVIEW_METADATA_COLUMNS = (
    "event_key, provider, message_id, event_type, is_group, finance_signal, "
    "payload_score, status, result_status, attempts, received_at, updated_at"
)


_init_lock = threading.Lock()
_initialized = False
_memory_lock = threading.Lock()
_memory_events: Dict[str, dict] = {}
_memory_review_audit: list[dict[str, Any]] = []


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "required"}


def _database_url() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def inbox_required() -> bool:
    configured = os.getenv("DURABLE_INBOX_REQUIRED")
    if configured is not None:
        return _truthy(configured)
    return _truthy(os.getenv("STATE_STORE_REQUIRED"))


def review_writes_enabled() -> bool:
    return _truthy(os.getenv("INBOX_REVIEW_WRITES_ENABLED"))


def _event_key(event: dict) -> str:
    provider = str(event.get("provider") or "wuzapi")
    chat_id = str(event.get("chat_id") or "")
    message_id = str(event.get("message_id") or "")
    if not message_id:
        message_id = str(event.get("fallback_id") or uuid.uuid4())
    raw = f"{provider}|{chat_id}|{message_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_db() -> bool:
    global _initialized
    dsn = _database_url()
    if not dsn:
        if inbox_required():
            raise InboxUnavailable("Durable inbox requires STATE_DATABASE_URL or DATABASE_URL")
        return False
    if _initialized:
        return True
    with _init_lock:
        if _initialized:
            return True
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS transaction_inbox (
                            event_key TEXT PRIMARY KEY,
                            provider TEXT NOT NULL,
                            message_id TEXT NOT NULL,
                            chat_id TEXT NOT NULL,
                            sender_id TEXT NOT NULL,
                            sender_name TEXT,
                            sender_jid TEXT,
                            event_type TEXT NOT NULL,
                            body_text TEXT,
                            media_data TEXT,
                            media_path TEXT,
                            quoted_message_id TEXT,
                            is_group BOOLEAN NOT NULL DEFAULT FALSE,
                            finance_signal BOOLEAN NOT NULL DEFAULT FALSE,
                            payload_score INTEGER NOT NULL DEFAULT 0,
                            status TEXT NOT NULL DEFAULT 'received',
                            result_status TEXT,
                            attempts INTEGER NOT NULL DEFAULT 0,
                            last_error TEXT,
                            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_transaction_inbox_recovery
                        ON transaction_inbox (status, next_attempt_at, received_at)
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_transaction_inbox_pair
                        ON transaction_inbox (chat_id, sender_id, received_at)
                        """
                    )
            _initialized = True
            secure_log("INFO", "Durable Postgres transaction inbox ready")
            return True
        except Exception as exc:
            if inbox_required():
                raise InboxUnavailable(f"Durable inbox unavailable: {type(exc).__name__}: {exc}") from exc
            secure_log("ERROR", f"Durable inbox degraded to memory: {type(exc).__name__}: {exc}")
            return False


def capture_event(event: dict) -> str:
    """Persist or upgrade one normalized provider event and return its key."""
    key = _event_key(event)
    normalized = {
        "event_key": key,
        "provider": str(event.get("provider") or "wuzapi"),
        "message_id": str(event.get("message_id") or ""),
        "chat_id": str(event.get("chat_id") or ""),
        "sender_id": str(event.get("sender_id") or ""),
        "sender_name": str(event.get("sender_name") or "User"),
        "sender_jid": str(event.get("sender_jid") or ""),
        "event_type": str(event.get("event_type") or "text"),
        "body_text": str(event.get("body_text") or ""),
        "media_data": event.get("media_data"),
        "media_path": event.get("media_path"),
        "quoted_message_id": str(event.get("quoted_message_id") or ""),
        "is_group": bool(event.get("is_group")),
        "finance_signal": bool(event.get("finance_signal")),
        "payload_score": int(event.get("payload_score") or 0),
        "status": "received",
        "received_at": datetime.now(timezone.utc),
    }
    if _ensure_db():
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO transaction_inbox (
                        event_key, provider, message_id, chat_id, sender_id,
                        sender_name, sender_jid, event_type, body_text, media_data,
                        media_path, quoted_message_id, is_group, finance_signal,
                        payload_score
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (event_key) DO UPDATE SET
                        body_text = CASE
                            WHEN EXCLUDED.payload_score >= transaction_inbox.payload_score
                            THEN EXCLUDED.body_text ELSE transaction_inbox.body_text END,
                        media_data = COALESCE(EXCLUDED.media_data, transaction_inbox.media_data),
                        media_path = COALESCE(EXCLUDED.media_path, transaction_inbox.media_path),
                        quoted_message_id = COALESCE(NULLIF(EXCLUDED.quoted_message_id, ''), transaction_inbox.quoted_message_id),
                        finance_signal = transaction_inbox.finance_signal OR EXCLUDED.finance_signal,
                        payload_score = GREATEST(transaction_inbox.payload_score, EXCLUDED.payload_score),
                        updated_at = NOW()
                    """,
                    (
                        key, normalized["provider"], normalized["message_id"], normalized["chat_id"],
                        normalized["sender_id"], normalized["sender_name"], normalized["sender_jid"],
                        normalized["event_type"], normalized["body_text"], normalized["media_data"],
                        normalized["media_path"], normalized["quoted_message_id"], normalized["is_group"],
                        normalized["finance_signal"], normalized["payload_score"],
                    ),
                )
        return key

    with _memory_lock:
        existing = _memory_events.get(key)
        if not existing or normalized["payload_score"] >= existing.get("payload_score", 0):
            if existing and not normalized.get("media_data"):
                normalized["media_data"] = existing.get("media_data")
            _memory_events[key] = normalized
    return key


def mark_event(event_key: str, status: str, *, result_status: str = "", error: str = "") -> None:
    """Set the durable lifecycle status for one provider event."""
    if not event_key:
        return
    if _ensure_db():
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE transaction_inbox
                    SET status = %s, result_status = NULLIF(%s, ''),
                        last_error = NULLIF(%s, ''), updated_at = NOW(),
                        next_attempt_at = CASE
                            WHEN %s = 'retryable' THEN NOW() + INTERVAL '30 seconds'
                            ELSE next_attempt_at END
                    WHERE event_key = %s
                    """,
                    (status, result_status, error[:500], status, event_key),
                )
        return
    with _memory_lock:
        if event_key in _memory_events:
            _memory_events[event_key].update(
                status=status,
                result_status=result_status,
                last_error=error[:500],
                updated_at=datetime.now(timezone.utc),
            )


def mark_source_event(provider: str, chat_id: str, message_id: str, status: str,
                      *, result_status: str = "", error: str = "") -> None:
    """Mark an event when the caller has provider identifiers instead of its hash."""
    if not message_id:
        return
    mark_event(
        _event_key({"provider": provider, "chat_id": chat_id, "message_id": message_id}),
        status,
        result_status=result_status,
        error=error,
    )


def claim_recovery_bundle(pair_window_seconds: int = 30) -> Optional[dict]:
    """Claim one stale event and its strongest deterministic counterpart."""
    if not _ensure_db():
        return None
    import psycopg

    with psycopg.connect(_database_url()) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM transaction_inbox
                WHERE (
                    status = 'waiting_pair' AND updated_at < NOW() - (%s * INTERVAL '1 second')
                ) OR (
                    status IN ('received', 'retryable') AND next_attempt_at <= NOW()
                    AND updated_at < NOW() - INTERVAL '15 seconds'
                ) OR (
                    status = 'needs_review' AND finance_signal = TRUE
                    AND updated_at < NOW() - (%s * INTERVAL '1 second')
                ) OR (
                    status = 'processing' AND updated_at < NOW() - INTERVAL '5 minutes'
                )
                ORDER BY received_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (pair_window_seconds, pair_window_seconds),
            )
            primary = cur.fetchone()
            if not primary:
                conn.commit()
                return None

            counterpart = None
            opposite = "text" if primary["event_type"] == "image" else "image"
            cur.execute(
                """
                SELECT *
                FROM transaction_inbox
                WHERE chat_id = %s AND sender_id = %s AND event_type = %s
                  AND event_key <> %s
                  AND status IN ('received', 'waiting_pair', 'needs_review', 'ignored')
                  AND received_at BETWEEN %s - (%s * INTERVAL '1 second')
                                      AND %s + (%s * INTERVAL '1 second')
                ORDER BY ABS(EXTRACT(EPOCH FROM (received_at - %s)))
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (
                    primary["chat_id"], primary["sender_id"], opposite, primary["event_key"],
                    primary["received_at"], pair_window_seconds,
                    primary["received_at"], pair_window_seconds,
                    primary["received_at"],
                ),
            )
            counterpart = cur.fetchone()
            if counterpart and counterpart["event_type"] == "text" and not counterpart["finance_signal"]:
                counterpart = None
            keys = [primary["event_key"]]
            if counterpart:
                keys.append(counterpart["event_key"])
            cur.execute(
                """
                UPDATE transaction_inbox
                SET status = 'processing', attempts = attempts + 1, updated_at = NOW()
                WHERE event_key = ANY(%s)
                """,
                (keys,),
            )
        conn.commit()
    return {"primary": dict(primary), "counterpart": dict(counterpart) if counterpart else None}


def complete_bundle(bundle: dict, status: str, result_status: str = "", error: str = "") -> None:
    """Complete both source events in a claimed recovery bundle."""
    for name in ("primary", "counterpart"):
        event = bundle.get(name) if isinstance(bundle, dict) else None
        if event:
            mark_event(event.get("event_key"), status, result_status=result_status, error=error)


def inbox_health() -> dict:
    """Return durability state and backlog size without exposing message data."""
    if _ensure_db():
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status NOT IN ('processed', 'ignored')),
                           COUNT(*) FILTER (WHERE status LIKE 'needs_review%%'),
                           EXTRACT(EPOCH FROM (NOW() - MIN(received_at) FILTER (
                               WHERE status LIKE 'needs_review%%'
                           )))
                    FROM transaction_inbox
                    """
                )
                backlog, review, oldest_seconds = cur.fetchone()
        schema = inbox_review_schema_health()
        return {
            "backend": "postgres", "durable": True, "backlog": int(backlog),
            "needs_review": int(review),
            "oldest_review_age_seconds": int(oldest_seconds) if oldest_seconds is not None else None,
            "review_writes_enabled": review_writes_enabled(),
            "review_schema_ready": bool(schema.get("ready")),
            "review_audit_ready": bool(schema.get("audit_ready")),
        }
    with _memory_lock:
        review = sum(1 for event in _memory_events.values() if str(event.get("status") or "").startswith("needs_review"))
        backlog = sum(1 for event in _memory_events.values() if event.get("status") not in {"processed", "ignored"})
    return {
        "backend": "memory", "durable": False, "backlog": backlog, "needs_review": review,
        "oldest_review_age_seconds": None, "review_writes_enabled": review_writes_enabled(),
        "review_schema_ready": False, "review_audit_ready": False,
    }


def inbox_review_schema_health() -> dict[str, Any]:
    """Read back migration-owned review schema without mutating it."""
    if not _database_url():
        return {"configured": False, "ready": False, "audit_ready": False}
    try:
        import psycopg

        required_columns = {
            "command_key", "request_hash", "event_key", "message_id", "action", "expected_status",
            "previous_status", "resulting_status", "actor", "reason", "ledger_proof",
            "event_snapshot_hash", "reviewed_at",
        }
        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'transaction_inbox_review_audit'
                    """
                )
                columns = {str(row[0]) for row in cur.fetchall()}
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'uq_transaction_inbox_review_command'
                    ), EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'trg_inbox_review_audit_append_only'
                          AND NOT tgisinternal
                    )
                    """
                )
                command_index, append_only = cur.fetchone()
        ready = required_columns.issubset(columns) and bool(command_index) and bool(append_only)
        return {
            "configured": True, "ready": ready, "audit_ready": ready,
            "columns": required_columns.issubset(columns),
            "command_index": bool(command_index), "append_only": bool(append_only),
        }
    except Exception as exc:
        secure_log("ERROR", f"Inbox review schema health failed: {type(exc).__name__}")
        return {"configured": True, "ready": False, "audit_ready": False}


def _review_metadata(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event.get(key)
        for key in (
            "event_key", "provider", "message_id", "event_type", "is_group",
            "finance_signal", "payload_score", "status", "result_status",
            "attempts", "received_at", "updated_at",
        )
    }


def list_review_events(*, limit: int = 50) -> list[dict[str, Any]]:
    """List private review metadata without message text, identities, or media."""
    safe_limit = max(1, min(int(limit), 100))
    if _ensure_db():
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT {_REVIEW_METADATA_COLUMNS}
                    FROM transaction_inbox
                    WHERE status LIKE 'needs_review%%'
                    ORDER BY received_at
                    LIMIT %s
                    """,  # nosec B608 -- selected columns are a private module constant
                    (safe_limit,),
                )
                return [dict(row) for row in cur.fetchall()]
    with _memory_lock:
        rows = [
            _review_metadata(event)
            for event in _memory_events.values()
            if str(event.get("status") or "").startswith("needs_review")
        ]
    rows.sort(key=lambda row: str(row.get("received_at") or ""))
    return rows[:safe_limit]


def get_review_event(event_key: str) -> dict[str, Any] | None:
    """Return one explicit review event for the owner-only detail route."""
    key = str(event_key or "").strip()
    if not key:
        return None
    if _ensure_db():
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(
                    """
                    SELECT event_key, provider, message_id, event_type, body_text,
                           quoted_message_id, is_group, finance_signal, payload_score,
                           status, result_status, attempts, received_at, updated_at,
                           (NULLIF(media_data, '') IS NOT NULL OR NULLIF(media_path, '') IS NOT NULL)
                               AS media_available
                    FROM transaction_inbox
                    WHERE event_key = %s AND status LIKE 'needs_review%%'
                    """,
                    (key,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    with _memory_lock:
        event = _memory_events.get(key)
        if not event or not str(event.get("status") or "").startswith("needs_review"):
            return None
        return dict(event)


def _review_request_hash(
    *,
    event_key: str,
    action: str,
    actor: str,
    reason: str,
    expected_status: str,
) -> str:
    return hashlib.sha256(json.dumps(
        {
            "event_key": event_key,
            "action": action,
            "actor": actor,
            "reason": reason,
            "expected_status": expected_status,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def get_review_command_result(
    command_key: str,
    *,
    event_key: str,
    action: str,
    actor: str,
    reason: str,
    expected_status: str,
) -> dict[str, Any] | None:
    """Replay a completed owner command before consulting the active review queue."""
    selected_command = str(command_key or "").strip()
    if not selected_command:
        raise ReviewValidationError("command key is required")
    if not _ensure_db() or not inbox_review_schema_health().get("ready"):
        raise InboxUnavailable("durable inbox review schema unavailable")
    request_hash = _review_request_hash(
        event_key=str(event_key or "").strip(),
        action=str(action or "").strip(),
        actor=str(actor or "").strip(),
        reason=str(reason or "").strip(),
        expected_status=str(expected_status or "").strip(),
    )

    import psycopg

    with psycopg.connect(_database_url(), autocommit=True) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT event_key, message_id, action, resulting_status, request_hash
                FROM transaction_inbox_review_audit
                WHERE command_key = %s
                """,
                (selected_command,),
            )
            replay = cur.fetchone()
    if not replay:
        return None
    if str(replay["request_hash"]) != request_hash:
        raise ReviewConflict("idempotency key was reused with another request")
    return {
        "event_key": str(replay["event_key"]),
        "message_id": str(replay["message_id"]),
        "action": str(replay["action"]),
        "status": str(replay["resulting_status"]),
        "replayed": True,
    }


def resolve_review_event(
    event_key: str,
    action: str,
    *,
    actor: str,
    reason: str,
    expected_status: str,
    command_key: str,
    ledger_proof: dict[str, Any],
) -> dict[str, Any]:
    """Resolve one review event through an idempotent audited compare-and-set."""
    key = str(event_key or "").strip()
    selected_action = str(action or "").strip()
    selected_actor = str(actor or "").strip()
    selected_reason = str(reason or "").strip()
    selected_expected = str(expected_status or "").strip()
    selected_command = str(command_key or "").strip()
    if selected_action not in REVIEW_ACTION_STATUSES:
        raise ReviewValidationError("unsupported review action")
    if not all((key, selected_actor, selected_reason, selected_expected, selected_command)):
        raise ReviewValidationError("event, actor, reason, expected status, and command are required")
    if len(selected_actor) > 320 or len(selected_reason) > 1000:
        raise ReviewValidationError("actor or reason is too long")
    if not isinstance(ledger_proof, dict) or ledger_proof.get("status") != "complete":
        raise ReviewValidationError("complete ledger proof is required")
    matches = ledger_proof.get("matches")
    if not isinstance(matches, list):
        raise ReviewValidationError("ledger matches are required")
    if selected_action == "ignore" and matches:
        raise ReviewValidationError("ignore requires zero ledger matches")
    if selected_action == "confirm_processed" and not matches:
        raise ReviewValidationError("confirm_processed requires ledger matches")
    if not review_writes_enabled():
        raise InboxUnavailable("inbox review writes are disabled")

    resulting_status = REVIEW_ACTION_STATUSES[selected_action]
    result_status = REVIEW_RESULT_STATUSES[selected_action]
    if not _ensure_db() or not inbox_review_schema_health().get("ready"):
        raise InboxUnavailable("durable inbox review schema unavailable")
    proof_json = json.dumps(ledger_proof, sort_keys=True, separators=(",", ":"), default=str)
    request_hash = _review_request_hash(
        event_key=key,
        action=selected_action,
        actor=selected_actor,
        reason=selected_reason,
        expected_status=selected_expected,
    )

    import psycopg

    with psycopg.connect(_database_url()) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT event_key, message_id, action, resulting_status, request_hash
                FROM transaction_inbox_review_audit WHERE command_key = %s
                """,
                (selected_command,),
            )
            replay = cur.fetchone()
            if replay:
                if str(replay["request_hash"]) != request_hash:
                    raise ReviewConflict("idempotency key was reused with another request")
                return {
                    "event_key": str(replay["event_key"]),
                    "message_id": str(replay["message_id"]),
                    "action": str(replay["action"]),
                    "status": str(replay["resulting_status"]),
                    "replayed": True,
                }
            cur.execute(
                """
                SELECT event_key, message_id, status, provider, event_type,
                       payload_score, received_at, updated_at
                FROM transaction_inbox WHERE event_key = %s FOR UPDATE
                """,
                (key,),
            )
            row = cur.fetchone()
            if not row:
                raise ReviewNotFound("review event not found")
            previous_status = str(row["status"] or "")
            if previous_status != selected_expected:
                raise ReviewConflict("event status no longer matches reviewed evidence")
            snapshot_hash = hashlib.sha256(json.dumps(
                dict(row), sort_keys=True, separators=(",", ":"), default=str,
            ).encode("utf-8")).hexdigest()
            cur.execute(
                """
                UPDATE transaction_inbox
                SET status = %s, result_status = %s, last_error = NULL, updated_at = NOW()
                WHERE event_key = %s AND status = %s
                RETURNING event_key, message_id, status
                """,
                (resulting_status, result_status, key, selected_expected),
            )
            updated = cur.fetchone()
            if not updated:
                raise ReviewConflict("review event changed concurrently")
            cur.execute(
                """
                INSERT INTO transaction_inbox_review_audit (
                    command_key, request_hash, event_key, message_id, action, expected_status,
                    previous_status, resulting_status, actor, reason, ledger_proof,
                    event_snapshot_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    selected_command, request_hash, key, str(updated["message_id"]),
                    selected_action, selected_expected, previous_status, resulting_status,
                    selected_actor, selected_reason, proof_json, snapshot_hash,
                ),
            )
        conn.commit()
    return {
        "event_key": str(updated["event_key"]),
        "message_id": str(updated["message_id"]),
        "action": selected_action,
        "status": str(updated["status"]),
        "replayed": False,
    }


def prune_inbox() -> int:
    """Delete old terminal events while retaining unresolved review evidence."""
    retention_days = max(1, int(os.getenv("INBOX_RETENTION_DAYS", "14")))
    if not _ensure_db():
        cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
        removed = 0
        with _memory_lock:
            for key, event in list(_memory_events.items()):
                received = event.get("received_at")
                if (
                    event.get("status") in {"processed", "ignored"}
                    and isinstance(received, datetime)
                    and received.timestamp() < cutoff
                ):
                    _memory_events.pop(key, None)
                    removed += 1
        return removed
    import psycopg

    with psycopg.connect(_database_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM transaction_inbox
                WHERE status IN ('processed', 'ignored')
                  AND received_at < NOW() - (%s * INTERVAL '1 day')
                """,
                (retention_days,),
            )
            return int(cur.rowcount or 0)
