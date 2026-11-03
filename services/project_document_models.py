"""Pure project-document domain contracts and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Any, Mapping


class ProjectDocumentValidationError(ValueError):
    """A project-document command violates a domain contract."""


class DocumentCalculationError(ProjectDocumentValidationError):
    """A commercial calculation cannot be represented exactly."""


BIGINT_MAX = 9_223_372_036_854_775_807
QUANTITY_MAX = Decimal("99999999999999.9999")
PERCENT_MAX = Decimal("100")
MAX_DOCUMENT_LINES = 500
MAX_RECEIPT_ALLOCATIONS = 10


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


def _fractional_digits(value: Decimal) -> int:
    digits = list(value.as_tuple().digits)
    exponent = value.as_tuple().exponent
    while exponent < 0 and digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    return max(0, -exponent)


def decimal_value(
    value: Any,
    *,
    field: str,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal | None = None,
    max_fractional_digits: int | None = None,
) -> Decimal:
    if isinstance(value, bool):
        raise DocumentCalculationError(f"{field} must be a decimal number")
    try:
        parsed = Decimal(str(value))
    except (DecimalException, ValueError, TypeError) as exc:
        raise DocumentCalculationError(f"{field} must be a decimal number") from exc
    if (
        not parsed.is_finite()
        or parsed < minimum
        or (maximum is not None and parsed > maximum)
    ):
        raise DocumentCalculationError(f"{field} is outside the allowed range")
    if (
        max_fractional_digits is not None
        and _fractional_digits(parsed) > max_fractional_digits
    ):
        raise DocumentCalculationError(
            f"{field} must have at most {max_fractional_digits} fractional digits"
        )
    return parsed


def integer_rupiah(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentCalculationError(f"{field} must be integer rupiah")
    if value < 0:
        raise DocumentCalculationError(f"{field} must not be negative")
    if value > BIGINT_MAX:
        raise DocumentCalculationError(f"{field} exceeds PostgreSQL BIGINT")
    return value


def bounded_idr(value: int, *, field: str) -> int:
    """Validate a calculated integer-rupiah intermediate or aggregate."""

    return integer_rupiah(value, field=field)


def decimal_text(value: Decimal) -> str:
    try:
        normalized = value.normalize()
        if normalized == normalized.to_integral():
            return str(normalized.quantize(Decimal("1")))
        return format(normalized, "f")
    except DecimalException as exc:
        raise DocumentCalculationError("decimal value cannot be serialized") from exc


def require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectDocumentValidationError(f"{field} must be an object")
    return value
