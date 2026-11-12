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


class GoogleSheetsRemoteExport:
    """Exact-row adapter for one dedicated, protected derived-export tab."""

    HEADER = (
        "export_ordinal",
        "export_schema_version",
        "export_key",
        "aggregate_type",
        "aggregate_id",
        "aggregate_version",
        "outbox_created_at_utc",
        "payload_sha256",
        "payload_json",
        "row_sha256",
    )
    MAX_CELL_CHARACTERS = 50_000

    def __init__(
        self,
        worksheet: Any,
        *,
        expected_workbook_id: str,
        expected_title: str,
        ensure_header: bool = False,
    ) -> None:
        workbook_id = str(
            getattr(getattr(worksheet, "spreadsheet", None), "id", "") or ""
        ).strip()
        if not expected_workbook_id or workbook_id != expected_workbook_id:
            raise RemoteExportDrift("canonical export workbook identity mismatch")
        if str(getattr(worksheet, "title", "")) != expected_title:
            raise RemoteExportDrift("canonical export tab identity mismatch")
        self._worksheet = worksheet
        if ensure_header:
            observed = list(worksheet.row_values(1))
            if not observed:
                worksheet.update(
                    "A1:J1", [list(self.HEADER)], value_input_option="RAW"
                )
            elif observed != list(self.HEADER):
                raise RemoteExportDrift("canonical export header drift")

    @staticmethod
    def _row_number(ordinal: int) -> int:
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            raise ValueError("export ordinal must be a positive integer")
        return ordinal + 1

    @classmethod
    def _values(cls, document: Mapping[str, Any]) -> list[Any]:
        if set(document) != set(cls.HEADER):
            raise RemoteExportDrift("canonical export document schema mismatch")
        body = {key: document[key] for key in cls.HEADER if key != "row_sha256"}
        if document["row_sha256"] != _sha256(_canonical_json(body)):
            raise RemoteExportDrift("canonical export row hash mismatch")
        values = [document[column] for column in cls.HEADER]
        if any(len(str(value)) > cls.MAX_CELL_CHARACTERS for value in values):
            raise RemoteExportDrift("canonical export cell exceeds Sheets limit")
        return values

    def read(self, ordinal: int) -> Mapping[str, Any] | None:
        values = list(self._worksheet.row_values(self._row_number(ordinal)))
        if not values or not any(value not in (None, "") for value in values):
            return None
        if len(values) != len(self.HEADER):
            raise RemoteExportDrift(f"canonical export row {ordinal} has schema drift")
        result: dict[str, Any] = dict(zip(self.HEADER, values, strict=True))
        try:
            result["export_ordinal"] = int(result["export_ordinal"])
            result["aggregate_version"] = int(result["aggregate_version"])
        except (TypeError, ValueError) as exc:
            raise RemoteExportDrift(
                f"canonical export row {ordinal} has invalid numeric fields"
            ) from exc
        return result

    def write(self, ordinal: int, document: Mapping[str, Any]) -> None:
        expected = dict(document)
        if expected.get("export_ordinal") != ordinal:
            raise RemoteExportDrift("canonical export ordinal/document mismatch")
        current = self.read(ordinal)
        if current is not None:
            if _canonical_json(dict(current)) != _canonical_json(expected):
                raise RemoteExportDrift(
                    f"canonical export row {ordinal} is already occupied"
                )
            return
        row_number = self._row_number(ordinal)
        self._worksheet.update(
            f"A{row_number}:J{row_number}",
            [self._values(expected)],
            value_input_option="RAW",
        )


def audit_remote_export(
    expected_rows: list[ClaimedExport],
    *,
    remote: RemoteExport,
    remote_max_ordinal: int | None = None,
) -> dict[str, Any]:
    expected_by_ordinal = {row.export_ordinal: row.document for row in expected_rows}
    if len(expected_by_ordinal) != len(expected_rows):
        raise ValueError("expected export ordinals must be unique")
    expected_key_positions = {
        document["export_key"]: ordinal
        for ordinal, document in expected_by_ordinal.items()
    }
    if len(expected_key_positions) != len(expected_rows):
        raise ValueError("expected export keys must be unique")
    ceiling = max(
        [*expected_by_ordinal, remote_max_ordinal or 0],
        default=0,
    )
    missing: list[int] = []
    edited: list[int] = []
    reordered: list[int] = []
    unexpected: list[int] = []
    observed_keys: dict[str, list[int]] = {}
    for ordinal in range(1, ceiling + 1):
        observed = remote.read(ordinal)
        expected = expected_by_ordinal.get(ordinal)
        if observed is None:
            if expected is not None:
                missing.append(ordinal)
            continue
        observed_document = dict(observed)
        key = str(observed_document.get("export_key") or "")
        observed_keys.setdefault(key, []).append(ordinal)
        expected_position = expected_key_positions.get(key)
        if expected is not None and key != expected["export_key"]:
            missing.append(ordinal)
        if expected_position is None:
            unexpected.append(ordinal)
            continue
        if expected_position != ordinal:
            reordered.append(ordinal)
        elif expected is not None and _canonical_json(observed_document) != _canonical_json(expected):
            edited.append(ordinal)
    duplicates = {
        key: ordinals for key, ordinals in observed_keys.items() if key and len(ordinals) > 1
    }
    return {
        "ready": not missing and not edited and not reordered and not unexpected and not duplicates,
        "expected": len(expected_rows),
        "observed": sum(len(value) for value in observed_keys.values()),
        "missing_ordinals": missing,
        "edited_ordinals": edited,
        "reordered_ordinals": reordered,
        "unexpected_ordinals": unexpected,
        "duplicate_keys": duplicates,
        "lag_rows": len(missing),
    }


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

    _CLAIM_SQL = """
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
        RETURNING
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
                    self._CLAIM_SQL,
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
