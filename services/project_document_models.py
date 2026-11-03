"""Pure project-document domain contracts and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class ProjectDocumentValidationError(ValueError):
    """A project-document command violates a domain contract."""


class DocumentCalculationError(ProjectDocumentValidationError):
    """A commercial calculation cannot be represented exactly."""


@dataclass(frozen=True, slots=True)
class DocumentLineTotal:
    description: str
    quantity: Decimal
    unit: str
    unit_price: int
    line_discount_percent: Decimal
    line_gross: int
    line_discount: int
    line_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "quantity": decimal_text(self.quantity),
            "unit": self.unit,
            "unit_price": self.unit_price,
            "line_discount_percent": decimal_text(self.line_discount_percent),
            "line_gross": self.line_gross,
            "line_discount": self.line_discount,
            "line_total": self.line_total,
        }


@dataclass(frozen=True, slots=True)
class DocumentTotals:
    lines: tuple[DocumentLineTotal, ...]
    subtotal: int
    document_discount: int
    taxable_base: int
    tax: int
    total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "subtotal": self.subtotal,
            "document_discount": self.document_discount,
            "taxable_base": self.taxable_base,
            "tax": self.tax,
            "total": self.total,
        }


def decimal_value(value: Any, *, field: str, minimum: Decimal = Decimal("0")) -> Decimal:
    if isinstance(value, bool):
        raise DocumentCalculationError(f"{field} must be a decimal number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DocumentCalculationError(f"{field} must be a decimal number") from exc
    if not parsed.is_finite() or parsed < minimum:
        raise DocumentCalculationError(f"{field} is outside the allowed range")
    return parsed


def integer_rupiah(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentCalculationError(f"{field} must be integer rupiah")
    if value < 0:
        raise DocumentCalculationError(f"{field} must not be negative")
    return value


def decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectDocumentValidationError(f"{field} must be an object")
    return value
