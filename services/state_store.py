"""
Optional external state backends for production durability.

The bot can keep using local JSON + Google Sheets fallback by default. When
STATE_STORE_BACKEND=postgres is configured, this module stores critical bot
state in Postgres without changing callers in state_manager.
"""

import os
import threading
from typing import Any, Dict, Optional

from security import secure_log


_STORE_LOCK = threading.Lock()
_STORE = None
_STORE_SIGNATURE = None


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "required"}


def external_state_required() -> bool:
    """Whether unavailable external state should fail closed."""
    return _truthy(os.getenv("STATE_STORE_REQUIRED"))


class PostgresStateStore:
    """Simple JSONB-backed state store."""

    def __init__(self, dsn: str, state_key: str):
        if not dsn:
            raise ValueError("Postgres DSN is required")
        self.dsn = dsn
        self.state_key = state_key or "default"
        self._initialized = False
        self._init_lock = threading.Lock()

        import psycopg
        from psycopg.types.json import Jsonb

        self._psycopg = psycopg
        self._Jsonb = Jsonb

    def _ensure_table(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            with self._psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS bot_state (
                            key TEXT PRIMARY KEY,
                            payload JSONB NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
            self._initialized = True

    def load(self) -> Optional[Dict[str, Any]]:
        self._ensure_table()
        with self._psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM bot_state WHERE key = %s",
                    (self.state_key,),
                )
                row = cur.fetchone()
        if not row:
            return None
        payload = row[0]
        return payload if isinstance(payload, dict) else None

    def save(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise TypeError("State payload must be a dict")
        self._ensure_table()
        with self._psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_state (key, payload, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (key)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                    """,
                    (self.state_key, self._Jsonb(payload)),
                )


def get_configured_state_store():
    """Return the configured external state store, or None when disabled."""
    global _STORE, _STORE_SIGNATURE

    backend = str(os.getenv("STATE_STORE_BACKEND", "")).strip().lower()
    explicit_dsn = os.getenv("STATE_DATABASE_URL")
    dsn = explicit_dsn or (os.getenv("DATABASE_URL") if backend in {"postgres", "postgresql"} else None)
    state_key = os.getenv("STATE_STORE_KEY", "default")
    signature = (backend, dsn, state_key)

    with _STORE_LOCK:
        if _STORE_SIGNATURE == signature:
            return _STORE

        _STORE_SIGNATURE = signature
        _STORE = None

        if backend in {"", "local", "none", "google_sheets"} and not explicit_dsn:
            return None
        if backend not in {"postgres", "postgresql", ""}:
            secure_log("WARNING", f"Unknown STATE_STORE_BACKEND '{backend}', external state disabled")
            return None
        if not dsn:
            secure_log("ERROR", "STATE_STORE_BACKEND=postgres requires STATE_DATABASE_URL or DATABASE_URL")
            return None

        try:
            _STORE = PostgresStateStore(dsn, state_key)
            secure_log("INFO", "External Postgres state store configured", state_key=state_key)
        except Exception as e:
            secure_log("ERROR", f"External Postgres state store unavailable: {type(e).__name__}: {e}")
            _STORE = None
        return _STORE


def reset_state_store_cache_for_tests() -> None:
    """Reset cached store after tests patch environment."""
    global _STORE, _STORE_SIGNATURE
    with _STORE_LOCK:
        _STORE = None
        _STORE_SIGNATURE = None
