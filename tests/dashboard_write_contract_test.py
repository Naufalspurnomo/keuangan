from dataclasses import FrozenInstanceError
from datetime import date, datetime
from typing import Any

import pytest

from dashboard_api.write_contracts import (
    MAX_SAFE_INTEGER,
    TransactionRequest,
    TransactionValidationError,
    validate_transaction_request,
)

TODAY = date(2026, 10, 2)


def valid_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "idempotency_key": "dashboard-request-0001",
        "date": TODAY.isoformat(),
        "scope": "project",
        "direction": "Pemasukan",
        "amount": 100_000,
        "description": "Pembayaran termin",
        "wallet": "CV HB(101)",
        "company": "HOLLA",
        "category": "Lain-lain",
        "project": "PROJECT-001",
    }
    payload.update(changes)
    return payload


def validate(payload: Any, *, exists=True, today=TODAY) -> TransactionRequest:
    return validate_transaction_request(
        payload,
        project_exists=lambda project: exists,
        today=lambda: today,
    )


def assert_invalid(payload: object, message: str) -> None:
    with pytest.raises(TransactionValidationError, match=message):
        validate(payload)


def test_returns_frozen_canonical_request_and_passes_project_to_validator():
    seen: list[str] = []
    result = validate_transaction_request(
        valid_payload(),
        project_exists=lambda project: not seen.append(project),
        today=lambda: TODAY,
    )

    assert result == TransactionRequest(
        idempotency_key="dashboard-request-0001",
        date=TODAY,
        scope="project",
        direction="Pemasukan",
        amount=100_000,
        description="Pembayaran termin",
        wallet="CV HB(101)",
        company="HOLLA",
        category="Lain-lain",
        project="PROJECT-001",
    )
    assert seen == ["PROJECT-001"]
    with pytest.raises(FrozenInstanceError):
        result.amount = 1


@pytest.mark.parametrize("payload", [None, [], "request"])
def test_rejects_non_object_request(payload):
    assert_invalid(payload, r"request: must be an object")


def test_rejects_unknown_and_missing_fields_deterministically():
    payload = valid_payload(zeta="bad", alpha="bad")
    assert_invalid(payload, r"unknown field\(s\): alpha, zeta")

    payload = valid_payload()
    del payload["amount"]
    del payload["date"]
    assert_invalid(payload, r"missing field\(s\): amount, date")


@pytest.mark.parametrize("amount", [True, False, 1.0, "1", None])
def test_amount_must_be_exact_integer_and_never_boolean(amount):
    assert_invalid(valid_payload(amount=amount), r"amount: must be an exact integer")


@pytest.mark.parametrize("amount", [0, -1, MAX_SAFE_INTEGER + 1])
def test_amount_must_be_positive_javascript_safe_integer(amount):
    assert_invalid(valid_payload(amount=amount), r"amount: must be between 1 and 9007199254740991")


def test_amount_accepts_safe_integer_upper_boundary():
    assert validate(valid_payload(amount=MAX_SAFE_INTEGER)).amount == MAX_SAFE_INTEGER


@pytest.mark.parametrize("raw_date", ["02-10-2026", "2026-2-3", "2026-02-30", 20261002])
def test_date_must_be_canonical_valid_iso_date(raw_date):
    assert_invalid(valid_payload(date=raw_date), r"date: must")


def test_date_must_equal_injected_current_jakarta_date():
    assert_invalid(valid_payload(date="2026-10-01"), r"date: must be the current Asia/Jakarta date")


def test_default_clock_uses_asia_jakarta(monkeypatch):
    captured = {}

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            captured["timezone"] = tz
            return cls(2026, 10, 2, 0, 30, tzinfo=tz)

    monkeypatch.setattr("dashboard_api.write_contracts.datetime", FixedDatetime)
    result = validate_transaction_request(
        valid_payload(),
        project_exists=lambda project: True,
    )
    assert result.date == TODAY
    assert captured["timezone"].key == "Asia/Jakarta"


def test_clock_and_project_validator_contracts_fail_clearly():
    with pytest.raises(TypeError, match="today must return datetime.date"):
        validate(valid_payload(), today=datetime(2026, 10, 2))

    with pytest.raises(TypeError, match="project_exists must return bool"):
        validate_transaction_request(
            valid_payload(),
            project_exists=lambda project: 1,  # type: ignore[arg-type,return-value]
            today=lambda: TODAY,
        )

    def broken_project_validator(project):
        raise RuntimeError("network not allowed")

    with pytest.raises(TransactionValidationError, match="project: existence validation failed"):
        validate_transaction_request(
            valid_payload(),
            project_exists=broken_project_validator,
            today=lambda: TODAY,
        )


@pytest.mark.parametrize("scope", ["Project", "operational", "", None, 1])
def test_scope_is_exactly_project_or_office(scope):
    assert_invalid(valid_payload(scope=scope), r"scope: must be project or office")


@pytest.mark.parametrize("direction", ["Income", "pemasukan", "Transfer", "", None, 1])
def test_direction_is_exactly_runtime_vocabulary(direction):
    assert_invalid(valid_payload(direction=direction), r"direction: must be Pemasukan or Pengeluaran")


