"""Project/document domain calculations and lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol

from services.project_document_models import (
    DocumentCalculationError,
    DocumentLineTotal,
    DocumentTotals,
    decimal_text,
    decimal_value,
    integer_rupiah,
)


class ProjectDocumentStore(Protocol):
    def create_project_with_sales_order(self, values: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]: ...
    def get_project(self, project_id: str) -> dict[str, Any]: ...
    def create_document_draft(self, project_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def create_receipt_draft(self, project_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_project_commercial_totals(self, project_id: str) -> dict[str, int]: ...
    def issue_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def void_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def revise_document(self, document_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def replay_audit(self, **kwargs: Any) -> list[dict[str, Any]]: ...


def _round_idr(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_document_totals(
    lines: Sequence[Mapping[str, Any]],
    *,
    document_discount_amount: int = 0,
    document_discount_percent: Any = "0",
    tax_percent: Any = "0",
) -> dict[str, Any]:
    """Calculate exact integer-rupiah totals using Decimal and half-up rounding."""

    amount_discount = integer_rupiah(document_discount_amount, field="document_discount_amount")
    percent_discount = decimal_value(
        document_discount_percent, field="document_discount_percent"
    )
    tax_rate = decimal_value(tax_percent, field="tax_percent")
    if percent_discount > Decimal("100"):
        raise DocumentCalculationError("document_discount_percent is outside the allowed range")
    if tax_rate > Decimal("100"):
        raise DocumentCalculationError("tax_percent is outside the allowed range")
    if amount_discount and percent_discount:
        raise DocumentCalculationError("document discount may be fixed or percentage, never both")
    if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)) or not lines:
        raise DocumentCalculationError("at least one document line is required")

    calculated: list[DocumentLineTotal] = []
    for position, raw_line in enumerate(lines, start=1):
        if not isinstance(raw_line, Mapping):
            raise DocumentCalculationError(f"line {position} must be an object")
        description = str(raw_line.get("description") or "").strip()
        unit = str(raw_line.get("unit") or "").strip()
        if not description or not unit:
            raise DocumentCalculationError(f"line {position} description and unit are required")
        quantity = decimal_value(raw_line.get("quantity"), field=f"line {position} quantity", minimum=Decimal("0.0001"))
        unit_price = integer_rupiah(raw_line.get("unit_price"), field=f"line {position} unit_price")
        line_rate = decimal_value(
            raw_line.get("line_discount_percent", "0"),
            field=f"line {position} line_discount_percent",
        )
        if line_rate > Decimal("100"):
            raise DocumentCalculationError(f"line {position} line_discount_percent is outside the allowed range")
        gross = _round_idr(quantity * Decimal(unit_price))
        discount = _round_idr(Decimal(gross) * line_rate / Decimal("100"))
        calculated.append(
            DocumentLineTotal(
                description=description,
                quantity=quantity,
                unit=unit,
                unit_price=unit_price,
                line_discount_percent=line_rate,
                line_gross=gross,
                line_discount=discount,
                line_total=gross - discount,
            )
        )

    subtotal = sum(line.line_total for line in calculated)
    document_discount = amount_discount or _round_idr(
        Decimal(subtotal) * percent_discount / Decimal("100")
    )
    taxable_base = subtotal - document_discount
    if taxable_base < 0:
        raise DocumentCalculationError("document discount exceeds taxable base")
    tax = _round_idr(Decimal(taxable_base) * tax_rate / Decimal("100"))
    return DocumentTotals(
        lines=tuple(calculated),
        subtotal=subtotal,
        document_discount=document_discount,
        taxable_base=taxable_base,
        tax=tax,
        total=taxable_base + tax,
    ).to_dict()


def _actor(actor: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(actor, Mapping) or not actor:
        raise ValueError("actor is required")
    return dict(actor)


class ProjectDocumentService:
    """Validate domain commands and delegate each atomic transition to the store."""

    def __init__(
        self,
        repository: ProjectDocumentStore,
        *,
        today: Callable[[], date] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._today = today or date.today
        self._now = now or (lambda: datetime.now(timezone.utc))

    def create_project(
        self,
        values: Mapping[str, Any],
        *,
        idempotency_key: str,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        command = dict(values)
        current = self._today()
        command.setdefault("tax_percent", "0")
        command.setdefault("sales_order_valid_until", (current + timedelta(days=14)).isoformat())
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
        project = self._repository.get_project(project_id)
        if project.get("status") not in {"planned", "active"}:
            raise ValueError("invoices require a planned or active project")
        command = dict(values)
        command["invoice_kind"] = kind
        command.setdefault("tax_percent", "0")
        command.setdefault("due_date", (self._today() + timedelta(days=7)).isoformat())
        if kind == "FINAL":
            commercial = self._repository.get_project_commercial_totals(project_id)
            residual = int(commercial["contract_total"]) - int(commercial["invoiced_non_final"])
            if residual <= 0:
                raise ValueError("FINAL invoice residual must be positive")
            command["lines"] = [
                {
                    "description": "Pelunasan akhir",
                    "quantity": "1",
                    "unit": "termin",
                    "unit_price": residual,
                    "line_discount_percent": "0",
                }
            ]
        totals = calculate_document_totals(
            command.get("lines") or [],
            document_discount_amount=command.get("document_discount_amount", 0),
            document_discount_percent=command.get("document_discount_percent", "0"),
            tax_percent=command.get("tax_percent", "0"),
        )
        command["lines"] = totals["lines"]
        command["totals"] = {key: value for key, value in totals.items() if key != "lines"}
        return self._repository.create_document_draft(
            project_id,
            document_type="invoice",
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
            issued_at=self._now(),
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
