"""Durable one-way delivery of canonical finance outbox rows to a derived export."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


EXPORT_SCHEMA_VERSION = "canonical.finance.export.v1"


class RemoteExportDrift(RuntimeError):
    """The protected remote destination differs from the canonical outbox."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ClaimedExport:
    id: str
    export_ordinal: int
    export_key: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    payload: Mapping[str, Any]
    payload_sha256: str
    created_at: str
    claim_token: str

    def __post_init__(self) -> None:
        for field in ("id", "aggregate_id", "claim_token"):
            try:
                normalized = str(uuid.UUID(str(getattr(self, field))))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"{field} must be UUID") from exc
            object.__setattr__(self, field, normalized)
        if isinstance(self.export_ordinal, bool) or self.export_ordinal < 1:
            raise ValueError("export_ordinal must be a positive integer")
        if isinstance(self.aggregate_version, bool) or self.aggregate_version < 1:
            raise ValueError("aggregate_version must be a positive integer")
        payload = dict(self.payload)
        if _sha256(_canonical_json(payload)) != self.payload_sha256:
            raise ValueError("outbox payload hash mismatch")
        object.__setattr__(self, "payload", payload)

    @property
    def document(self) -> dict[str, Any]:
        body = {
            "export_ordinal": self.export_ordinal,
            "export_schema_version": EXPORT_SCHEMA_VERSION,
            "export_key": self.export_key,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "outbox_created_at_utc": self.created_at,
            "payload_sha256": self.payload_sha256,
            "payload_json": _canonical_json(self.payload),
        }
        body["row_sha256"] = _sha256(_canonical_json(body))
        return body


class ExportOutbox(Protocol):
    def claim(self, *, limit: int, lease_seconds: int) -> list[ClaimedExport]: ...

    def acknowledge(
        self, row_id: str, claim_token: str, remote_locator: str
    ) -> bool: ...

    def fail(self, row_id: str, claim_token: str, error: str) -> bool: ...

    def mark_drifted(self, row_id: str, claim_token: str, error: str) -> bool: ...


class RemoteExport(Protocol):
    def read(self, ordinal: int) -> Mapping[str, Any] | None: ...

    def write(self, ordinal: int, document: Mapping[str, Any]) -> None: ...


class ExportWorker:
    def __init__(
        self,
        *,
        outbox: ExportOutbox,
        remote: RemoteExport,
        protected_destination: bool,
        lease_seconds: int = 300,
        after_remote_write: Callable[[ClaimedExport], None] | None = None,
    ) -> None:
        self._outbox = outbox
        self._remote = remote
        self._protected = protected_destination
        self._lease_seconds = lease_seconds
        self._after_remote_write = after_remote_write

    def run_once(self, *, limit: int = 100) -> dict[str, int]:
        if not self._protected:
            raise RemoteExportDrift("canonical export requires a protected destination")
        counts = {
            "claimed": 0,
            "written": 0,
            "unchanged": 0,
            "exported": 0,
            "drifted": 0,
            "failed": 0,
        }
        claimed = self._outbox.claim(limit=limit, lease_seconds=self._lease_seconds)
        counts["claimed"] = len(claimed)
        for row in claimed:
            try:
                expected = row.document
                observed = self._remote.read(row.export_ordinal)
                if observed is None:
                    self._remote.write(row.export_ordinal, expected)
                    counts["written"] += 1
                    if self._after_remote_write is not None:
                        self._after_remote_write(row)
                    observed = self._remote.read(row.export_ordinal)
                else:
                    counts["unchanged"] += 1
                if observed is None or _canonical_json(dict(observed)) != _canonical_json(expected):
                    message = f"remote export drift at ordinal {row.export_ordinal}"
                    self._outbox.mark_drifted(row.id, row.claim_token, message)
                    counts["drifted"] += 1
                    continue
                locator = f"row:{row.export_ordinal}:sha256:{expected['row_sha256']}"
                if not self._outbox.acknowledge(row.id, row.claim_token, locator):
                    raise RuntimeError("outbox acknowledgement lost its claim")
                counts["exported"] += 1
            except RemoteExportDrift as exc:
                self._outbox.mark_drifted(row.id, row.claim_token, str(exc))
                counts["drifted"] += 1
            except Exception as exc:
                self._outbox.fail(row.id, row.claim_token, f"{type(exc).__name__}: {exc}")
                counts["failed"] += 1
        return counts