def test_office_scope_only_allows_expenses_and_omits_project():
    office = valid_payload(
        scope="office",
        direction="Pengeluaran",
        category="ListrikAir",
    )
    del office["project"]
    assert validate(office).project is None

    assert_invalid(
        {**office, "direction": "Pemasukan"},
        r"direction: office transactions must be Pengeluaran",
    )
    assert_invalid(
        {**office, "project": "PROJECT-001"},
        r"project: must be omitted for office scope",
    )
    assert_invalid(
        {**office, "project": None},
        r"project: must be omitted for office scope",
    )


@pytest.mark.parametrize(
    ("wallet", "company"),
    [
        ("CV HB(101)", "HOLLA"),
        ("CV HB(101)", "HOJJA"),
        ("TX SBY(216)", "TEXTURIN-Surabaya"),
        ("TX BALI(087)", "TEXTURIN-Bali"),
        ("CV HB(101)", "CV HB"),
        ("TX SBY(216)", "TX SBY"),
        ("TX BALI(087)", "TX BALI"),
    ],
)
def test_accepts_existing_runtime_wallet_company_pairs(wallet, company):
    result = validate(valid_payload(wallet=wallet, company=company))
    assert (result.wallet, result.company) == (wallet, company)


@pytest.mark.parametrize(
    ("wallet", "company"),
    [
        ("TX SBY(216)", "HOLLA"),
        ("CV HB(101)", "TEXTURIN-Bali"),
        ("BCA", "GEP"),
        ("CV HB", "HOLLA"),
    ],
)
def test_rejects_unknown_or_mismatched_wallet_company_pairs(wallet, company):
    assert_invalid(
        valid_payload(wallet=wallet, company=company),
        r"wallet: unknown wallet/company combination",
    )


@pytest.mark.parametrize("category", ["Bahan Alat", "Gaji", "Operasi Kantor", "Lain-lain"])
def test_accepts_project_categories_used_by_runtime(category):
    assert validate(valid_payload(category=category)).category == category


@pytest.mark.parametrize("category", ["Gaji", "ListrikAir", "Konsumsi", "Peralatan", "Lain Lain"])
def test_accepts_office_categories_used_by_runtime(category):
    payload = valid_payload(scope="office", direction="Pengeluaran", category=category)
    del payload["project"]
    assert validate(payload).category == category


def test_rejects_categories_outside_selected_scope():
    assert_invalid(valid_payload(category="Material"), r"category: is not an operational project category")

    office = valid_payload(scope="office", direction="Pengeluaran", category="Lain-lain")
    del office["project"]
    assert_invalid(office, r"category: is not an operational office expense category")


def test_project_is_required_and_must_exist_for_wallet_company():
    payload = valid_payload()
    del payload["project"]
    assert_invalid(payload, r"project: is required for project scope")

    with pytest.raises(TransactionValidationError, match="project: does not exist for wallet/company"):
        validate(valid_payload(), exists=False)


@pytest.mark.parametrize("field", ["description", "wallet", "company", "category", "project"])
@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_rejects_formula_leading_text_in_every_ledger_text_field(field, prefix):
    assert_invalid(valid_payload(**{field: f"{prefix}SUM(A1:A2)"}), rf"{field}: must not start")


@pytest.mark.parametrize("field", ["description", "wallet", "company", "category", "project"])
def test_rejects_non_string_blank_whitespace_and_control_text(field):
    for value in (None, 1, "", " leading", "trailing ", "line\nbreak", "tab\ttext"):
        assert_invalid(valid_payload(**{field: value}), rf"{field}:")


@pytest.mark.parametrize(
    ("field", "limit"),
    [("description", 200), ("wallet", 100), ("company", 100), ("category", 100), ("project", 100)],
)
def test_enforces_text_lengths(field, limit):
    assert_invalid(valid_payload(**{field: "x" * (limit + 1)}), rf"{field}: length must be 1..{limit}")


def test_office_description_obeys_operational_writer_150_character_limit():
    payload = valid_payload(
        scope="office",
        direction="Pengeluaran",
        category="Lain Lain",
        description="x" * 151,
    )
    del payload["project"]
    assert_invalid(payload, r"description: length must be 1..150")


@pytest.mark.parametrize(
    "key",
    [
        "short-key",
        "x" * 129,
        " leading-key-0001",
        "trailing-key-0001 ",
        "contains space 0001",
        "contains\ttab-0001",
        "control-key-000\x00",
    ],
)
def test_idempotency_key_rejects_wrong_lengths_or_whitespace(key):
    assert_invalid(valid_payload(idempotency_key=key), r"idempotency_key:")


def test_accepts_idempotency_key_boundaries_and_formula_characters_as_opaque_data():
    assert validate(valid_payload(idempotency_key="=" * 16)).idempotency_key == "=" * 16
    assert validate(valid_payload(idempotency_key="é" * 16)).idempotency_key == "é" * 16
    assert validate(valid_payload(idempotency_key="x" * 128)).idempotency_key == "x" * 128
