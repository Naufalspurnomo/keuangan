"""Focused calculation-boundary and service protocol regression tests."""

from __future__ import annotations

import inspect
from decimal import localcontext

import pytest

from services.project_document_models import DocumentCalculationError
from services.project_documents import (
    ProjectDocumentService,
    ProjectDocumentStore,
    calculate_document_totals,
)


BIGINT_MAX = 9_223_372_036_854_775_807
QUANTITY_MAX = "99999999999999.9999"


def line(**overrides):
    value = {
        "description": "Boundary item",
        "quantity": "1",
        "unit": "unit",
        "unit_price": 1,
        "line_discount_percent": "0",
    }
    value.update(overrides)
    return value


def test_quantity_accepts_numeric_18_4_positive_upper_boundary():
    totals = calculate_document_totals([line(quantity=QUANTITY_MAX, unit_price=0)])

    assert totals["lines"][0]["quantity"] == QUANTITY_MAX
    assert totals["total"] == 0


@pytest.mark.parametrize(
    "quantity",
    ["0", "-0.0001", "100000000000000.0000", "1.00001"],
)
def test_quantity_rejects_non_positive_one_step_over_and_excess_scale(quantity):
    with pytest.raises(DocumentCalculationError):
        calculate_document_totals([line(quantity=quantity, unit_price=0)])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("line_discount_percent", "1.00001"),
        ("document_discount_percent", "1.00001"),
        ("tax_percent", "1.00001"),
        ("line_discount_percent", "100.0001"),
        ("document_discount_percent", "100.0001"),
        ("tax_percent", "100.0001"),
    ],
)
def test_percentage_rejects_excess_scale_and_range(field, value):
    kwargs = {}
    candidate = line()
    if field == "line_discount_percent":
        candidate[field] = value
    else:
        kwargs[field] = value

    with pytest.raises(DocumentCalculationError):
        calculate_document_totals([candidate], **kwargs)


def test_percentage_accepts_schema_scale_at_range_boundary():
    totals = calculate_document_totals(
        [line(line_discount_percent="100.0000")],
        tax_percent="100.0000",
    )

    assert totals["lines"][0]["line_discount_percent"] == "100"
    assert totals["total"] == 0


@pytest.mark.parametrize(
    ("kwargs", "candidate"),
    [
        ({"document_discount_amount": BIGINT_MAX + 1}, line(unit_price=BIGINT_MAX)),
        ({}, line(unit_price=BIGINT_MAX + 1)),
        ({}, line(quantity="2", unit_price=BIGINT_MAX)),
        ({"tax_percent": "100"}, line(unit_price=BIGINT_MAX)),
    ],
)
def test_every_idr_input_intermediate_and_final_is_bounded(kwargs, candidate):
    with pytest.raises(DocumentCalculationError, match="BIGINT"):
        calculate_document_totals([candidate], **kwargs)


def test_bigint_boundary_is_accepted_for_input_and_final():
    totals = calculate_document_totals([line(unit_price=BIGINT_MAX)])

    assert totals["lines"][0]["line_gross"] == BIGINT_MAX
    assert totals["subtotal"] == BIGINT_MAX
    assert totals["total"] == BIGINT_MAX


def test_aggregate_overflow_is_rejected_before_persistence():
    with pytest.raises(DocumentCalculationError, match="BIGINT"):
        calculate_document_totals(
            [
                line(unit_price=(BIGINT_MAX // 2) + 1),
                line(unit_price=(BIGINT_MAX // 2) + 1),
            ]
        )


def test_document_line_count_is_bounded_at_500():
    accepted = calculate_document_totals([line(unit_price=0) for _ in range(500)])
    assert len(accepted["lines"]) == 500

    with pytest.raises(DocumentCalculationError, match="500"):
        calculate_document_totals([line(unit_price=0) for _ in range(501)])


@pytest.mark.parametrize(
    ("candidate", "kwargs"),
    [
        (line(quantity="1e999999", unit_price=0), {}),
        (line(line_discount_percent="1e999999"), {}),
        (line(), {"tax_percent": "1e999999"}),
    ],
)
def test_huge_exponents_never_leak_raw_decimal_exceptions(candidate, kwargs):
    with pytest.raises(DocumentCalculationError) as captured:
        calculate_document_totals([candidate], **kwargs)

    assert captured.type is DocumentCalculationError


def test_calculation_uses_controlled_local_decimal_context():
    with localcontext() as hostile_context:
        hostile_context.prec = 2
        totals = calculate_document_totals(
            [line(quantity="2.555", unit_price=1001, line_discount_percent="10")],
            document_discount_percent="5",
            tax_percent="11",
        )

    assert totals["total"] == 2428


def test_store_protocol_declares_exact_update_draft_signature():
    assert inspect.signature(ProjectDocumentStore.update_draft) == inspect.signature(
        ProjectDocumentService.update_draft
    )