class PostgresExportOutbox:
    """Token-guarded claim/ack boundary for financial_export_outbox."""

    _RETURNING = """
        outbox.id, outbox.export_ordinal, outbox.export_key,
        outbox.aggregate_type, outbox.aggregate_id, outbox.aggregate_version,
        outbox.payload, outbox.payload_sha256, outbox.created_at,
        outbox.claim_token
    """

    def __init__(
        self, dsn: str, *, connection_factory: Callable[..., Any] | None = None
    ) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("export outbox requires a database DSN")
        self._connection_factory = connection_factory

    def _connect(self):
        if self._connection_factory is not None:
            return self._connection_factory(self._dsn)
        import psycopg

        return psycopg.connect(self._dsn)

    @staticmethod
    def _row(values: tuple[Any, ...]) -> ClaimedExport:
        payload = values[6]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return ClaimedExport(
            id=str(values[0]),
            export_ordinal=int(values[1]),
            export_key=str(values[2]),
            aggregate_type=str(values[3]),
            aggregate_id=str(values[4]),
            aggregate_version=int(values[5]),
            payload=dict(payload),
            payload_sha256=str(values[7]),
            created_at=values[8].isoformat().replace("+00:00", "Z")
            if hasattr(values[8], "isoformat")
            else str(values[8]),
            claim_token=str(values[9]),
        )

    def claim(self, *, limit: int, lease_seconds: int) -> list[ClaimedExport]:
        if limit < 1 or lease_seconds < 1:
            raise ValueError("claim limit and lease must be positive")
        claim_token = str(uuid.uuid4())
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH eligible AS (
                        SELECT id
                        FROM financial_export_outbox
                        WHERE (
                            status IN ('pending', 'failed') AND available_at <= now()
                        ) OR (
                            status = 'exporting'
                            AND claimed_at < now() - (%s * interval '1 second')
                        )
                        ORDER BY export_ordinal
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                    )
                    UPDATE financial_export_outbox AS outbox
                    SET status = 'exporting',
                        attempts = outbox.attempts + 1,
                        claimed_at = now(),
                        claim_token = %s,
                        last_error = NULL,
                        updated_at = now()
                    FROM eligible
                    WHERE outbox.id = eligible.id
                    RETURNING {self._RETURNING}
                    """,
                    (lease_seconds, limit, claim_token),
                )
                rows = [self._row(tuple(values)) for values in cursor.fetchall()]
            connection.commit()
            return rows
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _transition(
        self,
        row_id: str,
        claim_token: str,
        *,
        status: str,
        error: str | None = None,
        remote_locator: str | None = None,
    ) -> bool:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE financial_export_outbox
                    SET status = %s,
                        exported_at = CASE WHEN %s = 'exported' THEN now() ELSE exported_at END,
                        remote_locator = COALESCE(%s, remote_locator),
                        last_error = %s,
                        available_at = CASE
                            WHEN %s = 'failed' THEN now() + interval '30 seconds'
                            ELSE available_at
                        END,
                        claim_token = NULL,
                        updated_at = now()
                    WHERE id = %s AND status = 'exporting' AND claim_token = %s
                    """,
                    (
                        status,
                        status,
                        remote_locator,
                        error,
                        status,
                        row_id,
                        claim_token,
                    ),
                )
                changed = cursor.rowcount == 1
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def acknowledge(self, row_id: str, claim_token: str, remote_locator: str) -> bool:
        return self._transition(
            row_id,
            claim_token,
            status="exported",
            remote_locator=remote_locator,
        )

    def fail(self, row_id: str, claim_token: str, error: str) -> bool:
        return self._transition(row_id, claim_token, status="failed", error=error[:2000])

    def mark_drifted(self, row_id: str, claim_token: str, error: str) -> bool:
        return self._transition(row_id, claim_token, status="drifted", error=error[:2000])
