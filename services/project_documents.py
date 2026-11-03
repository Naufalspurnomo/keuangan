"""Project/document domain calculations and lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
from typing import Any, Protocol

from services.project_document_models import (
    DocumentCalculationError,
    DocumentLineTotal,
    DocumentTotals,
    BIGINT_MAX,
    MAX_DOCUMENT_LINES,
    PERCENT_MAX,
    QUANTITY_MAX,
    bounded_idr,
    decimal_text,
    decimal_value,
    integer_rupiah,
)


class ProjectDocumentStore(Protocol):
    def create_project_with_sales_order(self, values: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def get_project(self, project_id: str) -> dict[str, Any]: ...
    def create_document_draft(self, project_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def create_invoice_draft(self, project_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def create_receipt_draft(self, project_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def update_draft(
        self,
        document_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]: ...
    def issue_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def void_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def revise_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def replay_audit(self, **kwargs: Any) -> list[dict[str, Any]]: ...


def _round_idr(value: Decimal, *, field: str) -> int:
    try:
        rounded = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except DecimalException as exc:
        raise DocumentCalculationError(f"{field} cannot be represented as integer IDR") from exc
    return bounded_idr(rounded, field=field)


def calculate_document_totals(
    lines: Sequence[Mapping[str, Any]],
    *,
    document_discount_amount: int = 0,
    document_discount_percent: Any = "0",
    tax_percent: Any = "0",
) -> dict[str, Any]:
    """Calculate exact integer-rupiah totals using Decimal and half-up rounding."""

    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)) or not lines:
        raise DocumentCalculationError("at least one document line is required")
    if len(lines) > MAX_DOCUMENT_LINES:
        raise DocumentCalculationError(
            f"document may contain at most {MAX_DOCUMENT_LINES} lines"
        )

    try:
        with localcontext() as context:
            context.prec = 64
            amount_discount = integer_rupiah(
                document_discount_amount, field="document_discount_amount"
            )
            percent_discount = decimal_value(
                document_discount_percent,
                field="document_discount_percent",
                maximum=PERCENT_MAX,
                max_fractional_digits=4,
            )
            tax_rate = decimal_value(
                tax_percent,
                field="tax_percent",
                maximum=PERCENT_MAX,
                max_fractional_digits=4,
            )
            if amount_discount and percent_discount:
                raise DocumentCalculationError(
                    "document discount may be fixed or percentage, never both"
                )

            calculated: list[DocumentLineTotal] = []
            subtotal = 0
            for position, raw_line in enumerate(lines, start=1):
                if not isinstance(raw_line, Mapping):
                    raise DocumentCalculationError(f"line {position} must be an object")
                description = str(raw_line.get("description") or "").strip()
                unit = str(raw_line.get("unit") or "").strip()
                if not description or not unit:
                    raise DocumentCalculationError(
                        f"line {position} description and unit are required"
                    )
                quantity = decimal_value(
                    raw_line.get("quantity"),
                    field=f"line {position} quantity",
                    minimum=Decimal("0.0001"),
                    maximum=QUANTITY_MAX,
                    max_fractional_digits=4,
                )
                unit_price = integer_rupiah(
                    raw_line.get("unit_price"), field=f"line {position} unit_price"
                )
                line_rate = decimal_value(
                    raw_line.get("line_discount_percent", "0"),
                    field=f"line {position} line_discount_percent",
                    maximum=PERCENT_MAX,
                    max_fractional_digits=4,
                )
                gross = _round_idr(
                    quantity * Decimal(unit_price), field=f"line {position} line_gross"
                )
                discount = _round_idr(
                    Decimal(gross) * line_rate / Decimal("100"),
                    field=f"line {position} line_discount",
                )
                line_total = bounded_idr(
                    gross - discount, field=f"line {position} line_total"
                )
                subtotal = bounded_idr(
                    subtotal + line_total, field="document subtotal"
                )
                calculated.append(
                    DocumentLineTotal(
                        description=description,
                        quantity=quantity,
                        unit=unit,
                        unit_price=unit_price,
                        line_discount_percent=line_rate,
                        line_gross=gross,
                        line_discount=discount,
                        line_total=line_total,
                    )
                )

            document_discount = amount_discount or _round_idr(
                Decimal(subtotal) * percent_discount / Decimal("100"),
                field="document discount",
            )
            taxable_base = subtotal - document_discount
            if taxable_base < 0:
                raise DocumentCalculationError("document discount exceeds taxable base")
            taxable_base = bounded_idr(taxable_base, field="taxable base")
            tax = _round_idr(
                Decimal(taxable_base) * tax_rate / Decimal("100"), field="tax"
            )
            total = bounded_idr(taxable_base + tax, field="document total")
            return DocumentTotals(
                lines=tuple(calculated),
                subtotal=subtotal,
                document_discount=document_discount,
                taxable_base=taxable_base,
                tax=tax,
                total=total,
            ).to_dict()
    except DocumentCalculationError:
        raise
    except DecimalException as exc:
        raise DocumentCalculationError("document calculation is outside supported bounds") from exc


def _actor(actor: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(actor, Mapping) or not actor:
        raise ValueError("actor is required")
    return dict(actor)


class ProjectDocumentService:
    """Validate domain commands and delegate each atomic transition to the store."""

    def __init__(self, repository: ProjectDocumentStore) -> None:
        self._repository = repository

    def create_project(
        self,
        values: Mapping[str, Any],
        *,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        command = dict(values)
        command.setdefault("tax_percent", "0")
        return self._repository.create_project_with_sales_order(
            command,
            idempotency_key=idempotency_key,
            actor=_actor(actor),
        )

    def create_invoice(
        self,
        project_id: str,
        *,
        kind: str,
        values: Mapping[str, Any],
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind = str(kind or "").upper()
        if kind not in {"DP", "PROGRESS", "FINAL"}:
            raise ValueError("invoice kind must be DP, PROGRESS, or FINAL")
        command = dict(values)
        command["invoice_kind"] = kind
        command.setdefault("tax_percent", "0")
        if kind == "FINAL":
            if command.get("lines"):
                raise DocumentCalculationError("FINAL invoice lines are repository-generated")
            if (
                int(command.get("document_discount_amount") or 0)
                or Decimal(str(command.get("document_discount_percent") or "0"))
                or Decimal(str(command.get("tax_percent") or "0"))
            ):
                raise DocumentCalculationError(
                    "FINAL invoice cannot add discount or tax to the residual"
                )
        elif command.get("lines"):
            totals = calculate_document_totals(
                command["lines"],
                document_discount_amount=command.get("document_discount_amount", 0),
                document_discount_percent=command.get("document_discount_percent", "0"),
                tax_percent=command.get("tax_percent", "0"),
            )
            command["lines"] = totals["lines"]
            command["totals"] = {key: value for key, value in totals.items() if key != "lines"}
        elif kind == "PROGRESS":
            raise DocumentCalculationError("PROGRESS invoice requires explicit lines")
        return self._repository.create_invoice_draft(
            project_id,
            values=command,
            idempotency_key=idempotency_key,
            actor=_actor(actor),
        )

    def create_receipt(
        self,
        project_id: str,
        *,
        allocations: Sequence[Mapping[str, Any]],
        values: Mapping[str, Any],
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        materialized = [dict(allocation) for allocation in allocations]
        if not materialized:
            raise ValueError("at least one receipt allocation is required")
        command = dict(values)
        command.setdefault("tax_percent", "0")
        return self._repository.create_receipt_draft(
            project_id,
            values=command,
            allocations=materialized,
            idempotency_key=idempotency_key,
            actor=_actor(actor),
        )

    def update_draft(
        self,
        document_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        command = dict(changes)
        if "lines" in command:
            totals = calculate_document_totals(
                command["lines"],
                document_discount_amount=command.get("document_discount_amount", 0),
                document_discount_percent=command.get("document_discount_percent", "0"),
                tax_percent=command.get("tax_percent", "0"),
            )
            command["lines"] = totals["lines"]
        return self._repository.update_draft(
            document_id,
            command,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor=_actor(actor),
        )

    def issue_document(
        self,
        document_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._repository.issue_document(
            document_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor=_actor(actor),
        )

    def void_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]:
        kwargs["actor"] = _actor(kwargs["actor"])
        return self._repository.void_document(document_id, **kwargs)

    def revise_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]:
        kwargs["actor"] = _actor(kwargs["actor"])
        return self._repository.revise_document(document_id, **kwargs)

    def replay_audit(
        self,
        *,
        project_id: str | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._repository.replay_audit(project_id=project_id, document_id=document_id)
