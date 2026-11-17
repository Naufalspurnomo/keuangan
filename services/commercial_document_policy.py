"""Canonical brand policy and semantic commercial-line normalization."""

from __future__ import annotations

import json
from decimal import Decimal, DecimalException, ROUND_DOWN, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any, Mapping

from services.project_document_models import DocumentCalculationError, integer_rupiah

_POLICY_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "commercial_document_policies.json"
_TEMPLATE_KEYS = ("hollawall", "hojja", "texturin")
_PRICING_MODES = {"area_rate", "ppm_area", "fixed_artwork", "fixed_fee", "legacy_generic"}
_DIMENSION_FACTORS = {"m": Decimal("1"), "cm": Decimal("0.01"), "mm": Decimal("0.001")}
_AREA_MODES = {"area_rate", "ppm_area"}


def commercial_policies() -> dict[str, dict[str, Any]]:
    return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))


def _template_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "hojja" in text:
        return "hojja"
    if "texturin" in text or text.startswith("tx "):
        return "texturin"
    return "hollawall"


def commercial_policy(template_key: Any) -> dict[str, Any]:
    return commercial_policies()[_template_key(template_key)]


def _decimal(value: Any, *, field: str, max_fractional_digits: int) -> Decimal:
    text = str(value if value is not None else "").strip().replace(",", ".")
    try:
        parsed = Decimal(text)
    except (DecimalException, ValueError) as exc:
        raise DocumentCalculationError(f"{field} is invalid") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise DocumentCalculationError(f"{field} must be positive")
    exponent = parsed.as_tuple().exponent
    fractional = max(0, -exponent) if isinstance(exponent, int) else max_fractional_digits + 1
    if fractional > max_fractional_digits:
        unit = "eight" if max_fractional_digits == 8 else "four"
        raise DocumentCalculationError(f"{field} supports at most {unit} fractional digits")
    return parsed


def _text(value: Decimal) -> str:
    rendered = format(value, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _area(width: Any, height: Any, unit: Any) -> Decimal:
    dimension_unit = str(unit or "m").strip().lower()
    if dimension_unit not in _DIMENSION_FACTORS:
        raise DocumentCalculationError("dimension_unit must be mm, cm, or m")
    factor = _DIMENSION_FACTORS[dimension_unit]
    width_value = _decimal(width, field="width", max_fractional_digits=8) * factor
    height_value = _decimal(height, field="height", max_fractional_digits=8) * factor
    with localcontext() as context:
        context.prec = 32
        return width_value * height_value


def normalize_commercial_line(raw: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    line = dict(raw)
    description = str(line.get("description") or "").strip()
    if not description:
        raise DocumentCalculationError("description is required")
    mode = str(line.get("pricing_mode") or "legacy_generic").strip().lower()
    if mode not in _PRICING_MODES:
        raise DocumentCalculationError("pricing_mode is unsupported")
    expected_mode = str(policy.get("pricing_mode") or "")
    if mode != "legacy_generic" and mode != expected_mode:
        raise DocumentCalculationError("pricing_mode conflicts with template policy")
    unit_price = integer_rupiah(line.get("unit_price", 0), field="unit_price")

    normalized: dict[str, Any] = {**line, "description": description, "pricing_mode": mode, "unit_price": unit_price}
    raw_area: Decimal | None = None
    if line.get("width") not in (None, "") or line.get("height") not in (None, ""):
        if line.get("width") in (None, "") or line.get("height") in (None, ""):
            raise DocumentCalculationError("width and height must be supplied together")
        raw_area = _area(line.get("width"), line.get("height"), line.get("dimension_unit"))
        normalized["raw_area_m2"] = _text(raw_area)

    if mode in _AREA_MODES:
        if raw_area is None and line.get("billed_area_m2") in (None, ""):
            raise DocumentCalculationError("area dimensions or billed_area_m2 are required")
        rounding = str(line.get("area_rounding") or "half_up").strip().lower()
        if rounding not in {"exact", "half_up", "truncate", "manual_override"}:
            raise DocumentCalculationError("area_rounding is unsupported")
        supplied = line.get("billed_area_m2")
        if rounding == "manual_override":
            reason = str(line.get("area_override_reason") or "").strip()
            if not reason:
                raise DocumentCalculationError("manual area override reason is required")
            billed = _decimal(supplied, field="billed_area_m2", max_fractional_digits=4)
            normalized["area_override_reason"] = reason
        elif supplied not in (None, ""):
            billed = _decimal(supplied, field="billed_area_m2", max_fractional_digits=4)
            if raw_area is not None:
                target = raw_area.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP if rounding == "half_up" else ROUND_DOWN)
                if rounding == "exact":
                    target = raw_area.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                if billed != target:
                    raise DocumentCalculationError("billed_area_m2 disagrees with dimensions and rounding policy")
        else:
            assert raw_area is not None
            quantum = Decimal("0.0001") if rounding == "exact" else Decimal("0.01")
            billed = raw_area.quantize(quantum, rounding=ROUND_DOWN if rounding == "truncate" else ROUND_HALF_UP)
        normalized.update({"area_rounding": rounding, "billed_area_m2": _text(billed), "quantity": _text(billed), "unit": "m²"})
        quantity = billed
    elif mode == "fixed_artwork":
        quantity = _decimal(line.get("display_quantity", line.get("quantity", "1")), field="display_quantity", max_fractional_digits=4)
        if quantity != quantity.to_integral_value():
            raise DocumentCalculationError("display_quantity must be a whole artwork count")
        original = line.get("original_price")
        if original not in (None, ""):
            normalized["original_price"] = integer_rupiah(original, field="original_price")
            if normalized["original_price"] < unit_price:
                raise DocumentCalculationError("original_price must not be below agreed price")
        normalized.update({"display_quantity": _text(quantity), "quantity": _text(quantity), "unit": "artwork"})
    else:
        quantity = _decimal(line.get("quantity", "1"), field="quantity", max_fractional_digits=4)
        normalized.update({"quantity": _text(quantity), "unit": str(line.get("unit") or "unit").strip()})

    with localcontext() as context:
        context.prec = 32
        normalized["line_total"] = int((quantity * Decimal(unit_price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return normalized
