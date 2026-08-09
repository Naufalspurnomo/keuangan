"""Durable retry queue for failed ledger writes.

Postgres is used when STATE_DATABASE_URL/DATABASE_URL is configured. The JSON
file remains a development fallback only; Koyeb production should enable the
Postgres backend.
"""

import hashlib
import json
import os
import threading
import time
import uuid
from typing import Dict, List

from security import secure_log


QUEUE_FILE = "pending_writes.json"
RETRY_DELAYS_SECONDS = (5, 30, 120, 600, 3600)
_queue_lock = threading.Lock()
_db_init_lock = threading.Lock()
_db_initialized = False


def _database_url() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _dedup_key(transaction: Dict, metadata: Dict) -> str:
    message_id = str(transaction.get("message_id") or "").strip()
    route = "|".join(
        str(metadata.get(key) or "").strip()
        for key in ("dompet_sheet", "company", "nama_projek", "source_wallet", "category")
    )
    if message_id:
        raw = f"{message_id}|{route}"
    else:
        raw = json.dumps(
            {"transaction": transaction, "metadata": metadata},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_db() -> bool:
    global _db_initialized
    dsn = _database_url()
    if not dsn:
        return False
    if _db_initialized:
        return True
    with _db_init_lock:
        if _db_initialized:
            return True
        try:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS transaction_retry_queue (
                            id UUID PRIMARY KEY,
                            dedup_key TEXT NOT NULL UNIQUE,
                            transaction JSONB NOT NULL,
                            metadata JSONB NOT NULL,
                            status TEXT NOT NULL DEFAULT 'pending',
                            attempts INTEGER NOT NULL DEFAULT 0,
                            last_error TEXT,
                            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_transaction_retry_due
                        ON transaction_retry_queue (status, next_attempt_at)
                        """
                    )
            _db_initialized = True
            secure_log("INFO", "Durable Postgres retry queue ready")
        except Exception as exc:
            # A transient database outage must not discard the failed write. Fall
            # back to the local queue; the caller still reports the original
            # write failure and the worker will retry when the provider recovers.
            secure_log("ERROR", f"Retry queue Postgres unavailable; using local fallback: {type(exc).__name__}")
            return False
    return True


def load_queue() -> List[Dict]:
    """Load the local development fallback queue."""
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_queue(queue: List[Dict]) -> None:
    """Save the local development fallback queue."""
    try:
        with open(QUEUE_FILE, "w", encoding="utf-8") as handle:
            json.dump(queue, handle, indent=2, ensure_ascii=False, default=str)
    except OSError as exc:
        secure_log("ERROR", f"Failed to save local retry queue: {exc}")


def add_to_retry_queue(transaction: Dict, metadata: Dict) -> str:
    """Queue one failed write, deduplicated by source message and route."""
    queue_id = str(uuid.uuid4())
    dedup_key = _dedup_key(transaction, metadata)
    if _ensure_db():
        import psycopg
        from psycopg.types.json import Jsonb

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO transaction_retry_queue
                        (id, dedup_key, transaction, metadata)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (dedup_key) DO UPDATE SET
                        status = CASE
                            WHEN transaction_retry_queue.status = 'processing'
                            THEN transaction_retry_queue.status
                            ELSE 'pending'
                        END,
                        next_attempt_at = LEAST(transaction_retry_queue.next_attempt_at, NOW()),
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (queue_id, dedup_key, Jsonb(transaction), Jsonb(metadata)),
                )
                row = cur.fetchone()
        durable_id = str(row[0])
        secure_log("WARNING", f"Transaction queued durably for retry id={durable_id}")
        return durable_id

    queue_item = {
        "id": queue_id,
        "dedup_key": dedup_key,
        "created_at": time.time(),
        "next_attempt_at": time.time(),
        "attempts": 0,
        "transaction": transaction,
        "metadata": metadata,
    }
    with _queue_lock:
        queue = load_queue()
        existing = next((item for item in queue if item.get("dedup_key") == dedup_key), None)
        if existing:
            existing["next_attempt_at"] = min(existing.get("next_attempt_at", time.time()), time.time())
            queue_id = existing["id"]
        else:
            queue.append(queue_item)
        save_queue(queue)
    secure_log("WARNING", f"Transaction queued in local fallback id={queue_id}")
    return queue_id


def get_queue_status() -> Dict:
    """Return queue depth and age for health/watchdog reporting."""
    if _ensure_db():
        import psycopg

        with psycopg.connect(_database_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*), EXTRACT(EPOCH FROM MIN(created_at))
                    FROM transaction_retry_queue
                    WHERE status <> 'processed'
                    """
                )
                count, oldest = cur.fetchone()
        return {"backend": "postgres", "count": int(count), "oldest": oldest, "file_size": 0}

    with _queue_lock:
        queue = load_queue()
        return {
            "backend": "local",
            "count": len(queue),
            "oldest": min((item.get("created_at", 0) for item in queue), default=None),
            "file_size": os.path.getsize(QUEUE_FILE) if os.path.exists(QUEUE_FILE) else 0,
        }


def _retry_delay(attempts: int) -> int:
    index = min(max(0, attempts), len(RETRY_DELAYS_SECONDS) - 1)
    return RETRY_DELAYS_SECONDS[index]


def _process_db_queue(process_func) -> int:
    import psycopg

    dsn = _database_url()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH due AS (
                    SELECT id
                    FROM transaction_retry_queue
                    WHERE (
                        status IN ('pending', 'retry')
                        AND next_attempt_at <= NOW()
                    ) OR (
                        status = 'processing'
                        AND updated_at < NOW() - INTERVAL '5 minutes'
                    )
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 20
                )
                UPDATE transaction_retry_queue q
                SET status = 'processing', updated_at = NOW()
                FROM due
                WHERE q.id = due.id
                RETURNING q.id, q.transaction, q.metadata, q.attempts
                """
            )
            items = cur.fetchall()
        conn.commit()

    successes = 0
    for queue_id, transaction, metadata, attempts in items:
        error = None
        try:
            success = bool(process_func(transaction, metadata))
            if not success:
                error = "processor_returned_false"
        except Exception as exc:
            success = False
            error = f"{type(exc).__name__}: {exc}"

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                if success:
                    cur.execute("DELETE FROM transaction_retry_queue WHERE id = %s", (queue_id,))
                    successes += 1
                else:
                    delay = _retry_delay(int(attempts))
                    cur.execute(
                        """
                        UPDATE transaction_retry_queue
                        SET status = 'retry', attempts = attempts + 1,
                            last_error = %s,
                            next_attempt_at = NOW() + (%s * INTERVAL '1 second'),
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        ((error or "retry_failed")[:500], delay, queue_id),
                    )
    return successes


def _process_local_queue(process_func) -> int:
    now = time.time()
    with _queue_lock:
        queue = load_queue()
    due = [item for item in queue if float(item.get("next_attempt_at", 0) or 0) <= now]
    if not due:
        return 0

    successes = 0
    due_ids = {item["id"] for item in due}
    remaining = [item for item in queue if item.get("id") not in due_ids]
    for item in due:
        try:
            success = bool(process_func(item["transaction"], item["metadata"]))
        except Exception as exc:
            success = False
            item["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
        if success:
            successes += 1
            continue
        attempts = int(item.get("attempts", 0)) + 1
        item["attempts"] = attempts
        item["next_attempt_at"] = time.time() + _retry_delay(attempts - 1)
        remaining.append(item)

    with _queue_lock:
        save_queue(remaining)
    return successes


def process_retry_queue(process_func) -> int:
    """Process due retry jobs once."""
    if _ensure_db():
        return _process_db_queue(process_func)
    return _process_local_queue(process_func)
