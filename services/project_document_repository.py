"""PostgreSQL persistence for authoritative Hollawall projects and documents.

The repository owns durable project/document state, optimistic locking,
idempotency, numbering, immutable artifacts, allocations, and audit replay. It
never writes Google Sheets or creates financial-ledger rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from services.project_document_models import (
    MAX_DOCUMENT_LINES,
    PERCENT_MAX,
    QUANTITY_MAX,
    DocumentCalculationError,
    bounded_idr,
    decimal_value,
    integer_rupiah,
)


JAKARTA = ZoneInfo("Asia/Jakarta")
DOCUMENT_PREFIXES = {"sales_order": "SO", "invoice": "INV", "receipt": "KWT"}
DOCUMENT_TYPES = frozenset(DOCUMENT_PREFIXES)
PROJECT_STATUSES = frozenset({"planned", "active", "completed", "cancelled"})
INVOICE_KINDS = frozenset({"DP", "PROGRESS", "FINAL"})
_SELECT_PROJECT = """
    id, name, client_name, client_company, client_address, client_contact,
    issuer_key, wallet, company, status, start_date, completion_date,
    contract_notes, lock_version, created_by, updated_by, created_at, updated_at
"""
_SELECT_DOCUMENT = """
    id, project_id, issuer_key, document_type, invoice_kind, status,
    official_number, issue_date, due_date, valid_until,
    document_discount_amount, document_discount_percent, tax_percent,
    notes, payment_terms, immutable_snapshot, snapshot_sha256,
    renderer_version, revision_of_id, superseded_by_id, void_reason,
    lock_version, issued_at, voided_at, superseded_at,
    created_by, updated_by, created_at, updated_at
