"""Protected one-way canonical PostgreSQL-to-Sheets export contract."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol


EXPORT_SCHEMA_VERSION = "finance-export.v1"
_RESERVED_PAYLOAD_FIELDS = frozenset(
    {"schema_version", "export_key", "transaction_id", "sequence", "canonical_sha256"}
)


class ExportContractError(RuntimeError):
    """The destination or existing row violates the derived-export contract."""


class ExportSheet(Protocol):
    def read(self, export_key: str) -> Mapping[str, Any] | None: ...

    def upsert(self, export_key: str, payload: Mapping[str, Any]) -> None: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class CanonicalExportRow:
    transaction_id: str
    sequence: int
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        try:
            normalized = str(uuid.UUID(str(self.transaction_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ExportContractError("export transaction_id must be UUID") from exc
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ExportContractError("export sequence must be a positive integer")
        payload = dict(self.payload)
        reserved = sorted(_RESERVED_PAYLOAD_FIELDS.intersection(payload))
        if reserved:
            raise ExportContractError(f"export payload uses reserved fields: {', '.join(reserved)}")
        object.__setattr__(self, "transaction_id", normalized)
        object.__setattr__(self, "payload", payload)

    @property
    def export_key(self) -> str:
        return f"{self.transaction_id}:{self.sequence}"

    @property
    def document(self) -> dict[str, Any]:
        body = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "export_key": self.export_key,
            "transaction_id": self.transaction_id,
            "sequence": self.sequence,
            **dict(self.payload),
        }
        body["canonical_sha256"] = hashlib.sha256(
            _canonical_json(body).encode("utf-8")
        ).hexdigest()
        return body


def _same_document(existing: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return _canonical_json(dict(existing)) == _canonical_json(dict(expected))


def export_rows(
    rows: Iterable[CanonicalExportRow],
    *,
    sheet: ExportSheet,
    protected_destination: bool,
) -> dict[str, Any]:
    """Upsert derived rows by immutable key; replay after an ack crash is a no-op."""

    if not protected_destination:
        raise ExportContractError("canonical export requires a protected isolated destination")
    written = 0
    unchanged = 0
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: (item.transaction_id, item.sequence)):
        if row.export_key in seen:
            raise ExportContractError(f"duplicate export key in batch: {row.export_key}")
        seen.add(row.export_key)
        expected = row.document
        existing = sheet.read(row.export_key)
        if existing is not None:
            if not _same_document(existing, expected):
                raise ExportContractError(f"canonical export drift: {row.export_key}")
            unchanged += 1
            continue
        sheet.upsert(row.export_key, expected)
        # Immediate authoritative readback closes the write-before-ack crash window.
        observed = sheet.read(row.export_key)
        if observed is None or not _same_document(observed, expected):
            raise ExportContractError(f"canonical export readback failed: {row.export_key}")
        written += 1
    return {"written": written, "unchanged": unchanged, "total": len(seen)}


def verify_export_rows(
    rows: Iterable[CanonicalExportRow],
    *,
    sheet: ExportSheet,
) -> dict[str, Any]:
    missing: list[str] = []
    edited: list[str] = []
    expected_rows = sorted(rows, key=lambda item: (item.transaction_id, item.sequence))
    keys: set[str] = set()
    duplicates: list[str] = []
    for row in expected_rows:
        if row.export_key in keys:
            duplicates.append(row.export_key)
            continue
        keys.add(row.export_key)
        observed = sheet.read(row.export_key)
        if observed is None:
            missing.append(row.export_key)
        elif not _same_document(observed, row.document):
            edited.append(row.export_key)
    return {
        "ready": not missing and not edited and not duplicates,
        "missing": missing,
        "edited": edited,
        "duplicates": sorted(set(duplicates)),
        "expected": len(keys),
    }