"""


class ProjectDocumentError(RuntimeError):
    """Base project-document persistence failure."""


class ProjectDocumentUnavailable(ProjectDocumentError):
    """The durable PostgreSQL store is unavailable."""


class ProjectDocumentConflict(ProjectDocumentError):
    """Stored state conflicts with the requested command or version."""


class ProjectDocumentNotFound(ProjectDocumentError):
    """The requested project or document does not exist."""


ConnectionFactory = Callable[[str], Any]
DocumentRenderer = Callable[[Mapping[str, Any]], tuple[bytes, str]]


def _database_url() -> str:
    return str(os.getenv("STATE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()


def _default_connection_factory(dsn: str):
    import psycopg

    return psycopg.connect(dsn)


def _json(value: Any, *, label: str = "value") -> tuple[str, Any]:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
        return encoded, json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{label} must contain only JSON values") from exc


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal, uuid.UUID)):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def canonical_json_hash(value: Any) -> str:
    encoded, _ = _json(value, label="value")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _actor(value: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise TypeError("actor must be a mapping")
    encoded, canonical = _json(dict(value), label="actor")
    if not isinstance(canonical, dict) or not canonical:
        raise ValueError("actor must not be empty")
    return encoded, canonical


def _instant(value: datetime | None = None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        raise ValueError("instant must be timezone-aware")
    return selected


def format_official_number(
    document_type: str,
    issuer_code: str,
    sequence: int,
    instant: datetime | None = None,
) -> str:
    if document_type not in DOCUMENT_TYPES:
        raise ValueError("unsupported document type")
    code = str(issuer_code or "").strip().upper()
    if not code or "/" in code:
        raise ValueError("issuer code is invalid")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be a positive integer")
    year = _instant(instant).astimezone(JAKARTA).year
    return f"{DOCUMENT_PREFIXES[document_type]}/{code}/{year}/{sequence:06d}"


def _safe_json_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ProjectDocumentUnavailable("database returned invalid JSON object")
    return dict(decoded)


def _safe_json_array(value: Any) -> list[Any]:
    if value is None:
        return []
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        raise ProjectDocumentUnavailable("database returned invalid JSON array")
    return list(decoded)


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _row_dict(cursor: Any, columns: Sequence[str], row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return {str(key): _plain(value) for key, value in row.items()}
    if len(row) != len(columns):
        raise ProjectDocumentUnavailable("database returned an invalid row")
    return {column: _plain(value) for column, value in zip(columns, row)}


def _columns(selection: str) -> list[str]:
    return [part.strip() for part in selection.replace("\n", " ").split(",") if part.strip()]


_PROJECT_COLUMNS = _columns(_SELECT_PROJECT)
_DOCUMENT_COLUMNS = _columns(_SELECT_DOCUMENT)


_SCHEMA_HEALTH_QUERY = """
SELECT
    (
        (
            SELECT ARRAY_AGG(table_name ORDER BY table_name) = ARRAY[
                'project_document_allocations', 'project_document_artifacts',
                'project_document_commands', 'project_document_events',
                'project_document_lines', 'project_document_number_counters',
                'project_documents', 'project_issuer_profile_events',
                'project_issuer_profiles', 'project_scopes', 'projects'
            ]::information_schema.sql_identifier[]
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                  'project_issuer_profiles', 'projects', 'project_scopes',
                  'project_documents', 'project_document_lines',
                  'project_document_allocations', 'project_document_number_counters',
                  'project_document_events', 'project_document_artifacts',
                  'project_document_commands', 'project_issuer_profile_events'
              )
        )
        AND
        (
            SELECT MD5(STRING_AGG(
                table_name || '|' || ordinal_position || '|' || column_name || '|' ||
                udt_name || '|' || is_nullable || '|' || COALESCE(column_default, '') ||
                '|' || is_identity,
                E'\n' ORDER BY table_name, ordinal_position
            )) = 'ebbbf0c0268865631328cce6dab142eb'
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN (
                  'project_issuer_profiles', 'projects', 'project_documents',
                  'project_document_number_counters', 'project_document_artifacts',
                  'project_document_events'
              )
        )
    ) AS tables_ready,
    (
        SELECT COUNT(*) = 6 AND COALESCE(BOOL_AND(
            CASE c.conname
                WHEN 'project_scopes_project_id_fkey' THEN
                    r.relname = 'project_scopes'
                    AND pg_get_constraintdef(c.oid, TRUE) =
                        'FOREIGN KEY (project_id) REFERENCES projects(id)'
                WHEN 'project_document_lines_document_id_fkey' THEN
                    r.relname = 'project_document_lines'
                    AND pg_get_constraintdef(c.oid, TRUE) =
                        'FOREIGN KEY (document_id) REFERENCES project_documents(id)'
                WHEN 'project_document_allocations_document_id_fkey' THEN
                    r.relname = 'project_document_allocations'
                    AND pg_get_constraintdef(c.oid, TRUE) =
                        'FOREIGN KEY (document_id) REFERENCES project_documents(id)'
                WHEN 'project_documents_revision_of_id_fkey' THEN
                    r.relname = 'project_documents'
                    AND pg_get_constraintdef(c.oid, TRUE) =
                        'FOREIGN KEY (revision_of_id) REFERENCES project_documents(id) DEFERRABLE INITIALLY DEFERRED'
                WHEN 'project_documents_superseded_by_id_fkey' THEN
                    r.relname = 'project_documents'
                    AND pg_get_constraintdef(c.oid, TRUE) =
                        'FOREIGN KEY (superseded_by_id) REFERENCES project_documents(id) DEFERRABLE INITIALLY DEFERRED'
                WHEN 'project_document_artifacts_pdf_signature_check' THEN
                    r.relname = 'project_document_artifacts'
                    AND pg_get_constraintdef(c.oid, TRUE) =
                        'CHECK (SUBSTRING(pdf_bytes FROM 1 FOR 5) = convert_to(''%PDF-''::text, ''UTF8''::name))'
                ELSE FALSE
            END
        ), FALSE)
        FROM pg_constraint c
        JOIN pg_class r ON r.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = r.relnamespace
        WHERE n.nspname = 'public'
          AND c.conname IN (
              'project_scopes_project_id_fkey',
              'project_document_lines_document_id_fkey',
              'project_document_allocations_document_id_fkey',
              'project_documents_revision_of_id_fkey',
              'project_documents_superseded_by_id_fkey',
              'project_document_artifacts_pdf_signature_check'
          )
    ) AS constraints_ready,
    (
        SELECT COUNT(*) = 5 AND COALESCE(BOOL_AND(
            CASE ci.relname
                WHEN 'uq_project_issuer_profiles_number_code' THEN
                    r.relname = 'project_issuer_profiles'
                    AND i.indisunique
                    AND i.indnkeyatts = 1
                    AND pg_get_indexdef(i.indexrelid, 1, TRUE) =
                        'upper(TRIM(BOTH FROM number_code))'
                    AND pg_get_expr(i.indpred, i.indrelid, TRUE) IS NULL
                WHEN 'uq_project_active_final_invoice' THEN
                    r.relname = 'project_documents'
                    AND i.indisunique
                    AND i.indnkeyatts = 1
                    AND pg_get_indexdef(i.indexrelid, 1, TRUE) = 'project_id'
                    AND pg_get_expr(i.indpred, i.indrelid, TRUE) =
                        'document_type = ''invoice''::text AND invoice_kind = ''FINAL''::text AND (status = ''issued''::text OR status = ''draft''::text AND revision_of_id IS NULL)'
                WHEN 'uq_project_pending_document_revision' THEN
                    r.relname = 'project_documents'
                    AND i.indisunique
                    AND i.indnkeyatts = 1
                    AND pg_get_indexdef(i.indexrelid, 1, TRUE) = 'revision_of_id'
                    AND pg_get_expr(i.indpred, i.indrelid, TRUE) =
                        'revision_of_id IS NOT NULL AND status = ''draft''::text'
                WHEN 'idx_project_document_allocations_source' THEN
                    r.relname = 'project_document_allocations'
                    AND NOT i.indisunique
                    AND i.indnkeyatts = 1
                    AND pg_get_indexdef(i.indexrelid, 1, TRUE) = 'ledger_source_key'
                    AND pg_get_expr(i.indpred, i.indrelid, TRUE) IS NULL
                WHEN 'idx_project_document_events_project_replay' THEN
                    r.relname = 'project_document_events'
                    AND NOT i.indisunique
                    AND i.indnkeyatts = 2
                    AND ARRAY[
                        pg_get_indexdef(i.indexrelid, 1, TRUE),
                        pg_get_indexdef(i.indexrelid, 2, TRUE)
                    ] = ARRAY['project_id', 'id']::TEXT[]
                    AND pg_get_expr(i.indpred, i.indrelid, TRUE) IS NULL
                ELSE FALSE
            END
        ), FALSE)
        FROM pg_index i
        JOIN pg_class ci ON ci.oid = i.indexrelid
        JOIN pg_class r ON r.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = r.relnamespace
        WHERE n.nspname = 'public'
          AND ci.relname IN (
              'uq_project_issuer_profiles_number_code',
              'uq_project_active_final_invoice',
              'uq_project_pending_document_revision',
              'idx_project_document_allocations_source',
              'idx_project_document_events_project_replay'
          )
    ) AS indexes_ready,
    (
        SELECT COUNT(*) = 9 AND COALESCE(BOOL_AND(
            CASE t.tgname
                WHEN 'trg_project_issuer_number_code_immutable' THEN
                    r.relname = 'project_issuer_profiles'
                    AND p.proname = 'prevent_project_issuer_number_code_mutation'
                    AND t.tgtype = 19
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_issuer_number_code_immutable BEFORE UPDATE OF number_code ON project_issuer_profiles FOR EACH ROW EXECUTE FUNCTION prevent_project_issuer_number_code_mutation()'
                    AND POSITION('NEW.number_code IS DISTINCT FROM OLD.number_code' IN pg_get_functiondef(p.oid)) > 0
                    AND POSITION('issuer number_code is immutable after profile creation' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_projects_no_delete' THEN
                    r.relname = 'projects'
                    AND p.proname = 'prevent_project_delete'
                    AND t.tgtype = 11
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_projects_no_delete BEFORE DELETE ON projects FOR EACH ROW EXECUTE FUNCTION prevent_project_delete()'
                    AND POSITION('projects cannot be hard deleted' IN pg_get_functiondef(p.oid)) > 0
                    AND POSITION('RAISE EXCEPTION' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_project_documents_no_delete' THEN
                    r.relname = 'project_documents'
                    AND p.proname = 'prevent_project_document_delete'
                    AND t.tgtype = 11
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_documents_no_delete BEFORE DELETE ON project_documents FOR EACH ROW EXECUTE FUNCTION prevent_project_document_delete()'
                    AND POSITION('project documents cannot be hard deleted' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_project_document_immutable' THEN
                    r.relname = 'project_documents'
                    AND p.proname = 'prevent_project_document_mutation'
                    AND t.tgtype = 19
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_document_immutable BEFORE UPDATE ON project_documents FOR EACH ROW EXECUTE FUNCTION prevent_project_document_mutation()'
                    AND POSITION('invalid draft to issued mutation' IN pg_get_functiondef(p.oid)) > 0
                    AND POSITION('terminal project document is immutable' IN pg_get_functiondef(p.oid)) > 0
                    AND POSITION('invalid project document transition' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_project_document_lines_draft_only' THEN
                    r.relname = 'project_document_lines'
                    AND p.proname = 'prevent_non_draft_document_child_mutation'
                    AND t.tgtype = 31
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_document_lines_draft_only BEFORE INSERT OR DELETE OR UPDATE ON project_document_lines FOR EACH ROW EXECUTE FUNCTION prevent_non_draft_document_child_mutation()'
                    AND POSITION('issued project document children are immutable' IN pg_get_functiondef(p.oid)) > 0
                    AND POSITION('FOR UPDATE' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_project_document_allocations_draft_only' THEN
                    r.relname = 'project_document_allocations'
                    AND p.proname = 'prevent_non_draft_document_child_mutation'
                    AND t.tgtype = 31
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_document_allocations_draft_only BEFORE INSERT OR DELETE OR UPDATE ON project_document_allocations FOR EACH ROW EXECUTE FUNCTION prevent_non_draft_document_child_mutation()'
                    AND POSITION('issued project document children are immutable' IN pg_get_functiondef(p.oid)) > 0
                    AND POSITION('FOR UPDATE' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_project_document_events_append_only' THEN
                    r.relname = 'project_document_events'
                    AND p.proname = 'prevent_project_document_event_mutation'
                    AND t.tgtype = 27
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_document_events_append_only BEFORE DELETE OR UPDATE ON project_document_events FOR EACH ROW EXECUTE FUNCTION prevent_project_document_event_mutation()'
                    AND POSITION('project document events are append-only' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_project_issuer_profile_events_append_only' THEN
                    r.relname = 'project_issuer_profile_events'
                    AND p.proname = 'prevent_project_document_event_mutation'
                    AND t.tgtype = 27
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_issuer_profile_events_append_only BEFORE DELETE OR UPDATE ON project_issuer_profile_events FOR EACH ROW EXECUTE FUNCTION prevent_project_document_event_mutation()'
                    AND POSITION('project document events are append-only' IN pg_get_functiondef(p.oid)) > 0
                WHEN 'trg_project_document_artifacts_immutable' THEN
                    r.relname = 'project_document_artifacts'
                    AND p.proname = 'prevent_project_document_artifact_mutation'
                    AND t.tgtype = 27
                    AND pg_get_triggerdef(t.oid, TRUE) =
                        'CREATE TRIGGER trg_project_document_artifacts_immutable BEFORE DELETE OR UPDATE ON project_document_artifacts FOR EACH ROW EXECUTE FUNCTION prevent_project_document_artifact_mutation()'
                    AND POSITION('project document artifacts are immutable' IN pg_get_functiondef(p.oid)) > 0
                ELSE FALSE
            END
        ), FALSE)
        FROM pg_trigger t
        JOIN pg_class r ON r.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = r.relnamespace
        JOIN pg_proc p ON p.oid = t.tgfoid
        WHERE n.nspname = 'public' AND NOT t.tgisinternal
          AND t.tgname IN (
              'trg_project_issuer_number_code_immutable',
              'trg_projects_no_delete',
              'trg_project_documents_no_delete',
              'trg_project_document_immutable',
              'trg_project_document_lines_draft_only',
              'trg_project_document_allocations_draft_only',
              'trg_project_document_events_append_only',
              'trg_project_issuer_profile_events_append_only',
              'trg_project_document_artifacts_immutable'
          )
    ) AS triggers_ready
"""


def _schema_status(row: Any) -> dict[str, bool]:
    tables, constraints, indexes, triggers = map(bool, row or (False, False, False, False))
    return {
        "ready": tables and constraints and indexes and triggers,
        "tables": tables,
        "constraints": constraints,
        "indexes": indexes,
        "triggers": triggers,
    }


def project_document_schema_health(dsn: str | None = None) -> dict[str, bool]:
    selected = str(dsn or _database_url()).strip()
    if not selected:
        raise ProjectDocumentUnavailable(
            "Project document repository requires STATE_DATABASE_URL or DATABASE_URL"
        )
    try:
        with _default_connection_factory(selected) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_SCHEMA_HEALTH_QUERY)
                return _schema_status(cursor.fetchone())
    except ProjectDocumentUnavailable:
        raise
    except Exception as exc:
        raise ProjectDocumentUnavailable(
            f"Project document schema health unavailable: {type(exc).__name__}"
        ) from exc


def ensure_project_document_schema(dsn: str | None = None) -> dict[str, bool]:
    selected = str(dsn or _database_url()).strip()
    if not selected:
        raise ProjectDocumentUnavailable(
            "Project document repository requires STATE_DATABASE_URL or DATABASE_URL"
        )
    migration = (
        Path(__file__).parents[1]
        / "dashboard_api"
        / "migrations"
        / "003_project_documents.sql"
    ).read_text(encoding="utf-8")
    try:
        with _default_connection_factory(selected) as connection:
            with connection.cursor() as cursor:
                cursor.execute(migration)
                cursor.execute(_SCHEMA_HEALTH_QUERY)
                return _schema_status(cursor.fetchone())
    except Exception as exc:
        raise ProjectDocumentUnavailable(
            f"Project document migration unavailable: {type(exc).__name__}"
        ) from exc


class ProjectDocumentRepository:
    """PostgreSQL repository with transactional command boundaries."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection_factory: ConnectionFactory | None = None,
        now: Callable[[], datetime] | None = None,
        renderer: DocumentRenderer | None = None,
    ) -> None:
        self._dsn = str(dsn or "").strip()
        self._connection_factory = connection_factory or _default_connection_factory
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._renderer = renderer

    def _connect(self):
        dsn = self._dsn or _database_url()
        if not dsn:
            raise ProjectDocumentUnavailable(
                "Project document repository requires STATE_DATABASE_URL or DATABASE_URL"
            )
        try:
            return self._connection_factory(dsn)
        except ProjectDocumentUnavailable:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _claim(cursor: Any, command_type: str, idempotency_key: str, request: Any) -> tuple[str, str, Any | None]:
        key = str(idempotency_key or "")
        if not 16 <= len(key) <= 128 or key != key.strip() or any(character.isspace() for character in key):
            raise ValueError("idempotency_key must be 16..128 printable characters without whitespace")
        request_hash = canonical_json_hash(request)
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        cursor.execute(
            """
            INSERT INTO project_document_commands (
                idempotency_key_hash, command_type, request_hash
            ) VALUES (%s, %s, %s)
            ON CONFLICT (idempotency_key_hash) DO NOTHING
            RETURNING id
            """,
            (key_hash, command_type, request_hash),
        )
        inserted = cursor.fetchone()
        if inserted:
            return key_hash, request_hash, None
        cursor.execute(
            """
            SELECT command_type, request_hash, response
            FROM project_document_commands
            WHERE idempotency_key_hash = %s
            FOR UPDATE
            """,
            (key_hash,),
        )
        existing = cursor.fetchone()
        if not existing:
            raise ProjectDocumentUnavailable("idempotency command disappeared")
        existing_type, existing_hash, response = existing
        if str(existing_type) != command_type or str(existing_hash) != request_hash:
            raise ProjectDocumentConflict("idempotency key belongs to a different command")
        if response is None:
            raise ProjectDocumentConflict("idempotency command is already in progress")
        return key_hash, request_hash, _safe_json_object(response)

    @staticmethod
    def _complete(cursor: Any, key_hash: str, response: Mapping[str, Any]) -> dict[str, Any]:
        encoded, canonical = _json(dict(response), label="response")
        cursor.execute(
            """
            UPDATE project_document_commands
            SET response = %s::jsonb, completed_at = NOW()
            WHERE idempotency_key_hash = %s AND response IS NULL
            """,
            (encoded, key_hash),
        )
        if cursor.rowcount != 1:
            raise ProjectDocumentConflict("idempotency command completion conflicted")
        return canonical

    @staticmethod
    def _event(
        cursor: Any,
        *,
        project_id: str,
        event_type: str,
        actor_json: str,
        document_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        data_json, _ = _json(dict(data or {}), label="event data")
        cursor.execute(
            """
            INSERT INTO project_document_events (
                project_id, document_id, event_type, event_data, actor
            ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (project_id, document_id, event_type, data_json, actor_json),
        )

    def upsert_issuer_profile(
        self,
        *,
        issuer_key: str,
        legal_name: str,
        display_name: str,
        number_code: str,
        address: str,
        actor: Mapping[str, Any],
        phone: str | None = None,
        email: str | None = None,
        tax_identity: str | None = None,
        bank_details: Mapping[str, Any] | None = None,
        logo_path: str | None = None,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        actor_json, _ = _actor(actor)
        bank_json, _ = _json(dict(bank_details or {}), label="bank_details")
        values = (
            str(issuer_key or "").strip(),
            str(legal_name or "").strip(),
            str(display_name or "").strip(),
            str(number_code or "").strip().upper(),
            str(address or "").strip(),
            phone,
            email,
            tax_identity,
            bank_json,
            logo_path,
            actor_json,
        )
        if not all(values[:5]):
            raise ValueError("issuer identity fields are required")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        request = {
            "issuer_key": values[0],
            "legal_name": values[1],
            "display_name": values[2],
            "number_code": values[3],
            "address": values[4],
            "phone": phone,
            "email": email,
            "tax_identity": tax_identity,
            "bank_details": dict(bank_details or {}),
            "logo_path": logo_path,
            "expected_version": expected_version,
        }
        columns = [
            "issuer_key", "legal_name", "display_name", "number_code", "address",
            "phone", "email", "tax_identity", "bank_details", "logo_path",
            "profile_version", "created_at", "updated_at",
        ]
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(
                        cursor, "issuer.upsert", idempotency_key, request
                    )
                    if replay is not None:
                        return replay
                    cursor.execute(
                        "SELECT profile_version, number_code FROM project_issuer_profiles "
                        "WHERE issuer_key = %s FOR UPDATE",
                        (values[0],),
                    )
                    current = cursor.fetchone()
                    if current is None:
                        if expected_version != 0:
                            raise ProjectDocumentConflict("issuer profile version conflict")
                        cursor.execute(
                            """
                            INSERT INTO project_issuer_profiles (
                                issuer_key, legal_name, display_name, number_code, address,
                                phone, email, tax_identity, bank_details, logo_path,
                                created_by, updated_by
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                                %s::jsonb, %s::jsonb
                            )
                            RETURNING issuer_key, legal_name, display_name, number_code,
                                      address, phone, email, tax_identity, bank_details,
                                      logo_path, profile_version, created_at, updated_at
                            """,
                            (*values, actor_json),
                        )
                        event_type = "issuer.created"
                    else:
                        if int(current[0]) != expected_version:
                            raise ProjectDocumentConflict("issuer profile version conflict")
                        if str(current[1]) != values[3]:
                            raise ProjectDocumentConflict(
                                "issuer number_code is immutable after profile creation"
                            )
                        cursor.execute(
                            """
                            UPDATE project_issuer_profiles SET
                                legal_name = %s, display_name = %s,
                                address = %s, phone = %s, email = %s, tax_identity = %s,
                                bank_details = %s::jsonb, logo_path = %s,
                                profile_version = profile_version + 1,
                                updated_by = %s::jsonb, updated_at = NOW()
                            WHERE issuer_key = %s AND profile_version = %s
                            RETURNING issuer_key, legal_name, display_name, number_code,
                                      address, phone, email, tax_identity, bank_details,
                                      logo_path, profile_version, created_at, updated_at
                            """,
                            (
                                values[1], values[2], values[4], phone, email,
                                tax_identity, bank_json, logo_path, actor_json, values[0],
                                expected_version,
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise ProjectDocumentConflict("issuer profile version conflict")
                        event_type = "issuer.updated"
                    row = cursor.fetchone()
                    profile = _row_dict(None, columns, row) or {}
                    profile_json, _ = _json(profile, label="issuer profile")
                    cursor.execute(
                        """
                        INSERT INTO project_issuer_profile_events (
                            issuer_key, event_type, profile_version, event_data, actor
                        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                        """,
                        (
                            values[0], event_type, profile["profile_version"],
                            profile_json, actor_json,
                        ),
                    )
                    return self._complete(cursor, key_hash, profile)
        except (ProjectDocumentError, ValueError):
            raise
        except Exception as exc:
            if "issuer number_code is immutable after profile creation" in str(exc):
                raise ProjectDocumentConflict(
                    "issuer number_code is immutable after profile creation"
                ) from exc
            if "uq_project_issuer_profiles_number_code" in str(exc):
                raise ProjectDocumentConflict("issuer number_code already exists") from exc
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def get_issuer_profile(self, issuer_key: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT issuer_key, legal_name, display_name, number_code,
                               address, phone, email, tax_identity, bank_details,
                               logo_path, profile_version, created_at, updated_at
                        FROM project_issuer_profiles WHERE issuer_key = %s
                        """,
                        (issuer_key,),
                    )
                    row = cursor.fetchone()
            if not row:
                raise ProjectDocumentNotFound("issuer profile not found")
            return _row_dict(None, [
                "issuer_key", "legal_name", "display_name", "number_code", "address",
                "phone", "email", "tax_identity", "bank_details", "logo_path",
                "profile_version", "created_at", "updated_at",
            ], row) or {}
        except ProjectDocumentError:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def create_project_with_sales_order(
        self,
        values: Mapping[str, Any],
        *,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        command = dict(values)
        name = str(command.get("name") or "").strip()
        client_name = str(command.get("client_name") or "").strip()
        issuer_key = str(command.get("issuer_key") or "").strip()
        if not name or not client_name or not issuer_key:
            raise ValueError("name, client_name, and issuer_key are required")
        status = str(command.get("status") or "planned")
        if status not in PROJECT_STATUSES:
            raise ValueError("unsupported project status")
        actor_json, _ = _actor(actor)
        project_id = str(uuid.uuid4())
        document_id = str(uuid.uuid4())
        request = {"values": command, "actor": _safe_json_object(actor_json)}
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(cursor, "project.create", idempotency_key, request)
                    if replay is not None:
                        return replay
                    cursor.execute(
                        """
                        INSERT INTO projects (
                            id, name, client_name, client_company, client_address,
                            client_contact, issuer_key, wallet, company, status,
                            start_date, completion_date, contract_notes,
                            created_by, updated_by
                        ) VALUES (
                            %s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''),
                            NULLIF(%s, ''), %s, NULLIF(%s, ''), NULLIF(%s, ''),
                            %s, %s, %s, NULLIF(%s, ''), %s::jsonb, %s::jsonb
                        ) RETURNING """ + _SELECT_PROJECT,
                        (
                            project_id, name, client_name,
                            str(command.get("client_company") or "").strip(),
                            str(command.get("client_address") or "").strip(),
                            str(command.get("client_contact") or "").strip(),
                            issuer_key,
                            str(command.get("wallet") or "").strip(),
                            str(command.get("company") or "").strip(),
                            status,
                            command.get("start_date"), command.get("completion_date"),
                            str(command.get("contract_notes") or "").strip(),
                            actor_json, actor_json,
                        ),
                    )
                    project = _row_dict(cursor, _PROJECT_COLUMNS, cursor.fetchone()) or {}
                    sales_order_values = self._numeric_document_values(
                        self._with_document_defaults(
                            "sales_order",
                            {
                                "valid_until": command.get("sales_order_valid_until"),
                                "tax_percent": command.get("tax_percent", 0),
                            },
                        )
                    )
                    sales_order = self._insert_document(
                        cursor,
                        document_id=document_id,
                        project_id=project_id,
                        issuer_key=issuer_key,
                        document_type="sales_order",
                        invoice_kind=None,
                        values=sales_order_values,
                        actor_json=actor_json,
                    )
                    self._event(
                        cursor,
                        project_id=project_id,
                        event_type="project.created",
                        actor_json=actor_json,
                        data={"project": project},
                    )
                    self._event(
                        cursor,
                        project_id=project_id,
                        document_id=document_id,
                        event_type="document.created",
                        actor_json=actor_json,
                        data={"document_type": "sales_order", "automatic": True},
                    )
                    return self._complete(
                        cursor,
                        key_hash,
                        {"project": project, "sales_order": sales_order},
                    )
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def list_projects(self) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT " + _SELECT_PROJECT + " FROM projects ORDER BY created_at DESC, id")
                    rows = cursor.fetchall()
            return [_row_dict(None, _PROJECT_COLUMNS, row) or {} for row in rows]
        except ProjectDocumentError:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def get_project(self, project_id: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT " + _SELECT_PROJECT + " FROM projects WHERE id = %s", (project_id,))
                    row = cursor.fetchone()
            if not row:
                raise ProjectDocumentNotFound("project not found")
            return _row_dict(None, _PROJECT_COLUMNS, row) or {}
        except ProjectDocumentError:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def get_project_commercial_totals(self, project_id: str) -> dict[str, int]:
        """Return an issuance-safe prefill view for a FINAL invoice draft.

        This is a read model only. ``issue_document`` re-locks and revalidates the
        same commercial invariants before allocating an official number.
        """

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
                    if not cursor.fetchone():
                        raise ProjectDocumentNotFound("project not found")
                    cursor.execute(
                        """
                        SELECT immutable_snapshot
                        FROM project_documents
                        WHERE project_id = %s
                          AND document_type = 'sales_order'
                          AND status = 'issued'
                        ORDER BY id
                        """,
                        (project_id,),
                    )
                    sales_orders = cursor.fetchall()
                    if len(sales_orders) != 1:
                        raise ProjectDocumentConflict(
                            "FINAL invoice requires exactly one active issued Sales Order"
                        )
                    contract_total = self._issued_snapshot_total(
                        sales_orders[0][0], label="Sales Order"
                    )
                    cursor.execute(
                        """
                        SELECT invoice_kind, immutable_snapshot
                        FROM project_documents
                        WHERE project_id = %s
                          AND document_type = 'invoice'
                          AND status = 'issued'
                        ORDER BY id
                        """,
                        (project_id,),
                    )
                    invoices = cursor.fetchall()
                    if any(str(kind) == "FINAL" for kind, _snapshot in invoices):
                        raise ProjectDocumentConflict("a live FINAL invoice already exists")
                    invoiced_non_final = sum(
                        self._issued_snapshot_total(snapshot, label="prior invoice")
                        for kind, snapshot in invoices
                        if str(kind) in {"DP", "PROGRESS"}
                    )
                    residual = contract_total - invoiced_non_final
                    if residual <= 0:
                        raise ProjectDocumentConflict(
                            "FINAL invoice residual must be positive"
                        )
                    return {
                        "contract_total": contract_total,
                        "invoiced_non_final": invoiced_non_final,
                        "residual": residual,
                    }
        except ProjectDocumentError:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def project_exists(self, project_id: str, wallet: str | None = None, company: str | None = None) -> bool:
        try:
            uuid.UUID(str(project_id))
        except (ValueError, TypeError):
            return False
        query = "SELECT EXISTS(SELECT 1 FROM projects WHERE id = %s"
        params: list[Any] = [project_id]
        if wallet is not None:
            query += " AND wallet = %s"
            params.append(wallet)
        if company is not None:
            query += " AND company = %s"
            params.append(company)
        query += ")"
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, tuple(params))
                    return bool(cursor.fetchone()[0])
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def update_project(
        self,
        project_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "name", "client_name", "client_company", "client_address", "client_contact",
            "issuer_key", "wallet", "company", "status", "start_date", "completion_date",
            "contract_notes",
        }
        supplied = dict(changes)
        unknown = set(supplied) - allowed
        if unknown or not supplied:
            raise ValueError("project changes are empty or unsupported")
        if "status" in supplied and supplied["status"] not in PROJECT_STATUSES:
            raise ValueError("unsupported project status")
        actor_json, _ = _actor(actor)
        request = {"project_id": project_id, "changes": supplied, "expected_version": expected_version}
        assignments = []
        params: list[Any] = []
        for field, value in supplied.items():
            assignments.append(f"{field} = %s")
            params.append(value)
        assignments.extend(["lock_version = lock_version + 1", "updated_by = %s::jsonb", "updated_at = NOW()"])
        params.extend([actor_json, project_id, expected_version])
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(cursor, "project.update", idempotency_key, request)
                    if replay is not None:
                        return replay
                    cursor.execute(
                        f"UPDATE projects SET {', '.join(assignments)} "
                        "WHERE id = %s AND lock_version = %s RETURNING " + _SELECT_PROJECT,
                        tuple(params),
                    )
                    row = cursor.fetchone()
                    if not row:
                        self._raise_version_or_not_found(cursor, "projects", project_id)
                    project = _row_dict(cursor, _PROJECT_COLUMNS, row) or {}
                    self._event(
                        cursor,
                        project_id=project_id,
                        event_type="project.updated",
                        actor_json=actor_json,
                        data={"changes": supplied, "lock_version": project["lock_version"]},
                    )
                    return self._complete(cursor, key_hash, project)
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _raise_version_or_not_found(cursor: Any, table: str, record_id: str) -> None:
        cursor.execute(f"SELECT 1 FROM {table} WHERE id = %s", (record_id,))
        if cursor.fetchone():
            raise ProjectDocumentConflict("optimistic lock version conflict")
        raise ProjectDocumentNotFound(f"{table.rstrip('s')} not found")

    @staticmethod
    def _numeric_document_values(values: Mapping[str, Any]) -> dict[str, Any]:
        prepared = dict(values)
        prepared["document_discount_amount"] = integer_rupiah(
            prepared.get("document_discount_amount", 0),
            field="document_discount_amount",
        )
        prepared["document_discount_percent"] = str(
            decimal_value(
                prepared.get("document_discount_percent", "0"),
                field="document_discount_percent",
                maximum=PERCENT_MAX,
                max_fractional_digits=4,
            )
        )
        prepared["tax_percent"] = str(
            decimal_value(
                prepared.get("tax_percent", "0"),
                field="tax_percent",
                maximum=PERCENT_MAX,
                max_fractional_digits=4,
            )
        )
        if (
            prepared["document_discount_amount"]
            and Decimal(prepared["document_discount_percent"])
        ):
            raise DocumentCalculationError(
                "document discount may be fixed or percentage, never both"
            )
        return prepared

    @staticmethod
    def _insert_document(
        cursor: Any,
        *,
        document_id: str,
        project_id: str,
        issuer_key: str,
        document_type: str,
        invoice_kind: str | None,
        values: Mapping[str, Any],
        actor_json: str,
        revision_of_id: str | None = None,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO project_documents (
                id, project_id, issuer_key, document_type, invoice_kind,
                issue_date, due_date, valid_until,
                document_discount_amount, document_discount_percent, tax_percent,
                notes, payment_terms, revision_of_id, created_by, updated_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), %s,
                %s::jsonb, %s::jsonb
            ) RETURNING """ + _SELECT_DOCUMENT,
            (
                document_id, project_id, issuer_key, document_type, invoice_kind,
                values.get("issue_date"), values.get("due_date"), values.get("valid_until"),
                int(values.get("document_discount_amount") or 0),
                str(values.get("document_discount_percent") or "0"),
                str(values.get("tax_percent") or "0"),
                str(values.get("notes") or "").strip(),
                str(values.get("payment_terms") or "").strip(),
                revision_of_id, actor_json, actor_json,
            ),
        )
        return _row_dict(cursor, _DOCUMENT_COLUMNS, cursor.fetchone()) or {}

    def _with_document_defaults(
        self, document_type: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        prepared = dict(values)
        issue_date = prepared.get("issue_date")
        if issue_date is None:
            issue_date = _instant(self._now()).astimezone(JAKARTA).date()
            prepared["issue_date"] = issue_date
        elif isinstance(issue_date, str):
            issue_date = date.fromisoformat(issue_date)
        if document_type == "sales_order" and prepared.get("valid_until") is None:
            prepared["valid_until"] = issue_date + timedelta(days=14)
        if document_type == "invoice" and prepared.get("due_date") is None:
            prepared["due_date"] = issue_date + timedelta(days=7)
        return prepared

    def create_document_draft(
        self,
        project_id: str,
        *,
        document_type: str,
        values: Mapping[str, Any],
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("unsupported document type")
        invoice_kind = values.get("invoice_kind")
        if document_type == "invoice" and invoice_kind not in INVOICE_KINDS:
            raise ValueError("invoice_kind must be DP, PROGRESS, or FINAL")
        if document_type != "invoice" and invoice_kind is not None:
            raise ValueError("invoice_kind is only valid for invoices")
        actor_json, _ = _actor(actor)
        document_id = str(uuid.uuid4())
        request = {
            "project_id": project_id,
            "document_type": document_type,
            "values": dict(values),
        }
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(cursor, "document.create", idempotency_key, request)
                    if replay is not None:
                        return replay
                    cursor.execute(
                        "SELECT issuer_key, status FROM projects WHERE id = %s FOR UPDATE",
                        (project_id,),
                    )
                    project = cursor.fetchone()
                    if not project:
                        raise ProjectDocumentNotFound("project not found")
                    if document_type == "invoice" and str(project[1]) not in {"planned", "active"}:
                        raise ProjectDocumentConflict(
                            "invoices require a planned or active project"
                        )
                    prepared_values = self._numeric_document_values(
                        self._with_document_defaults(document_type, values)
                    )
                    document = self._insert_document(
                        cursor,
                        document_id=document_id,
                        project_id=project_id,
                        issuer_key=str(project[0]),
                        document_type=document_type,
                        invoice_kind=str(invoice_kind) if invoice_kind else None,
                        values=prepared_values,
                        actor_json=actor_json,
                    )
                    if prepared_values.get("lines"):
                        self._replace_lines(cursor, document_id, prepared_values["lines"])
                    self._event(
                        cursor,
                        project_id=project_id,
                        document_id=document_id,
                        event_type="document.created",
                        actor_json=actor_json,
                        data={"document_type": document_type, "invoice_kind": invoice_kind},
                    )
                    return self._complete(cursor, key_hash, self._load_document(cursor, document_id))
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            if "uq_project_active_final_invoice" in str(exc):
                raise ProjectDocumentConflict("a live FINAL invoice already exists") from exc
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _line_values(line: Mapping[str, Any], position: int) -> tuple[Any, ...]:
        description = str(line.get("description") or "").strip()
        unit = str(line.get("unit") or "unit").strip()
        if not description or not unit:
            raise DocumentCalculationError("document line description and unit are required")
        try:
            with localcontext() as context:
                context.prec = 64
                quantity = decimal_value(
                    line.get("quantity"),
                    field=f"line {position} quantity",
                    minimum=Decimal("0.0001"),
                    maximum=QUANTITY_MAX,
                    max_fractional_digits=4,
                )
                unit_price = integer_rupiah(
                    line.get("unit_price"), field=f"line {position} unit_price"
                )
                discount_percent = decimal_value(
                    line.get("line_discount_percent", "0"),
                    field=f"line {position} line_discount_percent",
                    maximum=PERCENT_MAX,
                    max_fractional_digits=4,
                )
                gross = bounded_idr(
                    int(
                        (quantity * Decimal(unit_price)).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    ),
                    field=f"line {position} line_gross",
                )
                discount = bounded_idr(
                    int(
                        (Decimal(gross) * discount_percent / Decimal("100")).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    ),
                    field=f"line {position} line_discount",
                )
                line_total = bounded_idr(
                    gross - discount, field=f"line {position} line_total"
                )
        except DocumentCalculationError:
            raise
        except DecimalException as exc:
            raise DocumentCalculationError(
                f"line {position} is outside supported numeric bounds"
            ) from exc
        return (
            str(uuid.uuid4()), position, description, str(quantity), unit,
            unit_price, str(discount_percent), gross, discount, line_total,
        )

    @classmethod
    def _replace_lines(cls, cursor: Any, document_id: str, lines: Sequence[Mapping[str, Any]]) -> None:
        if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)):
            raise DocumentCalculationError("document lines must be a sequence")
        if len(lines) > MAX_DOCUMENT_LINES:
            raise DocumentCalculationError(
                f"document may contain at most {MAX_DOCUMENT_LINES} lines"
            )
        cursor.execute("DELETE FROM project_document_lines WHERE document_id = %s", (document_id,))
        for position, line in enumerate(lines, start=1):
            values = cls._line_values(line, position)
            cursor.execute(
                """
                INSERT INTO project_document_lines (
                    id, document_id, position, description, quantity, unit,
                    unit_price, line_discount_percent, line_gross,
                    line_discount, line_total
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (values[0], document_id, *values[1:]),
            )

    @staticmethod
    def _load_lines(cursor: Any, document_id: str) -> list[dict[str, Any]]:
        columns = [
            "id", "position", "description", "quantity", "unit", "unit_price",
            "line_discount_percent", "line_gross", "line_discount", "line_total",
        ]
        cursor.execute(
            """
            SELECT id, position, description, quantity, unit, unit_price,
                   line_discount_percent, line_gross, line_discount, line_total
            FROM project_document_lines WHERE document_id = %s ORDER BY position
            """,
            (document_id,),
        )
        return [_row_dict(cursor, columns, row) or {} for row in cursor.fetchall()]

    @staticmethod
    def _load_allocations(cursor: Any, document_id: str) -> list[dict[str, Any]]:
        columns = ["id", "ledger_source_key", "amount", "ledger_amount", "ledger_snapshot", "created_at"]
        cursor.execute(
            """
            SELECT id, ledger_source_key, amount, ledger_amount, ledger_snapshot, created_at
            FROM project_document_allocations
            WHERE document_id = %s
            ORDER BY ledger_source_key, id
            """,
            (document_id,),
        )
        return [_row_dict(cursor, columns, row) or {} for row in cursor.fetchall()]

    @classmethod
    def _load_document(cls, cursor: Any, document_id: str, *, for_update: bool = False) -> dict[str, Any]:
        cursor.execute(
            "SELECT " + _SELECT_DOCUMENT + " FROM project_documents WHERE id = %s" + (" FOR UPDATE" if for_update else ""),
            (document_id,),
        )
        document = _row_dict(cursor, _DOCUMENT_COLUMNS, cursor.fetchone())
        if not document:
            raise ProjectDocumentNotFound("document not found")
        document["immutable_snapshot"] = _safe_json_object(document.get("immutable_snapshot"))
        document["created_by"] = _safe_json_object(document.get("created_by"))
        document["updated_by"] = _safe_json_object(document.get("updated_by"))
        document["lines"] = cls._load_lines(cursor, document_id)
        document["allocations"] = cls._load_allocations(cursor, document_id)
        return document

    def get_document(self, document_id: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    return self._load_document(cursor, document_id)
        except ProjectDocumentError:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def list_documents(self, project_id: str) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM project_documents WHERE project_id = %s "
                        "ORDER BY CASE document_type WHEN 'sales_order' THEN 0 ELSE 1 END, created_at, id",
                        (project_id,),
                    )
                    ids = [str(row[0]) for row in cursor.fetchall()]
                    return [self._load_document(cursor, document_id) for document_id in ids]
        except ProjectDocumentError:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def update_draft(
        self,
        document_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "issue_date", "due_date", "valid_until", "document_discount_amount",
            "document_discount_percent", "tax_percent", "notes", "payment_terms", "lines",
        }
        supplied = dict(changes)
        if not supplied or set(supplied) - allowed:
            raise ValueError("document changes are empty or unsupported")
        if "document_discount_amount" in supplied:
            supplied["document_discount_amount"] = integer_rupiah(
                supplied["document_discount_amount"], field="document_discount_amount"
            )
        for field in ("document_discount_percent", "tax_percent"):
            if field in supplied:
                supplied[field] = str(
                    decimal_value(
                        supplied[field],
                        field=field,
                        maximum=PERCENT_MAX,
                        max_fractional_digits=4,
                    )
                )
        actor_json, _ = _actor(actor)
        request = {"document_id": document_id, "changes": supplied, "expected_version": expected_version}
        fields = {key: value for key, value in supplied.items() if key != "lines"}
        assignments = [f"{key} = %s" for key in fields]
        params = list(fields.values())
        assignments.extend(["lock_version = lock_version + 1", "updated_by = %s::jsonb", "updated_at = NOW()"])
        params.extend([actor_json, document_id, expected_version])
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(cursor, "document.update", idempotency_key, request)
                    if replay is not None:
                        return replay
                    cursor.execute(
                        f"UPDATE project_documents SET {', '.join(assignments)} "
                        "WHERE id = %s AND lock_version = %s AND status = 'draft' RETURNING project_id",
                        tuple(params),
                    )
                    row = cursor.fetchone()
                    if not row:
                        self._raise_document_draft_conflict(cursor, document_id, expected_version)
                    project_id = str(row[0])
                    if "lines" in supplied:
                        self._replace_lines(cursor, document_id, supplied["lines"])
                    document = self._load_document(cursor, document_id)
                    self._event(
                        cursor,
                        project_id=project_id,
                        document_id=document_id,
                        event_type="document.updated",
                        actor_json=actor_json,
                        data={"fields": sorted(supplied), "lock_version": document["lock_version"]},
                    )
                    return self._complete(cursor, key_hash, document)
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _raise_document_draft_conflict(cursor: Any, document_id: str, expected_version: int) -> None:
        cursor.execute("SELECT status, lock_version FROM project_documents WHERE id = %s", (document_id,))
        row = cursor.fetchone()
        if not row:
            raise ProjectDocumentNotFound("document not found")
        if str(row[0]) != "draft":
            raise ProjectDocumentConflict("only a draft document may be changed")
        if int(row[1]) != int(expected_version):
            raise ProjectDocumentConflict("optimistic lock version conflict")
        raise ProjectDocumentConflict("document draft update conflicted")

    @staticmethod
    def _ledger_row(cursor: Any, source_key: str, *, for_update: bool = True) -> dict[str, Any]:
        columns = [
            "source_key", "source_sheet", "source_row", "source_block", "message_id",
            "transaction_date", "amount", "transaction_type", "company", "wallet",
            "project", "category", "description", "is_valid", "payload",
        ]
        cursor.execute(
            "SELECT " + ", ".join(columns) + " FROM financial_ledger WHERE source_key = %s" +
            (" FOR UPDATE" if for_update else ""),
            (source_key,),
        )
        row = _row_dict(cursor, columns, cursor.fetchone())
        if not row:
            raise ProjectDocumentConflict("receipt allocation source no longer exists")
        row["payload"] = _safe_json_object(row.get("payload")) or {}
        return row

    @staticmethod
    def _validate_income_row(row: Mapping[str, Any], *, project_id: str, issuer: Mapping[str, Any]) -> None:
        direction = str(row.get("transaction_type") or "").casefold()
        block = str(row.get("source_block") or "").casefold()
        if not row.get("is_valid") or direction not in {"pemasukan", "income"} or block in {
            "operasional", "office", "internal_transfer", "transfer", "hutang", "debt",
        }:
            raise ProjectDocumentConflict("receipt allocation must reference valid project income")
        if str(row.get("project") or "") != project_id:
            raise ProjectDocumentConflict("receipt allocation project does not match")
        wallet = str(issuer.get("wallet") or "").strip()
        company = str(issuer.get("company") or "").strip()
        if not wallet or not company:
            raise ProjectDocumentConflict(
                "receipt allocation requires non-empty project wallet and company"
            )
        if str(row.get("wallet") or "") != wallet:
            raise ProjectDocumentConflict("receipt allocation issuer wallet does not match")
        if str(row.get("company") or "") != company:
            raise ProjectDocumentConflict("receipt allocation issuer company does not match")
        if int(row.get("amount") or 0) <= 0:
            raise ProjectDocumentConflict("receipt allocation income amount is invalid")

    @staticmethod
    def _allocated_amount(cursor: Any, source_key: str, *, excluding_document_id: str) -> int:
        cursor.execute(
            """
            SELECT COALESCE(SUM(a.amount), 0)
            FROM project_document_allocations a
            JOIN project_documents d ON d.id = a.document_id
            WHERE a.ledger_source_key = %s
              AND a.document_id <> %s
              AND d.status <> 'void'
            """,
            (source_key, excluding_document_id),
        )
        return int(cursor.fetchone()[0] or 0)

    def lock_allocations(
        self,
        document_id: str,
        allocations: Sequence[Mapping[str, Any]],
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        materialized = [dict(item) for item in allocations]
        if not materialized:
            raise ValueError("at least one allocation is required")
        actor_json, _ = _actor(actor)
        request = {"document_id": document_id, "allocations": materialized, "expected_version": expected_version}
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(cursor, "document.allocate", idempotency_key, request)
                    if replay is not None:
                        return replay
                    document = self._load_document(cursor, document_id, for_update=True)
                    if document["status"] != "draft" or document["document_type"] != "receipt":
                        raise ProjectDocumentConflict("allocations require a receipt draft")
                    if int(document["lock_version"]) != int(expected_version):
                        raise ProjectDocumentConflict("optimistic lock version conflict")
                    cursor.execute(
                        "SELECT wallet, company FROM projects WHERE id = %s FOR UPDATE",
                        (document["project_id"],),
                    )
                    issuer = _row_dict(cursor, ["wallet", "company"], cursor.fetchone()) or {}
                    prepared = []
                    seen = set()
                    normalized = []
                    for allocation in materialized:
                        source_key = str(allocation.get("ledger_source_key") or "").strip()
                        amount = allocation.get("amount")
                        if not source_key or source_key in seen or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                            raise ValueError("receipt allocation is invalid")
                        seen.add(source_key)
                        normalized.append((source_key, amount))
                    for source_key, amount in sorted(normalized):
                        ledger = self._ledger_row(cursor, source_key)
                        self._validate_income_row(ledger, project_id=document["project_id"], issuer=issuer)
                        available = int(ledger["amount"]) - self._allocated_amount(
                            cursor, source_key, excluding_document_id=document_id
                        )
                        if amount > available:
                            raise ProjectDocumentConflict("receipt allocation exceeds available income")
                        prepared.append((source_key, amount, ledger))
                    cursor.execute("DELETE FROM project_document_allocations WHERE document_id = %s", (document_id,))
                    for source_key, amount, ledger in prepared:
                        snapshot_json, _ = _json(ledger, label="ledger snapshot")
                        cursor.execute(
                            """
                            INSERT INTO project_document_allocations (
                                id, document_id, ledger_source_key, amount,
                                ledger_amount, ledger_snapshot
                            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                            """,
                            (
                                str(uuid.uuid4()), document_id, source_key, amount,
                                int(ledger["amount"]), snapshot_json,
                            ),
                        )
                    cursor.execute(
                        """
                        UPDATE project_documents
                        SET lock_version = lock_version + 1,
                            updated_by = %s::jsonb, updated_at = NOW()
                        WHERE id = %s AND status = 'draft' AND lock_version = %s
                        """,
                        (actor_json, document_id, expected_version),
                    )
                    if cursor.rowcount != 1:
                        raise ProjectDocumentConflict("optimistic lock version conflict")
                    result = self._load_document(cursor, document_id)
                    self._event(
                        cursor,
                        project_id=document["project_id"],
                        document_id=document_id,
                        event_type="document.allocations_locked",
                        actor_json=actor_json,
                        data={"count": len(prepared), "total": sum(item[1] for item in prepared)},
                    )
                    return self._complete(cursor, key_hash, result)
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def _revalidate_allocations(self, cursor: Any, document: Mapping[str, Any]) -> None:
        if document["document_type"] != "receipt":
            return
        allocations = document.get("allocations") or []
        if not allocations:
            raise ProjectDocumentConflict("receipt requires verified income allocations")
        cursor.execute(
            "SELECT wallet, company FROM projects WHERE id = %s FOR UPDATE",
            (document["project_id"],),
        )
        issuer = _row_dict(cursor, ["wallet", "company"], cursor.fetchone()) or {}
        for allocation in sorted(allocations, key=lambda item: str(item["ledger_source_key"])):
            ledger = self._ledger_row(cursor, allocation["ledger_source_key"])
            self._validate_income_row(ledger, project_id=document["project_id"], issuer=issuer)
            available = int(ledger["amount"]) - self._allocated_amount(
                cursor, allocation["ledger_source_key"], excluding_document_id=document["id"]
            )
            if int(allocation["amount"]) > available:
                raise ProjectDocumentConflict("receipt allocation exceeds available income")
            if int(allocation["ledger_amount"]) != int(ledger["amount"]):
                raise ProjectDocumentConflict("receipt allocation source amount changed")

    @staticmethod
    def _calculate_totals(document: Mapping[str, Any]) -> dict[str, int | str]:
        try:
            with localcontext() as context:
                context.prec = 64
                subtotal = 0
                source_amounts = (
                    [item["amount"] for item in document.get("allocations") or []]
                    if document["document_type"] == "receipt"
                    else [line["line_total"] for line in document.get("lines") or []]
                )
                for position, amount in enumerate(source_amounts, start=1):
                    subtotal = bounded_idr(
                        subtotal + integer_rupiah(
                            amount, field=f"document source amount {position}"
                        ),
                        field="document subtotal",
                    )
                fixed_discount = integer_rupiah(
                    document.get("document_discount_amount") or 0,
                    field="document_discount_amount",
                )
                percent = decimal_value(
                    document.get("document_discount_percent") or "0",
                    field="document_discount_percent",
                    maximum=PERCENT_MAX,
                    max_fractional_digits=4,
                )
                if fixed_discount and percent:
                    raise DocumentCalculationError(
                        "document discount may be fixed or percentage, never both"
                    )
                percentage_discount = bounded_idr(
                    int(
                        (Decimal(subtotal) * percent / Decimal("100")).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    ),
                    field="document discount",
                )
                discount = fixed_discount or percentage_discount
                taxable_base = subtotal - discount
                if taxable_base < 0:
                    raise ProjectDocumentConflict("document discount exceeds subtotal")
                taxable_base = bounded_idr(taxable_base, field="taxable base")
                tax_percent = decimal_value(
                    document.get("tax_percent") or "0",
                    field="tax_percent",
                    maximum=PERCENT_MAX,
                    max_fractional_digits=4,
                )
                tax = bounded_idr(
                    int(
                        (Decimal(taxable_base) * tax_percent / Decimal("100")).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    ),
                    field="tax",
                )
                total = bounded_idr(taxable_base + tax, field="document total")
        except (DocumentCalculationError, ProjectDocumentConflict):
            raise
        except DecimalException as exc:
            raise DocumentCalculationError(
                "document calculation is outside supported bounds"
            ) from exc
        return {
            "subtotal": subtotal,
            "document_discount": discount,
            "taxable_base": taxable_base,
            "tax_percent": str(tax_percent),
            "tax": tax,
            "total": total,
        }

    @staticmethod
    def _issued_snapshot_total(snapshot: Any, *, label: str) -> int:
        decoded = _safe_json_object(snapshot)
        totals = decoded.get("totals") if decoded else None
        if not isinstance(totals, Mapping):
            raise ProjectDocumentConflict(f"{label} has no authoritative issued total")
        total = totals.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ProjectDocumentConflict(f"{label} has an invalid authoritative issued total")
        return total

    @classmethod
    def _validate_final_residual(
        cls,
        cursor: Any,
        document: Mapping[str, Any],
    ) -> None:
        if document.get("document_type") != "invoice" or document.get("invoice_kind") != "FINAL":
            return
        cursor.execute(
            """
            SELECT id, immutable_snapshot
            FROM project_documents
            WHERE project_id = %s
              AND document_type = 'sales_order'
              AND status = 'issued'
            ORDER BY id
            FOR UPDATE
            """,
            (document["project_id"],),
        )
        sales_orders = cursor.fetchall()
        if len(sales_orders) != 1:
            raise ProjectDocumentConflict(
                "FINAL invoice requires exactly one active issued Sales Order"
            )
        commercial_total = cls._issued_snapshot_total(
            sales_orders[0][1], label="Sales Order"
        )
        cursor.execute(
            """
            WITH RECURSIVE revision_chain(id, revision_of_id) AS (
                SELECT id, revision_of_id
                FROM project_documents
                WHERE id = %s
              UNION ALL
                SELECT parent.id, parent.revision_of_id
                FROM project_documents parent
                JOIN revision_chain child ON parent.id = child.revision_of_id
            )
            SELECT d.id, d.immutable_snapshot
            FROM project_documents d
            WHERE d.project_id = %s
              AND d.document_type = 'invoice'
              AND d.status = 'issued'
              AND NOT EXISTS (
                  SELECT 1 FROM revision_chain chain WHERE chain.id = d.id
              )
            ORDER BY d.id
            FOR UPDATE
            """,
            (document["id"], document["project_id"]),
        )
        prior_invoice_total = sum(
            cls._issued_snapshot_total(snapshot, label="prior invoice")
            for _invoice_id, snapshot in cursor.fetchall()
        )
        residual = commercial_total - prior_invoice_total
        if residual < 0:
            raise ProjectDocumentConflict(
                f"commercial amount is overbilled by {-residual}"
            )
        final_total = int(cls._calculate_totals(document)["total"])
        if final_total != residual:
            raise ProjectDocumentConflict(
                f"FINAL invoice total must equal residual commercial amount {residual}"
            )

    @staticmethod
    def _canonical_snapshot(
        *,
        document: Mapping[str, Any],
        project: Mapping[str, Any],
        issuer: Mapping[str, Any],
        official_number: str,
        issue_date: date,
        instant: datetime,
    ) -> dict[str, Any]:
        document_data = {
            key: value
            for key, value in document.items()
            if key not in {
                "immutable_snapshot", "snapshot_sha256", "renderer_version",
                "official_number", "status", "issued_at", "voided_at",
                "superseded_at", "void_reason", "superseded_by_id", "lines",
                "allocations", "created_by", "updated_by",
            }
        }
        document_data.update(
            {
                "status": "issued",
                "official_number": official_number,
                "issue_date": issue_date,
            }
        )
        project_data = {
            key: value
            for key, value in project.items()
            if key not in {"created_by", "updated_by"}
        }
        issuer_data = dict(issuer)
        return _plain(
            {
                "schema_version": 1,
                "issued_at": instant,
                "issuer": issuer_data,
                "project": project_data,
                "document": document_data,
                "lines": list(document.get("lines") or []),
                "allocations": list(document.get("allocations") or []),
                "totals": ProjectDocumentRepository._calculate_totals(document),
            }
        )

    def issue_document(
        self,
        document_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
        issued_at: datetime | None = None,
    ) -> dict[str, Any]:
        if self._renderer is None:
            raise ProjectDocumentUnavailable("document renderer is not configured")
        actor_json, _ = _actor(actor)
        request = {
            "document_id": document_id,
            "expected_version": expected_version,
            "issued_at": issued_at,
        }
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(
                        cursor, "document.issue", idempotency_key, request
                    )
                    if replay is not None:
                        return replay
                    instant = _instant(issued_at or self._now())
                    document = self._load_document(cursor, document_id, for_update=True)
                    if document["status"] != "draft":
                        raise ProjectDocumentConflict("only a draft document may be issued")
                    if int(document["lock_version"]) != int(expected_version):
                        raise ProjectDocumentConflict("optimistic lock version conflict")
                    cursor.execute(
                        "SELECT " + _SELECT_PROJECT + " FROM projects WHERE id = %s FOR UPDATE",
                        (document["project_id"],),
                    )
                    project = _row_dict(cursor, _PROJECT_COLUMNS, cursor.fetchone())
                    if not project:
                        raise ProjectDocumentConflict("document project is missing")
                    project["created_by"] = _safe_json_object(project.get("created_by"))
                    project["updated_by"] = _safe_json_object(project.get("updated_by"))
                    if document["document_type"] == "invoice" and project["status"] not in {
                        "planned", "active"
                    }:
                        raise ProjectDocumentConflict(
                            "invoices require a planned or active project"
                        )
                    self._revalidate_allocations(cursor, document)
                    self._validate_final_residual(cursor, document)
                    year = instant.astimezone(JAKARTA).year
                    cursor.execute(
                        """
                        INSERT INTO project_document_number_counters (
                            issuer_key, document_type, calendar_year, last_value
                        ) VALUES (%s, %s, %s, 1)
                        ON CONFLICT (issuer_key, document_type, calendar_year)
                        DO UPDATE SET last_value = project_document_number_counters.last_value + 1,
                                      updated_at = NOW()
                        RETURNING last_value
                        """,
                        (document["issuer_key"], document["document_type"], year),
                    )
                    sequence = int(cursor.fetchone()[0])
                    issuer_columns = [
                        "issuer_key", "legal_name", "display_name", "number_code",
                        "address", "phone", "email", "tax_identity", "bank_details",
                        "logo_path", "profile_version",
                    ]
                    cursor.execute(
                        "SELECT " + ", ".join(issuer_columns) +
                        " FROM project_issuer_profiles WHERE issuer_key = %s FOR UPDATE",
                        (document["issuer_key"],),
                    )
                    issuer = _row_dict(cursor, issuer_columns, cursor.fetchone())
                    if not issuer:
                        raise ProjectDocumentConflict("issuer profile is missing")
                    issuer["bank_details"] = _safe_json_object(issuer.get("bank_details")) or {}
                    official_number = format_official_number(
                        document["document_type"], str(issuer["number_code"]), sequence, instant
                    )
                    issue_date = document.get("issue_date") or instant.astimezone(JAKARTA).date()
                    snapshot = self._canonical_snapshot(
                        document=document,
                        project=project,
                        issuer=issuer,
                        official_number=official_number,
                        issue_date=date.fromisoformat(issue_date) if isinstance(issue_date, str) else issue_date,
                        instant=instant,
                    )
                    snapshot_json, canonical_snapshot = _json(snapshot, label="snapshot")
                    snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
                    rendered = self._renderer(canonical_snapshot)
                    if (
                        not isinstance(rendered, tuple)
                        or len(rendered) != 2
                        or not isinstance(rendered[0], bytes)
                    ):
                        raise ProjectDocumentUnavailable(
                            "document renderer must return (pdf_bytes, renderer_version)"
                        )
                    pdf_bytes, renderer_version = rendered
                    renderer_version = str(renderer_version or "").strip()
                    if (
                        not pdf_bytes.startswith(b"%PDF-")
                        or len(pdf_bytes) > 10 * 1024 * 1024
                        or not renderer_version
                    ):
                        raise ProjectDocumentUnavailable("document renderer returned an invalid PDF")
                    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
                    original_number = None
                    if document.get("revision_of_id"):
                        cursor.execute(
                            """
                            UPDATE project_documents
                            SET status = 'superseded', superseded_by_id = %s,
                                superseded_at = %s, lock_version = lock_version + 1,
                                updated_by = %s::jsonb, updated_at = NOW()
                            WHERE id = %s AND status = 'issued'
                            RETURNING official_number
                            """,
                            (document_id, instant, actor_json, document["revision_of_id"]),
                        )
                        original_row = cursor.fetchone()
                        if not original_row:
                            raise ProjectDocumentConflict(
                                "revision source is not an issued document"
                            )
                        original_number = str(original_row[0])
                    cursor.execute(
                        """
                        UPDATE project_documents
                        SET status = 'issued', official_number = %s,
                            issue_date = %s, immutable_snapshot = %s::jsonb,
                            snapshot_sha256 = %s, renderer_version = %s, issued_at = %s,
                            lock_version = lock_version + 1,
                            updated_by = %s::jsonb, updated_at = NOW()
                        WHERE id = %s AND status = 'draft' AND lock_version = %s
                        """,
                        (
                            official_number, issue_date, snapshot_json, snapshot_hash,
                            renderer_version, instant, actor_json, document_id, expected_version,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ProjectDocumentConflict("document issuance conflicted")
                    cursor.execute(
                        """
                        INSERT INTO project_document_artifacts (
                            document_id, byte_size, sha256, renderer_version, pdf_bytes
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (document_id, len(pdf_bytes), pdf_hash, renderer_version, pdf_bytes),
                    )
                    issued = self._load_document(cursor, document_id)
                    if issued["immutable_snapshot"] != canonical_snapshot:
                        raise ProjectDocumentUnavailable("stored snapshot readback mismatch")
                    revision_links = {}
                    if document.get("revision_of_id"):
                        revision_links = {
                            "original_document_id": document["revision_of_id"],
                            "original_official_number": original_number,
                            "replacement_document_id": document_id,
                            "replacement_official_number": official_number,
                        }
                        self._event(
                            cursor,
                            project_id=document["project_id"],
                            document_id=document["revision_of_id"],
                            event_type="document.superseded",
                            actor_json=actor_json,
                            data=revision_links,
                        )
                    self._event(
                        cursor,
                        project_id=document["project_id"],
                        document_id=document_id,
                        event_type="document.issued",
                        actor_json=actor_json,
                        data={
                            "official_number": official_number,
                            "snapshot_sha256": snapshot_hash,
                            "pdf_sha256": pdf_hash,
                            "renderer_version": renderer_version,
                            **revision_links,
                        },
                    )
                    return self._complete(cursor, key_hash, issued)
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def get_artifact(self, document_id: str) -> dict[str, Any]:
        columns = ["document_id", "mime_type", "byte_size", "sha256", "renderer_version", "pdf_bytes", "created_at"]
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT document_id, mime_type, byte_size, sha256, renderer_version, pdf_bytes, created_at "
                        "FROM project_document_artifacts WHERE document_id = %s",
                        (document_id,),
                    )
                    row = cursor.fetchone()
            if not row:
                raise ProjectDocumentNotFound("document artifact not found")
            artifact = _row_dict(None, columns, row) or {}
            stored = artifact.pop("pdf_bytes")
            artifact["bytes"] = bytes(stored)
            return artifact
        except ProjectDocumentError:
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def void_document(
        self,
        document_id: str,
        *,
        reason: str,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("void reason is required")
        actor_json, _ = _actor(actor)
        request = {"document_id": document_id, "reason": reason, "expected_version": expected_version}
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(cursor, "document.void", idempotency_key, request)
                    if replay is not None:
                        return replay
                    cursor.execute(
                        """
                        UPDATE project_documents
                        SET status = 'void', void_reason = %s, voided_at = NOW(),
                            lock_version = lock_version + 1,
                            updated_by = %s::jsonb, updated_at = NOW()
                        WHERE id = %s AND status = 'issued' AND lock_version = %s
                        RETURNING project_id
                        """,
                        (reason, actor_json, document_id, expected_version),
                    )
                    row = cursor.fetchone()
                    if not row:
                        self._raise_issued_conflict(cursor, document_id, expected_version)
                    document = self._load_document(cursor, document_id)
                    self._event(
                        cursor,
                        project_id=str(row[0]),
                        document_id=document_id,
                        event_type="document.voided",
                        actor_json=actor_json,
                        data={"reason": reason},
                    )
                    return self._complete(cursor, key_hash, document)
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _raise_issued_conflict(cursor: Any, document_id: str, expected_version: int) -> None:
        cursor.execute("SELECT status, lock_version FROM project_documents WHERE id = %s", (document_id,))
        row = cursor.fetchone()
        if not row:
            raise ProjectDocumentNotFound("document not found")
        if str(row[0]) != "issued":
            raise ProjectDocumentConflict("only an issued document may be changed")
        if int(row[1]) != int(expected_version):
            raise ProjectDocumentConflict("optimistic lock version conflict")
        raise ProjectDocumentConflict("issued document transition conflicted")

    def revise_document(
        self,
        document_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        actor_json, _ = _actor(actor)
        request = {"document_id": document_id, "expected_version": expected_version}
        revision_id = str(uuid.uuid4())
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    key_hash, _, replay = self._claim(cursor, "document.revise", idempotency_key, request)
                    if replay is not None:
                        return replay
                    original = self._load_document(cursor, document_id, for_update=True)
                    if original["status"] != "issued":
                        raise ProjectDocumentConflict("only an issued document may be revised")
                    if original["document_type"] == "receipt":
                        raise ProjectDocumentConflict(
                            "receipts cannot be revised; use payment reversal, receipt void, and a new receipt"
                        )
                    if int(original["lock_version"]) != int(expected_version):
                        raise ProjectDocumentConflict("optimistic lock version conflict")
                    revision = self._insert_document(
                        cursor,
                        document_id=revision_id,
                        project_id=original["project_id"],
                        issuer_key=original["issuer_key"],
                        document_type=original["document_type"],
                        invoice_kind=original.get("invoice_kind"),
                        values=original,
                        actor_json=actor_json,
                        revision_of_id=document_id,
                    )
                    if original.get("lines"):
                        self._replace_lines(cursor, revision_id, original["lines"])
                    self._event(
                        cursor,
                        project_id=original["project_id"],
                        document_id=revision_id,
                        event_type="document.revised",
                        actor_json=actor_json,
                        data={"revision_of_id": document_id},
                    )
                    return self._complete(cursor, key_hash, self._load_document(cursor, revision_id))
        except (ProjectDocumentError, ValueError, TypeError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc

    def replay_audit(
        self,
        *,
        project_id: str | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if bool(project_id) == bool(document_id):
            raise ValueError("provide exactly one of project_id or document_id")
        field = "project_id" if project_id else "document_id"
        value = project_id or document_id
        columns = ["id", "project_id", "document_id", "event_type", "event_data", "actor", "occurred_at"]
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT {', '.join(columns)} FROM project_document_events "
                        f"WHERE {field} = %s ORDER BY id",
                        (value,),
                    )
                    rows = cursor.fetchall()
            events = [_row_dict(None, columns, row) or {} for row in rows]
            for event in events:
                event["event_data"] = _safe_json_object(event["event_data"]) or {}
                event["actor"] = _safe_json_object(event["actor"]) or {}
            return events
        except (ProjectDocumentError, ValueError):
            raise
        except Exception as exc:
            raise ProjectDocumentUnavailable(
                f"Project document database unavailable: {type(exc).__name__}"
            ) from exc
